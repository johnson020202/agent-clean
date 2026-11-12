# 架构说明（ARCHITECTURE）

## 总览

```
                 ┌────────────┐   ┌────────────┐   ┌──────────────────┐
   用户/定时任务 →│  cli/      │   │  server/   │←──│ 手机 PWA (mobile/)│
                 │  main.py   │   │  app.py    │   └──────────────────┘
                 └─────┬──────┘   └─────┬──────┘
                       │  共用同一引擎   │
                 ┌─────▼─────────────────▼──────┐
                 │        core/engine.py        │
                 │  add / list / bury / reap /  │
                 │  resurrect / purge / scan /  │
                 │  extend / spare / stats / log│
                 └───┬─────────┬─────────┬──────┘
                     │         │         │
              core/guard  core/ttl  core/util
              （护栏/身份）（寿命解析）（体积统计）
                     │
              core/paths（平台判断：Windows / macOS / Linux）
```

核心原则：**业务逻辑全部在 `core/`，CLI 与 Web 只是两个薄壳**，行为天然一致。

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `core/paths.py` | 平台判断（`IS_WINDOWS`）、家目录、默认状态根（Windows `%LOCALAPPDATA%\AgentClean`，macOS/Linux `~/.agent-clean`，`AGENT_CLEAN_ROOT` 可覆盖）。不写死任何 macOS 路径 |
| `core/ttl.py` | 寿命解析（`30m/2h/1d/7d/1d12h`，支持 `s/m/h/d/w` 组合）与人类可读格式化 |
| `core/guard.py` | 删除护栏（精确拒绝 + 整树拒绝 + 层级过浅拒绝）、文件身份（`ident` / `ident_matches`） |
| `core/engine.py` | 全部业务命令与状态机 |
| `core/util.py` | 目录体积统计、人类可读大小 |
| `cli/main.py` | argparse 命令行壳，仅负责参数解析与输出排版 |
| `server/app.py` | `http.server` 本地服务 + JSON API + 静态托管手机端 |
| `server/mobile/` | 单页 PWA（`index.html` + `manifest.json` + `sw.js` + `icon.svg`），深色、简体中文、手机优先、零外部依赖 |

## 状态模型

登记簿 `manifest.json`：

```json
{
  "seq": 3,
  "items": [
    {
      "id": 1,
      "path": "/abs/path",
      "kind": "dir",
      "created": 1736000000.0,
      "due": 1736007200.0,
      "state": "alive",
      "reason": "调试产物",
      "dev": 16777220, "ino": 123456, "size": 4096, "mtime": 1735999000.0
    }
  ]
}
```

条目状态机：

```
alive ──(到期 reap / 手动 bury)──► buried ──(超过保留期 purge)──► purged（从登记簿移除）
  │                                  │
  │ 身份已变                          └──(resurrect)──► alive（默认再给 1 小时）
  └──► skipped（跳过不动）
  └──► spared（豁免，不再跟踪）
  └──► gone（源已不存在）
```

写入方式：`manifest.json.tmp` + `os.replace` 原子替换，不会出现半个登记簿。

## 下葬 / 复活流程

1. **下葬（bury）**：`exists` → `ident` 身份比对（`st_dev+st_ino`；Windows `st_ino` 或回退 `size+mtime`）→ 不符则 `skipped` → `shutil.move` 到 `graveyard/<id>_<时间戳>/<basename>`，绝不 `rm`。
2. **复活（resurrect）**：原路径空闲则移回原处；被占用则改名 `<name>.restored-N`，**绝不覆盖**；墓地目录清掉，条目回到 `alive` 并默认续 1 小时。
3. **火化（purge）**：只删除 `graveyard/` 内本工具创建的副本目录，默认保留 7 天（`--keep` 可调，`--all` 忽略保留期）。

## Web API 契约

- 全部 `/api/*` 要求 `Authorization: Bearer <token>` 或 `?token=<token>`（`hmac.compare_digest` 恒时比较）。
- 请求/响应均为 JSON；错误统一 `{"ok": false, "error": "..."}`，护栏/未找到 → 400，鉴权失败 → 401。
- `GET /api/state` 返回 `items`（含剩余时间 `left`）、`graveyard`（含距火化剩余 `left`）、`stats`。
- 写操作仅 4 个：`/api/bury` `/api/resurrect` `/api/reap` `/api/purge`，与 CLI 调同一个引擎。
- 静态壳（`/`、`manifest.json`、`sw.js`）不需要令牌，API 请求不做缓存（Service Worker 明确绕过 `/api/`）。

## 安装器

- macOS：`install.sh` 复制项目到 `~/.local/share/agent-clean`、生成 `~/.local/bin/agent-clean`、用 `macos/com.agentclean.reap.plist` 模板（`@PYTHON@` `@DEST@` `@LOG@` 占位符）生成 LaunchAgent，每天 04:00 `reap && purge`。幂等（先 bootout 再 load），`uninstall.sh` 只删本工具安装产物。
- Windows：`install.ps1` 复制到 `%LOCALAPPDATA%\AgentCleanApp`、生成 `bin\agent-clean.cmd`、写用户 PATH、用 `windows/agent-clean-task.xml` 模板（`@BINDIR@` 占位符）注册计划任务 `AgentCleanDaily`。`uninstall.ps1` 反向清理。
