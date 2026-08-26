@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "ROOT=%~dp0"
set "DPS_RESEARCH_SRC=%ROOT%src"
set "PYTHONPATH=%DPS_RESEARCH_SRC%;%PYTHONPATH%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not defined DPS_STUDIO_CONDA_ENV set "DPS_STUDIO_CONDA_ENV=dps-studio"

cd /d "%ROOT%" || goto :root_failure
call :find_conda || goto :conda_missing
call :verify_research_import || goto :import_failure
if /i "%~1"=="--verify-launcher" exit /b 0

echo.
echo WARNING:
echo This is the Research worktree.
echo The current GUI does NOT expose TASK-021A Global Path.
echo Use run_research_global_path.bat for Global Path research.
echo.
set /p "START_GUI=Type RUN to start the Research-worktree GUI, or press Enter to cancel: "
if /i not "%START_GUI%"=="RUN" goto :cancelled

"%DPS_CONDA%" run --no-capture-output -n "%DPS_STUDIO_CONDA_ENV%" python -m dps_studio.gui
exit /b %ERRORLEVEL%

:find_conda
set "DPS_CONDA=%CONDA_EXE%"
if defined DPS_CONDA if not exist "%DPS_CONDA%" set "DPS_CONDA="
if not defined DPS_CONDA if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "DPS_CONDA=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if not defined DPS_CONDA if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "DPS_CONDA=%USERPROFILE%\anaconda3\Scripts\conda.exe"
if not defined DPS_CONDA if exist "%ProgramData%\miniconda3\Scripts\conda.exe" set "DPS_CONDA=%ProgramData%\miniconda3\Scripts\conda.exe"
if not defined DPS_CONDA if exist "%ProgramData%\anaconda3\Scripts\conda.exe" set "DPS_CONDA=%ProgramData%\anaconda3\Scripts\conda.exe"
if not defined DPS_CONDA for /f "delims=" %%I in ('where conda.exe 2^>nul') do if not defined DPS_CONDA set "DPS_CONDA=%%I"
if not defined DPS_CONDA exit /b 1
exit /b 0

:verify_research_import
echo DPS Studio Research GUI
echo This launcher does NOT run Production code.
"%DPS_CONDA%" run --no-capture-output -n "%DPS_STUDIO_CONDA_ENV%" python -c "import os, pathlib, sys, dps_studio; research_src = pathlib.Path(os.environ['DPS_RESEARCH_SRC']).resolve(); module_path = pathlib.Path(dps_studio.__file__).resolve(); print('dps_studio import:', module_path); sys.exit(0 if module_path.is_relative_to(research_src) else 2)"
exit /b %ERRORLEVEL%

:root_failure
echo [FAILURE] Could not change to the Research worktree root: %ROOT%
exit /b 2

:conda_missing
echo [FAILURE] Conda was not found. Set CONDA_EXE or install Miniconda/Anaconda.
exit /b 2

:import_failure
echo [FAILURE] Refusing to start GUI because dps_studio was not imported from:
echo %DPS_RESEARCH_SRC%
exit /b 2

:cancelled
echo [CANCELLED] Research-worktree GUI was not started.
exit /b 0
