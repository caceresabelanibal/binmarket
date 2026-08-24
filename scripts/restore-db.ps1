# Restores a .sql dump produced by backup-db.ps1 into the running
# docker-compose Postgres. DESTRUCTIVE. Usage: .\scripts\restore-db.ps1 .\backups\binmarket_....sql
param([Parameter(Mandatory=$true)][string]$DumpFile)

Set-Location (Join-Path $PSScriptRoot "..")

$envVars = @{}
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $envVars[$matches[1]] = $matches[2]
    }
}

$confirm = Read-Host "This will OVERWRITE the current database '$($envVars.POSTGRES_DB)'. Type 'yes' to continue"
if ($confirm -ne "yes") {
    Write-Host "Aborted."
    exit 1
}

Write-Host "Restoring $DumpFile into '$($envVars.POSTGRES_DB)' ..."
Get-Content $DumpFile | docker compose exec -T postgres psql -U $envVars.POSTGRES_USER -d $envVars.POSTGRES_DB
Write-Host "Restore complete."
