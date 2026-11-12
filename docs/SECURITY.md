# 安全说明（SECURITY）

## 威胁模型

本工具的唯一破坏性动作是「火化」——删除墓地内本工具自己的副本。风险集中在：

1. 误登记重要路径（源码、用户数据、系统目录）；
2. 登记后原路径被换成别的文件，错误下葬新文件；
3. 复活时覆盖用户已放回原位的文件；
4. Web 服务被局域网内他人调用。

以下护栏逐条应对。

## 删除护栏（core/guard.py）

所有登记入口（`add`、`scan --apply`）在写入登记簿前必须过 `guard_path()`，解析真实路径（`realpath`）后按序检查，任一命中即拒绝：

| 规则 | 内容 |
| --- | --- |
| 精确拒绝 | `/`、家目录、`/tmp`、`/var`、`/private/tmp`、`/private/var`、`/private`、`/Users`、`/Applications`、`/Library`、`/System`、`/usr`、`/bin`、`/sbin`、`/etc`、`/opt`、`/Volumes`、`~/Desktop`、`~/Documents`、`~/Downloads`、`~/Library` |
| 整树拒绝 | `/System /Library /usr /bin /sbin /etc /Applications /opt`、`~/Library`、`~/.ssh`、`~/.codex`、`~/.hermes/skills`、`~/.hermes/scripts`、`~/.hermes/hermes-agent`、`~/.hermes/vendor`、`~/.openclaw/workspace`、**工具自身状态根目录** |
| Windows 补充 | `C:\` 根、`%WINDIR%`（通常 `C:\Windows`）、`C:\Program Files`、`C:\Program Files (x86)`、`%USERPROFILE%\AppData`、`%USERPROFILE%\.ssh`、`%TEMP%`、`%TMP%`、工具状态根 |
| 层级过浅 | POSIX 层级 ≤ 2（如 `/xx`）、Windows 盘符下层级 ≤ 2 一律拒绝，视为误传整盘/整树 |

比蓝本更严之处：`/tmp`、`/var` 等除精确拒绝外不允许多数浅层误传；工具自身状态根按「整树」处理；Windows 保护集独立实现，不复用 POSIX 列表。

## 文件身份校验

下葬前记录并复核身份（`dev/ino/size/mtime`）：

- POSIX：`st_dev + st_ino` 严格相等，否则跳过（条目置 `skipped`，文件原地不动）；
- Windows：`st_ino` 非零则比 `st_ino`，否则回退 `size + mtime`。

这条防住「登记的是 A，到期时原路径已被换成 B」的经典误删。

## 不用 rm -rf

- 下葬 = `shutil.move`（跨设备时等价于复制+删除原文件，是 Python 标准行为）；
- 火化 = `shutil.rmtree` 仅作用于 `graveyard/<条目>/`——本工具自己创建的副本目录；
- 任何路径都不拼接 `rm -rf` 子进程。安装/卸载脚本仅删除自己的安装目录（脚本内有路径等值校验），不涉及登记数据。

## 复活不覆盖

原路径已存在时改名 `<name>.restored-N`（N 递增直到不冲突），用户放回原位的文件永远安全。

## Web 服务

- 仅绑定本地服务语义（默认 `0.0.0.0:8787`，方便手机访问），但**所有 `/api/*` 必须携带令牌**（`--token` 指定或启动时随机生成并打印），恒时比较防时序侧信道；
- 只暴露 5 个 JSON 接口，不提供任意路径读写；静态资源白名单 4 个文件；
- API 响应 `Cache-Control: no-store`，Service Worker 对 `/api/` 不做缓存；
- 令牌不存在任何文件中，仅打印在启动输出里（可由启动脚本转发给手机）。

## 使用纪律

- **只登记可再生的中间产物**：调试脚本、日志、截图、`test-results/`、`__pycache__`、临时目录/容器。
- **不登记**：交付物、用户数据、源码、凭据目录。
- 拿不准就 `agent-clean scan` 看提议，人工确认后再 `--apply`。
- 项目内不含任何真实凭据、代理地址、账号信息；如自行扩展配置，凭据放环境变量。
