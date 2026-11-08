#requires -Version 7.0
param([string]$Python = 'python', [string]$BuildName = 'manual')
$archiveRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
& (Join-Path $archiveRepo 'scripts/build/build_windows.ps1') -Python $Python -Task TASK-012 -DistDirectory "artifacts/TASK-012/$BuildName"
exit $LASTEXITCODE
