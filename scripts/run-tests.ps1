# Spins up throwaway Postgres + Redis containers, runs the backend/shared
# pytest suite against them, then tears everything down.
$PgContainer = "binmarket-test-pg"
$RedisContainer = "binmarket-test-redis"
$PgPort = 55432
$RedisPort = 56379

function Cleanup {
    docker rm -f $PgContainer $RedisContainer 2>$null | Out-Null
}

Cleanup
docker run -d --name $PgContainer -e POSTGRES_DB=binmarket_test -e POSTGRES_USER=binmarket `
    -e POSTGRES_PASSWORD=binmarket -p "${PgPort}:5432" postgres:16-alpine | Out-Null
docker run -d --name $RedisContainer -p "${RedisPort}:6379" redis:7-alpine | Out-Null

Write-Host "Waiting for Postgres..."
for ($i = 0; $i -lt 30; $i++) {
    docker exec $PgContainer pg_isready -U binmarket 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
}

$env:POSTGRES_HOST = "localhost"
$env:POSTGRES_PORT = "$PgPort"
$env:POSTGRES_DB = "binmarket_test"
$env:POSTGRES_USER = "binmarket"
$env:POSTGRES_PASSWORD = "binmarket"
$env:REDIS_URL = "redis://localhost:${RedisPort}/0"
$env:SECRET_KEY = "test-secret-key"
$env:ADMIN_PASSWORD = "test-admin-password"

try {
    Set-Location (Join-Path $PSScriptRoot "..")
    python -m pytest tests @args
} finally {
    Cleanup
}
