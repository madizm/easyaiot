#!/bin/bash
# ============================================
# EasyAIoT Python 离线 wheel 预下载（按模块隔离）
# 目录: .build-cache/{ai,video,auto-labeling}/pip-wheels
# Docker 构建使用各模块 requirements-docker.txt，与镜像内 pip install 一致
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
EASYAIOT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=init-build-cache-dirs.sh
source "${SCRIPT_DIR}/init-build-cache-dirs.sh"

AI_DIR="${EASYAIOT_ROOT}/AI"
VIDEO_DIR="${EASYAIOT_ROOT}/VIDEO"
AUTO_LABELING_DIR="${EASYAIOT_ROOT}/AI/services/auto-labeling"

PYTORCH_BASE_IMAGE="${BASE_IMAGE:-pytorch/pytorch:2.9.0-cuda12.8-cudnn9-devel}"
AUTO_LABELING_BASE_IMAGE="${AUTO_LABELING_BASE_IMAGE:-pytorch/pytorch:2.9.0-cuda12.8-cudnn9-runtime}"

# PyPI 仅提供 sdist、需在 devel 镜像中预编译为 wheel（runtime 无 gcc）
SDIST_WHEEL_SPECS=(
    "netifaces==0.11.0"
)

# 参数: all（默认）| ai | video | auto-labeling
TARGET_MODULE="${1:-all}"

module_req_docker_file() {
    case "$(easyaiot_normalize_python_cache_module "$1")" in
        ai) echo "${AI_DIR}/requirements-docker.txt" ;;
        video) echo "${VIDEO_DIR}/requirements-docker.txt" ;;
        auto-labeling) echo "${AUTO_LABELING_DIR}/requirements-docker.txt" ;;
    esac
}

module_base_image() {
    case "$(easyaiot_normalize_python_cache_module "$1")" in
        auto-labeling) echo "$AUTO_LABELING_BASE_IMAGE" ;;
        *) echo "$PYTORCH_BASE_IMAGE" ;;
    esac
}

