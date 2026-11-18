#requires -Version 7.0
param(
    [string]$Python = 'python',
    [ValidatePattern('^(TASK-[0-9]{3}[A-Za-z0-9-]*|DEV|CI)$')][string]$Task = 'DEV',
    [string]$DistDirectory = 'release',
    [string]$WorkDirectory = '',
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
$buildTemporary = Join-Path $buildRepo "artifacts/$Task/tmp"
$buildWork = if ($WorkDirectory) { [IO.Path]::GetFullPath((Join-Path $buildRepo $WorkDirectory)) } else { Join-Path $buildTemporary "pyinstaller-work-$PID" }
if (!$buildWork.StartsWith($buildTemporary + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Use a work directory inside the selected task artifacts/tmp directory.'
}
foreach ($buildPath in @($buildDist, $buildWork)) {
    $buildAncestor = $buildPath
    while ($buildAncestor -and $buildAncestor -ne $buildRepo) {
        if ((Test-Path -LiteralPath $buildAncestor) -and ((Get-Item -LiteralPath $buildAncestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Build paths must not traverse directory links: $buildAncestor"
        }
        $buildAncestor = Split-Path -Parent $buildAncestor
    }
}
# An explicit Conda python.exe does not activate its Library/bin for PyInstaller's
# DLL dependency scanner. Use that interpreter's libraries, never the base env's.
$buildPythonDirectory = Split-Path -Parent (Get-Command $Python -CommandType Application).Source
$buildDllDirectories = @($buildPythonDirectory, (Join-Path $buildPythonDirectory 'Library/bin'), (Join-Path $buildPythonDirectory 'DLLs')) |
    Where-Object { Test-Path -LiteralPath $_ -PathType Container }
$buildPreviousPath = $env:PATH
try {
    $env:PATH = ($buildDllDirectories -join [IO.Path]::PathSeparator) + [IO.Path]::PathSeparator + $buildPreviousPath
    & $buildRunner -Task $Task -Python $Python -m PyInstaller --distpath $buildDist --workpath $buildWork (Join-Path $PSScriptRoot 'specs/pdv_research.spec')
    $buildExit = $LASTEXITCODE
}
finally { $env:PATH = $buildPreviousPath }
exit $buildExit
