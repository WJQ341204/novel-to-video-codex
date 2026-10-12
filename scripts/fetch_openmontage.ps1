# Restore OpenMontage (vendored dependency of the cloud video engines).
# Usage (from repo root):  powershell -ExecutionPolicy Bypass -File scripts\fetch_openmontage.ps1
# Upstream: https://github.com/calesthio/OpenMontage
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $root "OpenMontage"
$url  = "https://github.com/calesthio/OpenMontage.git"

if (Test-Path $dest) {
    Write-Host "OpenMontage already present: $dest"
    Write-Host "To update it manually: git -C `"$dest`" pull"
    exit 0
}

Write-Host "Cloning $url -> $dest ..."
git clone --depth 1 $url $dest
if ($LASTEXITCODE -ne 0) { Write-Error "clone failed"; exit 1 }

# engines/cli.py reads API keys from OpenMontage/.env
$envExample = Join-Path $dest ".env.example"
$envFile    = Join-Path $dest ".env"
if ((Test-Path $envExample) -and -not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host "Created $envFile - fill in real API keys (engines/cli.py reads them)."
}

Write-Host "Done. Cloud engines are restorable again."
Write-Host "Note: with settings.yaml video_mode=local (current) this dependency is unused."
