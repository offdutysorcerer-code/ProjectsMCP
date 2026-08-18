param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8091,
    [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$env:UV_PYTHON = "3.13"
$env:PROJECTSMCP_CONFIG_PATH = Join-Path $projectRoot "config.dev.json"
$env:PROJECTSMCP_ARTIFACTS_DIR = Join-Path $projectRoot "artifacts\dev"
$env:PROJECTSMCP_ENVIRONMENT = "DEV"

$logDirectory = Join-Path $projectRoot "logs\dev"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $env:PROJECTSMCP_ARTIFACTS_DIR -Force | Out-Null
Get-ChildItem -Path $logDirectory -Filter "projectsmcp-dev-*.log" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$logPath = Join-Path $logDirectory "projectsmcp-dev-$timestamp.log"

function Append-LogSafe([string]$Line) {
    [System.IO.File]::AppendAllText($logPath, $Line + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}
function Write-LoggedLine([string]$Level,[string]$Message) {
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Level, $Message
    Write-Host $line
    Append-LogSafe $line
}
function Find-UvCommand {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $uv) { return @{ Executable=$uv.Source; Prefix=@(); Display=$uv.Source } }
    foreach ($candidate in @("py","python")) {
        $python = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -eq $python) { continue }
        & $python.Source -m uv --version *> $null
        if ($LASTEXITCODE -eq 0) { return @{ Executable=$python.Source; Prefix=@("-m","uv"); Display="$($python.Source) -m uv" } }
    }
    return $null
}
function Get-PortListenerInfo([int]$LocalPort) {
    $listener = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $listener) { return $null }
    $processId = [int]$listener.OwningProcess
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    return [pscustomobject]@{ Pid=$processId; Name=if($process){$process.Name}else{"unknown"}; CommandLine=if($process){[string]$process.CommandLine}else{""} }
}

Write-LoggedLine "INFO" "ProjectsMCP DEV launcher started."
Write-LoggedLine "INFO" "Config: $env:PROJECTSMCP_CONFIG_PATH"
Write-LoggedLine "INFO" "Artifacts: $env:PROJECTSMCP_ARTIFACTS_DIR"
Write-LoggedLine "INFO" "Endpoint: http://${HostAddress}:$Port/sse"

try {
    $existing = Get-PortListenerInfo $Port
    if ($existing) {
        $isProjectsMcp = $existing.CommandLine -match '(?i)mcp-proxy(?:\.exe)?' -and $existing.CommandLine -match ('(?i)--port(?:\s+|=)' + [regex]::Escape([string]$Port)) -and $existing.CommandLine -match '(?i)server\.py'
        if ($isProjectsMcp) {
            Write-LoggedLine "INFO" "ProjectsMCP DEV is already running on ${HostAddress}:$Port (PID $($existing.Pid))."
            exit 76
        }
        throw "DEV port $Port is already used by PID $($existing.Pid) ($($existing.Name))."
    }

    $uvCommand = Find-UvCommand
    if ($null -eq $uvCommand) { throw "uv is not installed or cannot be found." }
    Write-LoggedLine "INFO" "Using uv: $($uvCommand.Display)"

    $arguments = @($uvCommand.Prefix) + @(
        "tool","run","--with","mcp>=1.27,<2","mcp-proxy==0.12.0",
        "--host",$HostAddress,"--port",$Port,
        "-e","PROJECTSMCP_CONFIG_PATH",$env:PROJECTSMCP_CONFIG_PATH,
        "-e","PROJECTSMCP_ARTIFACTS_DIR",$env:PROJECTSMCP_ARTIFACTS_DIR,
        "-e","PROJECTSMCP_ENVIRONMENT",$env:PROJECTSMCP_ENVIRONMENT,
        "--",$uvCommand.Executable
    ) + @($uvCommand.Prefix) + @(
        "run","--with-requirements","requirements.txt","python","server.py"
    )

    Write-LoggedLine "INFO" "Starting MCP proxy DEV."
    $ErrorActionPreference = "Continue"
    & $uvCommand.Executable @arguments 2>&1 | ForEach-Object {
        $message=$_.ToString(); Write-Host $message; Append-LogSafe $message
    }
    $exitCode=$LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($null -eq $exitCode) { $exitCode=1 }
    if ($exitCode -eq 0) { Write-LoggedLine "INFO" "ProjectsMCP DEV stopped normally." }
    else { Write-LoggedLine "ERROR" "ProjectsMCP DEV stopped with exit code $exitCode." }
    exit $exitCode
}
catch {
    Write-LoggedLine "FATAL" $_.Exception.ToString()
    exit 1
}
