---
name: importweaver
description: Configure Python project environments OR fix specific bugs in Python repositories. Use when setting up a Python project for testing, or when asked to fix a bug/issue in a Python codebase.
---

# importweaver — Python 环境自动配置

> 将一个 GitHub 仓库的环境配通，让测试能跑起来。

---

## 目标

**这个 Skill 有两种使用模式，根据任务描述自动判断走哪条路：**

### 模式 A：配环境（Make tests pass）

目标是为一个 Python 仓库配置运行环境，让现有测试能通过。

**优先级：**
1. **pytest 收集成功** — `pytest --collect-only` 必须 exit 0（或 exit 5，表示没有测试可收集）
2. **pytest 运行通过** — 若收集成功，让测试全部通过（exit 0）
3. **减少 pyright missing-imports** — 在不破坏测试的前提下，尽量压低

---

### 模式 B：修 Bug（Fix a specific issue）

目标是修复一个具体的 bug。**重点不是让测试通过，而是确认真实地修好了问题。**

> ⚠️ 这里的「让所有测试通过」是结果，不是目标。**先复现 bug，再修，再验证。**

---

## 环境说明

### 容器环境

- 默认 Python 镜像基于 Debian，**没有 sudo**。安装系统包直接用 `apt-get install -y -qq pkg1 pkg2`
- apt 锁冲突时（dpkg lock），sleep 30s 后重试，指数退避直到锁释放
- 命令在独立 shell 中执行，**环境变量不跨命令持久化**
  - 需要持久化时：`echo "export NAME=value" >> ~/.bashrc`
  - 需要 PYTHONPATH 时：`echo "export PYTHONPATH=/repo:$PYTHONPATH" >> ~/.bashrc`
- 默认 CPU-only 环境。GPU 相关包优先装 CPU 变体：`uv pip install --system ".[cpu]"`

### 镜像命名规则

`python:<version>` 追加后缀：`-mirrors`（配置镜像源） `-bootstrap`（安装基础构建工具）
示例：`python:3.10-mirrors-bootstrap`

### ⚡ 第一步：配置镜像源（优先执行，节省流量）

先跑一键镜像配置脚本，将 PyPI 和 Ubuntu apt 切换为 TUNA 清华镜像源：

```bash
bash scripts/setup_mirrors.sh
```

这个脚本会自动检测是否有 sudo，无 sudo 环境至少会配好 PyPI 源。

---

## Bug 修复流程（模式 B）

当你收到的任务描述是修一个 bug 时，**严格按照以下流程执行，不要跳过任何步骤。**

---

### 第 1 步：理解 bug 描述（5 分钟）

仔细阅读 bug 描述，回答以下问题：

1. **期望行为是什么？** — 描述说应该怎样工作？
2. **实际行为是什么？** — 描述说现在是什么表现？
3. **问题出在哪一层？** — import 错误？API 调用方式不对？参数传递？逻辑判断？
4. **复现条件是什么？** — 什么参数、什么配置、什么输入会触发？

把答案写下来。**如果描述里提到了代码片段，直接去看对应文件。**

---

### 第 2 步：写复现脚本（最重要！）

**在改任何代码之前**，先写一个最小复现脚本 `reproduce.py`，基于 bug 描述模拟出问题。

```bash
# 创建一个复现文件，模拟 bug 描述的场景
# 内容基于 bug 描述自行编写
cat > /workspace/reproduce.py << 'EOF'
# 从描述中提取最小复现步骤
# ...
EOF

# 运行确认 bug 存在
python /workspace/reproduce.py
```

**为什么要先写复现脚本？**
- 让你确切知道 bug 长什么样
- 验证修复后 bug 是否消失
- 防止「以为修好了但其实没修」

**复现脚本的原则：**
- 最小化：只包含触发 bug 的必要代码
- 可执行：直接 `python reproduce.py` 能跑
- 检查明确：如果有预期输出，用 assert 检查

> 🔴 **在写过复现脚本并确认 bug 存在之前，不要碰任何源码。**

---

### 第 3 步：读源码定位根因

有了复现脚本后，用它在代码中追踪问题：

```bash
# 在复现脚本中加 debug 输出，追踪调用链
# 或直接用 python -c 片段测试特定函数
python -c "
import logbook  # 替换为实际模块
# 测试特定函数的输入输出
help(logbook.MailHandler)
"
```

**定位根因的方法：**
1. 从复现脚本的入口函数开始，逐层看代码
2. 关注 bug 描述中提到的参数/函数
3. 用 `git log` 或 `git blame` 查看相关代码的修改历史
4. **不要只跑 `pytest` 就觉得没问题了**——现有测试不覆盖 bug

---

### 第 4 步：修复代码

修代码时遵循：

1. **只改有问题的行** — 不要顺带重构、格式化、优化
2. **理解原作者的意图** — 不要破坏正常逻辑
3. **一个修改解决一个问题** — 不要一次改多个文件
4. **如果多个位置都可能是根因，逐一排查，一次只试一个**

