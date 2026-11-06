@echo off
rem Builds dist\XeroxPro\XeroxPro.exe on a Windows PC.  Needs Python 3.12 (64-bit) from python.org, with the "py" launcher.
rem Usage:  packaging\build_windows.bat            (runs the tests first)
rem         packaging\build_windows.bat notests    (skip the tests)
setlocal
cd /d "%~dp0\.."

py -3.12 -m venv .venv-build || (echo Python 3.12 not found & exit /b 1)
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip || exit /b 1
pip install -r requirements-dev.txt || exit /b 1

if /i not "%1"=="notests" (
  set QT_QPA_PLATFORM=offscreen
  python -m pytest -q || (echo TESTS FAILED - not building & exit /b 1)
)

pyinstaller packaging\xeroxpro.spec --noconfirm --distpath dist --workpath build || exit /b 1

rem The exe is a windowed program, so "start /wait" is needed to get its exit code.
start /wait "" "dist\XeroxPro\XeroxPro.exe" --selftest "dist\selftest.txt"
set RESULT=%ERRORLEVEL%
type dist\selftest.txt
if not "%RESULT%"=="0" (echo SELF-TEST FAILED & exit /b 1)

echo.
echo Built OK: dist\XeroxPro\XeroxPro.exe
echo To make an installer, open packaging\installer.iss in Inno Setup (free) and press Compile.
