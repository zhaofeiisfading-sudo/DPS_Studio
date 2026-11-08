#requires -Version 7.0
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$outputRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$outputMoves = [Collections.Generic.List[object]]::new()
function Move-Reviewed([string]$SourceName, [string]$TargetName) {
    $source = [IO.Path]::GetFullPath((Join-Path $outputRoot $SourceName))
    $target = [IO.Path]::GetFullPath((Join-Path $outputRoot $TargetName))
    foreach ($path in @($source, $target)) {
        if (!$path.StartsWith($outputRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
            $path.StartsWith((Join-Path $outputRoot '.git'), [StringComparison]::OrdinalIgnoreCase) -or
            $path.StartsWith((Join-Path $outputRoot 'data/raw'), [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe path: $path" }
        $ancestor = $path
        while ($ancestor -ne $outputRoot) {
            if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Link: $ancestor" }
            $ancestor = Split-Path -Parent $ancestor
        }
    }
    if (!(Test-Path -LiteralPath $source)) { throw "Missing source: $source" }
    if (Test-Path -LiteralPath $target) { throw "Existing target: $target" }
    if (@(Get-ChildItem -LiteralPath $source -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "Nested link: $source" }
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Move-Item -LiteralPath $source -Destination $target
    $outputMoves.Add(@{ source = $SourceName; target = $TargetName; reason = 'data/release/artifact directory ownership' })
}
Move-Reviewed 'artifacts/research_clean_task9/source_data' 'data/research/TASK-009/source_data'
foreach ($task in @(11, 14)) {
    Move-Reviewed "artifacts/research_clean_task$task/PDV_Studio_Research_TASK$('{0:000}' -f $task)_Windows_x64.zip" "release/TASK-$('{0:000}' -f $task)/PDV_Studio_Research_TASK$('{0:000}' -f $task)_Windows_x64.zip"
}
Get-ChildItem -LiteralPath (Join-Path $outputRoot 'artifacts/research_clean_task15/release') -File | ForEach-Object {
    Move-Reviewed "artifacts/research_clean_task15/release/$($_.Name)" "release/TASK-015/$($_.Name)"
}
Move-Reviewed 'release/PDV_Studio_Research_TASK012_Windows_x64.zip' 'release/TASK-012/PDV_Studio_Research_TASK012_Windows_x64.zip'
foreach ($task in 8..15) { Move-Reviewed "artifacts/research_clean_task$task" "artifacts/TASK-$('{0:000}' -f $task)" }
Move-Reviewed 'results' 'artifacts/inherited/results'
Move-Reviewed 'logs' 'artifacts/inherited/logs'
$outputMoves | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $outputRoot 'artifacts/TASK-016/audit/output-migrations.json') -Encoding utf8NoBOM
Write-Output "Relocated $($outputMoves.Count) existing data/output/release entries; no new packages."
