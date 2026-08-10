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
    [string[]]$Targets = @(
        'esp32',
        'esp32c2',
        'esp32c3',
        'esp32c5',
        'esp32c6',
        'esp32c61',
        'esp32s3'
    ),
    [string]$IdfPath = $env:IDF_PATH,
    [string]$BuildRoot,
    [ValidateRange(0, 64)]
    [int]$Jobs = 0,
    [string]$Version = '0.3.4',
    [switch]$KeepGoing
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $BuildRoot) {
    $BuildRoot = $ProjectRoot
}
$BuildRoot = [System.IO.Path]::GetFullPath($BuildRoot)
New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null

function Resolve-IdfPath {
    param([string]$RequestedPath)

    $Candidates = @(
        $RequestedPath,
        'C:\Users\bobby\Documents\Codex\2026-07-29\new-chat-2\work\sdk\esp-idf-6.0.2',
        (Join-Path $ProjectRoot '..\..\work\sdk\esp-idf-6.0.2')
    ) | Where-Object { $_ }

    foreach ($Candidate in $Candidates) {
        $ExportBat = Join-Path $Candidate 'export.bat'
        if (Test-Path -LiteralPath $ExportBat) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }

    throw 'ESP-IDF v6.0.2 was not found. Set IDF_PATH or pass -IdfPath.'
}

function ConvertTo-CmdArgument {
    param([Parameter(Mandatory)][string]$Value)

    if ($Value.Contains('"')) {
        throw "Unsupported quote in command argument: $Value"
    }
    return '"' + $Value + '"'
}

