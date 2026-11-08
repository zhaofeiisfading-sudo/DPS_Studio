#requires -Version 7.0
param([switch]$Apply)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$migrationRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$migrationPlan = Get-Content -LiteralPath (Join-Path $migrationRoot 'artifacts/TASK-016/audit/migration-plan.json') -Raw | ConvertFrom-Json

function Get-CheckedPath([string]$RelativePath) {
    $candidate = [IO.Path]::GetFullPath((Join-Path $migrationRoot $RelativePath))
    if (!$candidate.StartsWith($migrationRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        $candidate -eq (Join-Path $migrationRoot '.git') -or
        $candidate.StartsWith((Join-Path $migrationRoot '.git') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        $candidate.StartsWith((Join-Path $migrationRoot 'data/raw'), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Protected or escaped path: $candidate"
    }
    $parent = $candidate
    while ($parent -ne $migrationRoot) {
        if (Test-Path -LiteralPath $parent) {
            $item = Get-Item -LiteralPath $parent -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Link in path: $parent" }
        }
        $parent = Split-Path -Parent $parent
    }
    return $candidate
}

# Verify every endpoint and original content before the first move.
foreach ($entry in $migrationPlan.moves) {
    $source = Get-CheckedPath $entry.source
    $target = Get-CheckedPath $entry.target
    if (Test-Path -LiteralPath $target) { throw "Destination exists: $target" }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $entry.sha256) { throw "Source changed: $source" }
}
if (!$Apply) { Write-Output "Validated $($migrationPlan.moves.Count) moves; use -Apply to execute."; exit 0 }
foreach ($entry in $migrationPlan.moves) {
    $source = Get-CheckedPath $entry.source
    $target = Get-CheckedPath $entry.target
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Move-Item -LiteralPath $source -Destination $target
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $entry.sha256) { throw "Moved content mismatch: $target" }
}
foreach ($entry in $migrationPlan.duplicates) {
    $source = Get-CheckedPath $entry.source
    $keep = Get-CheckedPath $entry.keep
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $entry.sha256 -or
        (Get-FileHash -LiteralPath $keep -Algorithm SHA256).Hash -ne $entry.sha256) { throw "Duplicate changed: $source" }
    Remove-Item -LiteralPath $source
}
Write-Output "Moved $($migrationPlan.moves.Count) files byte-for-byte; removed $($migrationPlan.duplicates.Count) proven duplicates."
