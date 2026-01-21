$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ScriptDir '..')
$Python = $env:PYTHON
if ([string]::IsNullOrWhiteSpace($Python)) {
    if (Get-Command python3.10 -ErrorAction SilentlyContinue) {
        $Python = 'python3.10'
    } elseif (Get-Command python3.11 -ErrorAction SilentlyContinue) {
        $Python = 'python3.11'
    } else {
        Write-Error 'Python 3.10 or 3.11 is required. Install one and re-run the installer, or set PYTHON to a valid interpreter.'
        exit 2
    }
} else {
    if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
        Write-Error "PYTHON='$Python' not found on PATH. Install Python 3.10 or 3.11, or set PYTHON to a valid interpreter."
        exit 2
    }
}

$ForceRecreate = $false
if (-not ($args -contains '--skip-venv')) {
    $VenvPython = Join-Path $RootDir '.venv\Scripts\python.exe'
    if (Test-Path $VenvPython) {
        try {
            $VenvVersion = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            if ($VenvVersion -ne '3.10' -and $VenvVersion -ne '3.11') {
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
