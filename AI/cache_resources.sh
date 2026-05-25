#!/bin/bash

# ============================================
# AI 离线 pip 资源预下载脚本（x86_64）
# ============================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_command() { command -v "$1" >/dev/null 2>&1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BUILD_CACHE_DIR="${SCRIPT_DIR}/.build-cache"
PIP_WHEELS_DIR="${BUILD_CACHE_DIR}/pip-wheels"
BASE_IMAGE="${BASE_IMAGE:-pytorch/pytorch:2.9.0-cuda12.8-cudnn9-devel}"

mkdir -p "$PIP_WHEELS_DIR"

if ! check_command docker; then
    print_error "未检测到 docker，请先安装 Docker"
    exit 1
fi

print_info "清理旧的 pip 离线包..."
find "$PIP_WHEELS_DIR" -maxdepth 1 -type f -delete 2>/dev/null || true

print_warning "依赖包体积较大，首次下载可能需要 10–30 分钟，请勿中断"
print_info "使用基础镜像 ${BASE_IMAGE} 下载与容器一致的 pip 离线包（无本地镜像时会先拉取）..."
set +e
docker run --rm \
    -e PYTHONUNBUFFERED=1 \
    -v "$SCRIPT_DIR:/work" \
    -w /work \
    "$BASE_IMAGE" \
    /bin/bash -lc 'pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && pip download -r requirements.txt -d .build-cache/pip-wheels --timeout 120 --retries 3 -i https://pypi.tuna.tsinghua.edu.cn/simple'
status=$?
set -e

if [ $status -ne 0 ]; then
    if [ "${ALLOW_HOST_PIP_FALLBACK:-0}" != "1" ]; then
        print_error "容器内下载失败；如需本机回退: ALLOW_HOST_PIP_FALLBACK=1 ./cache_resources.sh"
        exit 1
    fi
    print_warning "容器内下载失败，使用本机 python3 回退..."
    python3 -m pip download -r requirements.txt -d "$PIP_WHEELS_DIR" --timeout 120 --retries 3 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple
fi

du -sh "$BUILD_CACHE_DIR" 2>/dev/null || true
print_success "pip wheel 已保存到 $PIP_WHEELS_DIR"
