#!/bin/bash

# ============================================
# 标注平台离线 pip 资源预下载脚本
# ============================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_command() { command -v "$1" >/dev/null 2>&1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PIP_WHEELS_DIR="${SCRIPT_DIR}/.build-cache/pip-wheels"
BASE_IMAGE="${BASE_IMAGE:-python:3.10-slim}"

mkdir -p "$PIP_WHEELS_DIR"

if ! check_command docker; then
    print_error "未检测到 docker"
    exit 1
fi

find "$PIP_WHEELS_DIR" -maxdepth 1 -type f -delete 2>/dev/null || true

print_warning "依赖包体积较大，首次下载可能需要数分钟，请勿中断"
print_info "使用 ${BASE_IMAGE} 下载标注平台 pip 离线包（无本地镜像时会先拉取）..."
docker run --rm \
    -e PYTHONUNBUFFERED=1 \
    -v "$SCRIPT_DIR:/work" \
    -w /work \
    "$BASE_IMAGE" \
    /bin/bash -lc 'pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && pip download -r requirements.txt -d .build-cache/pip-wheels --timeout 120 --retries 3 -i https://pypi.tuna.tsinghua.edu.cn/simple'

print_success "pip wheel 已保存到 $PIP_WHEELS_DIR"
