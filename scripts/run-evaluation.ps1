# Load the repo-root .env, then run the evaluation checks in order:
# API tests, the scripted-judge experiment, then the model-judge experiment.
# Stops at the first failure. Does not print secret values.
#
#   powershell -ExecutionPolicy Bypass -File scripts/run-evaluation.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
$api = Join-Path $root "api"

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw ".env not found at $Path"
    }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            return
        }
        if ($line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            return
        }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        Set-Item -Path "Env:$name" -Value $value
    }
}

function Require-Env {
    param([string]$Name)
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$Name is missing. Set it in the repo-root .env."
    }
    Write-Host "$Name is set"
}

function Invoke-Step {
    param(
        [string]$Title,
        [scriptblock]$Action
    )
    Write-Host ""
    Write-Host "== $Title =="
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Title failed with exit code $LASTEXITCODE"
    }
}

Import-DotEnv -Path $envFile
Require-Env -Name "OPENAI_API_KEY"
Require-Env -Name "LANGSMITH_API_KEY"

Push-Location $api
try {
    Invoke-Step "pytest" { python -m pytest }
    Invoke-Step "scripted judge" { python experiment.py --scripted-judge }
    Invoke-Step "model judge" { python experiment.py }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "evaluation passed"
exit 0
