$iso = Get-Item "C:\docker\DevOS\out\devos-24.04-amd64.iso"
$sizeMb = [Math]::Round($iso.Length / (1024 * 1024), 2)
$sizeGb = [Math]::Round($iso.Length / (1024 * 1024 * 1024), 2)
$hash = (Get-FileHash -Path $iso.FullName -Algorithm SHA256).Hash

Write-Host "File: $($iso.FullName)"
Write-Host "Size: $sizeMb MB ($sizeGb GB / $($iso.Length) bytes)"
Write-Host "SHA256: $hash"
