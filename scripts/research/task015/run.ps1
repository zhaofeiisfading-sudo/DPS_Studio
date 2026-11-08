#requires -Version 7.0
param([string]$Python = 'python', [Parameter(ValueFromRemainingArguments = $true)][string[]]$PythonArgs)
$task15Repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
& (Join-Path $task15Repo 'scripts/dev/run.ps1') -Task TASK-015 -Python $Python @PythonArgs
exit $LASTEXITCODE
