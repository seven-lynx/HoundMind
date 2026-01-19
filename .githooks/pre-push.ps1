Write-Host "Running local CI: lint + tests"

$python = 'python'

try {
    & $python -m ruff check src
} catch {
    Write-Error "Lint failed (ruff). Aborting push."
    exit 1
}

$env:PYTHONPATH = 'src'
try {
    & $python -m pytest -q
} catch {
    Write-Error "Tests failed. Aborting push."
    exit 1
}

Write-Host "Local CI passed. Proceeding with push."
exit 0
