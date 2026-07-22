#requires -Version 5.1

[CmdletBinding()]
param(
    [string]$Version = "0.1.4",
    [string]$PackageSource = "",
    [switch]$Initialize,
    [switch]$SkipPythonInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "This installer supports native Windows only."
}

function Find-WikiBrainPython {
    $candidates = @(
        [pscustomobject]@{ Executable = "py.exe"; Prefix = @("-3") },
        [pscustomobject]@{ Executable = "python.exe"; Prefix = @() },
        [pscustomobject]@{
            Executable = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
            Prefix = @()
        }
    )

    foreach ($candidate in $candidates) {
        $available = Get-Command $candidate.Executable -ErrorAction SilentlyContinue
        if ($null -eq $available -and -not (Test-Path -LiteralPath $candidate.Executable)) {
            continue
        }
        try {
            $prefix = @($candidate.Prefix)
            $version = & $candidate.Executable @prefix -c `
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            if ($LASTEXITCODE -ne 0) {
                continue
            }
            $parts = ([string]$version).Trim().Split(".")
            if (
                [int]$parts[0] -gt 3 -or
                ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11)
            ) {
                return $candidate
            }
        } catch {
            continue
        }
    }
    return $null
}

function Invoke-WikiBrainPython {
    param([string[]]$PythonArguments)

    $prefix = @($script:Python.Prefix)
    & $script:Python.Executable @prefix @PythonArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

$script:Python = Find-WikiBrainPython
if ($null -eq $script:Python -and -not $SkipPythonInstall) {
    $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw (
            "Python 3.11 or newer is required. Install it from " +
            "https://www.python.org/downloads/windows/ and rerun this installer."
        )
    }

    Write-Host "Python 3.13 was not found. Installing it with winget..."
    & $winget.Source install --id Python.Python.3.13 --exact --scope user `
        --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install Python 3.13."
    }
    $script:Python = Find-WikiBrainPython
}

if ($null -eq $script:Python) {
    throw "Python 3.11 or newer was not found."
}

Write-Host "Installing pipx..."
Invoke-WikiBrainPython @("-m", "pip", "install", "--user", "--upgrade", "pipx")
Invoke-WikiBrainPython @("-m", "pipx", "ensurepath")

if ([string]::IsNullOrWhiteSpace($PackageSource)) {
    $PackageSource = (
        "https://github.com/hungrytech/wikibrain/archive/refs/tags/" +
        "v$Version.zip"
    )
} elseif (Test-Path -LiteralPath $PackageSource) {
    $PackageSource = (Resolve-Path -LiteralPath $PackageSource).Path
}

Write-Host "Installing WikiBrain $Version in an isolated pipx environment..."
Invoke-WikiBrainPython @(
    "-m", "pipx", "install", "--force", $PackageSource
)

$prefix = @($script:Python.Prefix)
$pipxBin = (
    & $script:Python.Executable @prefix -m pipx environment --value PIPX_BIN_DIR
).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($pipxBin)) {
    throw "Could not locate the pipx executable directory."
}
$env:PATH = "$pipxBin;$env:PATH"

$brainctl = Join-Path $pipxBin "brainctl.exe"
if (-not (Test-Path -LiteralPath $brainctl)) {
    $brainctl = Join-Path $pipxBin "brainctl"
}
if (-not (Test-Path -LiteralPath $brainctl)) {
    throw "WikiBrain installed, but brainctl was not found in $pipxBin."
}

$installedVersion = & $brainctl --version
if ($LASTEXITCODE -ne 0) {
    throw "brainctl was installed but could not start."
}
Write-Host ""
Write-Host "Installed $installedVersion"
Write-Host "Executable: $brainctl"

if ($Initialize) {
    Write-Host ""
    Write-Host "Initializing the private brain and agent hooks..."
    & $brainctl init
    if ($LASTEXITCODE -ne 0) {
        throw "brainctl init failed."
    }
    & $brainctl doctor
    if ($LASTEXITCODE -ne 0) {
        throw "brainctl doctor reported a problem."
    }
    Write-Host ""
    Write-Host "Codex: start a new session, open /hooks, and trust the reviewed definitions."
} else {
    Write-Host ""
    Write-Host "Installation is complete. Initialization changes agent settings explicitly."
    Write-Host "Run these commands when you are ready:"
    Write-Host "  & '$brainctl' init"
    Write-Host "  & '$brainctl' doctor"
}
