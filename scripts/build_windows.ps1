param([ValidateSet('Modern','Legacy')][string]$Profile = 'Modern')
$ErrorActionPreference = 'Stop'
$name = "OpenCoverStudio-NVIDIA-$Profile"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name $name --icon "assets/图标.ico" --paths src --add-data "assets;assets" --add-data "config;config" --add-data "src/opencover/workers/vevo2_runtime.py;workers" --add-data "src/opencover/workers/diffsinger_legacy_runtime.py;workers" --add-data "src/opencover/workers/espnet_visinger2_runtime.py;workers" --add-data "src/opencover/workers/alignment_runtime.py;workers" --add-data "src/opencover/workers/score_refinement_runtime.py;workers" --add-data "src/opencover/workers/rvc_batch_runtime.py;workers" app.py
$release = Join-Path 'dist' $name
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --console --onefile --name OpenCoverStudioWorker --paths src --add-data "src/opencover/workers/vevo2_runtime.py;workers" --add-data "src/opencover/workers/diffsinger_legacy_runtime.py;workers" --add-data "src/opencover/workers/espnet_visinger2_runtime.py;workers" --add-data "src/opencover/workers/alignment_runtime.py;workers" --add-data "src/opencover/workers/score_refinement_runtime.py;workers" --add-data "src/opencover/workers/rvc_batch_runtime.py;workers" worker_entry.py
Copy-Item -LiteralPath 'dist\OpenCoverStudioWorker.exe' -Destination $release -Force
# Local test songs and the derived Jingque preview source are valid local QA
# inputs, but their redistribution rights are not established.
$localOnlyAssets = @(
    (Join-Path $release '_internal\assets\audio'),
    (Join-Path $release '_internal\assets\test_source'),
    (Join-Path $release '_internal\assets\preview_sources\jingque_first_line.wav')
)
foreach ($localOnlyAsset in $localOnlyAssets) {
    if (Test-Path -LiteralPath $localOnlyAsset) {
        Remove-Item -LiteralPath $localOnlyAsset -Recurse -Force
    }
}
Copy-Item -LiteralPath 'README.md','LICENSE','THIRD_PARTY_NOTICES.md','RESOURCE_SOURCES.md' -Destination $release
Copy-Item -LiteralPath 'config' -Destination $release -Recurse -Force
$releaseAssets = Join-Path $release 'assets'
New-Item -ItemType Directory -Path $releaseAssets -Force | Out-Null
Get-ChildItem -LiteralPath 'assets' -Force | Where-Object { $_.Name -notin @('audio', 'test_source') } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $releaseAssets -Recurse -Force
}
$releaseJingquePreview = Join-Path $releaseAssets 'preview_sources\jingque_first_line.wav'
if (Test-Path -LiteralPath $releaseJingquePreview) {
    Remove-Item -LiteralPath $releaseJingquePreview -Force
}
if (Test-Path -LiteralPath 'ffmpeg') { Copy-Item -LiteralPath 'ffmpeg' -Destination (Join-Path $release 'ffmpeg') -Recurse }
New-Item -ItemType Directory -Path (Join-Path $release 'external_backends') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\rvc\bundled') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\rvc\user_models') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\ddsp\bundled') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $release 'weights\ddsp\user_models') -Force | Out-Null

# 白菜和祥子均是仅限本机使用的音色，公开构建不复制任何权重。
Write-Host "Built dist/$name/$name.exe and hidden-launch worker protocol executable."
