[CmdletBinding()]
param(
    [string]$IdfPath = $env:IDF_PATH
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

if (-not $IdfPath) {
    $BundledIdf = Join-Path $ProjectRoot '..\..\work\sdk\esp-idf-6.0.2'
    if (Test-Path -LiteralPath $BundledIdf) {
        $IdfPath = (Resolve-Path -LiteralPath $BundledIdf).Path
    }
}

if (-not $IdfPath) {
    throw 'ESP-IDF v6.0.2 경로를 IDF_PATH 또는 -IdfPath로 지정하십시오.'
}

$ExportBat = Join-Path $IdfPath 'export.bat'
if (-not (Test-Path -LiteralPath $ExportBat)) {
    throw "ESP-IDF export.bat를 찾을 수 없습니다: $ExportBat"
}

$Command = @(
    "call `"$ExportBat`""
    'idf.py --version'
    'idf.py set-target esp32c6'
    'idf.py fullclean'
    'idf.py build'
) -join ' && '

Push-Location $ProjectRoot
try {
    & cmd.exe /d /s /c $Command
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
