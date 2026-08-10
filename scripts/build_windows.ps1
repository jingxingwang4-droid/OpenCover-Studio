param([ValidateSet('Modern','Legacy')][string]$Profile = 'Modern')
$ErrorActionPreference = 'Stop'
$name = "OpenCoverStudio-NVIDIA-$Profile"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name $name --paths src --add-data "assets;assets" --add-data "config;config" --add-data "src/opencover/workers/vevo2_runtime.py;workers" --add-data "src/opencover/workers/diffsinger_legacy_runtime.py;workers" --add-data "src/opencover/workers/alignment_runtime.py;workers" app.py
$release = Join-Path 'dist' $name
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --console --onefile --name OpenCoverStudioWorker --paths src --add-data "src/opencover/workers/vevo2_runtime.py;workers" --add-data "src/opencover/workers/diffsinger_legacy_runtime.py;workers" --add-data "src/opencover/workers/alignment_runtime.py;workers" worker_entry.py
Copy-Item -LiteralPath 'dist\OpenCoverStudioWorker.exe' -Destination $release -Force
# assets/audio contains user-provided local test songs. They are valid inputs
# for backend QA but must never be copied into a redistributable application.
$bundledTestAudio = Join-Path $release '_internal\assets\audio'
if (Test-Path -LiteralPath $bundledTestAudio) {
    Remove-Item -LiteralPath $bundledTestAudio -Recurse -Force
}
Copy-Item -LiteralPath 'README.md','LICENSE','THIRD_PARTY_NOTICES.md','RESOURCE_SOURCES.md' -Destination $release
Copy-Item -LiteralPath 'config' -Destination $release -Recurse -Force
$releaseAssets = Join-Path $release 'assets'
New-Item -ItemType Directory -Path $releaseAssets -Force | Out-Null
Get-ChildItem -LiteralPath 'assets' -Force | Where-Object { $_.Name -ne 'audio' } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $releaseAssets -Recurse -Force
}
if (Test-Path -LiteralPath 'ffmpeg') { Copy-Item -LiteralPath 'ffmpeg' -Destination (Join-Path $release 'ffmpeg') -Recurse }
New-Item -ItemType Directory -Path (Join-Path $release 'external_backends') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\rvc\bundled') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\rvc\user_models') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\ddsp\bundled') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\ddsp\user_models') -Force | Out-Null
Write-Host "Built dist/$name/$name.exe and hidden-launch worker protocol executable."
