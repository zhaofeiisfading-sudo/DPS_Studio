@echo off
setlocal EnableExtensions
chcp 65001 >nul

cd /d "%~dp0"
if errorlevel 1 goto :cd_failure

set "PYTHON_EXE=D:\miniconda3\envs\dps-studio\python.exe"
set "PYTHONPATH=%CD%\src"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "DATA_FILE=%CD%\data\raw\20260607.csv"
set "OUTPUT_ROOT=%CD%\outputs\task008b_demo_runs"

:select_output_directory
set "RUN_ID=run_%RANDOM%_%RANDOM%"
set "OUTPUT_DIR=%OUTPUT_ROOT%\%RUN_ID%"
if exist "%OUTPUT_DIR%" goto :select_output_directory
set "DPS_DEMO_OUTPUT_DIR=%OUTPUT_DIR%"

echo ================================================================
echo DPS Studio TASK-007 + TASK-008A + TASK-008B development demo
echo ================================================================
echo [INPUT]  %DATA_FILE%
echo [OUTPUT] %OUTPUT_DIR%
echo [PYTHON] %PYTHON_EXE%
echo [NOTICE] Temporary 1550 nm parameter; unsigned velocity; no LiF correction.
echo.

if not exist "%PYTHON_EXE%" goto :python_missing
if not exist "%DATA_FILE%" goto :data_missing
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
if errorlevel 1 goto :output_failure

echo [STAGE] Launching TASK-007, TASK-008A, and TASK-008B diagnostic pipeline...
"%PYTHON_EXE%" "%CD%\scripts\run_demo_pipeline.py" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto :python_failure

echo.
echo [SUCCESS] TASK-007 + TASK-008A + TASK-008B development demo completed successfully.
echo [SUCCESS] The complete generated-file list is shown above.
echo [SUCCESS] Output directory: %OUTPUT_DIR%
echo [STAGE] Opening this run directory in Windows Explorer...
start "" explorer.exe "%OUTPUT_DIR%"
if errorlevel 1 echo [WARNING] Windows Explorer could not be launched automatically.
set "EXIT_CODE=0"
goto :pause_and_exit

:cd_failure
set "EXIT_CODE=2"
echo [FAILURE] Could not change to repository root: %~dp0
echo [FAILURE] Exit code: %EXIT_CODE%
goto :pause_and_exit

:python_missing
set "EXIT_CODE=2"
echo [FAILURE] Required Python executable was not found:
echo %PYTHON_EXE%
echo [FAILURE] Exit code: %EXIT_CODE%
goto :pause_and_exit

:data_missing
set "EXIT_CODE=2"
echo [FAILURE] Raw input file was not found:
echo %DATA_FILE%
echo [FAILURE] Exit code: %EXIT_CODE%
goto :pause_and_exit

:output_failure
set "EXIT_CODE=3"
echo [FAILURE] Could not create the output directory:
echo %OUTPUT_DIR%
echo [FAILURE] Existing outputs were not deleted or modified.
echo [FAILURE] Exit code: %EXIT_CODE%
goto :pause_and_exit

:python_failure
echo.
echo [FAILURE] Python pipeline failed with exit code %EXIT_CODE%.
echo [FAILURE] The Python error and traceback are shown above.
goto :pause_and_exit

:pause_and_exit
echo.
echo Press any key to close this window...
pause >nul
exit /b %EXIT_CODE%
