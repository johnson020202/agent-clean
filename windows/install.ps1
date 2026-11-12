# Agent Clean Windows 安装脚本（幂等，可重复执行）
#
# 做四件事：
#   1. 复制项目到 %LOCALAPPDATA%\AgentCleanApp
#   2. 生成 bin\agent-clean.cmd 包装器并把 bin 加入用户 PATH
#   3. 由 XML 模板注册计划任务 AgentCleanDaily（每天 04:00 reap + purge）
#   4. 打印验证提示
#
# 依赖：Python 3（python 命令在 PATH 中）。

$ErrorActionPreference = "Stop"

$Src = Split-Path -Parent $PSScriptRoot
$Dest = Join-Path $env:LOCALAPPDATA "AgentCleanApp"
$Bin = Join-Path $Dest "bin"
$Wrapper = Join-Path $Bin "agent-clean.cmd"
$TaskName = "AgentCleanDaily"

Write-Host "== Agent Clean 安装（源：$Src）"

# 1. 复制项目（不含缓存）
New-Item -ItemType Directory -Force -Path $Dest, $Bin | Out-Null
Get-ChildItem -Force $Src | Where-Object {
  $_.Name -notin @("__pycache__", ".git", "state")
} | ForEach-Object {
  Copy-Item -Recurse -Force $_.FullName $Dest
}
Write-Host "已复制到 $Dest"

# 2. 命令包装器 + 用户 PATH
@"
@echo off
python "%~dp0..\cli\main.py" %*
"@ | Set-Content -Encoding ASCII $Wrapper

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if ($userPath -notlike "*$Bin*") {
  [Environment]::SetEnvironmentVariable(
    "Path", ($userPath.TrimEnd(";") + ";" + $Bin), "User")
  Write-Host "已把 $Bin 加入用户 PATH（新终端生效）"
} else {
  Write-Host "PATH 中已有 $Bin"
}

# 3. 注册计划任务（模板占位符替换）
$template = Get-Content (Join-Path $PSScriptRoot "agent-clean-task.xml") -Raw
$xml = $template.Replace("@BINDIR@", $Bin)
Register-ScheduledTask -TaskName $TaskName -Xml $xml -Force | Out-Null
Write-Host "已注册计划任务 $TaskName（每天 04:00 执行 reap + purge）"

Write-Host "== 安装完成。用法：agent-clean add <路径> 2h"
