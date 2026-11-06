#requires -Version 7.0
param([string]$BuildName = 'staging_v1')
$ErrorActionPreference = 'Stop'
$task12Root = Split-Path -Parent $PSScriptRoot
$task12Python = 'D:\miniconda3\envs\dps-studio\python.exe'
$task12Artifact = Join-Path $task12Root 'artifacts/research_clean_task12'
$task12Dist = Join-Path $task12Artifact $BuildName
$task12Work = Join-Path $task12Artifact "build_$BuildName"
if (Test-Path -LiteralPath $task12Dist) { throw 'Output exists; use a new build name.' }
$env:PYTHONPATH = Join-Path $task12Root 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
Set-Location -LiteralPath $task12Root
& $task12Python -B -m PyInstaller --noconfirm --distpath $task12Dist --workpath $task12Work (Join-Path $task12Root 'packaging/pdv_research_task012.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
