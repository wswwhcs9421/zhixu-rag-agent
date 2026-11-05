$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$ragPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $ragPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
}
& $ragPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
Write-Host 'Open http://127.0.0.1:8000 . Initial credentials: data/bootstrap-admin.txt'
& $ragPython run.py
