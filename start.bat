@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [LISA] 未找到 Python，请安装 Python 3.12 并加入 PATH。
  exit /b 1
)

if not exist "backend\.venv" (
  echo [LISA] 创建 Python 虚拟环境...
  python -m venv backend\.venv || exit /b 1
)

echo [LISA] 安装后端依赖...
backend\.venv\Scripts\python -m pip install --quiet --upgrade pip
backend\.venv\Scripts\python -m pip install --quiet -r backend\requirements.txt || exit /b 1

if not exist "frontend\dist\index.html" (
  echo [LISA] 构建前端...
  pushd frontend
  call npm ci || (popd & exit /b 1)
  call npm run build || (popd & exit /b 1)
  popd
)

if "%JWT_SECRET%"=="" (
  echo [LISA] 警告：JWT_SECRET 未设置，将使用内置开发密钥；生产环境请先设置 JWT_SECRET。
)

echo [LISA] 启动服务：http://127.0.0.1:8000
backend\.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers
