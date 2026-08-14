@echo off
setlocal EnableExtensions
chcp 65001 >nul

cd /d "%~dp0"
if errorlevel 1 goto :cd_failure

set "PYTHON_EXE=D:\miniconda3\envs\dps-studio\python.exe"
set "CONFIG_FILE=%CD%\configs\demo_dual_profile.toml"
for /f %%I in ('powershell.exe -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%I"
set "OUTPUT_DIR=%CD%\outputs\production_runs\run_%RUN_STAMP%"
set "PYTHONPATH=%CD%\src"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo ================================================================
echo DPS Studio formal dual-profile production analysis
echo ================================================================
echo [CONFIG] %CONFIG_FILE%
echo [OUTPUT] %OUTPUT_DIR%
echo [PYTHON] %PYTHON_EXE%
echo [NOTICE] Unsigned apparent velocity; no LiF correction or data interpolation.
echo.

if not exist "%PYTHON_EXE%" goto :python_missing
if not exist "%CONFIG_FILE%" goto :config_missing

echo [STAGE] Launching Balanced and High time resolution profiles...
"%PYTHON_EXE%" "%CD%\scripts\run_demo_pipeline.py" --config "%CONFIG_FILE%" --output-directory "%OUTPUT_DIR%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto :python_failure

echo.
echo [SUCCESS] Dual-profile production analysis completed successfully.
echo [SUCCESS] Output directory: %OUTPUT_DIR%
start "" explorer.exe "%OUTPUT_DIR%"
if errorlevel 1 echo [WARNING] Windows Explorer could not be launched automatically.
set "EXIT_CODE=0"
goto :pause_and_exit

:cd_failure
set "EXIT_CODE=2"
echo [FAILURE] Could not change to repository root: %~dp0
goto :pause_and_exit

:python_missing
set "EXIT_CODE=2"
echo [FAILURE] Required Python executable was not found:
echo %PYTHON_EXE%
goto :pause_and_exit

:config_missing
set "EXIT_CODE=2"
echo [FAILURE] Formal TOML configuration was not found:
echo %CONFIG_FILE%
goto :pause_and_exit

:python_failure
echo.
echo [FAILURE] Python pipeline failed with exit code %EXIT_CODE%.
echo [FAILURE] The Python error and traceback are shown above.

:pause_and_exit
echo.
echo Press any key to close this window...
pause >nul
exit /b %EXIT_CODE%
