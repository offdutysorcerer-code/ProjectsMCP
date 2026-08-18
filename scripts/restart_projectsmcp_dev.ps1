param(
    [int]$Port = 8091,
    [int]$DelaySeconds = 3,
    [int]$StartupTimeoutSeconds = 30,
    [string]$ResultPath = ""
)

$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$port=$Port
if (-not $ResultPath) { $ResultPath=Join-Path $projectRoot 'artifacts\dev\restart\latest.json' }
$resultPath=$ResultPath
$resultDir=Split-Path -Parent $resultPath
$lockPath=Join-Path $resultDir 'restart.lock'
New-Item -ItemType Directory -Force $resultDir | Out-Null
$requestedAt=Get-Date
$downAt=$null
$readyAt=$null
$lock=$null

function Write-Result([string]$Status,[string]$Message,[int]$OldPid=0,[int]$NewPid=0,[bool]$PortReady=$false,[bool]$HttpReady=$false){
  $now=Get-Date
  $downtime=$null
  if($downAt){$end=if($readyAt){$readyAt}else{$now};$downtime=[Math]::Round(($end-$downAt).TotalSeconds,3)}
  [ordered]@{environment='DEV';status=$Status;message=$Message;port=$port;old_pid=$OldPid;new_pid=$NewPid;requested_at=$requestedAt.ToString('o');updated_at=$now.ToString('o');completed_at=if($Status -in @('ready','failed','already_running')){$now.ToString('o')}else{$null};port_ready=$PortReady;http_ready=$HttpReady;origin_downtime_seconds=$downtime} |
    ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $resultPath
}
function Test-Ready {
  $client=$null;$response=$null
  try{
    Add-Type -AssemblyName System.Net.Http
    $client=[System.Net.Http.HttpClient]::new();$client.Timeout=[TimeSpan]::FromSeconds(1)
    $response=$client.GetAsync("http://127.0.0.1:$port/sse",[System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
    return $response.IsSuccessStatusCode -and $response.Content.Headers.ContentType.MediaType -eq 'text/event-stream'
  }catch{return $false}finally{if($response){$response.Dispose()};if($client){$client.Dispose()}}
}
try{
  try{$lock=[System.IO.File]::Open($lockPath,[System.IO.FileMode]::OpenOrCreate,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)}catch [System.IO.IOException]{Write-Result 'already_running' 'Another DEV restart is already running.';exit 2}
  Write-Result 'scheduled' 'DEV restart watchdog started.'
  Start-Sleep -Seconds ([Math]::Max(1,$DelaySeconds))
  $listener=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue|Select-Object -First 1
  $oldPid=0
  if($listener){$oldPid=[int]$listener.OwningProcess;Stop-Process -Id $oldPid -Force;$downAt=Get-Date}
  $deadline=(Get-Date).AddSeconds(10);while((Get-Date)-lt $deadline){if(!(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)){break};Start-Sleep -Milliseconds 100}
  if(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue){throw "DEV port $port did not stop."}
  $env:PROJECTSMCP_NO_PAUSE='1'
  $bat=Join-Path $projectRoot 'StartProjectsMCP-DEV.bat'
  $proc=Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/c',('"'+$bat+'"') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
  Write-Result 'starting' 'DEV launcher started; waiting for MCP HTTP readiness.' $oldPid $proc.Id
  $deadline=(Get-Date).AddSeconds([Math]::Max(5,$StartupTimeoutSeconds))
  while((Get-Date)-lt $deadline){$new=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue|Select-Object -First 1;if($new -and (Test-Ready)){$readyAt=Get-Date;Write-Result 'ready' 'ProjectsMCP DEV is accepting MCP HTTP requests.' $oldPid ([int]$new.OwningProcess) $true $true;exit 0};Start-Sleep -Milliseconds 250}
  $final=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue|Select-Object -First 1
  Write-Result 'failed' 'Timed out waiting for DEV MCP readiness.' $oldPid $proc.Id ($null-ne $final) $false;exit 1
}catch{Write-Result 'failed' $_.Exception.Message;exit 1}finally{if($lock){$lock.Dispose();Remove-Item $lockPath -Force -ErrorAction SilentlyContinue}}
