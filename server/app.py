#!/usr/bin/env python3
"""Agent Clean 本地 Web 服务：标准库 http.server + 手机端 PWA。

启动：
  python3 server/app.py                 # 0.0.0.0:8787，随机令牌并打印
  python3 server/app.py --token abc123  # 指定访问令牌

API（全部要求 Authorization: Bearer <token> 或 ?token=<token>）：
  GET  /api/state      在册条目、墓地、统计
  POST /api/bury       {"target": 编号|路径}
  POST /api/resurrect  {"target": 编号} 或 {"last": true}
  POST /api/reap       {}
  POST /api/purge      {"keep": "7d", "all": false}
"""

import argparse
import hmac
import json
import os
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import AgentClean, NotFoundError
from core.guard import GuardError
from core.ttl import fmt_left
from core.util import dirsize, human

MOBILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mobile")
STATIC = {
    "/": "index.html",
    "/index.html": "index.html",
    "/manifest.json": "manifest.json",
    "/sw.js": "sw.js",
    "/icon.svg": "icon.svg",
}
CONTENT_TYPE = {
    "index.html": "text/html; charset=utf-8",
    "manifest.json": "application/manifest+json; charset=utf-8",
    "sw.js": "application/javascript; charset=utf-8",
    "icon.svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentCleanHTTP/1.0"

    # ---------- 基础 ----------
    def log_message(self, fmt, *args):
        """静默访问日志，只记错误。"""
        pass

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, name):
        path = os.path.join(MOBILE_DIR, name)
        if not os.path.isfile(path):
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE.get(name, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _token_ok(self, parsed):
        """校验 Bearer 或 ?token=。"""
        token = self.server.token
        supplied = ""
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        else:
            qs = parse_qs(parsed.query)
            supplied = (qs.get("token") or [""])[0]
        return bool(supplied) and hmac.compare_digest(supplied, token)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    # ---------- 状态 ----------
    def _state_payload(self):
        eng = self.server.engine
        m = eng.load()
        now = time.time()
        alive = sorted((i for i in m["items"] if i["state"] == "alive"),
                       key=lambda i: i["due"])
        buried = sorted((i for i in m["items"] if i["state"] == "buried"),
                        key=lambda i: i.get("buried_at", 0), reverse=True)
        items = [{"id": i["id"], "path": i["path"], "kind": i["kind"],
                  "due": i["due"], "left": fmt_left(i["due"] - now),
                  "reason": i.get("reason", "")} for i in alive]
        graves = [{"id": i["id"], "path": i["path"],
                   "buried_at": i.get("buried_at", 0), "why": i.get("why", ""),
                   "left": fmt_left(max(0, i.get("buried_at", 0) + 7 * 86400 - now))}
                  for i in buried]
        return {"ok": True, "now": now, "items": items, "graveyard": graves,
                "stats": {"alive": len(alive), "buried": len(buried),
                          "graveyard_bytes": dirsize(eng.graveyard)}}

    # ---------- 路由 ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in STATIC:
            self._send_file(STATIC[path])
            return
        if path == "/api/state":
            if not self._token_ok(parsed):
                self._send_json(401, {"ok": False, "error": "令牌无效"})
                return
            self._send_json(200, self._state_payload())
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/"):
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        if not self._token_ok(parsed):
            self._send_json(401, {"ok": False, "error": "令牌无效"})
            return
        eng = self.server.engine
        body = self._read_json()
        try:
            if path == "/api/bury":
                res = eng.bury(body.get("target"))
                self._send_json(200, {"ok": res["ok"], "item": res["item"]})
            elif path == "/api/resurrect":
                res = eng.resurrect(target=body.get("target"),
                                    last=bool(body.get("last")))
                self._send_json(200, {"ok": True, "item": res["item"],
                                      "path": res["path"]})
            elif path == "/api/reap":
                res = eng.reap()
                self._send_json(200, {"ok": True, "results": res["results"],
                                      "freed": res["freed"],
                                      "freed_human": human(res["freed"])})
            elif path == "/api/purge":
                res = eng.purge(keep=body.get("keep") or "7d",
                                include_all=bool(body.get("all")))
                self._send_json(200, {"ok": True, "purged": res["purged"],
                                      "freed": res["freed"],
                                      "freed_human": human(res["freed"])})
            else:
                self._send_json(404, {"ok": False, "error": "not found"})
        except (GuardError, NotFoundError, ValueError) as e:
            self._send_json(400, {"ok": False, "error": str(e)})
        except Exception as e:  # 兜底：不让服务线程崩掉
            self._send_json(500, {"ok": False, "error": "内部错误: %s" % e})


def main():
    ap = argparse.ArgumentParser(description="Agent Clean 本地 Web 服务")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--token", default="", help="访问令牌（缺省随机生成并打印）")
    ap.add_argument("--root", default="", help="覆盖状态根目录")
    ns = ap.parse_args()

    token = ns.token or secrets.token_urlsafe(16)
    eng = AgentClean(ns.root or None)
    eng.ensure()

    server = ThreadingHTTPServer((ns.host, ns.port), Handler)
    server.engine = eng
    server.token = token

    print("Agent Clean 服务已启动")
    print("  地址：http://%s:%d/  （手机与本机同网段即可访问）" % (ns.host, ns.port))
    print("  访问令牌：%s" % token)
    print("  手机访问：http://<本机IP>:%d/?token=%s" % (ns.port, token))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
