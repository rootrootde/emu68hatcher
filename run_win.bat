@echo off
rem launch emu68hatcher from this source checkout, using a windows-only venv
rem (.venvwin) so a macos/linux .venv in the same dir stays untouched
cd /d "%~dp0"

rem a venv without pip is the leftover of a create that failed at the
rem ensurepip step - rebuild it
if exist ".venvwin\Scripts\python.exe" if not exist ".venvwin\Scripts\pip.exe" (
    echo Found a broken .venvwin - rebuilding
    rmdir /s /q ".venvwin"
)

if not exist ".venvwin\Scripts\python.exe" (
    echo First run - creating windows venv at .venvwin
    where python >nul 2>nul
    if errorlevel 1 ( py -m venv .venvwin ) else ( python -m venv .venvwin )
)

if not exist ".venvwin\Scripts\python.exe" (
    echo Could not create .venvwin - is python installed?
    pause
    exit /b 1
)

if not exist ".venvwin\Scripts\emu68hatcher.exe" (
    echo Installing emu68hatcher into .venvwin
    ".venvwin\Scripts\python.exe" -m pip install -e .
    if errorlevel 1 (
        echo pip install failed.
        pause
        exit /b 1
    )
)

".venvwin\Scripts\python.exe" -m emu68hatcher
if errorlevel 1 (
    echo.
    echo emu68hatcher exited with an error.
    pause
    exit /b 1
)
