$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$config = (Join-Path $root "firmware\config").Replace("\", "/")
$keymap = (Join-Path $root "firmware\config\hw75_dynamic.keymap").Replace("\", "/")
$env:PATH = "$(Join-Path $root '.tools\protoc-3.20.3\bin');$env:PATH"
$env:ZEPHYR_TOOLCHAIN_VARIANT = "gnuarmemb"
$env:GNUARMEMB_TOOLCHAIN_PATH = "C:\Program Files (x86)\Arm GNU Toolchain arm-none-eabi\14.2 rel1"
$env:ZEPHYR_BASE = (Join-Path $root "firmware\zephyr").Replace("\", "/")
$modules = @(
    $config,
    (Join-Path $root "firmware\zmk\app\module").Replace("\", "/"),
    (Join-Path $root "firmware\modules\hal\cmsis").Replace("\", "/"),
    (Join-Path $root "firmware\modules\hal\stm32").Replace("\", "/"),
    (Join-Path $root "firmware\modules\lib\gui\lvgl").Replace("\", "/"),
    (Join-Path $root "firmware\modules\lib\nanopb").Replace("\", "/")
) -join ";"

function Invoke-Checked([scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

Push-Location (Join-Path $root "firmware")
try {
    foreach ($revision in @("A", "B")) {
        $build = "build-$revision"
        if (-not (Test-Path (Join-Path $build "CMakeCache.txt"))) {
            Invoke-Checked {
                cmake -S zmk/app -B $build -GNinja `
                    "-DBOARD=hw75_dynamic@$revision" `
                    "-DZMK_CONFIG=$config" `
                    "-DKEYMAP_FILE=$keymap" `
                    "-DZEPHYR_MODULES=$modules"
            }
        }
        Invoke-Checked { cmake --build $build }
    }
}
finally {
    Pop-Location
}

$release = Join-Path $root "release-focus-weather-temperature"
$firmwareOut = Join-Path $release "firmware"
New-Item -ItemType Directory -Force $firmwareOut | Out-Null
Copy-Item (Join-Path $root "firmware\build-A\zephyr\zmk.uf2") `
    (Join-Path $firmwareOut "HW75-FOCUS-Weather-A.uf2") -Force
Copy-Item (Join-Path $root "firmware\build-B\zephyr\zmk.uf2") `
    (Join-Path $firmwareOut "HW75-FOCUS-Weather-B.uf2") -Force

$hashes = Get-ChildItem $release -File -Recurse |
    Where-Object Name -ne "SHA256SUMS.txt" |
    Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash)  $($_.Path.Substring($release.Length + 1))" }
Set-Content (Join-Path $release "SHA256SUMS.txt") $hashes -Encoding UTF8

Write-Host ""
Write-Host "Firmware generated:" -ForegroundColor Green
Write-Host $firmwareOut
