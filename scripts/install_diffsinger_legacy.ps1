param([string]$Proxy = 'http://127.0.0.1:7897')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'external_backends\diffsinger'
$demo = Join-Path $backend 'legacy_demo'
$runtime = Join-Path $backend 'legacy_runtime'
$rvcPython = Join-Path $root 'external_backends\rvc\runtime\Scripts\python.exe'
$commit = '6a08cddc365c614a1f50efd5fea1333ac58b5359'

if (-not (Test-Path -LiteralPath $rvcPython -PathType Leaf)) {
    throw '请先安装并验证 RVC GPU runtime；DiffSinger legacy 复用其 PyTorch/CUDA。'
}
if (Test-Path -LiteralPath $demo) {
    throw "目标已存在，不会覆盖：$demo"
}
New-Item -ItemType Directory -Path $backend -Force | Out-Null
git -c "http.proxy=$Proxy" clone --depth 1 https://huggingface.co/spaces/Silentlin/DiffSinger $demo
$actual = git -c "safe.directory=$($demo.Replace('\','/'))" -C $demo rev-parse HEAD
if ($actual.Trim() -ne $commit) {
    throw "上游提交已变化：期望 $commit，实际 $actual"
}
& $rvcPython -m venv $runtime
$env:HTTPS_PROXY = $Proxy
$env:HTTP_PROXY = $Proxy
$python = Join-Path $runtime 'Scripts\python.exe'
& $python -m pip install --disable-pip-version-check `
    'pypinyin==0.43.0' 'h5py>=3.10,<4' 'matplotlib>=3.8,<4' 'pandas>=2,<3' `
    'einops>=0.3,<1' 'pycwt==0.4.0b0' 'scikit-image>=0.22,<1' `
    'webrtcvad-wheels>=2.0.14,<3' 'pyloudnorm==0.1.1'
Write-Host '安装完成；请运行 scripts/smoke_diffsinger_game.py，只有真实 WAV 通过后 backend.json 才可标记可用。'
