# Package redesigned masters into KDE Plasma wallpaper packages.
# Preserves originals. Larger sizes are high-quality covers of the master —
# NOT claimed as native 4K detail when master is 1280x720.
param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
)

Add-Type -AssemblyName System.Drawing
# ImageFormat lives in System.Drawing; no separate Imaging assembly needed on Windows PowerShell 5.

$collection = Join-Path $RepoRoot 'tools\wallpapers\flagship-collection'
$masters = Join-Path $collection 'redesigned\masters'
$thumbs = Join-Path $collection 'redesigned\thumbs'
$destRoot = Join-Path $RepoRoot 'build\includes.chroot\usr\share\wallpapers'
$mappingPath = Join-Path $collection 'mapping.json'
$progressPath = Join-Path $collection 'progress-manifest.json'

New-Item -ItemType Directory -Force -Path $thumbs | Out-Null

$sizes = @(
  @(1280,720), @(1280,800), @(1366,768), @(1440,900), @(1680,1050),
  @(1920,1080), @(2560,1440), @(2560,1600), @(3840,2160)
)

# id -> package + display name + category + theme + original source
$catalog = @(
  @{ id='home50-01'; file='devos-flagship-home50-01-cyan-orbit.jpg'; pkg='DevOS-Flagship-01-CyanOrbit'; name='Cyan Orbit'; cat='A'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-01-cyan-orbit.jpg'; legacy='DevOS-Home50-01-CyanOrbit' }
  @{ id='home50-02'; file='devos-flagship-home50-02-sapphire-vein.jpg'; pkg='DevOS-Flagship-02-SapphireVein'; name='Sapphire Vein'; cat='B'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-02-sapphire-vein.jpg'; legacy='DevOS-Home50-02-SapphireVein' }
  @{ id='home50-03'; file='devos-flagship-home50-03-glass-kernel.jpg'; pkg='DevOS-Flagship-03-GlassKernel'; name='Glass Kernel'; cat='B'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-03-glass-kernel.jpg'; legacy='DevOS-Home50-03-GlassKernel' }
  @{ id='home50-04'; file='devos-flagship-home50-04-night-buffer.jpg'; pkg='DevOS-Flagship-04-NightBuffer'; name='Night Buffer'; cat='C'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-04-night-buffer.jpg'; legacy='DevOS-Home50-04-NightBuffer' }
  @{ id='home50-08'; file='devos-flagship-home50-08-pearl-dawn.jpg'; pkg='DevOS-Flagship-08-PearlDawn'; name='Pearl Dawn'; cat='F'; theme='light'; original='tools/wallpapers/premium-collection/originals/devos-home50-08-pearl-dawn.jpg'; legacy='DevOS-Home50-08-PearlDawn' }
  @{ id='home50-09'; file='devos-flagship-home50-09-ink-horizon.jpg'; pkg='DevOS-Flagship-09-InkHorizon'; name='Ink Horizon'; cat='C'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-09-ink-horizon.jpg'; legacy='DevOS-Home50-09-InkHorizon' }
  @{ id='home50-10'; file='devos-flagship-home50-10-prism-dock.jpg'; pkg='DevOS-Flagship-10-PrismDock'; name='Prism Dock'; cat='B'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-10-prism-dock.jpg'; legacy='DevOS-Home50-10-PrismDock' }
  @{ id='home50-11'; file='devos-flagship-home50-11-aurora-shell.jpg'; pkg='DevOS-Flagship-11-AuroraShell'; name='Aurora Shell'; cat='G'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-11-aurora-shell.jpg'; legacy='DevOS-Home50-11-AuroraShell' }
  @{ id='home50-14'; file='devos-flagship-home50-14-graphite-halo.jpg'; pkg='DevOS-Flagship-14-GraphiteHalo'; name='Graphite Halo'; cat='B'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-14-graphite-halo.jpg'; legacy='DevOS-Home50-14-GraphiteHalo' }
  @{ id='home50-18'; file='devos-flagship-home50-18-liquid-lens.jpg'; pkg='DevOS-Flagship-18-LiquidLens'; name='Liquid Lens'; cat='B'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-18-liquid-lens.jpg'; legacy='DevOS-Home50-18-LiquidLens' }
  @{ id='home50-19'; file='devos-flagship-home50-19-void-ring.jpg'; pkg='DevOS-Flagship-19-VoidRing'; name='Void Ring'; cat='B'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-19-void-ring.jpg'; legacy='DevOS-Home50-19-VoidRing' }
  @{ id='home50-20'; file='devos-flagship-home50-20-home-bloom.jpg'; pkg='DevOS-Flagship-20-HomeBloom'; name='Home Bloom'; cat='A'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-20-home-bloom.jpg'; legacy='DevOS-Home50-20-HomeBloom' }
  @{ id='home50-25'; file='devos-flagship-home50-25-ice-cathedral.jpg'; pkg='DevOS-Flagship-25-IceCathedral'; name='Ice Cathedral'; cat='D'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-25-ice-cathedral.jpg'; legacy='DevOS-Home50-25-IceCathedral' }
  @{ id='home50-27'; file='devos-flagship-home50-27-silver-cascade.jpg'; pkg='DevOS-Flagship-27-SilverCascade'; name='Silver Cascade'; cat='E'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-27-silver-cascade.jpg'; legacy='DevOS-Home50-27-SilverCascade' }
  @{ id='home50-30'; file='devos-flagship-home50-30-alpine-glass.jpg'; pkg='DevOS-Flagship-30-AlpineGlass'; name='Alpine Glass'; cat='H'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-30-alpine-glass.jpg'; legacy='DevOS-Home50-30-AlpineGlass' }
  @{ id='home50-32'; file='devos-flagship-home50-32-obsidian-pool.jpg'; pkg='DevOS-Flagship-32-ObsidianPool'; name='Obsidian Pool'; cat='E'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-32-obsidian-pool.jpg'; legacy='DevOS-Home50-32-ObsidianPool' }
  @{ id='home50-35'; file='devos-flagship-home50-35-lattice-dawn.jpg'; pkg='DevOS-Flagship-35-LatticeDawn'; name='Lattice Dawn'; cat='F'; theme='light'; original='tools/wallpapers/premium-collection/originals/devos-home50-35-lattice-dawn.jpg'; legacy='DevOS-Home50-35-LatticeDawn' }
  @{ id='home50-39'; file='devos-flagship-home50-39-ink-studio.jpg'; pkg='DevOS-Flagship-39-InkStudio'; name='Ink Studio'; cat='C'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-39-ink-studio.jpg'; legacy='DevOS-Home50-39-InkStudio' }
  @{ id='home50-41'; file='devos-flagship-home50-41-arc-line.jpg'; pkg='DevOS-Flagship-41-ArcLine'; name='Arc Line'; cat='B'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-41-arc-line.jpg'; legacy='DevOS-Home50-41-ArcLine' }
  @{ id='home50-42'; file='devos-flagship-home50-42-soft-binary.jpg'; pkg='DevOS-Flagship-42-SoftBinary'; name='Soft Binary'; cat='C'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-42-soft-binary.jpg'; legacy='DevOS-Home50-42-SoftBinary' }
  @{ id='home50-47'; file='devos-flagship-home50-47-neon-filament.jpg'; pkg='DevOS-Flagship-47-NeonFilament'; name='Neon Filament'; cat='B'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-47-neon-filament.jpg'; legacy='DevOS-Home50-47-NeonFilament' }
  @{ id='home50-48'; file='devos-flagship-home50-48-tidal-glass.jpg'; pkg='DevOS-Flagship-48-TidalGlass'; name='Tidal Glass'; cat='E'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-48-tidal-glass.jpg'; legacy='DevOS-Home50-48-TidalGlass' }
  @{ id='home50-49'; file='devos-flagship-home50-49-north-glow.jpg'; pkg='DevOS-Flagship-49-NorthGlow'; name='North Glow'; cat='G'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-49-north-glow.jpg'; legacy='DevOS-Home50-49-NorthGlow' }
  @{ id='home50-50'; file='devos-flagship-home50-50-apex-bloom.jpg'; pkg='DevOS-Flagship-50-ApexBloom'; name='Apex Bloom'; cat='A'; theme='dark'; original='tools/wallpapers/premium-collection/originals/devos-home50-50-apex-bloom.jpg'; legacy='DevOS-Home50-50-ApexBloom' }
  @{ id='master-flagship-dark'; file='devos-flagship-master-flagship-dark.jpg'; pkg='DevOS-Flagship-Master-GlassRibbon'; name='Glass Ribbon'; cat='A'; theme='dark'; original='tools/wallpapers/master_sources/devos_flagship_masterpiece_dark_1792973005707.jpg'; legacy='DevOS-CelestialBloom' }
  @{ id='master-alpine'; file='devos-flagship-master-alpine.jpg'; pkg='DevOS-Flagship-Master-AlpineLake'; name='Alpine Lake'; cat='H'; theme='light'; original='tools/wallpapers/master_sources/devos_alpine_lake_wildflowers_light_1792973108587.jpg'; legacy='DevOS-AlpineTerrace' }
  @{ id='master-prism-bloom'; file='devos-flagship-master-prism-bloom.jpg'; pkg='DevOS-Flagship-Master-PrismBloom'; name='Prism Bloom'; cat='F'; theme='light'; original='tools/wallpapers/master_sources/devos_frosted_prism_bloom_light_1792973072171.jpg'; legacy=$null }
  @{ id='master-cosmic-orbit'; file='devos-flagship-master-cosmic-orbit.jpg'; pkg='DevOS-Flagship-Master-CosmicOrbit'; name='Cosmic Orbit'; cat='G'; theme='dark'; original='tools/wallpapers/master_sources/devos_cosmic_earth_orbit_1792973067991.jpg'; legacy='DevOS-CosmicOrbit' }
)

function Save-Cover([System.Drawing.Image]$master, [string]$outPath, [int]$tw, [int]$th) {
  $scale = [Math]::Max($tw / $master.Width, $th / $master.Height)
  $nw = [int][Math]::Ceiling($master.Width * $scale)
  $nh = [int][Math]::Ceiling($master.Height * $scale)
  $bmp = New-Object System.Drawing.Bitmap $tw, $th
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
  $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
  $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
  $left = [int](($nw - $tw) / 2)
  $top = [int](($nh - $th) / 2)
  $g.DrawImage($master, (New-Object System.Drawing.Rectangle (-$left), (-$top), $nw, $nh))
  $g.Dispose()
  $bmp.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
}

$mapping = @{
  version = 1
  created_at = (Get-Date).ToString('o')
  note = 'Reversible mapping. Originals preserved. Flagship packages are additive; legacy packages untouched.'
  native_master_resolution = '1280x720 (GenerateImage output). Larger Plasma sizes are covers/upscales — not native 4K detail.'
  entries = @()
}

$manifestItems = @()
$packaged = 0

foreach ($item in $catalog) {
  $srcPath = Join-Path $masters $item.file
  if (-not (Test-Path $srcPath)) {
    Write-Warning "Missing master: $($item.file)"
    continue
  }
  $master = [System.Drawing.Image]::FromFile($srcPath)
  $pkgDir = Join-Path $destRoot $item.pkg
  $images = Join-Path $pkgDir 'contents\images'
  New-Item -ItemType Directory -Force -Path $images | Out-Null

  $nativeName = '{0}x{1}.png' -f $master.Width, $master.Height
  Save-Cover $master (Join-Path $images $nativeName) $master.Width $master.Height
  Copy-Item (Join-Path $images $nativeName) (Join-Path $images 'wallpaper.png') -Force
  Copy-Item (Join-Path $images $nativeName) (Join-Path $pkgDir 'contents\screenshot.png') -Force

  foreach ($sz in $sizes) {
    $tw, $th = $sz[0], $sz[1]
    $out = Join-Path $images ("{0}x{1}.png" -f $tw, $th)
    if ($tw -eq $master.Width -and $th -eq $master.Height) { continue }
    Save-Cover $master $out $tw $th
  }

  # lazy thumb ~480px wide
  $thumbW = 480
  $thumbH = [int](480 * $master.Height / $master.Width)
  $thumbPath = Join-Path $thumbs ($item.file -replace '\.jpg$', '-thumb.jpg')
  $tb = New-Object System.Drawing.Bitmap $thumbW, $thumbH
  $tg = [System.Drawing.Graphics]::FromImage($tb)
  $tg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $tg.DrawImage($master, 0, 0, $thumbW, $thumbH)
  $tg.Dispose()
  $tb.Save($thumbPath, [System.Drawing.Imaging.ImageFormat]::Jpeg)
  $tb.Dispose()

  $meta = @{
    KPlugin = @{
      Id = $item.pkg
      Name = "DevOS Flagship · $($item.name)"
      Authors = @(@{ Name = 'Imran Ahmed'; Email = 'me@imrandev.bd' })
      Website = 'https://imrandev.bd'
      Description = "DevOS flagship wallpaper ($($item.cat)/$($item.theme)). Master $($master.Width)x$($master.Height); larger sizes are covers."
    }
    DevOSFlagship = @{
      category = $item.cat
      theme = $item.theme
      masterWidth = $master.Width
      masterHeight = $master.Height
      native4k = $false
      sourceMaster = "tools/wallpapers/flagship-collection/redesigned/masters/$($item.file)"
    }
  }
  ($meta | ConvertTo-Json -Depth 6) | Set-Content -Encoding utf8 (Join-Path $pkgDir 'metadata.json')

  $mapping.entries += [ordered]@{
    id = $item.id
    original = $item.original
    redesigned_master = "tools/wallpapers/flagship-collection/redesigned/masters/$($item.file)"
    flagship_package = $item.pkg
    legacy_package = $item.legacy
    reversible = $true
  }

  $manifestItems += [ordered]@{
    id = $item.id
    name = $item.name
    category = $item.cat
    theme = $item.theme
    package = $item.pkg
    source = "build/includes.chroot/usr/share/wallpapers/$($item.pkg)/contents/images/$nativeName"
    width = $master.Width
    height = $master.Height
    native_4k = $false
    sizes = @($sizes | ForEach-Object { '{0}x{1}' -f $_[0], $_[1] }) + @('wallpaper')
  }

  $master.Dispose()
  $packaged++
  Write-Host "Packaged $($item.pkg)"
}

($mapping | ConvertTo-Json -Depth 8) | Set-Content -Encoding utf8 $mappingPath
$shipManifest = @{
  collection = 'DevOS Flagship'
  packaged_at = (Get-Date).ToString('o')
  count = $manifestItems.Count
  items = $manifestItems
}
($shipManifest | ConvertTo-Json -Depth 8) | Set-Content -Encoding utf8 (Join-Path $collection 'manifest.json')

# Gallery with lazy thumbs
$cards = foreach ($m in $manifestItems) {
  $thumb = "redesigned/thumbs/" + (($catalog | Where-Object id -eq $m.id).file -replace '\.jpg$','-thumb.jpg')
  $href = "../../../build/includes.chroot/usr/share/wallpapers/$($m.package)/contents/images/wallpaper.png"
  "<a href=`"$href`"><img loading=`"lazy`" src=`"$thumb`" alt=`"$($m.name)`"><span>$($m.id) — $($m.name) · $($m.category)/$($m.theme)</span></a>"
}
$gallery = @"
<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevOS Flagship Collection</title>
<style>
body{margin:0;padding:48px;background:#070910;color:#eff4ff;font:16px/1.45 "Segoe UI",system-ui}
h1{font-size:40px;letter-spacing:-.04em;margin:0 0 8px;color:#38bdf8}
p{color:#acbdd5;margin:0 0 36px;max-width:60ch}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}
a{color:inherit;text-decoration:none;background:#0f172a;border:1px solid #243247;border-radius:16px;overflow:hidden}
img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;background:#111}
span{display:block;padding:18px}
a:hover{border-color:#38bdf8}
</style>
<h1>DevOS Flagship</h1>
<p>Batch redesign masters (subject-aware). Thumbs load lazily. Plasma packages are additive beside legacy Home50/Premium sets.</p>
<div class="grid">$($cards -join "`n")</div>
"@
Set-Content -Encoding utf8 (Join-Path $collection 'gallery.html') $gallery

Write-Host "Done. Packaged $packaged wallpapers."
