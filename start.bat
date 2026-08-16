@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   rag-platform 快速启动
echo ============================================

echo.
echo [1/4] 检查 Docker...
docker info >nul 2>&1
if errorlevel 1 (
    echo   Docker 未运行，正在启动 Docker Desktop（首次启动约需 30~60 秒）...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    set /a tries=0
    :wait_docker
    set /a tries+=1
    docker info >nul 2>&1
    if errorlevel 1 (
        if !tries! geq 40 (
            echo   [错误] 等待 Docker 超时（约 2 分钟）。请手动打开 Docker Desktop 后再运行本脚本。
            pause
            exit /b 1
        )
        timeout /t 3 /nobreak >nul
        goto wait_docker
    )
)
for /f "usebackq" %%v in (`docker info --format "{{.ServerVersion}}"`) do set DVER=%%v
echo   Docker 就绪（版本 !DVER!）

echo.
echo [2/4] 构建并启动全栈服务（首次构建较慢，请耐心等待）...
docker compose up -d --build
if errorlevel 1 (
    echo   [错误] 启动失败，请查看上方日志。
    pause
    exit /b 1
)

echo.
echo [3/4] 等待后端就绪（首次 Milvus 启动需 1~2 分钟）...
set /a tries=0
:wait_backend
set /a tries+=1
for /f "usebackq" %%h in (`docker inspect -f "{{.State.Health.Status}}" rag-backend 2^>nul`) do set STATUS=%%h
if not "!STATUS!"=="healthy" (
    if !tries! geq 60 (
        echo   [错误] 后端 5 分钟内未就绪。可运行 docker compose ps 查看各容器状态。
        pause
        exit /b 1
    )
    timeout /t 5 /nobreak >nul
    goto wait_backend
)
echo   后端 healthy。

echo.
echo [4/4] 检查演示数据...
for /f "usebackq" %%c in (`docker compose exec -T postgres psql -U rag -d rag -t -A -c "SELECT count(*) FROM users" 2^>nul`) do set UCOUNT=%%c
if "!UCOUNT!"=="0" (
    echo   数据库为空，灌入演示数据（账号 + 企业文档，约 1 分钟）...
    docker compose exec backend python scripts/seed_dev.py
    if errorlevel 1 (
        echo   [提示] 演示数据灌入失败，可稍后手动执行：
        echo          docker compose exec backend python scripts/seed_dev.py
    ) else (
        echo   演示数据就绪。
    )
) else (
    echo   已有 !UCOUNT! 个账号，跳过灌数据（不会清库）。
)

echo.
echo ============================================
echo   启动完成！
echo   前端页面:   http://localhost:5173
echo   API 文档:   http://localhost:8000/docs
echo   演示账号:   admin / mgr_hr / member_hr （密码均 123456）
echo   停止服务:   docker compose down
echo ============================================
echo.
pause
