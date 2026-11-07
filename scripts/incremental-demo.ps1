$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectDir

Invoke-RestMethod -Method Post -Uri "http://localhost:8000/admin/advance?new_count=100&update_count=20"
docker compose run --rm etl python -m etl.cli incremental

Write-Host "Инкрементальная загрузка завершена. Обновите страницу http://localhost:8501"
