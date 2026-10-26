# Headless screenshot capture for the ECCO 3D Energy Flow preview harness.
# Local tool only: starts preview/serve.mjs, drives a headless Chrome/Edge
# against each scenario at phone and desktop widths, writes PNGs to -OutDir.
#
#   cls; .\preview\capture.ps1 -OutDir C:\path\to\screenshots
param(
    [string]$OutDir = (Join-Path $env:TEMP "ecco-flow-3d-preview"),
    [int]$Port = 8765,
    [string[]]$Scenarios = @("day-export", "night-discharge", "night-import-charge", "dump-active", "idle", "unknown", "stale", "attention"),
    [string]$Assets = "",
    [string]$Img = "",
    [string[]]$Scenes = @(),
    [string[]]$Only = @(),
    [string]$Extra = "",
    [switch]$KeepServer
)
cls
$ErrorActionPreference = "Stop"
$card = Resolve-Path (Join-Path $PSScriptRoot "..")
$browser = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browser) { throw "No Chrome or Edge found for headless capture." }
New-Item -ItemType Directory -Force $OutDir | Out-Null

$serverArgs = @("preview/serve.mjs", "$Port"); if ($Assets) { $serverArgs += $Assets }
$server = Start-Process -FilePath "node" -ArgumentList $serverArgs -WorkingDirectory $card -PassThru -WindowStyle Hidden
try {
    Start-Sleep -Milliseconds 900
    $profile = Join-Path $env:TEMP ("ecco-flow-3d-capture-" + [guid]::NewGuid().ToString("N"))
    # Chrome clamps a headless window to roughly 500 px wide, so the phone
    # capture renders a 390 px frame left-aligned in a 520 px window and is
    # cropped to the frame afterwards (System.Drawing, no extra tooling).
    $sizes = @(
        @{ name = "mobile"; w = 520; h = 1320; frame = 390; crop = 414 },
        @{ name = "tablet"; w = 800; h = 1500; frame = 768; crop = 792 },
        @{ name = "desktop"; w = 1280; h = 980; frame = 1200; crop = 0 },
        @{ name = "wide"; w = 1920; h = 1300; frame = 1880; crop = 0 }
    )
    if ($Only.Count -gt 0) { $sizes = @($sizes | Where-Object { $Only -contains $_.name }) }
    # With -Scenes, one capture per scene (night scenes use the night-discharge telemetry, day scenes day-export).
    $jobs = @()
    if ($Scenes.Count -gt 0) {
        foreach ($sc in $Scenes) {
            $scenario = if ($sc -match "night") { "night-discharge" } else { "day-export" }
            $jobs += @{ name = "scene-$sc"; query = "s=$scenario&scene=$sc" }
        }
    } else {
        foreach ($s in $Scenarios) { $jobs += @{ name = $s; query = "s=$s" } }
    }
    foreach ($j in $jobs) {
        foreach ($z in $sizes) {
            $out = Join-Path $OutDir ("{0}-{1}.png" -f $j.name, $z.name)
            $url = "http://127.0.0.1:$Port/preview/index.html?$($j.query)&w=$($z.frame)&chrome=0" + $(if ($Img) { "&img=$Img" } else { "" }) + $(if ($Extra) { "&$Extra" } else { "" })
            $args = @(
                "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
                "--user-data-dir=$profile", "--window-size=$($z.w),$($z.h)", "--virtual-time-budget=2500",
                "--screenshot=$out", $url
            )
            # Start-Process keeps Chrome's own stderr chatter out of PowerShell 5.1's error stream.
            Start-Process -FilePath $browser -ArgumentList $args -Wait -WindowStyle Hidden
            if ((Test-Path $out) -and $z.crop -gt 0) {
                # Crop the left-aligned phone frame out of the clamped window (PIL; System.Drawing proved flaky here).
                $py = "from PIL import Image; im = Image.open(r'$out'); im.crop((0, 0, min($($z.crop), im.width), im.height)).save(r'$out')"
                & python -I -c $py
            }
            if (Test-Path $out) { Write-Host ("captured {0}" -f $out) } else { Write-Host ("FAILED {0}" -f $out) -ForegroundColor Red }
        }
    }
    Remove-Item -Recurse -Force $profile -ErrorAction SilentlyContinue
}
finally {
    if (-not $KeepServer -and $server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}
Write-Host "done: $OutDir"
