param([ValidateSet('Modern')][string]$Profile = 'Modern')
$ErrorActionPreference = 'Stop'

$name = "OpenCoverStudio-NVIDIA-$Profile"
$base = Join-Path 'dist' $name
$target = Join-Path 'release_private' "$name-LocalFull"
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
foreach ($backend in @('msst', 'rvc', 'ddsp', 'vevo2', 'game', 'diffsinger')) {
    Copy-Tree (Join-Path 'external_backends' $backend) (Join-Path $target "external_backends\$backend")
}
Copy-Tree 'weights\rvc' (Join-Path $target 'weights\rvc')
Copy-Tree 'weights\ddsp' (Join-Path $target 'weights\ddsp')
Copy-Item -LiteralPath 'docs\LOCAL_ONLY_FULL_PACKAGE.txt' -Destination $target

$exe = Join-Path $target "$name.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "组装后缺少 EXE：$exe" }
$bytes = (Get-ChildItem -LiteralPath $target -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host "Built local-only full package: $target ($([math]::Round($bytes / 1GB, 2)) GiB)"
