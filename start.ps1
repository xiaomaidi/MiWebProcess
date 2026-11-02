param(
  [switch]$NoBrowser,
  [switch]$Restart
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$Logs = Join-Path $Runtime "logs"
$PidFile = Join-Path $Runtime "pids.json"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

function Port-Busy([int]$Port) {
  $client = New-Object System.Net.Sockets.TcpClient
  try {
    $client.Connect("127.0.0.1", $Port)
    return $true
  } catch {
    return $false
  } finally {
    $client.Close()
  }
}

function Test-Http([string]$Url) {
  try {
    $null = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
    return $true
  } catch {
    $code = 0
    try { $code = [int]$_.Exception.Response.StatusCode } catch { }
    return ($code -eq 401)
  }
}

function Service-Healthy([string]$Name) {
  switch ($Name) {
    "dsh" { return (Test-Http "http://127.0.0.1:9000/health") }
    "backend" { return (Test-Http "http://127.0.0.1:8000/api/ai/status/") }
    "frontend" { return (Test-Http "http://127.0.0.1:5173/") }
  }
  return $false
}

function Stop-ProjectProcesses {
  $targets = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.Name -eq "python.exe" -and $_.CommandLine -match "daphne|dsh_service\.py|run_dsh_real\.py") -or
    ($_.Name -eq "node.exe" -and $_.CommandLine -match "vite")
  }
  foreach ($proc in $targets) {
    try {
      Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
      Write-Host "[stop] $($proc.Name) pid=$($proc.ProcessId)"
    } catch { }
  }
  Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

function Find-Python {
  $candidates = @($env:PYTHON, "python", "python3")
  foreach ($item in $candidates) {
    if (-not $item) { continue }
    try {
      $cmd = Get-Command $item -ErrorAction Stop
      return $cmd.Source
    } catch { }
  }
  throw "找不到 Python。"
}

function Find-Node {
  $candidates = @($env:NODE, "node")
  $known = "C:\Users\27606\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"
  if (Test-Path $known) { $candidates += $known }
  foreach ($item in $candidates) {
    if (-not $item) { continue }
    try {
      $cmd = Get-Command $item -ErrorAction Stop
      return $cmd.Source
    } catch { }
  }
  throw "找不到 Node.js。"
}

$entries = @()
function Save-Pid {
  param($Name, $Process, $Port, $Log)
  $script:entries += [pscustomobject]@{
    name = $Name
    pid = $Process.Id
    port = $Port
    started_at = (Get-Date).ToString("s")
    log = $Log
  }
  $script:entries | ConvertTo-Json -Depth 4 | Set-Content $PidFile -Encoding utf8
}

function Start-One {
  param(
    [string]$Name,
    [string]$File,
    [string[]]$Arguments,
    [string]$WorkingDirectory,
    [string]$LogName,
    [int]$Port,
    [string]$HealthUrl
  )
  $stdout = Join-Path $Logs "$LogName.log"
  $stderr = Join-Path $Logs "$LogName.error.log"
  $process = Start-Process -FilePath $File -ArgumentList $Arguments `
    -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  Save-Pid -Name $Name -Process $process -Port $Port -Log $stdout
  Write-Host "[start] $Name pid=$($process.Id) log=$stdout"

  $deadline = (Get-Date).AddSeconds(90)
  while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) { break }
    if (Test-Http $HealthUrl) {
      Write-Host "[ready] $Name $HealthUrl"
      return
    }
    Start-Sleep -Milliseconds 800
  }
  if ($process.HasExited) {
    Write-Warning "$Name 启动失败，查看 $stderr"
    if (Test-Path $stderr) { Get-Content $stderr -Tail 20 | ForEach-Object { Write-Host "  $_" } }
  } else {
    Write-Warning "$Name 90 秒内未就绪，查看 $stdout"
  }
}

$python = Find-Python
$node = Find-Node
$env:USE_SQLITE = "0"
$env:DSH_AGENT_URL = "http://127.0.0.1:9000"
$env:DSH_NO_UPDATE_CHECK = "1"

if ($Restart) {
  Stop-ProjectProcesses
  Start-Sleep -Seconds 2
}

if (Service-Healthy "dsh") {
  Write-Host "[skip] DSH 已运行"
} elseif (Port-Busy 9000) {
  Write-Warning "9000 被其他进程占用，未启动 DSH。先运行 stop.bat 或检查端口。"
} else {
  Start-One -Name "dsh" -File $python `
    -Arguments @((Join-Path $Root "services\run_dsh_real.py")) `
    -WorkingDirectory $Root -LogName "dsh" -Port 9000 -HealthUrl "http://127.0.0.1:9000/health"
}

if (Service-Healthy "backend") {
  Write-Host "[skip] Backend 已运行"
} elseif (Port-Busy 8000) {
  Write-Warning "8000 被其他进程占用，未启动 Backend。先运行 stop.bat 或检查端口。"
} else {
  $backend = Join-Path $Root "backend"
  Start-One -Name "backend" -File $python `
    -Arguments @("-m", "daphne", "-b", "127.0.0.1", "-p", "8000", "config.asgi:application") `
    -WorkingDirectory $backend -LogName "backend" -Port 8000 -HealthUrl "http://127.0.0.1:8000/api/ai/status/"
}

if (Service-Healthy "frontend") {
  Write-Host "[skip] Frontend 已运行"
} elseif (Port-Busy 5173) {
  Write-Warning "5173 被其他进程占用，未启动 Frontend。先运行 stop.bat 或检查端口。"
} else {
  $frontend = Join-Path $Root "frontend"
  $vite = Join-Path $frontend "node_modules\vite\bin\vite.js"
  if (-not (Test-Path $vite)) { throw "找不到 frontend\node_modules\vite\bin\vite.js，请先 npm install。" }
  Start-One -Name "frontend" -File $node `
    -Arguments @($vite, "--host", "127.0.0.1", "--port", "5173") `
    -WorkingDirectory $frontend -LogName "frontend" -Port 5173 -HealthUrl "http://127.0.0.1:5173/"
}

Write-Host ""
Write-Host "MiWebProcess:"
Write-Host "  前端:  http://127.0.0.1:5173"
Write-Host "  后端:  http://127.0.0.1:8000"
Write-Host "  DSH:   http://127.0.0.1:9000/status"
Write-Host "  日志:  $Logs"
Write-Host ""

if (-not $NoBrowser -and (Test-Http "http://127.0.0.1:5173/")) {
  Start-Process "http://127.0.0.1:5173/admin/apps"
}