# 展开 -r includes，避免合并文件中出现无法解析的相对引用
append_requirements_file() {
    local req_file="$1"
    local out_file="$2"
    local req_dir line include_path

    [ -f "$req_file" ] || return 0
    req_dir="$(cd "$(dirname "$req_file")" && pwd)"

    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%%#*}"
        line="$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        [ -z "$line" ] && continue
        case "$line" in
            --index-url*) ;;
            -r*)
                include_path="${line#-r }"
                include_path="${include_path#-r}"
                include_path="$(echo "$include_path" | sed 's/^[[:space:]]*//')"
                if [[ "$include_path" != /* ]]; then
                    include_path="${req_dir}/${include_path}"
                fi
                append_requirements_file "$include_path" "$out_file"
                ;;
            *)
                echo "$line" >> "$out_file"
                ;;
        esac
    done < "$req_file"
}

prepare_flattened_requirements() {
    local module="$1"
    local req_file out_file
    req_file="$(module_req_docker_file "$module")"
    out_file="$(mktemp)"
    : > "$out_file"
    echo "--index-url https://pypi.tuna.tsinghua.edu.cn/simple" >> "$out_file"
    if [ ! -f "$req_file" ]; then
        print_error "requirements-docker 不存在: $req_file"
        rm -f "$out_file"
        return 1
    fi
    append_requirements_file "$req_file" "$out_file"
    echo "$out_file"
}

# 将仅有 tar.gz 的 C 扩展预编译为 wheel，供 runtime 基础镜像离线/混合安装
build_required_sdist_wheels() {
    local wheels_dir="$1"
    local build_image="${SDIST_WHEEL_BUILD_IMAGE:-$PYTORCH_BASE_IMAGE}"
    local spec pkg_name

    for spec in "${SDIST_WHEEL_SPECS[@]}"; do
        pkg_name="${spec%%==*}"
        if compgen -G "${wheels_dir}/${pkg_name}-"*.whl >/dev/null 2>&1; then
            print_info "[sdist] 已有 ${pkg_name} wheel，跳过"
            continue
        fi
        print_info "[sdist] 使用 ${build_image} 编译 ${spec} wheel..."
        docker run --rm \
            -v "${wheels_dir}:/wheels" \
            "$build_image" \
            /bin/bash -lc "set -e
pip install -q --upgrade pip wheel setuptools -i https://pypi.tuna.tsinghua.edu.cn/simple
find_links=''
if compgen -G '/wheels/${pkg_name}-*.tar.gz' >/dev/null; then
  find_links='--find-links /wheels'
fi
pip wheel '${spec}' -w /wheels --no-deps \${find_links} -i https://pypi.tuna.tsinghua.edu.cn/simple"
        if ! compgen -G "${wheels_dir}/${pkg_name}-"*.whl >/dev/null 2>&1; then
            print_error "[sdist] 未生成 ${pkg_name} wheel"
            return 1
        fi
        print_success "[sdist] ${pkg_name} wheel 已写入 ${wheels_dir}"
    done
}

download_module_wheels() {
    local module="$1"
    local wheels_dir base_image flat_req status

    module="$(easyaiot_normalize_python_cache_module "$module")" || return 1
    wheels_dir="$(pip_wheels_build_context_dir_for "$EASYAIOT_ROOT" "$module")"
    base_image="$(module_base_image "$module")"
    flat_req="$(prepare_flattened_requirements "$module")"
    trap 'rm -f "$flat_req"' RETURN

    if [ "${CLEAR_PIP_WHEELS:-0}" = "1" ]; then
        print_info "[${module}] 清理旧 wheel（CLEAR_PIP_WHEELS=1）..."
        find "$wheels_dir" -maxdepth 1 -type f -delete 2>/dev/null || true
    fi

    print_info "[${module}] requirements-docker → ${flat_req}（$(wc -l < "$flat_req") 行）"
    print_info "[${module}] 目标: ${wheels_dir}"
    print_info "[${module}] 镜像: ${base_image}"

    set +e
    docker run --rm \
        -e PYTHONUNBUFFERED=1 \
        -v "${flat_req}:/tmp/requirements-docker.flat:ro" \
        -v "${wheels_dir}:/wheels" \
        "$base_image" \
        /bin/bash -lc 'pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && pip download -r /tmp/requirements-docker.flat -d /wheels --timeout 120 --retries 3 -i https://pypi.tuna.tsinghua.edu.cn/simple'
    status=$?
    set -e

    if [ $status -ne 0 ]; then
        if [ "${ALLOW_HOST_PIP_FALLBACK:-0}" != "1" ]; then
            print_error "[${module}] 容器内下载失败；回退: ALLOW_HOST_PIP_FALLBACK=1 $0 ${module}"
            return 1
        fi
        print_warning "[${module}] 容器内下载失败，使用本机 python3 回退..."
        python3 -m pip download -r "$flat_req" -d "$wheels_dir" --timeout 120 --retries 3 \
            -i https://pypi.tuna.tsinghua.edu.cn/simple
    fi

    build_required_sdist_wheels "$wheels_dir"

    print_success "[${module}] wheel 已保存到 ${wheels_dir}"
}

if ! check_command docker; then
    print_error "未检测到 docker，请先安装 Docker"
    exit 1
fi

init_easyaiot_build_cache_dirs "$EASYAIOT_ROOT"

print_warning "依赖包体积较大，首次按模块下载可能需要 10–30 分钟/模块，请勿中断"

case "${TARGET_MODULE,,}" in
    all)
        for module in "${EASYAIOT_PYTHON_CACHE_MODULES[@]}"; do
            download_module_wheels "$module"
        done
        ;;
    ai|video|auto-labeling|auto_labeling|autolabeling|labeling)
        download_module_wheels "$TARGET_MODULE"
        ;;
    *)
        print_error "未知模块: ${TARGET_MODULE}（支持: all, ai, video, auto-labeling）"
        exit 1
        ;;
esac

du -sh "$(easyaiot_build_cache_base "$EASYAIOT_ROOT")" 2>/dev/null || true
print_success "Python 离线 wheel 预下载完成（模块: ${TARGET_MODULE})"
