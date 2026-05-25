#!/bin/bash
# 初始化各模块 Docker 构建依赖缓存目录（宿主机持久化，构建时 bind mount）
# 用法: source 本脚本后调用 init_project_build_cache_dirs "/path/to/VIDEO"
#
# 环境变量:
#   BUILD_CACHE_UID  默认 1000（与常见 docker 用户一致，勿在容器内 chown）
#   BUILD_CACHE_GID  默认 1000

: "${BUILD_CACHE_UID:=1000}"
: "${BUILD_CACHE_GID:=1000}"

init_project_build_cache_dirs() {
    local project_dir="${1:-.}"
    local base="${project_dir}/.build-cache"

    mkdir -p \
        "${base}/pnpm-store" \
        "${base}/m2/repository" \
        "${base}/pip-cache" \
        "${base}/pip-cache/http" \
        "${base}/pip-wheels" \
        "${base}/docker-images"

    # 仅在宿主机设置属主，不在 Dockerfile 内改权限
    if [ "$(id -u)" -eq 0 ]; then
        chown -R "${BUILD_CACHE_UID}:${BUILD_CACHE_GID}" "${base}" 2>/dev/null || true
    elif command -v chown >/dev/null 2>&1; then
        chown -R "${BUILD_CACHE_UID}:${BUILD_CACHE_GID}" "${base}" 2>/dev/null || \
            print_build_cache_chown_hint "${base}" 2>/dev/null || true
    fi
}

print_build_cache_chown_hint() {
    echo "[build-cache] 提示: 若构建报权限错误，请执行: sudo chown -R ${BUILD_CACHE_UID}:${BUILD_CACHE_GID} $1"
}

# 构建前统一启用 BuildKit（Dockerfile RUN --mount=bind 需要）
enable_docker_buildkit() {
    export DOCKER_BUILDKIT=1
    export BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}"
}

# 宿主机 pip http 缓存目录（docker build --build-context pip-cache=...）
pip_cache_build_context_dir() {
    local project_dir="${1:-.}"
    local cache
    cache="$(cd "$project_dir" && pwd)/.build-cache/pip-cache"
    mkdir -p "${cache}/http"
    echo "$cache"
}
