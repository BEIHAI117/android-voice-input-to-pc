@echo off
chcp 65001 >nul
title PhoneMic PC Agent
cd /d "%~dp0pc-agent"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没找到 python，请先安装 Python 3.10 以上版本。
    pause
    exit /b 1
)

echo ==========================================================
echo   PhoneMic PC 端
echo   启动后保持这个窗口开着，最小化即可，不要关闭
echo ==========================================================
echo.

python -m agent

echo.
echo [已退出] 按任意键关闭窗口
pause >nul