```bash
# 修完后立刻用复现脚本验证
python /workspace/reproduce.py

# 确认 bug 消失了，同时跑全量测试确保没回归
cd /workspace/repo && python -m pytest
```

---

### 第 5 步：验证 + 回归

```bash
# 1. 先验证 bug 已修复（复现脚本输出符合期望）
python /workspace/reproduce.py

# 2. 再跑全量测试，确认没有回归
cd /workspace/repo
python -m pytest --tb=short -q 2>&1 | tail -20

# 3. 跑收集检查
python -m pytest --collect-only -q 2>&1 | tail -5
```

**退出条件（全部满足）：**
- ✅ 复现脚本输出符合期望行为
- ✅ pytest 收集成功（exit 0 或 exit 5）
- ✅ 所有测试通过（exit 0，或只有 skipped）
- ✅ 没有修改测试文件、配置文件、pytest 配置

---

### 「测试全过了」陷阱 ⚠️

这是最常见的翻车原因。**记住：**

```
现有测试全过 ≠ bug 已修复
现有测试全过 ≠ bug 已修复
现有测试全过 ≠ bug 已修复
```

**为什么？** 因为 bug 之所以是 bug，就是因为它没有被现有测试覆盖到。所以：
- ✅ 要做的：从 bug 描述出发，写新脚本验证
- ❌ 不要做的：「测试过了→代码没问题→修完了」

---

## 模式判断

任务描述中**提到 bug / issue / fix / 修复 / 错误 / 问题** 时 ⟶ **模式 B（修 Bug）**
任务描述中**只要求配环境、跑测试**时 ⟶ **模式 A（配环境）**

到一个新仓库后，**按顺序执行以下步骤：**

### 0. 先配镜像源（节省外网流量）

```bash
bash scripts/setup_mirrors.sh
```

### 1. 了解项目结构

```bash
ls -la
```

### 2. 判断模式

根据任务描述判断走哪条路：
- 任务是**修 bug** → 跳到上方「Bug 修复流程」，从第 1 步开始
- 任务是**配环境** → 继续下面的步骤 3-6

### 3. 查看依赖文件

> ⚠️ 在进行步骤 0 配好镜像源之前，**不要**执行后续任何步骤。

```bash
python scripts/dependency_analysis.py /repo
```

