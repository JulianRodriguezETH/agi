@echo off
rem ---------------------------------------------------------------------------
rem  AGI: test on Windows with a double click.
rem  Creates the environment, installs what's needed, runs the tests and opens AGI.
rem  The result is written to test_results.txt.
rem ---------------------------------------------------------------------------
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set OUT=%~dp0test_results.txt

echo AGI - Windows test > "%OUT%"
echo Date: %DATE% %TIME% >> "%OUT%"
ver >> "%OUT%"

rem 1. 64-bit (x64) Python, the same the ranch laptops would have
where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3.12) else (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo  Python 3.12 not found. Install it from python.org: "Windows installer (64-bit)"
    echo  and tick "Add python.exe to PATH". Then open this file again.
    echo Python 3.12 missing >> "%OUT%"
    pause
    exit /b 1
)
%PY% -c "import platform,sys; print('Python', sys.version.split()[0], platform.machine())" >> "%OUT%"
%PY% -c "import platform,sys; sys.exit(0 if platform.machine() in ('AMD64','x86_64') else 1)"
if errorlevel 1 (
    echo  NOTE: this Python is not x64. For a meaningful test, install the "Windows installer (64-bit)".
    echo NOTE: Python is not x64 >> "%OUT%"
)

rem 2. Separate environment and libraries
if not exist .venv (
    echo Creating the environment...
    %PY% -m venv .venv || goto :fail
)
echo Installing libraries (the first time takes a few minutes)...
.venv\Scripts\python -m pip install --upgrade pip >> "%OUT%" 2>&1
.venv\Scripts\python -m pip install -r requirements.txt >> "%OUT%" 2>&1 || goto :fail

rem 3. Tests (no windows)
set QT_QPA_PLATFORM=offscreen
echo.
echo Testing security and data...
echo. >> "%OUT%"
echo ===== probar_seguridad.py ===== >> "%OUT%"
.venv\Scripts\python probar_seguridad.py >> "%OUT%" 2>&1
set R1=%errorlevel%
echo Testing the app...
echo. >> "%OUT%"
echo ===== probar_app.py ===== >> "%OUT%"
.venv\Scripts\python probar_app.py >> "%OUT%" 2>&1
set R2=%errorlevel%
set QT_QPA_PLATFORM=

echo. >> "%OUT%"
if "%R1%%R2%"=="00" (
    echo RESULT: ALL GOOD >> "%OUT%"
    echo.
    echo  ALL GOOD. AGI opens now so you can look at it.
) else (
    echo RESULT: FAILURES ^(security=%R1% app=%R2%^) >> "%OUT%"
    echo.
    echo  FAILURES. Details are in test_results.txt.
)
start "" notepad "%OUT%"

rem 4. Open AGI for real, with separate test data
set GANADERIA_DATOS=%~dp0test_data
.venv\Scripts\python agi.py
exit /b 0

:fail
echo.
echo  Installation failed. Details are in test_results.txt.
echo INSTALLATION FAILED >> "%OUT%"
start "" notepad "%OUT%"
pause
exit /b 1
