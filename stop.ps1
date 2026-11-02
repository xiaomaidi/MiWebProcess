$ErrorActionPreference = "SilentlyContinue"
$Root = $PSScriptRoot
$PidFile = Join-Path $Root ".runtime\pids.json"

for ($round = 0; $round -lt 3; $round++) {
  $targets = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.Name -eq "python.exe" -and $_.CommandLine -match "daphne|dsh_service\.py|run_dsh_real\.py") -or
    ($_.Name -eq "node.exe" -and $_.CommandLine -match "vite")
  }
  foreach ($proc in $targets) {
    try {
      Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
      Write-Host "已停止 $($proc.Name) pid=$($proc.ProcessId)"
    } catch { }
  }
  Start-Sleep -Milliseconds 700
}
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "MiWebProcess 已停止。"