扫描项目的依赖声明：
- pyproject.toml / setup.py / setup.cfg
- requirements*.txt / requirements/*.txt
- uv.lock / poetry.lock / pdm.lock / Pipfile
- tox.ini / Makefile

**重要：优先使用项目声明的包名，不要从 import 名字猜 PyPI 包名。** 很多包导入名和安装名不一样（如 `import cv2` -> `pip install opencv-python`）。

### 4. 检查 Makefile

```bash
make help 2>/dev/null || cat Makefile
```

如果存在，优先使用 `make test` / `make install` 等已定义的工作流。

### 5. 阅读 README / CONTRIBUTING

**必须读**，里面可能有：
- 精确的测试命令
- 需要的系统包
- 环境变量配置
- 外部服务和数据集
- 配置示例文件（如 `configuration_example.py`）

如果 README 提到其他外部仓库的依赖，也要去读那些仓库的 README。

### 6. 确定 Python 版本

从 `requires-python`（pyproject.toml）、`runtime.txt`、`.python-version` 判断。
如果当前版本不兼容，切换 Python 版本。

---

## 安装策略

### 第一步：自动配环境

先跑自动配置脚本，它能处理大部分情况：

```bash
python scripts/auto_configure.py /repo
```

### 第二步：手动补全（自动配置失败时）

如果自动配置没完全成功，按以下策略处理：

**安装项目本身：**
```bash
uv pip install --system -e .
```
- 始终用 `.` 安装，不要用包名（避免装错版本）
- 有 extras 时带上：`uv pip install --system -e .[cpu,dev]`

**安装测试依赖：**
- requirements-dev.txt / requirements-test.txt
- tox.ini 中 testenv 的 deps
- 项目的 `.[test]` / `.[dev]` extras

**有 lock 文件时优先使用：**
- `uv.lock` -> `uv export --frozen | uv pip install -r -`
- `poetry.lock` -> `poetry export --all-extras | uv pip install --system -r -`（不要用 `poetry install`）
- `pdm.lock` -> `pdm export --all-extras -f requirements | uv pip install --system -r -`
- `Pipfile` -> `pipenv requirements | uv pip install --system -r -`

**常用操作：**
- 批量装包：`uv pip install --system pkgA pkgB ...`（一次不要超过 50 个）
- 卸载：`uv pip uninstall pkgA pkgB`（不需要 `-y`）
- 编译失败时：`uv pip install --system --no-build-isolation ...`
- 分批发：如果一个包阻塞了批处理，先装能装的，再单独处理失败的那个

---

## 验证循环

> **每做一次环境变更，就验证一次。** 不要攒到最后一口气验证。

```bash
python scripts/run_validation.py /repo
```

`run_validation` 会做三件事：
1. **pytest 收集** — `pytest --collect-only -q`
2. **pytest 运行** — 如果收集成功则运行测试
3. **pyright 检查** — 扫描 missing-imports

验证输出中包含详细的诊断信息，包括：
- pytest 收集/运行的 exit code
- 缺了哪些模块（自动尝试 pip install）
- pyright 发现的 missing-imports
- 回归检测（之前能通过现在不能通过的）

**修复优先级：**
- **A 级优先**：修复 pytest 收集错误（import 问题、配置问题、插件缺失）
- **B 级其次**：修复 pytest 运行失败（服务、环境变量、fixtures、系统依赖）
- **C 级最后**：减少 pyright missing-imports

**退出条件：** 只有 pytest 运行通过（exit 0）或没有测试可收集（exit 5）时才算完成。pyright 错误可以忽略。

---

## 故障排查手册

### 1. 导入名不等于 PyPI 包名

很多包的 import 名和 pip 安装名不一样：

```python
import cv2        -> pip install opencv-python
import PIL        -> pip install Pillow
import skimage    -> pip install scikit-image
```

- 先在依赖文件（pyproject/requirements）中查找正确的包名
- 用 `pip show <pkg>` 查看已安装的包
- 版本不确定时：`python scripts/pypi_time_travel.py <pkg> /repo`

### 2. 外部服务 / 商业软件

- 需要系统服务 -> apt 安装并在容器内启动 daemon
- 需要 GUI 应用 -> 在容器内安装，不要 mock
- 配置环境变量 -> 持久化到 `~/.bashrc`

### 3. 缺失子模块 / 数据集 / fixtures

```bash
git submodule update --init --recursive
```

- 有下载脚本的按文档跑
- 有配置示例文件的（如 `configuration_example.py`），阅读并照做

### 4. C 扩展编译失败

- 优先装 binary wheel，避免从源码编译
- 需要系统构建依赖时：`apt-get install -y build-essential python3-dev libXXX-dev`
- 分包安装，定位具体哪个包编译失败

### 5. 装了包但还报缺子模块

通常版本不兼容：
- 尝试降级/升级那个包
- 用 `python scripts/pypi_time_travel.py <pkg> /repo` 查看仓库创建时间附近的版本
- 换个版本试试

### 6. Django 项目

- 需要创建 settings.py 配置数据库和 migrations，光设环境变量不够
- `AppRegistryNotReady` 错误 -> 装 `pytest-django` + 配置 pytest.ini

### 7. 奇怪的 import / 运行时错误

- 直接 `python -c "import pkg"` 测试，看具体报什么错
- 缺 CUDA 共享库（如 `libcudart.so.11.0`）-> 装对应 CUDA runtime
- CUDA 安装参考：
  - CUDA >= 12.4：`conda install -y -n repo -c nvidia cuda cuda-version=12.4`
  - CUDA 12.0-12.3：`conda install -y -n repo -c conda-forge cuda cuda-version=12.0`
  - CUDA 11.x：`conda install -y -n repo -c nvidia cudatoolkit=11.8`
  - cuDNN 8（CUDA 11.x）：`conda install -y -n repo -c nvidia cudnn=8 cuda-version=11`

---

## 可用脚本

| 脚本 | 作用 | 调用方式 |
|------|------|---------|
| `scripts/auto_configure.py` | 自动扫描并安装依赖 | `python scripts/auto_configure.py <repo_path>` |
| `scripts/run_validation.py` | 运行 pytest + pyright 验证 | `python scripts/run_validation.py <repo_path>` |
| `scripts/dependency_analysis.py` | 分析项目依赖文件结构 | `python scripts/dependency_analysis.py <repo_path>` |
| `scripts/pypi_time_travel.py` | 查某包在历史时间点的版本 | `python scripts/pypi_time_travel.py <pkg_name> <repo_path>` |
| `scripts/github_time_travel.py` | 查某 GitHub 仓库的历史 commit | `python scripts/github_time_travel.py <owner/repo> <repo_path>` |
| `scripts/setup_mirrors.sh` | 一键配置 TUNA 清华镜像源（PyPI + apt） | `bash scripts/setup_mirrors.sh` |

---

## 禁止事项

- 不要删除测试或弱化断言来让测试通过
- 不要修改测试文件、注入 mock 或绕过外部服务
- 不要修改源代码
- 不要修改 pytest 配置文件（pytest.ini / tox.ini / setup.cfg / conftest.py / pyproject.toml）—— 修改会在验证前被还原
- 可以临时改依赖文件（requirements*.txt / lock 文件），但会在验证前被还原
- 优先安装/配置，而不是改代码
- 尽量用 PYTHONPATH 而非改源码来解决 import 路径问题
