@echo off
chcp 65001 > nul
echo ============================================
echo  虚拟币智能筛选工具 - 一键启动
echo ============================================
echo.

:: 检查 Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    echo.
    echo 安装步骤：
    echo  1. 打开上面的下载地址
    echo  2. 点击 "Download Python 3.12.x"（推荐3.12版本）
    echo  3. 运行安装包，务必勾选 "Add Python to PATH"
    echo  4. 安装完成后重启本脚本
    pause
    exit /b 1
)

echo [✓] 检测到 Python:
python --version

echo.
echo [1/3] 安装 Python 依赖（使用阿里云镜像加速）...
cd /d %~dp0backend
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -q
if errorlevel 1 (
    echo [提示] 阿里云镜像失败，改用官方源重试...
    pip install -r requirements.txt -q
)

echo [✓] 依赖安装完成
echo.
echo [2/3] 启动后端服务（端口 8000）...
start "虚拟币筛选-后端" cmd /k "cd /d %~dp0backend && python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"

echo [3/3] 等待后端启动，然后打开前端页面...
timeout /t 4 > nul
start "" "%~dp0frontend\index.html"

echo.
echo ============================================
echo  ✅ 启动完成！
echo  后端 API: http://localhost:8000
echo  API 文档: http://localhost:8000/docs
echo  前端页面: 已在浏览器打开
echo ============================================
echo.
echo [提示] 首次筛选约需 3-5 分钟，请耐心等待
echo [提示] 若前端页面出现 CORS 错误，请直接访问：
echo         file://%~dp0frontend\index.html
echo.
pause
