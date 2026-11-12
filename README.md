# Agent Clean

给 AI 代理产生的临时文件设寿命：登记即倒计时，到期移入「墓地」保留 7 天，期间可原样复活，超过保留期才真正删除——全程不用 `rm -rf`，绝不碰源码与系统目录。

## 一句话定位

AI 时代的临时文件讣告簿：**文件一出生就带寿命，到期进墓地，7 天内可复活**。

## 四端安装

### macOS

```bash
bash macos/install.sh     # 复制到 ~/.local/share/agent-clean，注册 launchd
```

- 每天 04:00 自动执行 `reap + purge`，日志写入 `~/Library/Logs/agent-clean.log`
- `agent-clean` 命令进入 PATH（`~/.local/bin`）
- 卸载：`bash macos/uninstall.sh`

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File windows\install.ps1
```

- 复制到 `%LOCALAPPDATA%\AgentCleanApp`，注册计划任务 `AgentCleanDaily`（每天 04:00 reap + purge）
- `bin\agent-clean.cmd` 加入用户 PATH
- 卸载：`powershell -File windows\uninstall.ps1`

### Linux

```bash
mkdir -p ~/.local/bin
printf '#!/bin/bash\nexec python3 %q/cli/main.py "$@"\n' "$PWD" > ~/.local/bin/agent-clean
chmod +x ~/.local/bin/agent-clean
# 每天 04:00 自动收割与火化
(crontab -l 2>/dev/null; echo '0 4 * * * python3 '"$PWD"'/cli/main.py reap && python3 '"$PWD"'/cli/main.py purge') | crontab -
```

### 手机 PWA

```bash
python3 server/app.py          # 0.0.0.0:8787，启动时打印访问令牌
```

手机浏览器打开 `http://<本机IP>:8787/?token=<令牌>`，可查看在册条目与剩余时间、立即下葬、复活最近一条、触发 reap、查看墓地。「添加到主屏幕」即成为 PWA，深色界面、纯手写 CSS、无任何外部 CDN。

## 命令速查表

| 命令 | 作用 |
| --- | --- |
| `agent-clean add <路径> <寿命>` | 登记寿命（`30m` / `2h` / `1d` / `7d` / `1d12h`），重复 add 同一路径自动合并 |
| `agent-clean add <路径> --at "2026-12-01 18:00"` | 按绝对时间下葬 |
| `agent-clean list` | 在册条目与剩余时间 |
| `agent-clean bury <编号\|路径>` | 立即下葬 |
| `agent-clean reap [--dry-run]` | 收割到期条目 |
| `agent-clean resurrect <编号>` / `--last` | 复活（原路径被占用则改名 `.restored-N`，绝不覆盖） |
| `agent-clean purge [--keep 7d] [--all] [--dry-run]` | 火化超过保留期的墓地条目（默认保留 7 天） |
| `agent-clean extend <编号> <寿命>` | 续命 |
| `agent-clean spare <编号>` | 豁免，不再跟踪 |
| `agent-clean scan [--older 24h] [--apply]` | 扫描垃圾候选；默认只提议，`--apply` 才登记 |
| `agent-clean stats` | 统计 |
| `agent-clean log [--tail N]` | 操作日志 |

Web API（均需 `Authorization: Bearer <令牌>` 或 `?token=`）：

| 接口 | 说明 |
| --- | --- |
| `GET /api/state` | 在册条目、墓地、统计 |
| `POST /api/bury` | `{"target": 编号\|路径}` |
| `POST /api/resurrect` | `{"target": 编号}` 或 `{"last": true}` |
| `POST /api/reap` | 触发收割 |
| `POST /api/purge` | `{"keep": "7d"}` 火化超期墓地 |

## 安全边界

- **绝不 `rm -rf`**：下葬 = `shutil.move` 进墓地，火化 = 仅删除墓地内本工具自己的副本。
- **删除护栏**（比蓝本更严）：精确拒绝 `/`、家目录、`/tmp`、`/var`、`/private/tmp`、`~/Desktop|Documents|Downloads|Library`；整树拒绝 `/System /Library /usr /bin /sbin /etc /Applications /opt`、`~/Library`、`~/.ssh`、`~/.codex`、`~/.hermes/{skills,scripts,hermes-agent,vendor}`、`~/.openclaw/workspace` 与工具自身状态根；Windows 对应 `C:\Windows`、`C:\Program Files`、`%USERPROFILE%\AppData`、`%USERPROFILE%\.ssh` 与工具状态根；层级过浅的路径一律拒绝。
- **身份校验**：下葬前核对 `st_dev + st_ino`（Windows 用 `st_ino`，回退 `size + mtime`），原路径被换成别的文件则跳过不动。
- **复活不覆盖**：原路径已存在时改名 `.restored-N`。
- **只登记可再生的中间产物**：交付物、用户数据、源码、凭据目录不要登记；拿不准先 `scan` 看提议。

详见 [docs/SECURITY.md](docs/SECURITY.md)。

## 状态目录

| 平台 | 位置 |
| --- | --- |
| macOS / Linux | `~/.agent-clean/`（`AGENT_CLEAN_ROOT` 可覆盖） |
| Windows | `%LOCALAPPDATA%\AgentClean\` |

内含 `manifest.json`（登记簿）、`graveyard/`（墓地）、`agent-clean.log`（日志）。

## 测试

```bash
python3 tests/run_tests.py
```

纯标准库，状态根建于临时目录；覆盖全链路、护栏拒绝、身份变更跳过、重复 add 合并、purge --keep、scan 提议不落地、复活不覆盖。全部通过 exit 0。

## 与 woodfishhhh/obituary 的关系

「文件一出生就带寿命、到期进墓地可复活」的产品思路来源于 [woodfishhhh/obituary](https://github.com/woodfishhhh/obituary)（Windows 版）。本项目是独立重写的跨平台实现：**只借鉴思路，不拷贝代码**，核心库、护栏、Web/PWA、安装器均为全新实现（Python 标准库，无第三方依赖）。

## 项目结构

```
agent-clean/
├── core/            跨平台核心库（路径、TTL、护栏、引擎）
├── cli/             命令行入口
├── server/          本地 Web 服务（http.server）+ mobile/ 手机端 PWA
├── macos/           install.sh + launchd plist 模板 + uninstall.sh
├── windows/         install.ps1 + 计划任务 XML + uninstall.ps1
├── docs/            ARCHITECTURE.md、SECURITY.md
└── tests/           run_tests.py（纯标准库测试套件）
```
