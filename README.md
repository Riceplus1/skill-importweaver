# Skill Importweaver

> 将 importweaver（AutoGen 配环境 Agent）转写为 SKILL.md + 独立脚本，
> 并配置 SkillOpt 训练框架优化配环境能力。适用于 Harbor 评测框架。

---

## 项目结构

```
.
├── SKILL.md                        # 核心技能文档（给 Claude Code 读的指令）
├── run_skillopt.py                 # SkillOpt 训练启动入口
│
├── scripts/                        # 配环境脚本（Task 2 → Task 3）
│   ├── heuristic_env_setup.py      # 编排脚本：镜像源 → 依赖安装 → 验证（Task 3）
│   ├── auto_configure.py           # 自动扫描并安装项目依赖
│   ├── run_validation.py           # pytest 验证 + 缺包自动安装
│   ├── dependency_analysis.py      # 项目依赖分析
│   ├── pypi_time_travel.py         # PyPI 版本回溯工具
│   ├── github_time_travel.py       # GitHub 版本回溯工具
│   └── setup_mirrors.sh            # TUNA 镜像源配置
│
└── skillopt_adapter/               # SkillOpt 训练适配器（Task 4 → Task 5）
    ├── __init__.py
    ├── adapter.py                  # HarborEnvAdapter：包装 Harbor CLI 做 rollout
    ├── dataloader.py               # 通用数据加载器（支持 MDE / MEnvBench）
    ├── config.yaml                 # 训练配置：Multi-Docker-Eval × deepseek-v4-pro
    ├── config_menvbench.yaml       # 训练配置：MEnvBench × deepseek-v4-pro（Task 4）
    └── config_script_opt.yaml      # 训练配置：脚本代码优化模式（Task 5）
```

---

## 背景

### 任务二：importweaver → SKILL.md 转写

将 importweaver（AutoGen Agent）转写为一份 SKILL.md + 5 个独立脚本：
- 系统 prompt 全部保留到 SKILL.md
- 配环境逻辑拆为独立脚本（auto_configure / run_validation / 三个工具）
- 工具以脚本形式调用，workflow 以自然语言写在 SKILL.md 中
- 在 Harbor 上用 Multi-Docker-Eval 的 Python 任务验证通过，Reward = 1.0 🎉

### 任务三：脚本 Agent

构建一个「假」Agent（`HeuristicEnvAgent`），不调用 LLM，纯脚本执行配环境流程。
封装后接入 Harbor，注册为 `heuristic-env` agent。

### 任务四：SkillOpt 训练

将 SkillOpt 优化框架配置到 SKILL.md 上，完整 6 阶段流水线：
```
Rollout → Reflect → Aggregate → Select → Update → Evaluate
```

核心实现：
- `HarborEnvAdapter`：包装 Harbor CLI，每个 rollout 调用 `harbor run`
- `SkillOptDataLoader`：通用数据加载器（支持 HuggingFace 数据集）
- 支持 `claude-code` 和 `heuristic-env` 两种 agent

### 任务五：脚本代码优化

将 SkillOpt 的优化目标从 SKILL.md 文本迁移到 Python 源代码。
使用 `full_rewrite_minibatch` 模式（整脚本重写，而非文本 patch）。
自定义 analyst prompt，分析脚本执行日志后输出完整改进版。

---

## 用法

```bash
# 1. 设置环境变量
export ANTHROPIC_API_KEY=sk-...
export ANTHROPIC_BASE_URL=https://www.right.codes/deepseek/anthropic

# 2. 启动 SkillOpt 训练
#    MEnvBench（正在跑）
python run_skillopt.py skillopt_adapter/config_menvbench.yaml

#    Multi-Docker-Eval
python run_skillopt.py skillopt_adapter/config.yaml

#    脚本代码优化模式
python run_skillopt.py skillopt_adapter/config_script_opt.yaml

# 3. 只验证配置不跑训练
python run_skillopt.py skillopt_adapter/config_menvbench.yaml --validate
```

---

## 环境要求

- Python 3.10+
- Harbor CLI（`pip install harbor`）
- SkillOpt 包（`pip install skillopt`）
- 服务器需配置代理（容器内通过 HTTP_PROXY 访问 GitHub / PyPI）
