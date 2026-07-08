#!/usr/bin/env python3
"""SkillOpt training launcher — HarborEnvAdapter × any HF benchmark.

Usage
-----
    # 1. Ensure required env vars are set (for Claude Code in container):
    export ANTHROPIC_API_KEY=sk-...
    export ANTHROPIC_BASE_URL=https://www.right.codes/deepseek/anthropic

    # 2. Mounts via env var (recommended):
    export HARBOR_MOUNTS='[{"type":"bind","source":"/usr/local/bin/claude","target":"/usr/local/bin/claude","read_only":true}]'

    # 3. Run training:
    python run_skillopt.py skillopt_adapter/config_menvbench.yaml

    # Validate setup without running:
    python run_skillopt.py skillopt_adapter/config_menvbench.yaml --validate

    # Override config keys:
    python run_skillopt.py skillopt_adapter/config.yaml train.num_epochs=1
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))

from skillopt.config import load_config, flatten_config
from skillopt.engine.trainer import ReflACTTrainer
from skillopt_adapter import HarborEnvAdapter


def build_mounts(flat_cfg: dict) -> list[dict]:
    """Build volume mounts from env var ``HARBOR_MOUNTS`` or config ``mounts``."""
    raw = os.environ.get("HARBOR_MOUNTS", "").strip()
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            print(f"[warning] Failed to parse HARBOR_MOUNTS: {exc}", file=sys.stderr)
    cfg_mounts = flat_cfg.get("mounts", [])
    if cfg_mounts and isinstance(cfg_mounts, list):
        return cfg_mounts
    return []


def validate_setup(flat: dict) -> None:
    """Check environment readiness without running training."""
    import shutil

    print("[skillopt] === Setup validation ===")
    ok = True

    hb = flat.get("harbor_bin", "harbor")
    if shutil.which(hb):
        print(f"  ✅ harbor CLI: {hb}")
    else:
        print(f"  ❌ harbor CLI not found: {hb}")
        ok = False

    td = flat.get("task_dir", "")
    if td and Path(td).exists():
        tasks = [d for d in Path(td).iterdir() if d.is_dir() and (d / "task.toml").exists()]
        print(f"  ✅ Task dir: {td} ({len(tasks)} tasks)")
    else:
        print(f"  ❌ Task dir not found: {td}")
        ok = False

    si = flat.get("skill_init", "")
    if si and Path(si).exists():
        print(f"  ✅ Initial skill: {si}")
    else:
        print(f"  ⚠️  Initial skill not found: {si}")

    if os.environ.get("ANTHROPIC_API_KEY"):
        print(f"  ✅ ANTHROPIC_API_KEY set")
    else:
        print(f"  ⚠️  ANTHROPIC_API_KEY not set")

    for m in build_mounts(flat):
        src = m.get("source", "")
        if src and not Path(src).exists():
            print(f"  ⚠️  Mount source not found: {src}")

    print(f"\n  Config: batch_size={flat.get('batch_size')}, "
          f"epochs={flat.get('num_epochs')}, "
          f"n_concurrent={flat.get('n_concurrent')}")

    print("\n  " + ("✅ Setup looks good — ready to train!" if ok else "❌ Fix issues above."))
    sys.exit(0 if ok else 1)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print(__doc__)
        sys.exit(1)

    config_path = sys.argv[1]
    overrides = sys.argv[2:] if len(sys.argv) > 2 else None

    if "--validate" in (overrides or []):
        overrides = [o for o in (overrides or []) if o != "--validate"]
        cfg = load_config(config_path, overrides=overrides)
        validate_setup(flatten_config(cfg))

    # ── 1. Load config ────────────────────────────────────────────────────
    print(f"[skillopt] Loading config from {config_path}")
    cfg = load_config(config_path, overrides=overrides)
    flat = flatten_config(cfg)

    # ── 2. Create adapter ─────────────────────────────────────────────────
    mounts = build_mounts(flat)
    if mounts:
        print(f"[skillopt] Using {len(mounts)} volume mount(s)")
    else:
        print("[skillopt] No volume mounts — agent setup may be slow")

    adapter = HarborEnvAdapter(
        harbor_bin=flat.get("harbor_bin", "harbor"),
        task_dir=flat.get("task_dir", ""),
        agent_name=flat.get("agent_name", "claude-code"),
        model=flat.get("model", ""),
        mounts=mounts,
        n_concurrent=int(flat.get("n_concurrent", 2)),
        task_timeout=int(flat.get("task_timeout", 900)),
        split_path=flat.get("split_path", ""),
        train_size=int(flat.get("train_size", 20)),
        val_size=int(flat.get("val_size", 5)),
        test_size=int(flat.get("test_size", 5)),
        seed=int(flat.get("seed", 42)),
        dataset_name=flat.get("dataset_name", "litble/Multi-Docker-Eval"),
        language_filter=flat.get("language_filter", None),
    )

    # ── 3. Run training ───────────────────────────────────────────────────
    trainer = ReflACTTrainer(cfg=flat, adapter=adapter)
    print("\n[skillopt] === Starting SkillOpt training ===")
    summary = trainer.train()

    # ── 4. Report ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Training complete!")
    print("=" * 60)
    if summary:
        for key in ("best_gate_score", "best_epoch", "final_gate_score"):
            if key in summary:
                print(f"  {key}: {summary[key]}")

    out_root = flat.get("out_root", "/tmp/skillopt-runs")
    summary_path = Path(out_root) / "training_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Summary saved to {summary_path}")


if __name__ == "__main__":
    main()
