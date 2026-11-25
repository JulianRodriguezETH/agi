@echo off
rem Builds the installer on this Windows machine (same as GitHub does): dist\AGI and instalador\salida\
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist .venv (py -3.12 -m venv .venv || python -m venv .venv)
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller || goto :fail
.venv\Scripts\python -m PyInstaller agi.spec --noconfirm || goto :fail
set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (
    echo Inno Setup 6 is missing: download it for free from jrsoftware.org. AGI.exe is already in dist\AGI.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('.venv\Scripts\python instalador\version.py') do set VERSION=%%v
"%ISCC%" /DVersion=%VERSION% instalador\agi.iss || goto :fail
echo.
echo Done: instalador\salida\AGI-%VERSION%-setup.exe
start "" explorer instalador\salida
exit /b 0
:fail
echo Something failed. Check the messages above.
pause
exit /b 1
