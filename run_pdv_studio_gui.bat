@echo off
setlocal

rem Start from the repository root that contains this launcher.
cd /d "%~dp0"

rem Prefer the Conda executable inherited from an active Conda installation.
set "DPS_CONDA=%CONDA_EXE%"

rem Then try the standard per-user and all-user installation locations.
if not defined DPS_CONDA if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "DPS_CONDA=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if not defined DPS_CONDA if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "DPS_CONDA=%USERPROFILE%\anaconda3\Scripts\conda.exe"
if not defined DPS_CONDA if exist "%ProgramData%\miniconda3\Scripts\conda.exe" set "DPS_CONDA=%ProgramData%\miniconda3\Scripts\conda.exe"
if not defined DPS_CONDA if exist "%ProgramData%\anaconda3\Scripts\conda.exe" set "DPS_CONDA=%ProgramData%\anaconda3\Scripts\conda.exe"

rem A custom environment name can be supplied before double-clicking the launcher.
if not defined DPS_STUDIO_CONDA_ENV set "DPS_STUDIO_CONDA_ENV=dps-studio"

if not exist "%DPS_CONDA%" (
    echo [PDV Studio] Conda was not found.
    echo Standard Miniconda and Anaconda locations were checked.
    echo Open Miniconda Prompt and run: conda activate %DPS_STUDIO_CONDA_ENV%
    echo Then run: python -m dps_studio.gui
    pause
    exit /b 1
)

echo [PDV Studio] Starting with Conda environment: %DPS_STUDIO_CONDA_ENV%
"%DPS_CONDA%" run --no-capture-output -n %DPS_STUDIO_CONDA_ENV% python -m dps_studio.gui

if errorlevel 1 (
    echo.
    echo [PDV Studio] Startup failed. Review the error message above.
    pause
)

endlocal