function Invoke-IdfCommand {
    param(
        [Parameter(Mandatory)][string]$ExportBat,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $ArgumentLine = ($Arguments | ForEach-Object { ConvertTo-CmdArgument $_ }) -join ' '
    $Command = "call $(ConvertTo-CmdArgument $ExportBat) && idf.py $ArgumentLine"
    & cmd.exe /d /s /c $Command
    if ($LASTEXITCODE -ne 0) {
        throw "idf.py failed with exit code $LASTEXITCODE"
    }
}

function Invoke-NinjaBuild {
    param(
        [Parameter(Mandatory)][string]$ExportBat,
        [Parameter(Mandatory)][string]$BuildDir,
        [Parameter(Mandatory)][int]$Jobs
    )

    $Command = "call $(ConvertTo-CmdArgument $ExportBat) && ninja.exe -C $(ConvertTo-CmdArgument $BuildDir) -j $Jobs all"
    & cmd.exe /d /s /c $Command
    if ($LASTEXITCODE -ne 0) {
        throw "ninja failed with exit code $LASTEXITCODE"
    }
}

function Invoke-EspToolMerge {
    param(
        [Parameter(Mandatory)][string]$ExportBat,
        [Parameter(Mandatory)][string]$Chip,
        [Parameter(Mandatory)][string]$BuildDir,
        [Parameter(Mandatory)][pscustomobject]$FlasherArgs,
        [Parameter(Mandatory)][string]$OutputPath
    )

    $Arguments = @(
        '-m',
        'esptool',
        '--chip',
        $Chip,
        'merge-bin',
        '-o',
        $OutputPath,
        '--flash-mode',
        [string]$FlasherArgs.flash_settings.flash_mode,
        '--flash-size',
        '4MB',
        '--flash-freq',
        [string]$FlasherArgs.flash_settings.flash_freq
    )

    foreach ($FlashFile in $FlasherArgs.flash_files.PSObject.Properties) {
        $Arguments += [string]$FlashFile.Name
        $Arguments += Join-Path $BuildDir ([string]$FlashFile.Value)
    }

    $ArgumentLine = ($Arguments | ForEach-Object { ConvertTo-CmdArgument $_ }) -join ' '
    $Command = "call $(ConvertTo-CmdArgument $ExportBat) && python $ArgumentLine"
    & cmd.exe /d /s /c $Command
    if ($LASTEXITCODE -ne 0) {
        throw "esptool merge-bin failed with exit code $LASTEXITCODE"
    }
}

$IdfPath = Resolve-IdfPath $IdfPath
$ExportBat = Join-Path $IdfPath 'export.bat'
$Results = [System.Collections.Generic.List[object]]::new()
$DependencyLockPath = Join-Path $ProjectRoot 'dependencies.lock'
$DependencyLockExisted = Test-Path -LiteralPath $DependencyLockPath
$OriginalDependencyLock = if ($DependencyLockExisted) {
    [System.IO.File]::ReadAllText($DependencyLockPath)
} else {
    $null
}

Push-Location $ProjectRoot
try {
    foreach ($Target in $Targets) {
        Write-Host "Building $Target" -ForegroundColor Cyan
        $BuildDir = Join-Path $BuildRoot "build-$Target"
        $SdkconfigPath = Join-Path $ProjectRoot "sdkconfig.$Target"
        $FirmwareDir = Join-Path $ProjectRoot "docs\firmware\$Target"
        $OutputPath = Join-Path $FirmwareDir "ios-ancs-$Target-v$Version.factory.bin"

        try {
            if (Test-Path -LiteralPath $SdkconfigPath) {
                Remove-Item -LiteralPath $SdkconfigPath
            }
            $ConfigureArguments = @(
                "-B$BuildDir",
                "-DIDF_TARGET=$Target",
                "-DSDKCONFIG=$SdkconfigPath"
            )
            if ($Jobs -gt 0) {
                Invoke-IdfCommand `
                    -ExportBat $ExportBat `
                    -Arguments ($ConfigureArguments + 'reconfigure')
                Invoke-NinjaBuild `
                    -ExportBat $ExportBat `
                    -BuildDir $BuildDir `
                    -Jobs $Jobs
            }
            else {
                Invoke-IdfCommand `
                    -ExportBat $ExportBat `
                    -Arguments ($ConfigureArguments + 'build')
            }

            $FlasherArgsPath = Join-Path $BuildDir 'flasher_args.json'
            if (-not (Test-Path -LiteralPath $FlasherArgsPath)) {
                throw "Missing flasher_args.json: $FlasherArgsPath"
            }

            $FlasherArgs = Get-Content -Raw -LiteralPath $FlasherArgsPath | ConvertFrom-Json
            $Chip = [string]$FlasherArgs.extra_esptool_args.chip
            if (-not $Chip) {
                throw "Missing esptool chip identity in $FlasherArgsPath"
            }

            New-Item -ItemType Directory -Force -Path $FirmwareDir | Out-Null
            Invoke-EspToolMerge `
                -ExportBat $ExportBat `
                -Chip $Chip `
                -BuildDir $BuildDir `
                -FlasherArgs $FlasherArgs `
                -OutputPath $OutputPath

            $Firmware = Get-Item -LiteralPath $OutputPath
            $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath).Hash.ToLowerInvariant()
            $Results.Add([pscustomobject]@{
                target = $Target
                chip_family = $Chip
                success = $true
                path = $OutputPath.Substring($ProjectRoot.Length + 1).Replace('\', '/')
                size = $Firmware.Length
                sha256 = $Hash
                error = $null
            })
            Write-Host "Built $Target ($($Firmware.Length) bytes, SHA256 $Hash)" -ForegroundColor Green
        }
        catch {
            $Results.Add([pscustomobject]@{
                target = $Target
                chip_family = $null
                success = $false
                path = $null
                size = 0
                sha256 = $null
                error = $_.Exception.Message
            })
            Write-Warning "Build failed for ${Target}: $($_.Exception.Message)"
            if (-not $KeepGoing) {
                throw
            }
        }
    }
}
finally {
    Pop-Location
    if ($DependencyLockExisted) {
        [System.IO.File]::WriteAllText(
            $DependencyLockPath,
            $OriginalDependencyLock,
            [System.Text.UTF8Encoding]::new($false)
        )
    }
    elseif (Test-Path -LiteralPath $DependencyLockPath) {
        Remove-Item -LiteralPath $DependencyLockPath
    }
}

$ArtifactsDir = Join-Path $ProjectRoot 'artifacts'
New-Item -ItemType Directory -Force -Path $ArtifactsDir | Out-Null
$ReportPath = Join-Path $ArtifactsDir 'build-matrix.json'
$Results | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 -LiteralPath $ReportPath

$Failed = @($Results | Where-Object { -not $_.success })
Write-Host "Build matrix report: $ReportPath"
if ($Failed.Count -gt 0) {
    Write-Warning "$($Failed.Count) target build(s) failed."
    exit 1
}
