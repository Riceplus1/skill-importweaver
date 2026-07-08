"""HarborEnvAdapter — SkillOpt EnvAdapter that uses Harbor CLI for rollout.

Each ``rollout()`` call writes the current ``skill_content`` to a temp
directory, then runs ``harbor run`` for each task (parallelised via
ThreadPoolExecutor).

Supports two modes:
  - ``claude-code`` (default): skill = SKILL.md, agent runs with --model
  - ``heuristic-env``:         skill = heuristic_env_setup.py, no LLM
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from skillopt.datasets.base import BatchSpec
from skillopt.envs.base import EnvAdapter

from .dataloader import SkillOptDataLoader


class HarborEnvAdapter(EnvAdapter):
    """SkillOpt EnvAdapter backed by Harbor CLI.

    Parameters
    ----------
    task_dir : str
        Path to directory containing pre-converted task subdirectories.
    harbor_bin : str
        Path to the ``harbor`` CLI binary.
    agent_name : str
        Harbor agent name (e.g. ``"claude-code"`` or ``"heuristic-env"``).
    model : str
        Model name passed to Harbor's ``--model`` (ignored for heuristic-env).
    mounts : list[dict]
        Docker volume mounts.
    n_concurrent : int
        Max parallel ``harbor run`` processes.
    task_timeout : int
        Per-task timeout in seconds.
    split_path, train_size, val_size, test_size, seed :
        Forwarded to data loader.
    dataset_name : str
        HuggingFace dataset name for task metadata.
    language_filter : str | None
        Optional language filter (e.g. "Python" for MEnvBench).
    """

    def __init__(
        self,
        task_dir: str = "",
        harbor_bin: str = "harbor",
        agent_name: str = "claude-code",
        model: str = "",
        mounts: list[dict] | None = None,
        n_concurrent: int = 2,
        task_timeout: int = 900,
        split_path: str = "",
        train_size: int = 20,
        val_size: int = 5,
        test_size: int = 5,
        seed: int = 42,
        dataset_name: str = "litble/Multi-Docker-Eval",
        language_filter: str | None = None,
        analyst_workers: int = 4,
        failure_only: bool = False,
        minibatch_size: int = 4,
        edit_budget: int = 4,
        agent_setup_timeout_multiplier: int = 3,
        **kwargs,
    ) -> None:
        self.task_dir = task_dir
        self.harbor_bin = harbor_bin
        self.agent_name = agent_name
        self.model = model
        self.mounts = mounts or []
        self.n_concurrent = n_concurrent
        self.task_timeout = task_timeout
        self.agent_setup_timeout_multiplier = agent_setup_timeout_multiplier

        self.analyst_workers = analyst_workers
        self.failure_only = failure_only
        self.minibatch_size = minibatch_size
        self.edit_budget = edit_budget

        self.dataloader = SkillOptDataLoader(
            dataset_name=dataset_name,
            split_path=split_path or "",
            train_size=train_size,
            val_size=val_size,
            test_size=test_size,
            seed=seed,
            language_filter=language_filter,
        )

    # ── EnvAdapter interface ──────────────────────────────────────────────

    def setup(self, cfg: dict) -> None:
        super().setup(cfg)
        self.dataloader.setup(cfg)

    def get_dataloader(self):
        return self.dataloader

    def get_task_types(self) -> list[str]:
        return [self.agent_name]

    def build_env_from_batch(self, batch: BatchSpec, **kwargs):
        return list(batch.payload or [])

    def build_train_env(self, batch_size: int, seed: int, **kwargs):
        batch = self.dataloader.build_train_batch(batch_size=batch_size, seed=seed)
        return self.build_env_from_batch(batch, **kwargs)

    def build_eval_env(self, env_num: int, split: str, seed: int, **kwargs):
        batch = self.dataloader.build_eval_batch(env_num=env_num, split=split, seed=seed)
        return self.build_env_from_batch(batch, **kwargs)

    # ── Skill writing ─────────────────────────────────────────────────────

    def _write_skill(self, skill_dir: str, skill_content: str) -> str:
        """Write skill content to the temp directory.

        For ``heuristic-env`` agent, writes ``heuristic_env_setup.py``.
        For other agents, writes ``SKILL.md``.

        Returns the path to the written file.
        """
        if self.agent_name == "heuristic-env":
            file_name = "heuristic_env_setup.py"
        else:
            file_name = "SKILL.md"

        file_path = os.path.join(skill_dir, file_name)
        with open(file_path, "w") as f:
            f.write(skill_content)
        return file_path

    def _build_harbor_cmd(
        self, local_id: str, skill_dir: str, job_root: str
    ) -> list[str]:
        """Build the ``harbor run`` CLI command."""
        cmd = [
            self.harbor_bin,
            "run",
            "--path", self.task_dir,
            "-i", local_id,
            "--agent", self.agent_name,
            "--skill", skill_dir,
            "--n-concurrent", "1",
            "--jobs-dir", job_root,
            "--no-delete",
            "--agent-setup-timeout-multiplier",
            str(self.agent_setup_timeout_multiplier),
            "-y",
        ]

        # --model is only needed for LLM-based agents
        if self.model and self.agent_name != "heuristic-env":
            cmd.extend(["--model", self.model])

        # Forward environment variables to container
        agent_env = self._build_harbor_env()
        for key, val in agent_env.items():
            cmd.extend(["--ae", f"{key}={val}"])

        # Volume mounts
        if self.mounts:
            cmd.extend(["--mounts", json.dumps(self.mounts)])

        return cmd

    @staticmethod
    def _build_harbor_env() -> dict[str, str]:
        """Collect env vars to forward to the Harbor container."""
        forward_keys = {
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
        }
        env = {}
        for key in forward_keys:
            val = os.environ.get(key)
            if val:
                env[key] = val
        return env

    # ── Rollout ───────────────────────────────────────────────────────────

    def rollout(
        self,
        env_manager,
        skill_content: str,
        out_dir: str,
        **kwargs,
    ) -> list[dict]:
        """Run Harbor on each task in *env_manager* (list of task dicts)."""
        items: list[dict] = env_manager
        pred_dir = os.path.join(out_dir, "predictions")
        os.makedirs(pred_dir, exist_ok=True)

        # Write current skill to a temp directory
        skill_dir = tempfile.mkdtemp(prefix="skillopt-skill-")
        self._write_skill(skill_dir, skill_content)

        results: list[dict] = []
        try:
            lock = threading.Lock()

            def _run(item: dict) -> dict:
                return self._run_one(item, skill_dir, pred_dir)

            with ThreadPoolExecutor(max_workers=self.n_concurrent) as pool:
                futs = {pool.submit(_run, it): it for it in items}
                for fut in as_completed(futs):
                    item = futs[fut]
                    try:
                        row = fut.result()
                    except Exception as exc:
                        row = self._make_error_row(item, exc)
                    with lock:
                        results.append(row)
        finally:
            shutil.rmtree(skill_dir, ignore_errors=True)

        return results

    # ── Single-task execution ─────────────────────────────────────────────

    def _make_error_row(
        self, item: dict, exc: Exception | None = None, **overrides
    ) -> dict:
        """Build a result dict for a failed rollout."""
        row = {
            "id": item["instance_id"],
            "hard": 0,
            "soft": 0.0,
            "fail_reason": "",
            "agent_ok": False,
            "task_description": (item.get("problem_statement") or "")[:200],
            "task_type": self.agent_name,
            "n_turns": 0,
        }
        if exc:
            row["fail_reason"] = (
                f"rollout-error: {type(exc).__name__}: {exc}"
            )
        row.update(overrides)
        return row

    def _find_trial_output(self, job_root: str) -> tuple[float, str, str]:
        """Walk *job_root* to find reward and logs.

        Returns
        -------
        tuple[float, str, str]
            (reward, rollout_log, verifier_stdout)
        """
        rollout_log = ""
        reward = 0.0
        verifier_stdout = ""

        for root, _dirs, files in os.walk(job_root):
            parts = root.split(os.sep)
            is_verifier = "verifier" in parts
            is_agent = "agent" in parts

            if is_verifier and "reward.txt" in files:
                try:
                    with open(os.path.join(root, "reward.txt")) as f:
                        reward = max(reward, float(f.read().strip()))
                except (ValueError, OSError):
                    pass

            if is_verifier and "test-stdout.txt" in files:
                try:
                    with open(os.path.join(root, "test-stdout.txt")) as f:
                        verifier_stdout = f.read()
                except OSError:
                    pass

            # Agent log — different agents produce different files
            if is_agent:
                # Claude Code: claude-code.txt
                if "claude-code.txt" in files:
                    try:
                        with open(os.path.join(root, "claude-code.txt")) as f:
                            rollout_log = f.read()
                    except OSError:
                        pass
                # Heuristic env: trial stores metadata; look for trajectory.json
                elif "trajectory.json" in files:
                    try:
                        with open(os.path.join(root, "trajectory.json")) as f:
                            rollout_log = f.read()
                    except OSError:
                        pass

        return reward, rollout_log, verifier_stdout

    def _build_conversation(
        self,
        item: dict,
        rollout_log: str,
        verifier_stdout: str,
        reward: float,
    ) -> list[dict]:
        """Build a conversation.json from rollout results."""
        MAX_LOG = 50_000
        conv: list[dict] = []

        if rollout_log:
            display = rollout_log
            if len(display) > MAX_LOG:
                display = (
                    display[:MAX_LOG // 2]
                    + f"\n... [truncated {len(display)} bytes] ...\n"
                    + display[-MAX_LOG // 2:]
                )
            conv.append({"role": "assistant", "content": display})
        else:
            # No agent log — use verifier output as the "trajectory"
            conv.append({
                "role": "assistant",
                "content": verifier_stdout[:MAX_LOG] or "(no agent output)",
            })

        if verifier_stdout:
            conv.append({
                "role": "system",
                "content": f"[VERIFIER OUTPUT]\n{verifier_stdout[:2000]}",
            })

        status = "All tests passed" if reward >= 1.0 else "Tests failed"
        conv.append({
            "role": "system",
            "content": f"[EVALUATION RESULT]\n{status}. Reward: {reward}",
        })
        return conv

    def _build_target_prompt(self, item: dict) -> str:
        """Build the target_system_prompt.txt content."""
        prompt_parts = [
            f"Repository: {item.get('repo', '')}",
            f"Base commit: {item.get('base_commit', '')}",
            "",
            item.get("problem_statement", "").strip(),
        ]
        return "\n\n".join(prompt_parts)

    def _compute_fail_reason(
        self, reward: float, verifier_stdout: str, proc: subprocess.CompletedProcess
    ) -> str:
        """Extract a human-readable failure reason from artifacts."""
        if reward >= 1.0:
            return ""
        if "FAILED" in verifier_stdout:
            fail_lines = [
                l for l in verifier_stdout.splitlines()
                if "FAILED" in l or "Error" in l or "error" in l
            ]
            return " | ".join(fail_lines[:3]) if fail_lines else "Tests failed"
        if proc.returncode != 0:
            return f"Harbor CLI exit code {proc.returncode}"
        return "Agent did not produce a correct fix"

    def _run_one(self, item: dict, skill_dir: str, pred_dir: str) -> dict:
        """Run ``harbor run`` for a single task and convert to SkillOpt result."""
        task_id = item["instance_id"]
        local_id = task_id.replace("/", "__")

        job_root = tempfile.mkdtemp(prefix=f"harbor-{local_id[:30]}-")

        try:
            # ── Build and run CLI command ─────────────────────────────────
            cmd = self._build_harbor_cmd(local_id, skill_dir, job_root)

            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.task_timeout,
            )

            # ── Parse output ──────────────────────────────────────────────
            reward, rollout_log, verifier_stdout = self._find_trial_output(job_root)

            # ── Build prediction_dir ──────────────────────────────────────
            item_pred_dir = os.path.join(pred_dir, task_id)
            os.makedirs(item_pred_dir, exist_ok=True)

            conversation = self._build_conversation(
                item, rollout_log, verifier_stdout, reward,
            )
            with open(os.path.join(item_pred_dir, "conversation.json"), "w") as f:
                json.dump(conversation, f, indent=2)

            prompt_text = self._build_target_prompt(item)
            with open(os.path.join(item_pred_dir, "target_system_prompt.txt"), "w") as f:
                f.write(prompt_text)

            # ── Build result row ──────────────────────────────────────────
            fail_reason = self._compute_fail_reason(reward, verifier_stdout, proc)

            return {
                "id": task_id,
                "hard": 1 if reward >= 1.0 else 0,
                "soft": float(reward),
                "fail_reason": fail_reason,
                "agent_ok": proc.returncode == 0,
                "task_description": (item.get("problem_statement") or "")[:200],
                "task_type": self.agent_name,
                "n_turns": 1,
            }

        except subprocess.TimeoutExpired:
            return self._make_error_row(
                item, fail_reason=f"task-timeout-{self.task_timeout}s",
            )
        except Exception as exc:
            return self._make_error_row(item, exc)
        finally:
            shutil.rmtree(job_root, ignore_errors=True)

    # ── Prompt configuration (script optimization mode) ──────────────────

    def get_error_minibatch_prompt(self) -> str | None:
        """Return the code-analysis prompt for script optimization."""
        if self.agent_name == "heuristic-env":
            return _SCRIPT_ANALYST_PROMPT
        return super().get_error_minibatch_prompt()

    def get_success_minibatch_prompt(self) -> str | None:
        """Reuse the error prompt for success cases in script mode."""
        if self.agent_name == "heuristic-env":
            return _SCRIPT_ANALYST_PROMPT
        return super().get_success_minibatch_prompt()


_SCRIPT_ANALYST_PROMPT = r"""You are an expert Python environment/debugging engineer. Your job is to analyze failed execution logs from an automatic environment-setup script and write an improved version of that script.

