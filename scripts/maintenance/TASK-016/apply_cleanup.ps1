#requires -Version 7.0
param([switch]$Apply, [string]$Plan = 'artifacts/TASK-016/audit/cleanup-plan.json',
      [string]$Report = 'artifacts/TASK-016/audit/cleanup-executed.json')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$cleanupRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$cleanupPlan = Get-Content -LiteralPath (Join-Path $cleanupRoot $Plan) -Raw | ConvertFrom-Json
$cleanupTracked = @(& git --no-optional-locks -C $cleanupRoot ls-files)
$cleanupRunning = @(Get-Process | ForEach-Object { try { $_.Path } catch {} } | Where-Object { $_ })
$cleanupApproved = [Collections.Generic.List[object]]::new()
$cleanupSkipped = [Collections.Generic.List[object]]::new()
foreach ($entry in $cleanupPlan.candidates) {
    $target = [IO.Path]::GetFullPath((Join-Path $cleanupRoot $entry.path))
    if (!$target.StartsWith($cleanupRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        $target.StartsWith((Join-Path $cleanupRoot '.git'), [StringComparison]::OrdinalIgnoreCase) -or
        $target.StartsWith((Join-Path $cleanupRoot 'data'), [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe deletion target: $target" }
    $ancestor = $target
    while ($ancestor -ne $cleanupRoot) {
        if ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Link in deletion path: $ancestor" }
        $ancestor = Split-Path -Parent $ancestor
    }
    $targetItem = Get-Item -LiteralPath $target -Force
    $children = if ($targetItem.PSIsContainer) { @(Get-ChildItem -LiteralPath $target -Recurse -Force) } else { @($targetItem) }
    if (@($children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "Nested link: $target" }
    $files = @($children | Where-Object { !$_.PSIsContainer })
    $bytes = if ($files.Count) { ($files | Measure-Object -Property Length -Sum).Sum } else { 0 }
    if ($files.Count -ne $entry.files -or [long]$bytes -ne $entry.bytes) { throw "Candidate changed after review: $target" }
    if ($entry.PSObject.Properties.Name -contains 'keep') {
        $keeper = [IO.Path]::GetFullPath((Join-Path $cleanupRoot $entry.keep))
        if (!$keeper.StartsWith($cleanupRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
            (Get-FileHash -LiteralPath $keeper -Algorithm SHA256).Hash -ne $entry.sha256 -or
            (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $entry.sha256) { throw "Duplicate proof changed: $target" }
    }
    if (@($cleanupTracked | Where-Object { $_ -eq $entry.path -or $_.StartsWith($entry.path + '/') }).Count) { throw "Tracked content: $target" }
    if (@($cleanupRunning | Where-Object { $_.StartsWith($target + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) }).Count) {
        $cleanupSkipped.Add(@{ path = $entry.path; reason = 'currently running executable' })
        continue
    }
    $cleanupApproved.Add(@{ path = $entry.path; absolute = $target; bytes = $entry.bytes; files = $entry.files; reason = $entry.reason; evidence = $entry.evidence })
}
if (!$Apply) { Write-Output "Validated $($cleanupApproved.Count) candidates; use -Apply to delete."; exit 0 }
foreach ($entry in $cleanupApproved) { Remove-Item -LiteralPath $entry.absolute -Recurse -Force }
@{ deleted = @($cleanupApproved); skipped = @($cleanupSkipped); bytes = ($cleanupApproved | Measure-Object -Property bytes -Sum).Sum } |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $cleanupRoot $Report) -Encoding utf8NoBOM
Write-Output "Deleted $($cleanupApproved.Count) reviewed candidates; skipped $($cleanupSkipped.Count); $([math]::Round(($cleanupApproved | Measure-Object -Property bytes -Sum).Sum / 1GB, 3)) GiB reclaimed."
