# BuildKit（DOCKER_BUILDKIT=1）内置 Dockerfile 前端，支持 RUN --mount，无需拉取 docker/dockerfile 镜像
# 标注平台以 CPU 推理为主（Ultralytics 未指定 device=cuda；compose 无 nvidia runtime）。
# 使用 runtime 镜像（非 devel）以减小体积；若需 GPU 加速可在 compose 中启用 runtime: nvidia。
ARG BASE_IMAGE=pytorch/pytorch:2.9.0-cuda12.8-cudnn9-runtime
FROM ${BASE_IMAGE} AS base

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    PIP_UPGRADE_STRATEGY=only-if-needed \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

FROM base AS dependencies

RUN set -ex && \
    ln -sf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    sed -i 's|http://.*archive.ubuntu.com|https://mirrors.huaweicloud.com|g' /etc/apt/sources.list && \
    sed -i 's|http://.*security.ubuntu.com|https://mirrors.huaweicloud.com|g' /etc/apt/sources.list

# 标注平台仅需 OpenCV / Ultralytics 运行时库
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt-cache-auto-labeling \
    --mount=type=cache,target=/var/lib/apt,sharing=locked,id=apt-lib-auto-labeling \
    set -ex && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gcc \
        python3-dev \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

FROM dependencies AS python-deps

COPY requirements-docker.txt requirements-base.txt ./
COPY --from=pip-wheels . /opt/offline-pip
ARG OFFLINE_MODE=0

RUN --mount=type=bind,from=pip-cache,source=.,target=/mnt/pip-cache,rw \
    --mount=type=cache,target=/tmp/pip-wheels-build,id=pip-wheels-build-auto-labeling \
    set -ex && \
    mkdir -p /mnt/pip-cache/http /tmp/pip-wheels-build && \
    rm -rf /mnt/pip-cache/wheels && \
    ln -sfn /tmp/pip-wheels-build /mnt/pip-cache/wheels && \
    export PIP_CACHE_DIR=/mnt/pip-cache && \
    pip install --upgrade pip -i "${PIP_INDEX_URL}" && \
    if [ -n "$(find /opt/offline-pip -maxdepth 1 -type f 2>/dev/null)" ]; then \
        if [ "$OFFLINE_MODE" = "1" ]; then \
            echo "OFFLINE_MODE=1：仅使用 pip-wheels 离线安装..." && \
            pip install -r requirements-docker.txt --no-index --find-links /opt/offline-pip --prefer-binary; \
        elif pip install -r requirements-docker.txt --dry-run --no-index --find-links /opt/offline-pip --prefer-binary >/dev/null 2>&1; then \
            echo "pip-wheels 可覆盖全部依赖，离线安装..." && \
            pip install -r requirements-docker.txt --no-index --find-links /opt/offline-pip --prefer-binary; \
        else \
            echo "pip-wheels 与 requirements 未完全匹配，使用清华源 + find-links 混合安装..." && \
            pip install -r requirements-docker.txt --find-links /opt/offline-pip --prefer-binary -i "${PIP_INDEX_URL}"; \
        fi; \
    elif [ "$OFFLINE_MODE" = "1" ]; then \
        echo "OFFLINE_MODE=1 且无 pip-wheels，请先执行 cache_resources.sh" && exit 1; \
    else \
        pip install -r requirements-docker.txt -i "${PIP_INDEX_URL}"; \
    fi

FROM python-deps AS runtime

COPY . .

RUN test -f static/style.css && test -f static/script.js && test -f static/all.min.css

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fs http://localhost:8000/ > /dev/null || exit 1

CMD ["python", "app.py", "--env=docker"]
