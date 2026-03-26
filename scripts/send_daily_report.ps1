$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$outputDir = Join-Path $repoRoot "reports"

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
Set-Location $repoRoot

$arguments = @(
    "main.py",
    "--no-cache",
    "--export",
    "html",
    "--output-dir",
    $outputDir,
    "--send-teams"
)

if ($env:PERFSRAPER_TEAMS_WEBHOOK_URL) {
    $arguments += @("--teams-webhook-url", $env:PERFSRAPER_TEAMS_WEBHOOK_URL)
}

& py @arguments
exit $LASTEXITCODE
