@echo off
setlocal

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher was not found. Install Python 3.10 or newer first.
    exit /b 1
)

py -m pip install --upgrade -r requirements-dev.txt
if errorlevel 1 exit /b 1

if not exist release mkdir release

echo Building portable single-file version...
py -m PyInstaller --noconfirm --clean --onefile --windowed --name MiniCalculator --icon mini_calc.ico --add-data "mini_calc.ico;." --add-data "default_calculator_state.txt;." --hidden-import pystray._win32 mini_calculator.pyw
if errorlevel 1 exit /b 1
copy /y dist\MiniCalculator.exe release\MiniCalculator.exe >nul

echo Building faster-starting folder version...
py -m PyInstaller --noconfirm --clean --onedir --windowed --name MiniCalculator-Fast --icon mini_calc.ico --add-data "mini_calc.ico;." --add-data "default_calculator_state.txt;." --hidden-import pystray._win32 mini_calculator.pyw
if errorlevel 1 exit /b 1

powershell -NoProfile -Command "Compress-Archive -Path 'dist\MiniCalculator-Fast\*' -DestinationPath 'release\MiniCalculator-Fast.zip' -Force"
if errorlevel 1 exit /b 1

echo.
echo Finished. Packages are in the release folder.
endlocal
