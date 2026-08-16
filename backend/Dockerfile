# ---------- 构建阶段：只装依赖，产出最小可运行镜像 ----------
FROM python:3.12-slim AS builder

# 境内网络提速：pip 走清华镜像源（生产部署可去掉，改走默认源）
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- 运行阶段：非 root，降低容器逃逸后的权限 ----------
FROM python:3.12-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /install /usr/local

# 上传目录必须可写：预建并归 appuser（.dockerignore 排除了 data/，需自建）
RUN useradd -m appuser \
    && mkdir -p /app/data/uploads \
    && chown -R appuser:appuser /app/data

COPY . .
RUN chown -R appuser:appuser /app/data

# 非 root 运行（P1-4 生产安全基线）
USER appuser

EXPOSE 8000

# 不经 compose 直跑时同样先应用 Alembic 迁移再起服务
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
