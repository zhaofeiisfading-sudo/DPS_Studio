@echo off
setlocal

rem Start from the repository root that contains this launcher.
cd /d "%~dp0"

rem Prefer the Conda executable inherited from an active Conda installation.
set "DPS_CONDA=%CONDA_EXE%"

rem Fall back to the known local Miniconda installation.
if not defined DPS_CONDA set "DPS_CONDA=D:\miniconda3\Scripts\conda.exe"

if not exist "%DPS_CONDA%" (
    echo [PDV Studio] Conda was not found.
    echo Checked: "%DPS_CONDA%"
    echo Edit run_pdv_studio_gui.bat and set DPS_CONDA to your conda.exe path.
    pause
    exit /b 1
)

echo [PDV Studio] Starting with Conda environment: dps-studio
"%DPS_CONDA%" run --no-capture-output -n dps-studio python -m dps_studio.gui

if errorlevel 1 (
    echo.
    echo [PDV Studio] Startup failed. Review the error message above.
    pause
)

endlocal
