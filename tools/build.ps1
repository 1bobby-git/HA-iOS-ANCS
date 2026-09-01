[CmdletBinding()]
param(
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
    [string]$IdfPath = $env:IDF_PATH,
    [string]$Version = '0.3.5'
)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'build_matrix.ps1') `
    -Targets $Target `
    -IdfPath $IdfPath `
    -Version $Version
exit $LASTEXITCODE
