@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul

set "ROOT=%~dp0"
set "DPS_RESEARCH_SRC=%ROOT%src"
set "PYTHONPATH=%DPS_RESEARCH_SRC%;%PYTHONPATH%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
if not defined DPS_STUDIO_CONDA_ENV set "DPS_STUDIO_CONDA_ENV=dps-studio"

cd /d "%ROOT%" || goto :root_failure
call :find_conda || goto :conda_missing

echo ================================================================
echo DPS Studio Research - Global Path Real Data
echo Branch target: research_2 / Global Path
echo This launcher does NOT run Production code.
echo ================================================================
call :verify_research_import || goto :import_failure

if /i "%~1"=="--verify-launcher" exit /b 0
if /i "%~1"=="--help" goto :forward_arguments
if not "%~1"=="" goto :forward_arguments

call :select_raw_data || goto :selection_cancelled
call :timestamp || goto :timestamp_failure
for %%I in ("%RAW_DATA%") do set "SOURCE_STEM=%%~nI"
set "OUTPUT_DIR=%ROOT%artifacts\task021a_global_path\run_%RUN_STAMP%_%SOURCE_STEM%"
echo Selected raw file:
echo %RAW_DATA%
echo [OUTPUT] %OUTPUT_DIR%
"%DPS_CONDA%" run --no-capture-output -n "%DPS_STUDIO_CONDA_ENV%" python "%ROOT%scripts\run_task021a_global_path_research.py" --mode real --raw-data "%RAW_DATA%" --output-directory "%OUTPUT_DIR%"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" goto :research_failure
echo.
echo Analysis complete
echo Source: %SOURCE_STEM%.csv
echo Results: %OUTPUT_DIR%\00_RESULT_SUMMARY
start "" explorer.exe "%OUTPUT_DIR%\00_RESULT_SUMMARY"
exit /b 0

:forward_arguments
"%DPS_CONDA%" run --no-capture-output -n "%DPS_STUDIO_CONDA_ENV%" python "%ROOT%scripts\run_task021a_global_path_research.py" %*
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
"%DPS_CONDA%" run --no-capture-output -n "%DPS_STUDIO_CONDA_ENV%" python -c "import os, pathlib, sys, dps_studio; research_src = pathlib.Path(os.environ['DPS_RESEARCH_SRC']).resolve(); module_path = pathlib.Path(dps_studio.__file__).resolve(); print('dps_studio import:', module_path); sys.exit(0 if module_path.is_relative_to(research_src) else 2)"
exit /b %ERRORLEVEL%

:select_raw_data
set "RAW_DATA="
for /f "usebackq delims=" %%I in (`powershell.exe -NoProfile -STA -Command "Add-Type -AssemblyName System.Windows.Forms; $dialog = New-Object System.Windows.Forms.OpenFileDialog; $dialog.Title = 'Select raw PDV data for TASK-021A research'; $dialog.Filter = 'Data files (*.csv;*.txt;*.data)|*.csv;*.txt;*.data|All files (*.*)|*.*'; if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::WriteLine($dialog.FileName) }"`) do set "RAW_DATA=%%I"
if not defined RAW_DATA exit /b 1
if not exist "%RAW_DATA%" exit /b 1
exit /b 0

:timestamp
set "RUN_STAMP="
for /f %%I in ('powershell.exe -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "RUN_STAMP=%%I"
if not defined RUN_STAMP exit /b 1
exit /b 0

:root_failure
echo [FAILURE] Could not change to the Research worktree root: %ROOT%
exit /b 2

:conda_missing
echo [FAILURE] Conda was not found. Set CONDA_EXE or install Miniconda/Anaconda.
exit /b 2

:import_failure
echo [FAILURE] Refusing to run because dps_studio was not imported from:
echo %DPS_RESEARCH_SRC%
exit /b 2

:selection_cancelled
echo [CANCELLED] No raw-data file was selected.
exit /b 0

:timestamp_failure
echo [FAILURE] Could not create an output timestamp.
exit /b 2

:research_failure
echo [FAILURE] Global Path research failed with exit code %EXIT_CODE%.
exit /b %EXIT_CODE%
