param([string]$Proxy = 'http://127.0.0.1:7897')
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'external_backends\alignment'
$stable = Join-Path $backend 'stable-ts'
$whisper = Join-Path $backend 'whisper'
$runtime = Join-Path $backend 'runtime'
$models = Join-Path $backend 'models'
$stableCommit = 'e312072cc024ae9fceb25b057d7d18524873a02b'
$whisperCommit = '5f86d1d86363843179951550570367b37c5d6f78'
$modelHash = 'ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e'
$modelUrl = "https://openaipublic.azureedge.net/main/whisper/models/$modelHash/base.pt"

if (Test-Path -LiteralPath $backend) {
    throw "Target already exists; refusing to overwrite: $backend"
}
New-Item -ItemType Directory -Path $backend,$models -Force | Out-Null

function Checkout-Commit([string]$Repository, [string]$Target, [string]$Commit) {
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    git -C $Target init
    git -C $Target remote add origin $Repository
    git -c "http.proxy=$Proxy" -C $Target fetch --depth 1 origin $Commit
    git -C $Target checkout --detach FETCH_HEAD
    $actual = git -c "safe.directory=$($Target.Replace('\','/'))" -C $Target rev-parse HEAD
    if ($actual.Trim() -ne $Commit) { throw "Source commit mismatch: expected $Commit, got $actual" }
}

Checkout-Commit 'https://github.com/jianfch/stable-ts.git' $stable $stableCommit
Checkout-Commit 'https://github.com/openai/whisper.git' $whisper $whisperCommit

$env:HTTP_PROXY = $Proxy
$env:HTTPS_PROXY = $Proxy
uv venv --python 3.10 $runtime
$python = Join-Path $runtime 'Scripts\python.exe'
uv pip install --python $python --index https://download.pytorch.org/whl/cu130 'torch==2.9.1+cu130' 'torchaudio==2.9.1+cu130'
uv pip install --python $python more-itertools numba numpy tiktoken tqdm
uv pip install --python $python --no-deps $whisper $stable

$model = Join-Path $models 'base.pt'
curl.exe -L --proxy $Proxy --retry 3 --continue-at - -o $model $modelUrl
if ((Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash.ToLowerInvariant() -ne $modelHash) {
    throw 'Whisper base model SHA256 verification failed'
}
$env:PYTHONPATH = Join-Path $root 'src'
& $python (Join-Path $root 'scripts\smoke_alignment.py') $root --mark-verified
Write-Host 'Lyric alignment component installed and verified with a real CUDA forced-alignment smoke test.'
