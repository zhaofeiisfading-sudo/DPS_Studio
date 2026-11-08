#requires -Version 7.0
param(
    [string]$Python = 'python',
    [ValidatePattern('^(TASK-[0-9]{3}[A-Za-z0-9-]*|DEV|CI)$')][string]$Task = 'DEV',
    [string]$DistDirectory = 'release',
    [switch]$CheckOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$buildRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$buildRunner = Join-Path $buildRepo 'scripts/dev/run.ps1'
& $buildRunner -Task $Task -Python $Python -m scripts.build.check_build_inputs
if ($LASTEXITCODE -ne 0) { throw 'Build inputs are invalid.' }
if ($CheckOnly) { exit 0 }
$buildDist = [IO.Path]::GetFullPath((Join-Path $buildRepo $DistDirectory))
$buildFinal = Join-Path $buildDist 'PDV_Studio_Research'
$buildRelease = Join-Path $buildRepo 'release'
if (!$buildDist.StartsWith($buildRepo + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
    !($buildDist -eq $buildRelease -or $buildDist.StartsWith($buildRelease + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or $buildDist.StartsWith((Join-Path $buildRepo 'artifacts') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))) {
    throw 'Use release or a task-specific artifacts directory for build output.'
}
if (Test-Path -LiteralPath $buildFinal) { throw "Output already exists; choose a new destination: $buildFinal" }
$buildWork = Join-Path $buildRepo "artifacts/$Task/tmp/pyinstaller-work-$PID"
& $buildRunner -Task $Task -Python $Python -m PyInstaller --distpath $buildDist --workpath $buildWork (Join-Path $PSScriptRoot 'specs/pdv_research.spec')
exit $LASTEXITCODE
