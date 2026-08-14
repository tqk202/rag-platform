FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
# 境内网络提速：npm 走阿里镜像（npm10 会自动把锁文件里的官方地址重写到该镜像）
RUN npm config set registry https://registry.npmmirror.com
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
