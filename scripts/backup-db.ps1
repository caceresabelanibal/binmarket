# Dumps the running docker-compose Postgres to a timestamped .sql file in
# .\backups\. Usage: .\scripts\backup-db.ps1 [-OutDir .\backups]
param([string]$OutDir = ".\backups")

Set-Location (Join-Path $PSScriptRoot "..")
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$envVars = @{}
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $envVars[$matches[1]] = $matches[2]
    }
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outFile = Join-Path $OutDir "binmarket_$timestamp.sql"

Write-Host "Dumping database '$($envVars.POSTGRES_DB)' to $outFile ..."
docker compose exec -T postgres pg_dump -U $envVars.POSTGRES_USER -d $envVars.POSTGRES_DB > $outFile
Write-Host "Done: $outFile"
