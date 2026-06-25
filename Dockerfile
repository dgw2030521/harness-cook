# ===== 本地构建后，Docker 只负责 nginx serve =====
# 构建命令：pnpm build:docs（在本地执行）
# 然后用此 Dockerfile 打包静态文件到 nginx

FROM nginx:alpine

# 复制自定义 nginx 配置
COPY docker/local/nginx.conf /etc/nginx/conf.d/default.conf

# 复制本地构建好的静态文件
COPY playground/docs/.vitepress/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
