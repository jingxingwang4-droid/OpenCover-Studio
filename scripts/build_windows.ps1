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
Copy-Item -LiteralPath 'THIRD_PARTY_LICENSES' -Destination $release -Recurse -Force
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

# Only copy the fixed allow-list whose model and training-data rights were
# independently recorded. Local-only character models must never enter a
# redistributable package through a broad weights/ copy.
$publicRvcVoices = @('saisho_utane_rvc', 'vctk_p231_rvc', 'vctk_p226_rvc')
foreach ($voiceId in $publicRvcVoices) {
    $source = Join-Path 'weights\rvc\bundled' $voiceId
    $metadataPath = Join-Path $source 'model.json'
    if (-not (Test-Path -LiteralPath $metadataPath)) {
        throw "缺少可再分发内置音色 $voiceId；请先运行 scripts/install_bundled_rvc_voices.py --generate-previews"
    }
    $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($metadata.id -ne $voiceId -or -not $metadata.bundled -or -not $metadata.redistribution_allowed -or $metadata.preview_source -ne 'generated') {
        throw "内置音色元数据未通过发行检查：$voiceId"
    }
    $required = @('model.pth', 'model.json', 'avatar.webp', 'preview.wav')
    foreach ($fileName in $required) {
        $path = Join-Path $source $fileName
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "内置音色缺少 $fileName：$voiceId" }
        if ($fileName -ne 'model.json') {
            $expected = $metadata.sha256.$fileName
            $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
            if (-not $expected -or $actual -ne $expected) { throw "内置音色文件哈希不匹配：$voiceId/$fileName" }
        }
    }
    $target = Join-Path $release "weights\rvc\bundled\$voiceId"
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    foreach ($fileName in $required) { Copy-Item -LiteralPath (Join-Path $source $fileName) -Destination $target -Force }
}
Write-Host "Built dist/$name/$name.exe and hidden-launch worker protocol executable."
