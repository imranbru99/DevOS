# Run the DevOS ISO in Docker Desktop and open its screen in the browser.
#   .\tests\docker-vm\run-devos-vm.ps1            # UEFI boot (default)
#   .\tests\docker-vm\run-devos-vm.ps1 -Legacy    # legacy BIOS boot
#   .\tests\docker-vm\run-devos-vm.ps1 -Reset     # wipe the virtual disk first
#   .\tests\docker-vm\run-devos-vm.ps1 -Stop
#   .\tests\docker-vm\run-devos-vm.ps1 -Iso out\devos-24.04-amd64-v6.iso -Reset
param([switch]$Legacy, [switch]$Reset, [switch]$Stop, [string]$Iso = "")

# Docker writes progress to stderr. With "Stop", Windows PowerShell 5.1
# turns that into a fatal NativeCommandError, so check exit codes instead.
$ErrorActionPreference = "Continue"
$here = $PSScriptRoot
$iso = Join-Path $here "..\..\out\devos-24.04-amd64.iso"
if ($Iso) {
    $iso = (Resolve-Path $Iso -ErrorAction SilentlyContinue).Path
    if (-not $iso) { Write-Host "ISO not found: $Iso" -ForegroundColor Red; exit 1 }
}
$env:DEVOS_ISO = $iso
$compose = Join-Path $here "compose.yml"

if ($Stop) {
    docker compose -f $compose down 2>&1 | Out-Host
    exit 0
}

if (-not (Test-Path $iso)) {
    Write-Host "ISO not found at $iso. Build it first (make iso-docker)." -ForegroundColor Red
    exit 1
}

# Docker Desktop ships KVM as a module that is not loaded after it starts.
# Without /dev/kvm the VM would run in slow software emulation or not at all.
docker run --rm --privileged --pid=host alpine:latest nsenter -t 1 -m -- sh -c "modprobe kvm_intel 2>/dev/null || modprobe kvm_amd; test -e /dev/kvm" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Could not load KVM in Docker Desktop. Enable virtualization (VT-x/AMD-V) in BIOS." -ForegroundColor Red
    exit 1
}

docker compose -f $compose down 2>&1 | Out-Null
if ($Reset) {
    Remove-Item -Recurse -Force (Join-Path $here "storage") -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force (Join-Path $here "storage") | Out-Null

if ($Legacy) { $env:DEVOS_BOOT_MODE = "legacy" } else { $env:DEVOS_BOOT_MODE = "uefi" }
docker compose -f $compose up -d 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { exit 1 }
Start-Sleep -Seconds 3
Start-Process "http://localhost:8006"
Write-Host "DevOS VM is starting. Screen: http://localhost:8006"
