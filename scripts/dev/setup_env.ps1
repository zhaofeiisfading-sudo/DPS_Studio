Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

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
    Write-Host "Updating environment: $EnvironmentName" -ForegroundColor Cyan
    conda env update -n $EnvironmentName -f environment.yml --prune
}
else {
    Write-Host "Creating environment: $EnvironmentName" -ForegroundColor Cyan
    conda env create -f environment.yml
}

conda run -n $EnvironmentName python -m pip install --upgrade pip
conda run -n $EnvironmentName python -m pip install -e ".[dev]"

conda run -n $EnvironmentName python -m dps_studio --version
conda run -n $EnvironmentName pytest
conda run -n $EnvironmentName ruff check .

Write-Host "Environment setup and validation completed." -ForegroundColor Green