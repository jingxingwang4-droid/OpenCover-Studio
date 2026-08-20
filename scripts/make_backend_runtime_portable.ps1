param(
    [Parameter(Mandatory = $true)][string]$BackendRoot,
    [switch]$RvcEditablePackages
)

$ErrorActionPreference = 'Stop'
$backend = (Resolve-Path -LiteralPath $BackendRoot).Path
$runtime = Join-Path $backend 'runtime'
$config = Join-Path $runtime 'pyvenv.cfg'
if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
    throw "找不到运行时配置：$config"
}

$homeLine = Get-Content -LiteralPath $config -Encoding UTF8 | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1
if (-not $homeLine) {
    throw "pyvenv.cfg 没有 home：$config"
}
$baseText = ($homeLine -split '=', 2)[1].Trim()
$base = (Resolve-Path -LiteralPath $baseText).Path
if (-not (Test-Path -LiteralPath (Join-Path $base 'python.exe') -PathType Leaf)) {
    throw "基础 Python 不完整：$base"
}

& robocopy.exe $base $runtime /E /COPY:DAT /DCOPY:T /R:2 /W:2 /NFL /NDL /NJH /NJS /NP /XD __pycache__ /XF *.pyc *.pyo
if ($LASTEXITCODE -ge 8) {
    throw "复制便携 Python 失败（robocopy $LASTEXITCODE）：$base"
}
Remove-Item -LiteralPath $config -Force

if ($RvcEditablePackages) {
    $sitePackages = Join-Path $runtime 'Lib\site-packages'
    foreach ($packageName in @('fairseq', 'fairseq_cli')) {
        $source = Join-Path $backend "fairseq\$packageName"
        $destination = Join-Path $sitePackages $packageName
        if (-not (Test-Path -LiteralPath $source -PathType Container)) {
            throw "RVC editable 包源码缺失：$source"
        }
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        & robocopy.exe $source $destination /E /COPY:DAT /DCOPY:T /R:2 /W:2 /NFL /NDL /NJH /NJS /NP /XD __pycache__ /XF *.pyc *.pyo
        if ($LASTEXITCODE -ge 8) {
            throw "复制 RVC editable 包失败（robocopy $LASTEXITCODE）：$packageName"
        }
    }
    Get-ChildItem -LiteralPath $sitePackages -File | Where-Object {
        $_.Name -like '__editable__.fairseq-*.pth' -or $_.Name -like '__editable___fairseq_*_finder.py'
    } | Remove-Item -Force
}

# pip records local installation sources for diagnostics. They are not used at
# runtime and would leak the development checkout path into the portable copy.
Get-ChildItem -LiteralPath (Join-Path $runtime 'Lib\site-packages') -Recurse -Filter 'direct_url.json' -File -ErrorAction SilentlyContinue | ForEach-Object {
    $metadata = Get-Content -Raw -LiteralPath $_.FullName -ErrorAction SilentlyContinue
    if ($metadata -match '"url"\s*:\s*"file:') {
        Remove-Item -LiteralPath $_.FullName -Force
    }
}

$python = Join-Path $runtime 'python.exe'
$probe = 'import json,sys; print(json.dumps(dict(prefix=sys.prefix,base_prefix=sys.base_prefix,executable=sys.executable)))'
$result = & $python -I -X utf8 -c $probe
if ($LASTEXITCODE -ne 0) {
    throw "便携 Python 启动失败：$python"
}
$info = $result | ConvertFrom-Json
if ([IO.Path]::GetFullPath([string]$info.prefix).TrimEnd('\') -ne [IO.Path]::GetFullPath($runtime).TrimEnd('\')) {
    throw "便携 Python 仍使用外部 prefix：$($info.prefix)"
}
Write-Host "Portable runtime ready: $runtime ($($info.executable))"
