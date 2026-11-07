$ErrorActionPreference = "Stop"

$Docker = Get-Command docker -ErrorAction SilentlyContinue
$Git = Get-Command git -ErrorAction SilentlyContinue

if ($Git) {
    Write-Host "[OK] Git найден: $($Git.Source)"
} else {
    Write-Host "[НУЖНО] Установить Git"
}

if ($Docker) {
    Write-Host "[OK] Docker найден: $($Docker.Source)"
    docker compose version
} else {
    Write-Host "[НУЖНО] Установить и запустить Docker Desktop"
}

if (-not $Git -or -not $Docker) {
    exit 1
}
