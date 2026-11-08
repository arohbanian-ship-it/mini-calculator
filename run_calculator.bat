@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher not found. Install Python 3.10 or later for Windows.
    pause
    exit /b 1
)

py -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo Tkinter is missing. Reinstall Python with the Tcl/Tk option selected.
    pause
    exit /b 1
)

py -c "import PIL, pystray" >nul 2>nul
if errorlevel 1 (
    echo Installing optional tray libraries into the current user account...
    py -m pip install --user --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo Optional libraries could not be installed. The calculator will run without its tray icon.
    )
)

where pyw >nul 2>nul
if errorlevel 1 (
    py mini_calculator.pyw
) else (
    start "" pyw "%~dp0mini_calculator.pyw"
)
endlocal
