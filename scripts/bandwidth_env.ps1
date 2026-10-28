# Dot-source or run from the DPS_Studio_BANDWIDTH PowerShell session:
#   . .\scripts\bandwidth_env.ps1
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ((Split-Path $projectRoot -Leaf) -ne 'DPS_Studio_BANDWIDTH') {
    throw "Wrong worktree: $projectRoot. Expected DPS_Studio_BANDWIDTH."
}
$cacheRoot = Join-Path $projectRoot '.local_cache'
$dirs = @(
    $cacheRoot,
    (Join-Path $cacheRoot 'tmp'),
    (Join-Path $cacheRoot 'pytest_tmp'),
    (Join-Path $cacheRoot 'pytest_cache'),
    (Join-Path $cacheRoot 'ruff'),
    (Join-Path $cacheRoot 'mypy'),
    (Join-Path $cacheRoot 'matplotlib'),
    (Join-Path $cacheRoot 'pip')
)
foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = Join-Path $projectRoot 'src'
$env:TMP = Join-Path $cacheRoot 'tmp'
$env:TEMP = Join-Path $cacheRoot 'tmp'
$env:RUFF_CACHE_DIR = Join-Path $cacheRoot 'ruff'
$env:MYPY_CACHE_DIR = Join-Path $cacheRoot 'mypy'
$env:MPLCONFIGDIR = Join-Path $cacheRoot 'matplotlib'
$env:PIP_CACHE_DIR = Join-Path $cacheRoot 'pip'
# The pytest settings apply to commands launched from this PowerShell session.
$env:PYTEST_ADDOPTS = "-o cache_dir=$($cacheRoot.Replace('\', '/'))/pytest_cache --basetemp=$($cacheRoot.Replace('\', '/'))/pytest_tmp"
Write-Host "Bandwidth environment ready; temporary/cache files -> $cacheRoot"
Write-Host 'Note: only the current PowerShell process and its children use these environment variables.'
