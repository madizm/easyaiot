#!/bin/bash

# ============================================
# VIDEO 构建资源预下载脚本（ARM架构）
# 1) 保存构建所需 Docker 镜像到 .build-cache/docker-images
# 2) 下载 requirements.txt 的 pip wheel 到 .build-cache/pip-wheels
# ============================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_command() {
    command -v "$1" >/dev/null 2>&1
}

image_to_tar_name() {
    echo "$1" | sed 's#[/:]#_#g'
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

EASYAIOT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../.scripts/docker/init-build-cache-dirs.sh
source "${EASYAIOT_ROOT}/.scripts/docker/init-build-cache-dirs.sh"

BUILD_CACHE_DIR="${SCRIPT_DIR}/.build-cache"
DOCKER_IMAGES_DIR="${BUILD_CACHE_DIR}/docker-images"
PIP_WHEELS_DIR="${BUILD_CACHE_DIR}/pip-wheels"

ARM_BASE_IMAGE="${ARM_BASE_IMAGE:-pytorch/manylinuxaarch64-builder:cuda12.9}"

init_project_build_cache_dirs "$SCRIPT_DIR"

if ! check_command docker; then
    print_error "未检测到 docker，请先安装 Docker"
    exit 1
fi

download_docker_image() {
    local image="$1"
    local tar_file="${DOCKER_IMAGES_DIR}/$(image_to_tar_name "$image").tar"

    print_info "拉取镜像: $image"
    docker pull "$image"
    print_info "保存镜像到: $tar_file"
    docker save -o "$tar_file" "$image"
    print_success "镜像已保存: $image"
}

print_info "下载并保存 Docker 基础镜像..."
download_docker_image "$ARM_BASE_IMAGE"

download_pip_packages() {
    print_info "清理旧的 pip wheel，避免不同 Python ABI 混用..."
    find "$PIP_WHEELS_DIR" -maxdepth 1 -type f -delete 2>/dev/null || true

    print_warning "依赖包体积较大，首次下载可能需要 10–30 分钟，请勿中断"
    print_info "使用 ARM 基础镜像 ${ARM_BASE_IMAGE} 下载 pip wheel（无本地镜像时会先拉取）..."
    set +e
    docker run --rm \
        -e PYTHONUNBUFFERED=1 \
        -v "$SCRIPT_DIR:/work" \
        -w /work \
        "$ARM_BASE_IMAGE" \
        /bin/bash -lc '
set -e
if [ -x /opt/python/cp311-cp311/bin/pip3.11 ]; then
    PIP_BIN=/opt/python/cp311-cp311/bin/pip3.11
elif [ -x /opt/python/cp310-cp310/bin/pip3.10 ]; then
    PIP_BIN=/opt/python/cp310-cp310/bin/pip3.10
elif command -v pip3 >/dev/null 2>&1; then
    PIP_BIN=$(command -v pip3)
else
    echo "未找到可用 pip3"
    exit 1
fi

"$PIP_BIN" --version
"$PIP_BIN" download -r requirements.txt -d .build-cache/pip-wheels --timeout 120 --retries 3 -i https://pypi.tuna.tsinghua.edu.cn/simple
'
    local docker_download_status=$?
    set -e

    if [ $docker_download_status -eq 0 ]; then
        print_success "pip wheel 下载完成（与目标容器 ABI 一致）"
        return 0
    fi

    if [ "${ALLOW_HOST_PIP_FALLBACK:-0}" != "1" ]; then
        print_error "容器内下载失败（默认禁用本机回退，避免 ABI 不匹配）"
        print_info "如确需回退: ALLOW_HOST_PIP_FALLBACK=1 ./cache_resources_arm.sh"
        return 1
    fi

    print_warning "容器内下载失败，使用本机 python3 回退..."
    if ! check_command python3 || ! python3 -m pip --version >/dev/null 2>&1; then
        print_error "本机 python3/pip 不可用"
        return 1
    fi

    python3 -m pip download -r requirements.txt -d "$PIP_WHEELS_DIR" --timeout 120 --retries 3
    print_warning "已使用本机环境回退下载，可能与目标容器 ABI 不一致"
    return 0
}

print_info "开始下载 pip 依赖到: $PIP_WHEELS_DIR"
download_pip_packages

print_info "构建缓存目录："
du -sh "$BUILD_CACHE_DIR" 2>/dev/null || true
print_success "预下载完成，可使用 install_linux_arm.sh 构建"
