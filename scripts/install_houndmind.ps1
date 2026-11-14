$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ScriptDir '..')
$Python = $env:PYTHON
# Python 3.11-3.13 is what `pyproject.toml` declares, and what `installer_core.py` enforces.
# 3.10 is end-of-life where pip refuses the package, so the newest probe wins (#113).
function Test-SupportedPython {
    param([string]$Exe)
    try {
        $version = & $Exe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    } catch {
        return $false
    }
    return @('3.11', '3.12', '3.13') -contains ([string]$version).Trim()
}

if ([string]::IsNullOrWhiteSpace($Python)) {
    foreach ($candidate in @('python3.13', 'python3.12', 'python3.11')) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            $Python = $candidate
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($Python)) {
        Write-Error 'Python 3.11-3.13 is required. Install one and re-run the installer, or set PYTHON to a valid interpreter.'
        exit 2
    }
} else {
    if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
        Write-Error "PYTHON='$Python' not found on PATH. Install Python 3.11-3.13, or set PYTHON to a valid interpreter."
        exit 2
    }
    if (-not (Test-SupportedPython $Python)) {
        Write-Error "PYTHON='$Python' is not 3.11-3.13. HoundMind supports 3.11-3.13 (Bookworm ships 3.11)."
        exit 2
    }
}

$ForceRecreate = $false
if (-not ($args -contains '--skip-venv')) {
    $VenvPython = Join-Path $RootDir '.venv\Scripts\python.exe'
    if (Test-Path $VenvPython) {
        try {
            if (-not (Test-SupportedPython $VenvPython)) {
                $ForceRecreate = $true
            }
        } catch {
            $ForceRecreate = $true
        }
    }
}

$InstallerArgs = @('--auto-system-deps') + $args
if ($ForceRecreate -and -not ($InstallerArgs -contains '--force-recreate-venv')) {
    $InstallerArgs += '--force-recreate-venv'
}

& $Python (Join-Path $RootDir 'scripts\installer_core.py') @InstallerArgs
