$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ScriptDir '..')
$Python = $env:PYTHON
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = 'python'
}

& $Python (Join-Path $RootDir 'scripts\pidog_install.py') --auto-system-deps @args
