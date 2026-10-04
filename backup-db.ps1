# Backs up the MSUEdu AI database (and uploaded files). Run in the project folder:  .\backup-db.ps1
# If mysqldump is not on your PATH, pass its location:
#   .\backup-db.ps1 -MysqlDump "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe"
# Backups contain personal data: keep them private. The backups folder is ignored by Git.
param([string]$MysqlDump = "mysqldump", [int]$Keep = 14)
$ErrorActionPreference = "Stop"

$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) { throw ".env was not found in $PSScriptRoot" }
$cfg = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*?)\s*$') { $cfg[$matches[1]] = $matches[2].Trim('"') }
}
foreach ($name in "DB_USER", "DB_PASSWORD", "DB_NAME") {
    if (-not $cfg[$name]) { throw "$name is missing in .env" }
}
$dbHost = if ($cfg["DB_HOST"]) { $cfg["DB_HOST"] } else { "localhost" }
$port = if ($cfg["DB_PORT"]) { $cfg["DB_PORT"] } else { "3306" }

$backups = Join-Path $PSScriptRoot "backups"
New-Item -ItemType Directory -Force -Path $backups | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$sqlFile = Join-Path $backups "msuedu_$stamp.sql"

# The password goes in a temporary file (not on the command line, where other programs could see it).
# A password containing a double quote or a backslash would break this: avoid those characters.
$cnf = Join-Path $env:TEMP ("msuedu_" + [guid]::NewGuid().ToString("N") + ".cnf")
Set-Content -Path $cnf -Encoding ASCII -Value @(
    "[client]", "user=$($cfg['DB_USER'])", "password=`"$($cfg['DB_PASSWORD'])`"", "host=$dbHost", "port=$port")
try {
    & $MysqlDump "--defaults-extra-file=$cnf" --single-transaction --no-tablespaces $cfg["DB_NAME"] "--result-file=$sqlFile"
    if ($LASTEXITCODE -ne 0) { throw "mysqldump failed (exit code $LASTEXITCODE)" }
} finally {
    Remove-Item $cnf -Force -ErrorAction SilentlyContinue
}
Write-Host "Database saved to $sqlFile"

$uploads = if ($cfg["UPLOAD_FOLDER"]) { $cfg["UPLOAD_FOLDER"] } else { "uploads" }
if (-not [System.IO.Path]::IsPathRooted($uploads)) { $uploads = Join-Path $PSScriptRoot $uploads }
if (Test-Path $uploads) {
    $zip = Join-Path $backups "uploads_$stamp.zip"
    Compress-Archive -Path (Join-Path $uploads "*") -DestinationPath $zip -Force
    Write-Host "Uploaded files saved to $zip"
}

foreach ($pattern in "msuedu_*.sql", "uploads_*.zip") {
    Get-ChildItem $backups -Filter $pattern | Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $Keep | Remove-Item -Force
}
Write-Host "Done. The newest $Keep backups of each kind are kept."