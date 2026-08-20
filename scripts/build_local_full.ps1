param([ValidateSet('Modern')][string]$Profile = 'Modern')
$ErrorActionPreference = 'Stop'

$name = "OpenCoverStudio-NVIDIA-$Profile"
$base = Join-Path 'dist' $name
$target = Join-Path 'release_private' 'OCS-Private-Modern'
if (Test-Path -LiteralPath $target) {
    throw "目标已存在，不会覆盖：$target"
}

& "$PSScriptRoot\build_windows.ps1" -Profile $Profile
New-Item -ItemType Directory -Path $target -Force | Out-Null

function Copy-Tree([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source)) { throw "缺少目录：$Source" }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    & robocopy.exe $Source $Destination /E /COPY:DAT /DCOPY:T /R:2 /W:2 /NFL /NDL /NJH /NJS /NP /XD .git __pycache__ .pytest_cache .cache /XF *.pyc *.pyo
    if ($LASTEXITCODE -ge 8) { throw "复制失败（robocopy $LASTEXITCODE）：$Source" }
}

Copy-Tree $base $target
foreach ($backend in @('msst', 'uvr5', 'rvc', 'ddsp', 'vevo2', 'game', 'diffsinger', 'alignment', 'espnet_visinger2')) {
    Copy-Tree (Join-Path 'external_backends' $backend) (Join-Path $target "external_backends\$backend")
}
Copy-Tree 'weights\rvc' (Join-Path $target 'weights\rvc')
Copy-Tree 'weights\ddsp' (Join-Path $target 'weights\ddsp')
Copy-Item -LiteralPath 'docs\LOCAL_ONLY_FULL_PACKAGE.txt' -Destination $target

foreach ($backend in @('msst', 'uvr5', 'rvc', 'ddsp', 'vevo2', 'game', 'alignment', 'espnet_visinger2')) {
    $portableScript = Join-Path $PSScriptRoot 'make_backend_runtime_portable.ps1'
    $backendTarget = Join-Path $target "external_backends\$backend"
    if ($backend -eq 'rvc') {
        & $portableScript -BackendRoot $backendTarget -RvcEditablePackages
    } else {
        & $portableScript -BackendRoot $backendTarget
    }
}
Get-ChildItem -LiteralPath (Join-Path $target 'external_backends') -Recurse -Filter 'pyvenv.cfg' -File -ErrorAction SilentlyContinue | Remove-Item -Force

$portableNotice = @'
OpenCover Studio 私人跨电脑包
============================

仅供包的所有者在自己的 Windows 电脑之间复制使用，不得公开上传、出售或转发。
建议解压到短路径，例如 C:\OCS；不要直接在压缩包内运行。
目标电脑需要 64 位 Windows 10/11、NVIDIA 显卡和足够新的 NVIDIA 驱动；无需安装 Python、Conda 或 CUDA Toolkit。
改词翻唱仍是实验功能，当前丰川祥子 RVC 对普通话吐字和部分音符落字存在已知听感问题。
'@
Set-Content -LiteralPath (Join-Path $target '请先阅读-私人包.txt') -Value $portableNotice -Encoding UTF8

$exe = Join-Path $target "$name.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "组装后缺少 EXE：$exe" }
$bytes = (Get-ChildItem -LiteralPath $target -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host "Built local-only full package: $target ($([math]::Round($bytes / 1GB, 2)) GiB)"
