@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
where uv >nul 2>nul
if not errorlevel 1 (
  uv run --locked --no-dev python app.py
  goto finished
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app.py
  goto finished
)
python app.py

:finished
set "WWBS_EXIT_CODE=%ERRORLEVEL%"
if not "%WWBS_EXIT_CODE%"=="0" (
  echo.
  echo 启动失败。使用 uv 时请先运行: uv sync --locked --no-dev
  echo 未安装 uv 时，请确认 Python 可用并运行: python -m pip install -r requirements.txt
  pause
)
exit /b %WWBS_EXIT_CODE%
