[CmdletBinding()]
param(
    [string]$Proxy = "http://127.0.0.1:7897",
    [ValidateRange(1, 32)][int]$ChunkMiB = 8,
    [ValidateRange(1, 8)][int]$Parallel = 4,
    [ValidateRange(1, 20)][int]$Retries = 8,
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePython = Join-Path $projectRoot "external_backends\ddsp\runtime\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "restore_ddsp_resources.py"
if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
    throw "DDSP isolated runtime is missing: $runtimePython"
}

$arguments = @(
    $script,
    "--proxy", $Proxy,
    "--chunk-mib", "$ChunkMiB",
    "--workers", "$Parallel",
    "--retries", "$Retries"
)
if ($Install) {
    $arguments += "--install"
}

& $runtimePython @arguments
if ($LASTEXITCODE -ne 0) {
    throw "DDSP resource restore failed with exit code $LASTEXITCODE"
}
