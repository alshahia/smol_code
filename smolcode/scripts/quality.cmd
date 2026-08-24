@echo off
REM Run the same quality gate as 'make quality' on Windows without make.
setlocal
set VENV=.venv
if not exist %VENV%\Scripts\ruff.exe (
  echo .venv missing or ruff not installed. Run scripts\install.cmd first.
  exit /b 1
)
%VENV%\Scripts\ruff.exe check src
if errorlevel 1 exit /b 1
%VENV%\Scripts\ruff.exe format --check src
if errorlevel 1 exit /b 1
echo OK quality
endlocal
