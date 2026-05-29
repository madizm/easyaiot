# BuildKit 内置前端，支持 RUN --mount
# 构建阶段：pnpm store 使用 BuildKit cache mount（id=web-pnpm-store），
# 由 install_linux.sh 通过 --cache-from/--cache-to type=local 持久化到 .build-cache/web/pnpm-store
FROM node:22-alpine3.21 AS builder

ENV CI=true

RUN npm config set registry https://registry.npmmirror.com/

RUN npm install -g pnpm@11.3.0 && \
    pnpm config set registry https://registry.npmmirror.com/ && \
    pnpm config set fetch-timeout 600000 && \
    pnpm config set fetch-retries 5 && \
    pnpm config set fetch-retry-mintimeout 20000 && \
    pnpm config set fetch-retry-maxtimeout 120000

WORKDIR /app
RUN mkdir -p /tmp/web-build-logs /pnpm

# 先复制依赖清单（利用层缓存）；registry 与 fetch 配置已通过上方 pnpm config set 设置
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

# 预拉依赖到 store（持久化见 install_linux.sh --cache-from/--cache-to type=local）
RUN --mount=type=cache,target=/pnpm/store,id=web-pnpm-store \
    pnpm config set store-dir /pnpm/store && \
    pnpm fetch --frozen-lockfile 2>&1 | tee /tmp/web-build-logs/pnpm-fetch.log || true

# 源码变更或 install_linux.sh clean 后通过 CACHE_BUST 使后续层失效（避免命中 CACHED 跳过 pnpm build）
ARG CACHE_BUST=0
RUN echo "cache-bust=${CACHE_BUST}" > /tmp/.web-cache-bust

COPY . .

# 必须在 COPY 源码后 install，否则 node_modules 不完整（cross-env not found）
RUN --mount=type=cache,target=/pnpm/store,id=web-pnpm-store \
    pnpm config set store-dir /pnpm/store && \
    pnpm install --frozen-lockfile 2>&1 | tee /tmp/web-build-logs/pnpm-install.log && \
    test -x node_modules/.bin/cross-env || (echo "=== pnpm install 未生成 node_modules/.bin/cross-env ===" && exit 1)

# vite 打包通常需数分钟；用 tee 同时写日志，避免终端长时间无输出像卡住
RUN --mount=type=cache,target=/pnpm/store,id=web-pnpm-store \
    pnpm config set store-dir /pnpm/store && \
    set -e && \
    echo "=== pnpm run build 开始（Vite 打包，约 2–10 分钟，请耐心等待）===" && \
    pnpm run build 2>&1 | tee /tmp/web-build-logs/pnpm-build.log || \
    (echo "=== pnpm build failed, log: ===" && cat /tmp/web-build-logs/pnpm-build.log && exit 1)

RUN test -d dist || (echo "=== dist missing after build ===" && cat /tmp/web-build-logs/pnpm-build.log && exit 1)

FROM nginx:1.29.2-alpine

RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories

LABEL org.opencontainers.image.authors="basiclab"

WORKDIR /usr/share/nginx/html

RUN mkdir -p /usr/share/nginx/html /app/logs /opt/web-build-logs

COPY ./conf/nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist /usr/share/nginx/html
COPY --from=builder /tmp/web-build-logs /opt/web-build-logs

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/health || exit 1

CMD ["sh", "-c", "mkdir -p /app/logs && cp -af /opt/web-build-logs/. /app/logs/ && echo \"[$(date '+%Y-%m-%d %H:%M:%S')] web-service container started\" >> /app/logs/runtime.log && nginx -g 'daemon off;'"]
