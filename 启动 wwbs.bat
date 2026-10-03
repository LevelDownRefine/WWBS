@echo off
chcp 65001 >nul
cd /d "%~dp0"
uv run app.py
if errorlevel 1 (
  echo.
  echo 启动失败。请确认已安装 uv，并且可以在命令行运行 uv。
  echo 可在项目目录运行 uv sync 检查环境和依赖。
  pause
  exit /b 1
)
