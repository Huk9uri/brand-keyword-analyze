@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 10
if not exist ".venv\Scripts\python.exe" exit /b 11
if not exist "outputs\scheduler-logs" mkdir "outputs\scheduler-logs"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
if /I "%~1"=="--check" (
  ".venv\Scripts\python.exe" -m scripts.menu_keyword_pipeline.operations --help
  exit /b
)
echo [%date% %time%] START>>"outputs\scheduler-logs\pipeline.log"
".venv\Scripts\python.exe" -m scripts.menu_keyword_pipeline.operations --scheduled --send-mail --allow-write --allow-network >>"outputs\scheduler-logs\pipeline.log" 2>&1
set "PIPELINE_EXIT=%ERRORLEVEL%"
echo [%date% %time%] END exit=%PIPELINE_EXIT%>>"outputs\scheduler-logs\pipeline.log"
exit /b %PIPELINE_EXIT%
