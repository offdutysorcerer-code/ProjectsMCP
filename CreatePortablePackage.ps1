param(
    [string]$OutputPath = "",
    [switch]$IncludeGit
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectName = Split-Path $projectRoot -Leaf
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $OutputPath) {
    $OutputPath = Join-Path (Split-Path $projectRoot -Parent) "$projectName-portable-$timestamp.zip"
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "$projectName-portable-$([guid]::NewGuid().ToString('N'))"
$stage = Join-Path $tempRoot $projectName

$excludedDirs = @('artifacts', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.venv', 'venv', 'env', 'NVIDIA Corporation')
if (-not $IncludeGit) { $excludedDirs += '.git' }
$excludedFiles = @('*.log', '*.pyc', '*.pyo', '*.pyd', '.env', '.env.*')

try {
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    $args = @($projectRoot, $stage, '/E', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    foreach ($dir in $excludedDirs) { $args += @('/XD', (Join-Path $projectRoot $dir)) }
    foreach ($pattern in $excludedFiles) { $args += @('/XF', $pattern) }
    & robocopy @args | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }
    if (Test-Path $OutputPath) { Remove-Item $OutputPath -Force }
    Compress-Archive -Path $stage -DestinationPath $OutputPath -CompressionLevel Optimal
    $size = (Get-Item $OutputPath).Length
    [pscustomobject]@{ OutputPath=$OutputPath; SizeMB=[math]::Round($size/1MB,2); IncludedGit=[bool]$IncludeGit; ExcludedDirectories=$excludedDirs } | Format-List
} finally {
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
