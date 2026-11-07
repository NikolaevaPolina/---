$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectDir

$EnvPath = Join-Path $ProjectDir ".env"
if (-not (Test-Path -LiteralPath $EnvPath)) {
    throw "Создайте .env по образцу .env.example и задайте POSTGRES_PASSWORD."
}
if (-not (Select-String -LiteralPath $EnvPath -Pattern '^\s*POSTGRES_PASSWORD\s*=\s*\S+' -Quiet)) {
    throw "Задайте POSTGRES_PASSWORD в локальном файле .env."
}

docker compose build mock-api etl dashboard
docker compose up -d db mock-api dashboard
docker compose run --rm etl python -m etl.cli full

Write-Host ""
Write-Host "Платформа запущена:"
Write-Host "  API:       http://localhost:8000/docs"
Write-Host "  Dashboard: http://localhost:8501"
