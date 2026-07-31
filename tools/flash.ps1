[CmdletBinding()]
param(
    [string]$Port,
    [ValidateSet(
        'esp32',
        'esp32c2',
        'esp32c3',
        'esp32c5',
        'esp32c6',
        'esp32c61',
        'esp32s3'
    )]
    [string]$Target = 'esp32c6',
    [string]$IdfPath = $env:IDF_PATH
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

if (-not $IdfPath) {
    $IdfCandidates = @(
        'C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2',
        (Join-Path $ProjectRoot '..\..\work\sdk\esp-idf-6.0.2')
    )
    foreach ($Candidate in $IdfCandidates) {
        if (Test-Path -LiteralPath (Join-Path $Candidate 'export.bat')) {
            $IdfPath = (Resolve-Path -LiteralPath $Candidate).Path
            break
        }
    }
}

if (-not $IdfPath) {
    throw 'ESP-IDF v6.0.2 경로를 IDF_PATH 또는 -IdfPath로 지정하십시오.'
}

$ExportBat = Join-Path $IdfPath 'export.bat'
if (-not (Test-Path -LiteralPath $ExportBat)) {
    throw "ESP-IDF export.bat를 찾을 수 없습니다: $ExportBat"
}

if (-not $Port) {
    $Port = (& python (Join-Path $PSScriptRoot 'detect_port.py')).Trim()
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$BuildDir = "build-$Target"
$Command = @(
    "call `"$ExportBat`""
    'idf.py --version'
    "idf.py -B `"$BuildDir`" -p `"$Port`" flash"
) -join ' && '

Push-Location $ProjectRoot
try {
    & cmd.exe /d /s /c $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

Write-Host ''
Write-Host '플래시 완료. iPhone 페어링 후 다음 명령으로 캡처를 검증하십시오:'
Write-Host "python tools/verify_capture.py --target $Target --port $Port --baud 115200 --timeout 180 --output artifacts/ancs-capture.jsonl"
