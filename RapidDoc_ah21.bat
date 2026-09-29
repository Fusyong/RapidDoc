@echo off
REM ah21 launcher: portable layout (Python\ + app\ + models\) or dev (.venv + repo root).
REM Keep messages ASCII-only so cmd.exe code page does not mangle paths.
REM Upstream: maintain *ah21* files only; do not PR ah21 customizations upstream.

setlocal EnableExtensions
cd /d "%~dp0" || exit /b 1

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if exist "%ROOT%\models" (
  if not defined RAPID_MODELS_DIR set "RAPID_MODELS_DIR=%ROOT%\models"
)

set "PYTHON_EXE="
set "APP_DIR="

if exist "%ROOT%\Python\python.exe" if exist "%ROOT%\app\gui_ah21.py" (
  set "PYTHON_EXE=%ROOT%\Python\python.exe"
  set "APP_DIR=%ROOT%\app"
  goto run
)

if exist "%ROOT%\.venv\Scripts\python.exe" if exist "%ROOT%\gui_ah21.py" (
  set "PYTHON_EXE=%ROOT%\.venv\Scripts\python.exe"
  set "APP_DIR=%ROOT%"
  goto run
)

echo [ERROR] Python or gui_ah21.py not found.
echo Portable: Python\python.exe + app\gui_ah21.py
echo Dev:      .venv\Scripts\python.exe + gui_ah21.py
pause
exit /b 1

:run
set "PYTHONPATH=%APP_DIR%"
if defined PYTHONPATH_EXTRA set "PYTHONPATH=%APP_DIR%;%PYTHONPATH_EXTRA%"
cd /d "%APP_DIR%" || (
  echo [ERROR] cannot cd to APP_DIR=%APP_DIR%
  pause
  exit /b 1
)
echo RAPID_MODELS_DIR=%RAPID_MODELS_DIR%
echo PYTHONPATH=%PYTHONPATH%
echo Starting: "%PYTHON_EXE%" gui_ah21.py
"%PYTHON_EXE%" gui_ah21.py
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo [ERROR] exit code %ERR%
  pause
)
exit /b %ERR%
