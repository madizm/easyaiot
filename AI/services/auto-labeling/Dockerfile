# syntax=docker/dockerfile:1.4
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

RUN set -ex && \
    ln -sf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gcc \
        g++ \
        python3-dev \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY .build-cache/pip-wheels /opt/offline-pip
ARG OFFLINE_MODE=0

RUN --mount=type=bind,from=pip-cache,source=.,target=/mnt/pip-cache,rw \
    --mount=type=cache,target=/tmp/pip-wheels-build,id=pip-wheels-build \
    set -ex && \
    mkdir -p /mnt/pip-cache/http /tmp/pip-wheels-build && \
    rm -rf /mnt/pip-cache/wheels && \
    ln -sfn /tmp/pip-wheels-build /mnt/pip-cache/wheels && \
    export PIP_CACHE_DIR=/mnt/pip-cache && \
    pip install --upgrade pip -i "${PIP_INDEX_URL}" && \
    if [ -n "$(find /opt/offline-pip -maxdepth 1 -type f 2>/dev/null)" ]; then \
        pip install --user -r requirements.txt --no-index --find-links /opt/offline-pip --prefer-binary; \
    elif [ "$OFFLINE_MODE" = "1" ]; then \
        echo "OFFLINE_MODE=1 且无 pip-wheels" && exit 1; \
    else \
        pip install --user -r requirements.txt -i "${PIP_INDEX_URL}"; \
    fi && \
    apt-get purge -y --auto-remove gcc g++ python3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY . .

RUN test -f static/style.css && test -f static/script.js && test -f static/all.min.css

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fs http://localhost:8000/ > /dev/null || exit 1

CMD ["python", "app.py", "--env=docker"]
