param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8090,
    [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

# Keep every standalone launch on the Python version prepared by SetupProjectsMCP.bat.
$env:UV_PYTHON = "3.13"

$logDirectory = Join-Path $projectRoot "logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

Get-ChildItem -Path $logDirectory -Filter "projectsmcp-*.log" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$logPath = Join-Path $logDirectory "projectsmcp-$timestamp.log"

function Append-LogSafe {
    param([string]$Line)

    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $stream = New-Object System.IO.FileStream(
        $logPath,
        [System.IO.FileMode]::Append,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::ReadWrite
    )
    try {
        $writer = New-Object System.IO.StreamWriter($stream, $utf8)
        try {
            $writer.WriteLine($Line)
            $writer.Flush()
        }
        finally {
            $writer.Dispose()
        }
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
    }
}

function Write-LoggedLine {
    param(
        [string]$Level,
        [string]$Message
    )

    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Level, $Message
    Write-Host $line
    Append-LogSafe $line
}

function Find-UvCommand {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $uv) {
        return @{
            Executable = $uv.Source
            Prefix = @()
            Display = $uv.Source
        }
    }

    foreach ($candidate in @("py", "python")) {
        $python = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -eq $python) {
            continue
        }

        & $python.Source -m uv --version *> $null
        if ($LASTEXITCODE -eq 0) {
            return @{
                Executable = $python.Source
                Prefix = @("-m", "uv")
                Display = "$($python.Source) -m uv"
            }
        }
    }

    return $null
}

Write-LoggedLine "INFO" "ProjectsMCP launcher started."
Write-LoggedLine "INFO" "Log file: $logPath"
Write-LoggedLine "INFO" "Endpoint: http://${HostAddress}:$Port/sse"

function Get-PortListenerInfo {
    param([int]$LocalPort)

    $listener = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) {
        return $null
    }

    $processId = [int]$listener.OwningProcess
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        Pid = $processId
        Name = if ($null -ne $process) { $process.Name } else { "unknown" }
        CommandLine = if ($null -ne $process) { [string]$process.CommandLine } else { "" }
    }
}

try {
    $existingListener = Get-PortListenerInfo -LocalPort $Port
    if ($null -ne $existingListener) {
        $commandLine = $existingListener.CommandLine
        $isProjectsMcp =
            $commandLine -match '(?i)mcp-proxy(?:\.exe)?' -and
            $commandLine -match ('(?i)(?:--port\s+|--port=)' + [regex]::Escape([string]$Port)) -and
            $commandLine -match '(?i)server\.py'

        if ($isProjectsMcp) {
            Write-LoggedLine "INFO" "ProjectsMCP is already running on ${HostAddress}:$Port (PID $($existingListener.Pid))."
            Write-LoggedLine "INFO" "No second instance will be started."
            exit 0
        }

        Write-LoggedLine "ERROR" "Port $Port is already in use by another process."
        Write-LoggedLine "ERROR" "PID: $($existingListener.Pid); Process: $($existingListener.Name)"
        if ($commandLine) {
            Write-LoggedLine "ERROR" "Command line: $commandLine"
        }
        Write-LoggedLine "ERROR" "ProjectsMCP was not started."
        exit 3
    }

    $uvCommand = Find-UvCommand
    if ($null -eq $uvCommand) {
        Write-LoggedLine "ERROR" "uv is not installed or cannot be found."
        Write-LoggedLine "ERROR" "Run SetupProjectsMCP.bat, then try again."
        exit 2
    }

    Write-LoggedLine "INFO" "Using uv: $($uvCommand.Display)"

    $arguments = @($uvCommand.Prefix) + @(
        "tool", "run",
        "--with", "mcp>=1.27,<2",
        "mcp-proxy==0.12.0",
        "--host", $HostAddress,
        "--port", $Port,
        "--",
        $uvCommand.Executable
    ) + @($uvCommand.Prefix) + @(
        "run",
        "--with-requirements", "requirements.txt",
        "python", "server.py"
    )

    Write-LoggedLine "INFO" "Starting MCP proxy."
    $ErrorActionPreference = "Continue"
    & $uvCommand.Executable @arguments 2>&1 | ForEach-Object {
        $message = $_.ToString()
        Write-Host $message
        Append-LogSafe $message
    }
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    if ($null -eq $exitCode) {
        $exitCode = 1
    }

    if ($exitCode -eq 0) {
        Write-LoggedLine "INFO" "ProjectsMCP stopped normally."
    }
    else {
        Write-LoggedLine "ERROR" "ProjectsMCP stopped with exit code $exitCode."
    }

    exit $exitCode
}
catch {
    Write-LoggedLine "FATAL" $_.Exception.ToString()
    exit 1
}
