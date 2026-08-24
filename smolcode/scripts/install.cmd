@echo off
REM Create venv and install smolcode with dev extras on Windows.
setlocal
set PY=py -3.12
%PY% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip show smolagents >nul && echo OK smolagents installed
endlocal
