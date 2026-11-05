# PowerShell 7; non-recursive relocation of a junction, never its target contents.
$ErrorActionPreference = 'Stop'
$task9Root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
if ($task9Root -ne 'D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN') { throw 'Unexpected target worktree' }
$task9Source = 'D:\Code\Python_Projects\DPS_Studio_TASK021A\artifacts'
$task9Artifacts = Join-Path $task9Root 'artifacts'
$task9HeldLink = Join-Path $task9Root 'artifacts_link_task009_preserved'
$task9SavedLink = Join-Path $task9Artifacts 'legacy_task021a_link'
$task9Item = Get-Item -Force -LiteralPath $task9Artifacts
if ($task9Item.LinkType -ne 'Junction' -or $task9Item.Target -ne $task9Source) { throw 'Expected known junction is absent; refusing mutation' }
if ((Test-Path -LiteralPath $task9HeldLink) -or (Test-Path -LiteralPath $task9SavedLink)) { throw 'Backup path already exists' }
# Rename-Item and Move-Item below operate on the reparse point itself, without Recurse.
Rename-Item -LiteralPath $task9Artifacts -NewName (Split-Path -Leaf $task9HeldLink)
New-Item -ItemType Directory -Path $task9Artifacts | Out-Null
Move-Item -LiteralPath $task9HeldLink -Destination $task9SavedLink
if ((Get-Item -Force -LiteralPath $task9Artifacts).LinkType) { throw 'Target artifacts is still a link' }
if ((Get-Item -Force -LiteralPath $task9SavedLink).Target -ne $task9Source) { throw 'Preserved junction changed target' }
$task9Out = Join-Path $task9Artifacts 'research_clean_task9'
New-Item -ItemType Directory -Path $task9Out | Out-Null
New-Item -ItemType Directory -Path (Join-Path $task9Out 'provenance/junction_probe') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $task9Source 'research_clean_task9/*') -Destination (Join-Path $task9Out 'provenance/junction_probe') -Recurse -ErrorAction SilentlyContinue
# LiteralPath does not expand wildcard. Enumerate the six self-created probe files explicitly.
$task9ProbeSource = Join-Path $task9Source 'research_clean_task9'
foreach ($task9File in Get-ChildItem -LiteralPath $task9ProbeSource -Recurse -File) {
    $task9Relative = [System.IO.Path]::GetRelativePath($task9ProbeSource, $task9File.FullName)
    $task9Destination = Join-Path (Join-Path $task9Out 'provenance/junction_probe') $task9Relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $task9Destination) -Force | Out-Null
    if (Test-Path -LiteralPath $task9Destination) { throw "No overwrite: $task9Destination" }
    Copy-Item -LiteralPath $task9File.FullName -Destination $task9Destination
}
foreach ($task9Name in @('__init__.py','audit.py')) {
    Copy-Item -LiteralPath (Join-Path $task9ProbeSource $task9Name) -Destination (Join-Path $task9Out $task9Name)
}
# Retain unrelated legacy artifact paths with their prior junction-backed behavior.
# TASK-008 and TASK-009 are deliberately excluded and become physical local directories.
foreach ($task9Folder in Get-ChildItem -LiteralPath $task9Source -Directory) {
    if ($task9Folder.Name -in @('research_clean_task8','research_clean_task9')) { continue }
    $task9Legacy = Join-Path $task9Artifacts $task9Folder.Name
    if (Test-Path -LiteralPath $task9Legacy) { throw "No overwrite: $task9Legacy" }
    New-Item -ItemType Junction -Path $task9Legacy -Target $task9Folder.FullName | Out-Null
}
Write-Output "Physical local artifacts created: $task9Artifacts"
Write-Output "Original junction preserved: $task9SavedLink"
Write-Output "Probe evidence backed up; source probe directory was not deleted."
