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

function Write-Result {
    param(
        [string]$Status,
        [string]$Message,
        [int]$OldPid = 0,
        [int]$NewPid = 0
    )

    $payload = [ordered]@{
        status = $Status
        message = $Message
        port = $Port
        old_pid = $OldPid
        new_pid = $NewPid
        timestamp = (Get-Date).ToString('o')
    }
    $json = $payload | ConvertTo-Json -Depth 5
    [System.IO.File]::WriteAllText($ResultPath, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

try {
    Write-Result -Status 'scheduled' -Message 'Restart watchdog started.'
    Start-Sleep -Seconds ([Math]::Max(1, $DelaySeconds))

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    $oldPid = 0
    if ($listener) {
        $oldPid = [int]$listener.OwningProcess
        Stop-Process -Id $oldPid -Force -ErrorAction Stop
    }

    $stopDeadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $stopDeadline) {
        $stillListening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $stillListening) { break }
        Start-Sleep -Milliseconds 250
    }

    $env:PROJECTSMCP_NO_PAUSE = '1'
    $startBat = Join-Path $projectRoot 'StartProjectsMCP.bat'
    if (!(Test-Path $startBat)) { throw "Start script not found: $startBat" }

    $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/c',('"' + $startBat + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    Write-Result -Status 'starting' -Message 'New launcher started; waiting for port.' -OldPid $oldPid -NewPid $proc.Id

    $deadline = (Get-Date).AddSeconds([Math]::Max(5, $StartupTimeoutSeconds))
    while ((Get-Date) -lt $deadline) {
        $newListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($newListener) {
            Write-Result -Status 'ready' -Message 'ProjectsMCP is listening again.' -OldPid $oldPid -NewPid ([int]$newListener.OwningProcess)
            exit 0
        }
        Start-Sleep -Milliseconds 500
    }

    Write-Result -Status 'failed' -Message "Timed out waiting for port $Port." -OldPid $oldPid -NewPid $proc.Id
    exit 1
}
catch {
    Write-Result -Status 'failed' -Message $_.Exception.Message
    exit 1
}
