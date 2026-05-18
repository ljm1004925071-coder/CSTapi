@echo off
setlocal

set "CST_ROOT=D:\CST"
set "PYTHON_EXE=%CST_ROOT%\Python\python.exe"
set "PYTHONPATH=%CST_ROOT%\AMD64\python_cst_libraries"
set "PATH=%CST_ROOT%\AMD64;%PATH%"

if not exist "%PYTHON_EXE%" (
  echo [CST-PY] Bundled CST Python not found: %PYTHON_EXE%
  exit /b 1
)

"%PYTHON_EXE%" "%~dp0test_cst_python.py" %*
exit /b %ERRORLEVEL%
