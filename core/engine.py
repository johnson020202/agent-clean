"""核心引擎：登记、下葬、复活、火化的全部业务逻辑。

状态目录布局（state_root）：
  manifest.json   登记簿（原子写入）
  graveyard/      墓地，每个条目一个子目录，保留期内可复活
  agent-clean.log 操作日志
"""

import json
import os
import shutil
import time
from datetime import datetime

from .guard import GuardError, guard_path, ident, ident_matches
from .paths import default_state_root
from .ttl import parse_ttl
from .util import dirsize, human

# scan 的垃圾候选模式（目录 / 文件）
JUNK_PATTERNS = [
    ("__pycache__", "d"), ("test-results", "d"), (".playwright-mcp", "d"),
    (".pytest_cache", "d"), (".mypy_cache", "d"), ("node_modules", "d"),
    (".DS_Store", "f"),
]
JUNK_SUFFIX = (".log", ".tmp", ".bak", ".orig", ".rej", ".pid", ".cache")

# 复活后默认再给 1 小时寿命
RESURRECT_GRACE = 3600


class NotFoundError(Exception):
    """找不到条目。"""


class AgentClean:
    """引擎入口。state_root 可覆盖（测试时指向临时目录）。"""

    def __init__(self, state_root=None):
        self.root = os.path.abspath(state_root or default_state_root())
        self.manifest_path = os.path.join(self.root, "manifest.json")
        self.graveyard = os.path.join(self.root, "graveyard")
        self.logfile = os.path.join(self.root, "agent-clean.log")

    # ---------- 状态存取 ----------
    def ensure(self):
        os.makedirs(self.graveyard, exist_ok=True)

    def load(self):
        if os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path, encoding="utf-8") as f:
                    m = json.load(f)
                if isinstance(m, dict) and "items" in m:
                    m.setdefault("seq", 0)
                    return m
            except (OSError, ValueError):
                pass
        return {"items": [], "seq": 0}

    def save(self, m):
        self.ensure()
        tmp = self.manifest_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1, ensure_ascii=False)
        os.replace(tmp, self.manifest_path)

    def log(self, msg):
        self.ensure()
        with open(self.logfile, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))

    # ---------- 查询 ----------
    def find(self, m, key, state="alive"):
        """按编号或路径找条目。"""
        key = str(key)
        if key.isdigit():
            for it in m["items"]:
                if str(it["id"]) == key and it["state"] == state:
                    return it
            raise NotFoundError("没有编号 %s 的对应条目" % key)
        real = os.path.realpath(os.path.abspath(os.path.expanduser(key)))
        for it in m["items"]:
            if it["state"] == state and os.path.realpath(it["path"]) == real:
                return it
        raise NotFoundError("未登记：%s（先 add）" % real)

    def list_items(self):
        """在册（alive）条目，按到期时间升序。"""
        m = self.load()
        items = [i for i in m["items"] if i["state"] == "alive"]
        items.sort(key=lambda i: i["due"])
        return items

    def stats(self):
        m = self.load()
        alive = [i for i in m["items"] if i["state"] == "alive"]
        buried = [i for i in m["items"] if i["state"] == "buried"]
        return {"alive": len(alive), "buried": len(buried),
                "graveyard_bytes": dirsize(self.graveyard),
                "alive_preview": alive[:10]}

    def log_tail(self, n=20):
        if not os.path.exists(self.logfile):
            return []
        with open(self.logfile, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-n:]

    # ---------- 命令 ----------
    def add(self, path, ttl=None, at=None, reason=""):
        """登记一条寿命。重复登记同一路径 → 合并更新，不产生重复条目。"""
        real = guard_path(path, self.root)
        if at:
            due = datetime.strptime(at, "%Y-%m-%d %H:%M").timestamp()
        elif ttl:
            due = time.time() + parse_ttl(ttl)
        else:
            raise ValueError("必须给出寿命（如 2h）或到期时间（--at）")
        m = self.load()
        for it in m["items"]:
            if it["state"] == "alive" and os.path.realpath(it["path"]) == real:
                it["due"] = due
                if reason:
                    it["reason"] = reason
                self.save(m)
                return {"merged": True, "item": it}
        m["seq"] += 1
        item = {"id": m["seq"], "path": real,
                "kind": "dir" if os.path.isdir(real) else "file",
                "created": time.time(), "due": due, "state": "alive",
                "reason": reason, **ident(real)}
        m["items"].append(item)
        self.save(m)
        self.log("add #%d %s due=%s" % (item["id"], real,
                 time.strftime("%m-%d %H:%M", time.localtime(due))))
        return {"merged": False, "item": item}

    def _bury_item(self, m, it, why="expired"):
        """下葬单条：先验身份，不符则跳过；从不覆盖、从不 rm。"""
        src = it["path"]
        if not os.path.exists(src):
            it["state"] = "gone"
            it["note"] = "源已不存在"
            return False
        try:
            cur = ident(src)
        except OSError:
            it["state"] = "gone"
            it["note"] = "无法读取身份信息"
            return False
        if not ident_matches(it, cur):
            it["state"] = "skipped"
            it["note"] = "身份已变，未处理"
            self.log("skip #%d %s（身份已变）" % (it["id"], src))
            return False
        gid = "%04d_%s" % (it["id"], time.strftime("%Y%m%d-%H%M%S"))
        gdir = os.path.join(self.graveyard, gid)
        os.makedirs(gdir, exist_ok=True)
        dst = os.path.join(gdir, os.path.basename(src.rstrip("/\\")))
        try:
            shutil.move(src, dst)
        except OSError as e:
            self.log("bury fail #%d %s %s" % (it["id"], src, e))
            return False
        it.update({"state": "buried", "buried_at": time.time(),
                   "graveyard": gdir, "payload": dst, "why": why})
        self.log("bury #%d %s → %s" % (it["id"], src, gdir))
        return True

    def bury(self, target):
        """立刻下葬指定条目（编号或路径）。"""
        m = self.load()
        it = self.find(m, target, state="alive")
        ok = self._bury_item(m, it, why="manual")
        self.save(m)
        return {"ok": ok, "item": it}

    def reap(self, dry_run=False):
        """收割：把到期条目下葬。"""
        m = self.load()
        due = [i for i in m["items"]
               if i["state"] == "alive" and i["due"] <= time.time()]
        results, freed = [], 0
        for it in due:
            if dry_run:
                results.append({"id": it["id"], "path": it["path"],
                                "ok": False, "dry_run": True})
                continue
            size = dirsize(it["path"]) if os.path.exists(it["path"]) else 0
            ok = self._bury_item(m, it)
            if ok:
                freed += size
            results.append({"id": it["id"], "path": it["path"], "ok": ok,
                            "note": it.get("note", "")})
        if not dry_run:
            self.save(m)
        return {"results": results, "freed": freed}

    def resurrect(self, target=None, last=False):
        """复活墓地条目。原路径被占用时改名 .restored-N，绝不覆盖。"""
        m = self.load()
        if last:
            buried = [i for i in m["items"] if i["state"] == "buried"]
            if not buried:
                raise NotFoundError("墓地是空的")
            it = max(buried, key=lambda i: i.get("buried_at", 0))
        else:
            it = self.find(m, target, state="buried")
        payload = it.get("payload")
        if not payload or not os.path.exists(payload):
            raise NotFoundError("墓地副本已不存在（可能已火化）")
        dest = it["path"]
        if os.path.exists(dest):
            base, ext = os.path.splitext(dest)
            n = 1
            while os.path.exists("%s.restored-%d%s" % (base, n, ext)):
                n += 1
            dest = "%s.restored-%d%s" % (base, n, ext)
        parent = os.path.dirname(dest) or "."
        os.makedirs(parent, exist_ok=True)
        shutil.move(payload, dest)
        g = it.get("graveyard")
        if g and os.path.isdir(g):
            shutil.rmtree(g, ignore_errors=True)
        for k in ("payload", "graveyard", "buried_at", "why", "note"):
            it.pop(k, None)
        it.update({"state": "alive", "path": dest,
                   "due": time.time() + RESURRECT_GRACE, **ident(dest)})
        self.save(m)
        self.log("resurrect #%d → %s" % (it["id"], dest))
        return {"item": it, "path": dest}

    def purge(self, keep="7d", include_all=False, dry_run=False):
        """火化墓地中超过保留期的条目（默认保留 7 天）。"""
        keep_sec = parse_ttl(keep) if keep else 7 * 86400
        m = self.load()
        results, freed, n = [], 0, 0
        for it in list(m["items"]):
            if it["state"] != "buried":
                continue
            age = time.time() - it.get("buried_at", 0)
            if not include_all and age < keep_sec:
                continue
            g = it.get("graveyard")
            if dry_run:
                results.append({"id": it["id"], "path": it["path"],
                                "dry_run": True})
                continue
            if g and os.path.isdir(g):
                freed += dirsize(g)
                shutil.rmtree(g, ignore_errors=True)
            it["state"] = "purged"
            n += 1
            self.log("purge #%d %s" % (it["id"], it["path"]))
            results.append({"id": it["id"], "path": it["path"]})
        if not dry_run:
            m["items"] = [i for i in m["items"] if i["state"] != "purged"]
            self.save(m)
        return {"purged": n, "freed": freed, "results": results}

    def extend(self, target, ttl):
        """续命：从当前到期时间再加一段寿命。"""
        m = self.load()
        it = self.find(m, target, state="alive")
        add = parse_ttl(ttl)
        it["due"] = max(it["due"], time.time()) + add
        self.save(m)
        return it

    def spare(self, target):
        """豁免：不再跟踪该条目。"""
        m = self.load()
        it = self.find(m, target, state="alive")
        it["state"] = "spared"
        self.save(m)
        return it

    def scan(self, paths=None, older="24h", ttl="2d", apply=False):
        """扫描垃圾候选。默认只提议，apply=True 才登记。"""
        from .paths import home_dir
        roots = paths or [os.path.join(home_dir(), ".hermes", "workspace"),
                          os.path.join(home_dir(), ".hermes", "cache", "scratch")]
        older_sec = parse_ttl(older)
        cands = []
        for root in roots:
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames
                               if d not in (".git", "node_modules", "venv", ".venv")]
                for d in list(dirnames):
                    if any(d == pat for pat, kind in JUNK_PATTERNS if kind == "d"):
                        cands.append(os.path.join(dirpath, d))
                        dirnames.remove(d)
                for f in filenames:
                    p = os.path.join(dirpath, f)
                    if (f in [pat for pat, kind in JUNK_PATTERNS if kind == "f"]
                            or f.endswith(JUNK_SUFFIX)):
                        cands.append(p)
        out = []
        for p in cands:
            try:
                if time.time() - os.path.getmtime(p) < older_sec:
                    continue
                out.append((p, dirsize(p)))
            except OSError:
                pass
        out.sort(key=lambda x: -x[1])
        registered = 0
        if apply and out:
            m = self.load()
            for p, _ in out:
                try:
                    real = guard_path(p, self.root)
                except GuardError:
                    continue
                if any(i["state"] == "alive"
                       and os.path.realpath(i["path"]) == real
                       for i in m["items"]):
                    continue
                m["seq"] += 1
                m["items"].append({"id": m["seq"], "path": real,
                                   "kind": "dir" if os.path.isdir(real) else "file",
                                   "created": time.time(),
                                   "due": time.time() + parse_ttl(ttl),
                                   "state": "alive", "reason": "scan",
                                   **ident(real)})
                registered += 1
            self.save(m)
        return {"candidates": out, "registered": registered}
