# 多阶段：镜像内 pnpm build，无需在宿主机先执行 build
# 企业模式前端需 VITE_ENTERPRISE=true（compose 已传 build-arg）
FROM node:22-bookworm-slim AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.12.1 --activate
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY index.html vite.config.ts tsconfig.json env.d.ts ./
COPY public ./public
COPY src ./src
ARG VITE_BASE_PATH=/
ENV VITE_BASE_PATH=$VITE_BASE_PATH
ARG VITE_ENTERPRISE=true
ENV VITE_ENTERPRISE=$VITE_ENTERPRISE
RUN pnpm run build

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production
RUN corepack enable && corepack prepare pnpm@10.12.1 --activate
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --prod
COPY server ./server
COPY --from=builder /app/dist ./dist
EXPOSE 8787
CMD ["node", "--disable-warning=ExperimentalWarning", "server/index.mjs"]
