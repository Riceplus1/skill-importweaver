---
name: importweaver
description: Automatically configure Python project environments — install dependencies, resolve conflicts, and make pytest pass. Use when setting up a Python repository for the first time or debugging environment issues.
---

# importweaver — Python 环境自动配置

> 将一个 GitHub 仓库的环境配通，让测试能跑起来。

---

## 目标

你的核心任务是为一个 Python 仓库配置运行环境，让测试能通过。

**优先级：**
1. **pytest 收集成功** — `pytest --collect-only` 必须 exit 0（或 exit 5，表示没有测试可收集）
2. **pytest 运行通过** — 若收集成功，让测试全部通过（exit 0）
3. **减少 pyright missing-imports** — 在不破坏测试的前提下，尽量压低

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

## 启动流程

到一个新仓库后，**按顺序执行以下步骤：**

### 0. 先配镜像源（节省外网流量）

```bash
bash scripts/setup_mirrors.sh
```

### 1. 了解项目结构

```bash
ls -la
```

### 2. 查看依赖文件

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

### 3. 检查 Makefile

```bash
make help 2>/dev/null || cat Makefile
```

如果存在，优先使用 `make test` / `make install` 等已定义的工作流。

### 4. 阅读 README / CONTRIBUTING

**必须读**，里面可能有：
- 精确的测试命令
- 需要的系统包
- 环境变量配置
- 外部服务和数据集
- 配置示例文件（如 `configuration_example.py`）

如果 README 提到其他外部仓库的依赖，也要去读那些仓库的 README。

### 5. 确定 Python 版本

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
