# Build (if needed) and run the FinAlly container on http://localhost:8000.
# Idempotent: safe to run repeatedly. Pass -Build to force a rebuild.
param([switch]$Build)

$ErrorActionPreference = "Stop"

$Image     = "finally"
$Container = "finally"
$Volume    = "finally-data"
$Port      = "8000"

$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

if (-not (Test-Path ".env")) {
    Write-Host "No .env found; copying .env.example. Edit it to add your OPENROUTER_API_KEY."
    Copy-Item ".env.example" ".env"
}

$imageExists = docker image inspect $Image 2>$null
if ($Build -or -not $imageExists) {
    Write-Host "Building image '$Image'..."
    docker build -t $Image .
}

# Friendly hint about the market data source (does not mutate .env).
$MassiveLine = Select-String -Path ".env" -Pattern '^MASSIVE_API_KEY=(.*)$' | Select-Object -Last 1
if ($MassiveLine -and $MassiveLine.Matches[0].Groups[1].Value.Trim()) {
    Write-Host "Using Massive live data; blank MASSIVE_API_KEY in .env to use the simulator."
}

# Remove any existing container so this is safe to re-run.
docker rm -f $Container 2>$null | Out-Null

Write-Host "Starting container '$Container'..."
docker run -d `
    --name $Container `
    --env-file .env `
    -e FINALLY_DB_PATH=/app/db/finally.db `
    -v "${Volume}:/app/db" `
    -p "${Port}:8000" `
    $Image | Out-Null

$Url = "http://localhost:$Port"
Write-Host "FinAlly is running at $Url"
Start-Process $Url
