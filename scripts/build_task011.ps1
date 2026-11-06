#requires -Version 7.0
param([string]$BuildName = 'portable_v2')
$ErrorActionPreference = 'Stop'
$task11Root = Split-Path -Parent $PSScriptRoot
$task11Python = 'D:\miniconda3\envs\dps-studio\python.exe'
$task11Artifact = Join-Path $task11Root 'artifacts/research_clean_task11'
$task11Dist = Join-Path $task11Artifact $BuildName
$task11Work = Join-Path $task11Artifact "build_$BuildName"
if (Test-Path -LiteralPath $task11Dist) { throw 'Build output exists; preserve it and use a new version.' }
$env:PYTHONPATH = Join-Path $task11Root 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
Set-Location -LiteralPath $task11Root
& $task11Python -B -m PyInstaller --noconfirm --distpath $task11Dist --workpath $task11Work (Join-Path $task11Root 'packaging/pdv_research_task011.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit $LASTEXITCODE" }
