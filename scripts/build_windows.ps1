param([ValidateSet('Modern','Legacy')][string]$Profile = 'Modern')
$ErrorActionPreference = 'Stop'
$name = "OpenCoverStudio-NVIDIA-$Profile"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name $name --paths src --add-data "assets;assets" --add-data "config;config" app.py
$release = Join-Path 'dist' $name
Copy-Item -LiteralPath 'README.md','LICENSE','THIRD_PARTY_NOTICES.md','RESOURCE_SOURCES.md' -Destination $release
if (Test-Path -LiteralPath 'ffmpeg') { Copy-Item -LiteralPath 'ffmpeg' -Destination (Join-Path $release 'ffmpeg') -Recurse }
New-Item -ItemType Directory -Path (Join-Path $release 'external_backends') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\rvc\bundled') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\rvc\user_models') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\ddsp\bundled') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\ddsp\user_models') -Force | Out-Null
Write-Host "Built dist/$name/$name.exe (windowed subsystem; no console window)."
