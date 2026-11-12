# Agent Clean Windows 卸载脚本：删除计划任务、PATH 项与安装目录。
# 状态数据 %LOCALAPPDATA%\AgentClean 保留，如需清理请手动确认后删除。

$ErrorActionPreference = "Stop"

$Dest = Join-Path $env:LOCALAPPDATA "AgentCleanApp"
$Bin = Join-Path $Dest "bin"
$TaskName = "AgentCleanDaily"

Write-Host "== Agent Clean 卸载"

# 1. 删除计划任务
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Host "已删除计划任务 $TaskName"
} else {
  Write-Host "计划任务不存在，跳过"
}

# 2. 从用户 PATH 移除 bin
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath) {
  $parts = $userPath -split ";" | Where-Object { $_ -and ($_ -ne $Bin) }
  [Environment]::SetEnvironmentVariable("Path", ($parts -join ";"), "User")
  Write-Host "已从用户 PATH 移除 $Bin"
}

# 3. 删除安装目录（仅限预期路径，防误删）
$expected = Join-Path $env:LOCALAPPDATA "AgentCleanApp"
if ($Dest -eq $expected -and (Test-Path $Dest)) {
  Remove-Item -Recurse -Force $Dest
  Write-Host "已删除 $Dest"
}

Write-Host "== 卸载完成（状态数据 %LOCALAPPDATA%\AgentClean 未动）"
