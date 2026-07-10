Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Command,
        [Parameter(Mandatory = $true)][string]$Description
    )

    Write-Host $Description -ForegroundColor Cyan
    & $Command

    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "Conda was not found. Run 'conda init powershell' and reopen PowerShell."
}

$EnvironmentName = "dps-studio"
$EnvironmentList = conda env list --json | ConvertFrom-Json
$EnvironmentExists = $false

foreach ($EnvironmentPath in $EnvironmentList.envs) {
    if ((Split-Path $EnvironmentPath -Leaf) -eq $EnvironmentName) {
        $EnvironmentExists = $true
        break
    }
}

if ($EnvironmentExists) {
    Invoke-Checked `
        -Description "Updating Conda environment: $EnvironmentName" `
        -Command { conda env update -n $EnvironmentName -f environment.yml --prune }
}
else {
    Invoke-Checked `
        -Description "Creating Conda environment: $EnvironmentName" `
        -Command { conda env create -f environment.yml }
}

Invoke-Checked `
    -Description "Upgrading pip" `
    -Command { conda run -n $EnvironmentName python -m pip install --upgrade pip }

Invoke-Checked `
    -Description "Installing DPS Studio and development dependencies" `
    -Command { conda run -n $EnvironmentName python -m pip install -e ".[dev]" }

Invoke-Checked `
    -Description "Checking package version" `
    -Command { conda run -n $EnvironmentName python -m dps_studio --version }

Invoke-Checked `
    -Description "Running tests" `
    -Command { conda run -n $EnvironmentName python -m pytest }

Invoke-Checked `
    -Description "Running Ruff" `
    -Command { conda run -n $EnvironmentName python -m ruff check . }

Write-Host ""
Write-Host "Environment setup and validation completed successfully." -ForegroundColor Green