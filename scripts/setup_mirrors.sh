#!/usr/bin/env bash
# ============================================================
# setup_mirrors.sh — 一键配置 TUNA 镜像源 (PyPI + Ubuntu)
# ============================================================
# 在容器内首次执行，减少对外网流量的依赖。
# 同时兼容有 sudo / 无 sudo 的环境。
# ============================================================
set -euo pipefail

MIRROR_PYPI="https://pypi.tuna.tsinghua.edu.cn/simple"
MIRROR_UBUNTU="mirrors.tuna.tsinghua.edu.cn"

log() { echo "[mirrors] $*"; }

# --------------------------------------------------
# 1. PyPI 镜像 (pip)
# --------------------------------------------------
configure_pip() {
    log "Configuring PyPI mirror → ${MIRROR_PYPI}"

    # 全局配置 (pip >= 10)
    pip config set global.index-url "$MIRROR_PYPI" 2>/dev/null || true

    # 兼容 pip < 10 (没有 config 子命令时)
    mkdir -p ~/.config/pip ~/.pip
    cat > ~/.config/pip/pip.conf <<-EOF 2>/dev/null || true
[global]
index-url = ${MIRROR_PYPI}
trusted-host = pypi.tuna.tsinghua.edu.cn
EOF
    cp ~/.config/pip/pip.conf ~/.pip/pip.conf 2>/dev/null || true

    log "PyPI mirror configured ✓"
}

# --------------------------------------------------
# 2. Ubuntu apt 镜像
# --------------------------------------------------
configure_apt() {
    log "Configuring apt mirror → ${MIRROR_UBUNTU}"

    # 检测 Ubuntu 版本代号
    UBUNTU_CODENAME=""
    if [ -f /etc/os-release ]; then
        UBUNTU_CODENAME=$(grep -oP 'VERSION_CODENAME=\K.*' /etc/os-release 2>/dev/null || true)
    fi

    # 如果没有 os-release 或 codename 为空，尝试 lsb_release
    if [ -z "$UBUNTU_CODENAME" ] && command -v lsb_release &>/dev/null; then
        UBUNTU_CODENAME=$(lsb_release -cs 2>/dev/null || true)
    fi

    # 仍然没有 → 用镜像站自动重定向
    if [ -z "$UBUNTU_CODENAME" ]; then
        log "Could not detect Ubuntu codename; will use mirror with automatic redirect"
        UBUNTU_CODENAME=""
    fi

    # 检查是否有 sudo
    HAS_SUDO=0
    if command -v sudo &>/dev/null && sudo -n true 2>/dev/null; then
        HAS_SUDO=1
    fi

    # 没有 sudo 且不是 root → 跳过 apt 配置（非致命）
    if [ "$HAS_SUDO" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
        log "No sudo access, skipping apt mirror (non-fatal)"
        log "Hint: if you need apt packages, try: apt-get install -y -qq <pkg>"
        return
    fi

    SUDO=""
    [ "$(id -u)" -ne 0 ] && SUDO="sudo"

    # --- 新版 Ubuntu (>= 24.04): 使用 /etc/apt/sources.list.d/ubuntu.sources ---
    if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
        log "Detected Ubuntu 24.04+ format (ubuntu.sources)"
        $SUDO sed -i "s|http://archive.ubuntu.com/ubuntu/|http://${MIRROR_UBUNTU}/ubuntu/|g" \
            /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
        $SUDO sed -i "s|http://security.ubuntu.com/ubuntu/|http://${MIRROR_UBUNTU}/ubuntu/|g" \
            /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
        $SUDO sed -i "s|https://archive.ubuntu.com/ubuntu/|http://${MIRROR_UBUNTU}/ubuntu/|g" \
            /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
        $SUDO sed -i "s|https://security.ubuntu.com/ubuntu/|http://${MIRROR_UBUNTU}/ubuntu/|g" \
            /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true
    # --- 旧版 Ubuntu: 使用 /etc/apt/sources.list ---
    elif [ -f /etc/apt/sources.list ]; then
        log "Detected legacy format (sources.list)"
        $SUDO sed -i "s|http://archive.ubuntu.com/ubuntu/|http://${MIRROR_UBUNTU}/ubuntu/|g" \
            /etc/apt/sources.list 2>/dev/null || true
        $SUDO sed -i "s|http://security.ubuntu.com/ubuntu/|http://${MIRROR_UBUNTU}/ubuntu/|g" \
            /etc/apt/sources.list 2>/dev/null || true
        $SUDO sed -i "s|https://archive.ubuntu.com/ubuntu/|http://${MIRROR_UBUNTU}/ubuntu/|g" \
            /etc/apt/sources.list 2>/dev/null || true
        $SUDO sed -i "s|https://security.ubuntu.com/ubuntu/|http://${MIRROR_UBUNTU}/ubuntu/|g" \
            /etc/apt/sources.list 2>/dev/null || true
        # 如果没有替换到任何内容（说明 sources.list 可能用的是别的域名或直接写 IP）
        # 额外尝试 deb.debian.org
        $SUDO sed -i "s|http://deb.debian.org/debian|http://${MIRROR_UBUNTU}/debian|g" \
            /etc/apt/sources.list 2>/dev/null || true
    else
        log "No apt sources file found; skipping apt mirror (non-fatal)"
    fi

    log "Apt mirror configured ✓"
    log "You may want to run: apt-get update (if installing packages)"
}

# --------------------------------------------------
# 3. (可选) 其他镜像
# --------------------------------------------------
# 目前只配了 PyPI 和 Ubuntu apt，后续可扩展：
# - conda (conda config --add channels ...)
# - npm (npm config set registry ...)
# - rust (cargo 海外一般够用)

# --------------------------------------------------
# 主入口
# --------------------------------------------------
log "===== Mirror Configuration ====="
log "PyPI → ${MIRROR_PYPI}"
log "Ubuntu → ${MIRROR_UBUNTU}"
log ""echo ""

configure_pip
echo ""
configure_apt
echo ""

log "===== Done ====="
log "These changes are safe to run multiple times (idempotent)."
echo ""
log "Tip: To verify PyPI mirror: pip install --dry-run flask 2>&1 | tail -3"
log "Tip: To verify apt mirror: apt-get update --dry-run 2>&1 | head -5"
