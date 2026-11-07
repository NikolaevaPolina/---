$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectDir

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectDir "artifacts") | Out-Null
docker compose build etl
docker compose run --rm etl python -m etl.benchmark_stable --targets 7200 12000 22000 --repeats 3 --batch-size 100

Write-Host "Результаты сохранены в artifacts/benchmark_stable_summary.csv и benchmark_stable.svg"
