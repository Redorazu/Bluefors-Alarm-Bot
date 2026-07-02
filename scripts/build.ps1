$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (Test-Path ".venv\Scripts\pip.exe") {
    .\.venv\Scripts\pip.exe install -e ".[dev]"
} else {
    pip install -e ".[dev]"
}

pyinstaller --noconfirm --onedir --name alarm-bot main.py

$dist = "dist\alarm-bot"
Copy-Item config.yaml "$dist\config.yaml" -ErrorAction SilentlyContinue
Copy-Item .env "$dist\.env" -ErrorAction SilentlyContinue
Copy-Item scripts\setup.bat "$dist\setup.bat"
Copy-Item scripts\run.bat "$dist\run.bat"
Copy-Item README.md "$dist\README.txt" -ErrorAction SilentlyContinue

Write-Host "Build complete: $dist"
