#requires -Version 7.0
param(
    [string]$Python = 'python',
    [string]$EnvironmentDirectory = (Join-Path $env:LOCALAPPDATA 'DPS-Studio/venvs/research')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$setupRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$setupEnvironment = [IO.Path]::GetFullPath($EnvironmentDirectory)
if ($setupEnvironment.StartsWith($setupRepo, [StringComparison]::OrdinalIgnoreCase)) { throw 'Create the environment outside this source checkout.' }
if (Test-Path -LiteralPath $setupEnvironment) { throw 'Environment exists; activate it or choose a new path. This script does not prune existing environments.' }
& $Python -B -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 2)'
if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.12 x64 to create the build environment.' }
& $Python -B -m venv $setupEnvironment
if ($LASTEXITCODE -ne 0) { throw 'venv creation failed; use Python 3.12 x64.' }
$setupPython = Join-Path $setupEnvironment 'Scripts/python.exe'
& (Join-Path $PSScriptRoot 'run.ps1') -Task DEV -Python $setupPython -m pip install -c (Join-Path $setupRepo 'scripts/build/windows-constraints.txt') -e '.[dev,research]'
exit $LASTEXITCODE
