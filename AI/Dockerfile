# syntax=docker/dockerfile:1.4
# 使用PyTorch官方镜像作为基础镜像
FROM pytorch/pytorch:2.9.0-cuda12.8-cudnn9-devel AS base

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    CUDA_VISIBLE_DEVICES=0 \
    QT_QPA_PLATFORM=xcb \
    QT_X11_NO_MITSHM=1

# 设置工作目录
WORKDIR /app

# ======================= 第一阶段：系统依赖安装 =======================
FROM base AS dependencies

# 配置镜像源和时区
RUN set -ex && \
    # 设置时区
    ln -sf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    # 配置apt镜像源
    sed -i 's|http://.*archive.ubuntu.com|https://mirrors.huaweicloud.com|g' /etc/apt/sources.list && \
    sed -i 's|http://.*security.ubuntu.com|https://mirrors.huaweicloud.com|g' /etc/apt/sources.list

# 安装系统依赖包（单层RUN提高缓存效率）
RUN set -ex && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        wget \
        git \
        vim \
        htop \
        gnupg \
        gcc \
        g++ \
        make \
        libgl1 \
        libglib2.0-0 \
        libpython3-dev \
        libusb-1.0-0 \
        libsm6 \
        libgomp1 \
        libgtk-3-0 \
        x11-apps \
        libgl1-mesa-glx \
        libxcb-xinerama0 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# ======================= 第二阶段：Python依赖安装 =======================
FROM dependencies AS python-deps

COPY requirements.txt .
COPY .build-cache/pip-wheels /opt/offline-pip
ARG OFFLINE_MODE=0
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# http 缓存落盘宿主机 pip-cache；wheels 构建目录须可写（BuildKit cache）
RUN --mount=type=bind,from=pip-cache,source=.,target=/mnt/pip-cache,rw \
    --mount=type=cache,target=/tmp/pip-wheels-build,id=pip-wheels-build \
    set -ex && \
    mkdir -p /mnt/pip-cache/http /tmp/pip-wheels-build && \
    rm -rf /mnt/pip-cache/wheels && \
    ln -sfn /tmp/pip-wheels-build /mnt/pip-cache/wheels && \
    export PIP_CACHE_DIR=/mnt/pip-cache && \
    pip install --upgrade pip -i "${PIP_INDEX_URL}" && \
    if [ -n "$(find /opt/offline-pip -maxdepth 1 -type f 2>/dev/null)" ]; then \
        py_tag="$(python -c 'import sys; print("cp{}{}".format(sys.version_info.major, sys.version_info.minor))')" && \
        if grep -Eq '^torch([<>= ].*)?$' requirements.txt && ls /opt/offline-pip/torch-*.whl >/dev/null 2>&1; then \
            if ! ls /opt/offline-pip/torch-*-"${py_tag}"-*.whl >/dev/null 2>&1; then \
                echo "离线 wheel ABI 不匹配: ${py_tag}" && exit 1; \
            fi; \
        fi && \
        echo "使用宿主机 pip-wheels 离线安装..." && \
        pip install --user -r requirements.txt --no-index --find-links /opt/offline-pip --prefer-binary; \
    elif [ "$OFFLINE_MODE" = "1" ]; then \
        echo "OFFLINE_MODE=1 且无 pip-wheels，请先执行 cache_resources.sh" && exit 1; \
    else \
        echo "使用清华源 + 宿主机 pip-cache 在线安装..." && \
        pip install --user -r requirements.txt -i "${PIP_INDEX_URL}"; \
    fi

# ======================= 第三阶段：应用部署 =======================
FROM python-deps AS runtime

# 复制项目源码
COPY . .

# 创建必要的目录结构
RUN set -ex && \
    mkdir -p \
        data/uploads \
        data/datasets \
        data/models \
        data/inference_results \
        temp_uploads \
        static/models && \
    # 设置执行权限
    chmod +x run.py

# 创建非root用户和权限设置
RUN set -ex && \
    groupadd -r appuser && \
    useradd -r -m -g appuser appuser && \
    mkdir -p /home/appuser/.paddlex/temp /home/appuser/.config/Ultralytics && \
    chown -R appuser:appuser /app /home/appuser

# 切换到非root用户
USER appuser

# 暴露端口
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fs http://localhost:5000/actuator/health > /dev/null || exit 1

# 启动命令
CMD ["python", "run.py"]
