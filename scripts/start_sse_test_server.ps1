# start_sse_test_server.ps1
# Launch the MCP-over-SSE test server (scripts/sse_http_server.py) on port 8765.
# Output is shown in this window AND appended to logs\sse_server_8765.log.
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptFile = Join-Path $PSScriptRoot "sse_http_server.py"
$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "sse_server_8765.log"

Write-Host "[launcher] repo root : $repoRoot"
Write-Host "[launcher] script    : $scriptFile"
Write-Host "[launcher] log file  : $logFile"
Write-Host ""

python "$scriptFile" --port 8765 *>&1 | Tee-Object -FilePath $logFile
