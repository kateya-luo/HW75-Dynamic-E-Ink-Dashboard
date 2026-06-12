param(
    [ValidateSet("All", "Firmware", "Host")]
    [string]$Target = "All"
)

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

if ($Target -in @("All", "Firmware")) {
    Push-Location (Join-Path $root "firmware")
    try {
        Remove-Item build-A, build-B -Recurse -Force -ErrorAction SilentlyContinue
        Invoke-Checked { cmake -S zmk/app -B build-A -GNinja "-DBOARD=hw75_dynamic@A" "-DZMK_CONFIG=$config" "-DKEYMAP_FILE=$keymap" "-DZEPHYR_MODULES=$modules" }
        Invoke-Checked { cmake --build build-A }
        Invoke-Checked { cmake -S zmk/app -B build-B -GNinja "-DBOARD=hw75_dynamic@B" "-DZMK_CONFIG=$config" "-DKEYMAP_FILE=$keymap" "-DZEPHYR_MODULES=$modules" }
        Invoke-Checked { cmake --build build-B }
    }
    finally {
        Pop-Location
    }
}

if ($Target -in @("All", "Host")) {
    Push-Location (Join-Path $root "host")
    try {
        Invoke-Checked { dotnet publish temperature_helper\HW75TemperatureService.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:DebugType=None -p:DebugSymbols=false -o temperature_helper\publish }
        Invoke-Checked { python -m pip install -r requirements.txt }
        $spec = Get-ChildItem -File -Filter "*.spec" | Where-Object Name -Like "*FOCUS*" | Select-Object -First 1
        if (-not $spec) { throw "Host spec file not found" }
        Invoke-Checked { pyinstaller --clean --noconfirm $spec.FullName }
    }
    finally {
        Pop-Location
    }
}

& (Join-Path $root "package.ps1") -Target $Target
