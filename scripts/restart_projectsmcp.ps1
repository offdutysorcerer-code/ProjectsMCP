param(
    [int]$Port = 8090,
    [int]$DelaySeconds = 3,
    [int]$StartupTimeoutSeconds = 30,
    [string]$ResultPath = ""
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ResultPath) {
    $ResultPath = Join-Path $projectRoot 'artifacts\restart\latest.json'
}

$resultDir = Split-Path -Parent $ResultPath
New-Item -ItemType Directory -Path $resultDir -Force | Out-Null
$lockPath = Join-Path $resultDir 'restart.lock'
$requestedAt = Get-Date
$originDownAt = $null
$originReadyAt = $null
$lockStream = $null

function Write-Result {
    param(
        [string]$Status,
        [string]$Message,
        [int]$OldPid = 0,
        [int]$NewPid = 0,
        [bool]$PortReady = $false,
        [bool]$HttpReady = $false
    )

    $now = Get-Date
    $downtimeSeconds = $null
    if ($null -ne $originDownAt) {
        $end = if ($null -ne $originReadyAt) { $originReadyAt } else { $now }
        $downtimeSeconds = [Math]::Round(($end - $originDownAt).TotalSeconds, 3)
    }
    $payload = [ordered]@{
        status = $Status
        message = $Message
        port = $Port
        old_pid = $OldPid
        new_pid = $NewPid
        requested_at = $requestedAt.ToString('o')
        updated_at = $now.ToString('o')
        completed_at = if ($Status -in @('ready','failed','already_running')) { $now.ToString('o') } else { $null }
        port_ready = $PortReady
        http_ready = $HttpReady
        origin_downtime_seconds = $downtimeSeconds
    }
    $json = $payload | ConvertTo-Json -Depth 5
    [System.IO.File]::WriteAllText($ResultPath, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

function Test-McpHttpReady {
    param([int]$LocalPort)
    $client = $null
    $response = $null
    try {
        Add-Type -AssemblyName System.Net.Http
        $client = [System.Net.Http.HttpClient]::new()
        $client.Timeout = [TimeSpan]::FromSeconds(1)
        $response = $client.GetAsync(
            "http://127.0.0.1:$LocalPort/sse",
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        return $response.IsSuccessStatusCode -and
            $response.Content.Headers.ContentType.MediaType -eq 'text/event-stream'
    }
    catch { return $false }
    finally {
        if ($null -ne $response) { $response.Dispose() }
        if ($null -ne $client) { $client.Dispose() }
    }
}

try {
    try {
        $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    }
    catch [System.IO.IOException] {
        Write-Result -Status 'already_running' -Message 'Another ProjectsMCP restart watchdog already owns the restart lock.'
        exit 2
    }

    Write-Result -Status 'scheduled' -Message 'Restart watchdog started; exclusive restart lock acquired.'
    Start-Sleep -Seconds ([Math]::Max(1, $DelaySeconds))

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    $oldPid = 0
    if ($listener) {
        $oldPid = [int]$listener.OwningProcess
        Stop-Process -Id $oldPid -Force -ErrorAction Stop
        $originDownAt = Get-Date
    }

    $stopDeadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $stopDeadline) {
        $stillListening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $stillListening) { break }
        Start-Sleep -Milliseconds 100
    }
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $Port did not stop listening after terminating PID $oldPid."
    }

    $env:PROJECTSMCP_NO_PAUSE = '1'
    $startBat = Join-Path $projectRoot 'StartProjectsMCP.bat'
    if (!(Test-Path $startBat)) { throw "Start script not found: $startBat" }

    $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/c',('"' + $startBat + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    Write-Result -Status 'starting' -Message 'New launcher started; waiting for MCP HTTP readiness.' -OldPid $oldPid -NewPid $proc.Id

    $deadline = (Get-Date).AddSeconds([Math]::Max(5, $StartupTimeoutSeconds))
    while ((Get-Date) -lt $deadline) {
        $newListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        $portReady = $null -ne $newListener
        $httpReady = $portReady -and (Test-McpHttpReady -LocalPort $Port)
        if ($httpReady) {
            $originReadyAt = Get-Date
            Write-Result -Status 'ready' -Message 'ProjectsMCP MCP endpoint is accepting HTTP requests again.' -OldPid $oldPid -NewPid ([int]$newListener.OwningProcess) -PortReady $true -HttpReady $true
            exit 0
        }
        Start-Sleep -Milliseconds 250
    }

    $finalListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    Write-Result -Status 'failed' -Message "Timed out waiting for MCP HTTP readiness on port $Port." -OldPid $oldPid -NewPid $proc.Id -PortReady ($null -ne $finalListener) -HttpReady $false
    exit 1
}
catch {
    Write-Result -Status 'failed' -Message $_.Exception.Message
    exit 1
}
finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    }
}