## Background

The script (heuristic_env_setup.py) is used to automatically set up Python project environments for testing. It runs inside a Docker container and performs these steps:
1. Configure TUNA mirrors (PyPI + apt) for faster downloads in China
2. Run auto_configure.py - scans project dependencies, installs them via uv
3. If setup.py exists, run pip install -e . as fallback
4. Run run_validation.py - collects and runs pytest tests
5. Retry up to 3 rounds if validation fails

## What you receive
- The CURRENT source code of heuristic_env_setup.py
- Execution logs from MULTIPLE tasks where the script FAILED
- Execution logs from tasks where the script SUCCEEDED (if available)

## Your task
1. Read ALL execution logs in the batch.
2. Identify the most common, systematic failure patterns across tasks. Common categories:
   - uv install fails (project uses only pip, has native extensions, etc.)
   - Missing system packages (e.g., libpq-dev, gcc, python3-dev)
   - PyPI mirror timeout or 403 errors (fall back to default index)
   - Test collection fails due to missing test-only dependencies
   - pip install -e . fails due to outdated setup.py format
   - Python version mismatch (project requires different version)
   - Network issues during git clone or dependency download
   - Permission errors (running pip as non-root)
3. Propose code improvements that address COMMON patterns - not individual tasks.
4. Output a COMPLETE rewritten heuristic_env_setup.py.

## Coding guidelines
- Must remain standalone (stdlib only, no external deps)
- Preserve CLI interface: python heuristic_env_setup.py <repo_path>
- Keep overall structure (mirrors -> auto_configure -> pip fallback -> validation -> retry)
- Only modify logic that addresses recurring failures. Do not add speculative features.
- Use subprocess.run() with capture_output=True, text=True, timeout= pattern.
- If adding new retry/fallback logic, ensure max attempt count.
- Do NOT hardcode task-specific values (repo names, file paths, test names).

## Output format
Respond ONLY with valid JSON:
{
  "batch_size": <int>,
  "failure_summary": [
    {"failure_type": "<category>", "count": <int>, "description": "<one-line>"}
  ],
  "patch": {
    "reasoning": "<concise summary of changes>",
    "skill_candidates": [
      {
        "title": "<version title>",
        "change_summary": ["<change 1>", "<change 2>"],
        "new_skill": "<COMPLETE rewritten heuristic_env_setup.py source code>"
      }
    ]
  }
}
Return exactly one item in skill_candidates. new_skill must be the COMPLETE script, not a diff.
"""
