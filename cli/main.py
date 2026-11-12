#!/usr/bin/env python3
"""Agent Clean 命令行入口。

用法示例：
  python3 cli/main.py add ./scratch 2h --reason "调试产物"
  python3 cli/main.py list
  python3 cli/main.py reap
  python3 cli/main.py resurrect --last
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import AgentClean, NotFoundError
from core.guard import GuardError
from core.ttl import fmt_left, fmt_ts
from core.util import human


def cmd_add(ns, eng):
    res = eng.add(ns.path, ttl=ns.ttl, at=ns.at, reason=ns.reason or "")
    it = res["item"]
    if res["merged"]:
        print("#%d 已在册，更新寿命：%s 后下葬" % (it["id"], fmt_left(it["due"] - time.time())))
    else:
        print("#%d 登记 %s，%s 后下葬（%s）" % (
            it["id"], it["path"], fmt_left(it["due"] - time.time()), fmt_ts(it["due"])))


def cmd_list(ns, eng):
    items = eng.list_items()
    if not items:
        print("没有在册条目")
        return
    print("%-4s %-10s %-19s %s" % ("#", "剩余", "到期时间", "路径"))
    for i in items:
        print("%-4d %-10s %-19s %s" % (i["id"], fmt_left(i["due"] - time.time()),
                                       fmt_ts(i["due"]), i["path"]))


def cmd_bury(ns, eng):
    res = eng.bury(ns.target)
    it = res["item"]
    if res["ok"]:
        print("已下葬 #%d → %s" % (it["id"], it.get("graveyard")))
    else:
        print("未下葬 #%d：%s" % (it["id"], it.get("note", "见日志")))


def cmd_reap(ns, eng):
    res = eng.reap(dry_run=ns.dry_run)
    if not res["results"]:
        print("没有到期条目")
        return
    for r in res["results"]:
        if ns.dry_run:
            print("[dry-run] 将下葬 #%d %s" % (r["id"], r["path"]))
        elif r["ok"]:
            print("#%d 下葬 %s" % (r["id"], r["path"]))
        else:
            print("#%d 跳过 %s（%s）" % (r["id"], r["path"], r.get("note") or "见日志"))
    if not ns.dry_run:
        print("共下葬 %d 项，腾出 %s" % (sum(1 for r in res["results"] if r["ok"]),
                                     human(res["freed"])))


def cmd_resurrect(ns, eng):
    res = eng.resurrect(target=ns.target, last=ns.last)
    it = res["item"]
    print("#%d 已复活 → %s（默认再给 1 小时，可 extend 续命）" % (it["id"], res["path"]))


def cmd_purge(ns, eng):
    res = eng.purge(keep=ns.keep, include_all=ns.all, dry_run=ns.dry_run)
    if ns.dry_run:
        for r in res["results"]:
            print("[dry-run] 将火化 #%d %s" % (r["id"], r["path"]))
        return
    print("火化 %d 项，释放 %s" % (res["purged"], human(res["freed"])))


def cmd_extend(ns, eng):
    it = eng.extend(ns.target, ns.ttl)
    print("#%d 续命 %s，新到期 %s" % (it["id"], ns.ttl, fmt_ts(it["due"])))


def cmd_spare(ns, eng):
    it = eng.spare(ns.target)
    print("#%d 已豁免，不再跟踪：%s" % (it["id"], it["path"]))


def cmd_scan(ns, eng):
    res = eng.scan(paths=ns.paths or None, older=ns.older, ttl=ns.ttl, apply=ns.apply)
    out = res["candidates"]
    if not out:
        print("没有候选")
        return
    print("候选 %d 项，共 %s：" % (len(out), human(sum(s for _, s in out))))
    for p, s in out[:40]:
        print("  %8s  %s" % (human(s), p))
    if ns.apply:
        print("已登记 %d 项，%s 后下葬" % (res["registered"], ns.ttl))
    else:
        print("仅提议，未登记（加 --apply 才落地）")


def cmd_stats(ns, eng):
    st = eng.stats()
    print("在册 %d 项 / 墓地 %d 项（%s）" % (st["alive"], st["buried"],
                                         human(st["graveyard_bytes"])))
    for i in st["alive_preview"]:
        print("  #%d %-10s %s" % (i["id"], fmt_left(i["due"] - time.time()), i["path"]))


def cmd_log(ns, eng):
    lines = eng.log_tail(ns.tail)
    if not lines:
        print("暂无记录")
        return
    for l in lines:
        print(l)


def build_parser():
    ap = argparse.ArgumentParser(prog="agent-clean", description="给 AI 产物设寿命，到期进墓地可复活")
    ap.add_argument("--root", help="覆盖状态根目录（默认平台标准位置）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="登记路径并设置寿命")
    a.add_argument("path")
    a.add_argument("ttl", nargs="?", default="", help="如 30m / 2h / 1d / 7d / 1d12h")
    a.add_argument("--at", help="到期时间，格式 YYYY-MM-DD HH:MM")
    a.add_argument("--reason", help="登记原因")
    a.set_defaults(f=cmd_add)

    sub.add_parser("list", help="列出在册条目与剩余时间").set_defaults(f=cmd_list)

    b = sub.add_parser("bury", help="立即下葬（编号或路径）")
    b.add_argument("target")
    b.set_defaults(f=cmd_bury)

    r = sub.add_parser("reap", help="收割到期条目")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(f=cmd_reap)

    rs = sub.add_parser("resurrect", help="复活墓地条目")
    rs.add_argument("target", nargs="?")
    rs.add_argument("--last", action="store_true", help="复活最近下葬的一条")
    rs.set_defaults(f=cmd_resurrect)

    p = sub.add_parser("purge", help="火化超过保留期的墓地条目")
    p.add_argument("--keep", help="保留期，默认 7d")
    p.add_argument("--all", action="store_true", help="忽略保留期全部火化")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(f=cmd_purge)

    e = sub.add_parser("extend", help="续命")
    e.add_argument("target")
    e.add_argument("ttl")
    e.set_defaults(f=cmd_extend)

    s = sub.add_parser("spare", help="豁免，不再跟踪")
    s.add_argument("target")
    s.set_defaults(f=cmd_spare)

    sc = sub.add_parser("scan", help="扫描垃圾候选（默认只提议）")
    sc.add_argument("paths", nargs="*")
    sc.add_argument("--older", default="24h")
    sc.add_argument("--ttl", default="2d")
    sc.add_argument("--apply", action="store_true")
    sc.set_defaults(f=cmd_scan)

    sub.add_parser("stats", help="统计").set_defaults(f=cmd_stats)

    lg = sub.add_parser("log", help="查看操作日志")
    lg.add_argument("--tail", type=int, default=20)
    lg.set_defaults(f=cmd_log)
    return ap


def main():
    ns = build_parser().parse_args()
    if ns.cmd == "resurrect" and not ns.target and not ns.last:
        print("错误：resurrect 需要编号或 --last")
        sys.exit(2)
    eng = AgentClean(ns.root)
    try:
        eng.ensure()
        ns.f(ns, eng)
    except (GuardError, NotFoundError, ValueError) as e:
        print("错误：%s" % e)
        sys.exit(2)


if __name__ == "__main__":
    main()
