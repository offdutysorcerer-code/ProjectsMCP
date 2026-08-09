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

function Write-LoggedLine {
    param(
        [string]$Level,
        [string]$Message
    )

    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Level, $Message
    Write-Host $line
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
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

try {
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
        Add-Content -LiteralPath $logPath -Value $message -Encoding UTF8
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
