#requires -Version 7.0
param(
    [ValidatePattern('^(TASK-[0-9]{3}[A-Za-z0-9-]*|DEV|CI)$')][string]$Task = 'DEV',
    [string]$Python = 'python',
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$PythonArgs
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$devRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$devTemp = Join-Path $devRepo "artifacts/$Task/tmp"
$devPrevious = @{}
$devSettings = @{
    TMP = $devTemp
    TEMP = $devTemp
    PYTHONDONTWRITEBYTECODE = '1'
    PYTHONPYCACHEPREFIX = (Join-Path $devTemp 'python')
    PYTHONUTF8 = '1'
    PYTHONIOENCODING = 'utf-8'
    PYTHONPATH = "$devRepo/src;$devRepo"
    MPLCONFIGDIR = (Join-Path $devTemp 'matplotlib')
    RUFF_CACHE_DIR = (Join-Path $devTemp 'ruff')
    MYPY_CACHE_DIR = (Join-Path $devTemp 'mypy')
    PIP_CACHE_DIR = (Join-Path $devTemp 'pip')
    XDG_CACHE_HOME = (Join-Path $devTemp 'cache')
    PYINSTALLER_CONFIG_DIR = (Join-Path $devTemp 'pyinstaller')
    HYPOTHESIS_STORAGE_DIRECTORY = (Join-Path $devTemp 'hypothesis')
    OPENBLAS_NUM_THREADS = '1'
    OMP_NUM_THREADS = '1'
    MKL_NUM_THREADS = '1'
    GIT_OPTIONAL_LOCKS = '0'
}
$devSettings.PYTEST_ADDOPTS = "$env:PYTEST_ADDOPTS -o cache_dir=`"$devTemp/pytest-cache`" --basetemp=`"$devTemp/pytest-$PID`""
if (!$PythonArgs -or $PythonArgs.Count -eq 0) { $PythonArgs = @('-m', 'dps_studio.gui') }
try {
    foreach ($key in $devSettings.Keys) {
        $devPrevious[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $devSettings[$key], 'Process')
    }
    New-Item -ItemType Directory -Path $devTemp -Force | Out-Null
    Push-Location -LiteralPath $devRepo
    try {
        & $Python -B -c 'import sys; sys.exit(0 if (3,12) <= sys.version_info[:2] < (3,14) else 2)'
        if ($LASTEXITCODE -ne 0) { throw 'Use a Python 3.12 or 3.13 interpreter (3.12 x64 for Windows builds).' }
        & $Python -B @PythonArgs
        $devExit = $LASTEXITCODE
    }
    finally { Pop-Location }
}
finally {
    foreach ($key in $devPrevious.Keys) {
        [Environment]::SetEnvironmentVariable($key, $devPrevious[$key], 'Process')
    }
}
exit $devExit
