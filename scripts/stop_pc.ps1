# Stop and remove the FinAlly container. The data volume is preserved.
# Idempotent: safe to run when nothing is running.
$ErrorActionPreference = "Stop"

$Container = "finally"

$removed = docker rm -f $Container 2>$null
if ($removed) {
    Write-Host "Stopped and removed container '$Container'. Data volume preserved."
} else {
    Write-Host "No running container '$Container' found."
}
