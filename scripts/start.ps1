$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectDir

docker compose build mock-api etl dashboard
docker compose up -d db mock-api dashboard
docker compose run --rm etl python -m etl.cli full

Write-Host ""
Write-Host "Платформа запущена:"
Write-Host "  API:       http://localhost:8000/docs"
Write-Host "  Dashboard: http://localhost:8501"
