#!/usr/bin/env python3
"""Agent Clean 测试套件（纯标准库，无第三方依赖）。

在系统临时目录下自建状态根与测试目标，覆盖：
- TTL 解析（30m / 2h / 1d / 7d / 1d12h）
- add → 到期 → reap → resurrect 全链路
- 护栏拒绝：/ 、~/Desktop、状态根自身
- 身份变更（inode 不符）跳过不动
- 重复 add 合并，不产生重复条目
- purge --keep 保留期内不火化
- scan 只提议不落地
- 复活不覆盖：原路径被占用则改名 .restored-N

运行：python3 tests/run_tests.py   （全部通过 exit 0，输出 OK/FAIL 明细）
"""

import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.engine import AgentClean  # noqa: E402
from core.guard import GuardError  # noqa: E402
from core.ttl import parse_ttl  # noqa: E402

PAST = "2000-01-01 00:00"  # 已过期的到期时间，便于立刻 reap


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------- 测试用例（每个函数收到独立的临时目录 base） ----------------

def test_ttl(base):
    check(parse_ttl("30m") == 1800, "30m 应为 1800 秒")
    check(parse_ttl("2h") == 7200, "2h 应为 7200 秒")
    check(parse_ttl("1d") == 86400, "1d 应为 86400 秒")
    check(parse_ttl("7d") == 7 * 86400, "7d 应为 604800 秒")
    check(parse_ttl("1d12h") == 129600, "1d12h 应为 129600 秒")
    try:
        parse_ttl("abc")
    except ValueError:
        return
    raise AssertionError("非法 TTL 应抛 ValueError")


def test_full_chain(base):
    """add → 到期 → reap 下葬 → resurrect 复活，内容原样。"""
    eng = AgentClean(os.path.join(base, "state"))
    target = os.path.join(base, "work", "scratch")
    write(os.path.join(target, "out.txt"), "hello")
    res = eng.add(target, at=PAST, reason="测试产物")
    check(res["item"]["id"] == 1, "首条应为 #1")

    r = eng.reap()
    check(r["results"] and r["results"][0]["ok"], "到期条目应下葬: %s" % r)
    check(not os.path.exists(target), "下葬后原路径应消失")
    item = eng.load()["items"][0]
    check(item["state"] == "buried", "状态应为 buried: %s" % item)
    check(os.path.exists(item["payload"]), "墓地副本应存在")

    rr = eng.resurrect(last=True)
    back = os.path.join(rr["path"], "out.txt")
    check(os.path.exists(back), "复活后文件应回到原处: %s" % rr["path"])
    check(read(back) == "hello", "复活后内容应原样")
    check(eng.load()["items"][0]["state"] == "alive", "复活后状态应为 alive")


def test_guard(base):
    """护栏必须拒绝 / 、~/Desktop、状态根自身。"""
    eng = AgentClean(os.path.join(base, "state"))
    eng.ensure()
    bad_paths = ["/", os.path.expanduser("~"),
                 os.path.expanduser("~/Desktop"), eng.root]
    for bad in bad_paths:
        try:
            eng.add(bad, ttl="1h")
        except GuardError:
            continue
        raise AssertionError("护栏未拒绝: %s" % bad)


def test_identity_change(base):
    """登记后原文件被换掉（身份已变）→ reap 必须跳过，绝不移动新文件。"""
    eng = AgentClean(os.path.join(base, "state"))
    f = os.path.join(base, "work", "a.txt")
    write(f, "one")
    eng.add(f, at=PAST)
    os.remove(f)
    write(f, "different-content-longer")  # 新文件：inode 必变
    r = eng.reap()
    check(not r["results"][0]["ok"], "身份已变应跳过: %s" % r)
    item = eng.load()["items"][0]
    check(item["state"] == "skipped", "状态应为 skipped: %s" % item)
    check(os.path.exists(f) and read(f) == "different-content-longer",
          "新文件必须原地不动")


def test_add_merge(base):
    """重复 add 同一路径 → 合并更新，不产生重复条目。"""
    eng = AgentClean(os.path.join(base, "state"))
    d = os.path.join(base, "work", "d1")
    os.makedirs(d)
    a = eng.add(d, ttl="1h", reason="第一次")
    b = eng.add(d, ttl="30m", reason="第二次")
    check(b["merged"], "第二次应为合并")
    items = eng.load()["items"]
    check(len(items) == 1, "不应产生重复条目: %s" % items)
    check(items[0]["id"] == a["item"]["id"], "编号应保持不变")
    check(items[0]["reason"] == "第二次", "原因应被更新")


def test_purge_keep(base):
    """purge --keep：保留期内不火化，超过才火化。"""
    eng = AgentClean(os.path.join(base, "state"))
    d = os.path.join(base, "work", "d2")
    write(os.path.join(d, "x.bin"), "data")
    res = eng.add(d, ttl="1h")
    buried = eng.bury(res["item"]["id"])
    check(buried["ok"], "手动下葬应成功")
    gdir = buried["item"]["graveyard"]
    check(os.path.isdir(gdir), "墓地目录应存在")

    p = eng.purge(keep="7d")
    check(p["purged"] == 0, "保留期内不应火化: %s" % p)
    check(os.path.isdir(gdir), "保留期内墓地应保留")

    p2 = eng.purge(keep="0s")
    check(p2["purged"] == 1, "超过保留期应火化: %s" % p2)
    check(not os.path.isdir(gdir), "火化后墓地目录应消失")
    check(eng.load()["items"] == [], "火化条目应从登记簿移除")


def test_scan(base):
    """scan 默认只提议不落地；--apply 才登记。"""
    eng = AgentClean(os.path.join(base, "state"))
    root = os.path.join(base, "work", "scanroot")
    pc = os.path.join(root, "junk", "__pycache__")
    os.makedirs(pc)
    lg = os.path.join(root, "junk", "x.log")
    write(lg, "log")
    old = time.time() - 3 * 86400
    os.utime(pc, (old, old))
    os.utime(lg, (old, old))

    r = eng.scan(paths=[root], older="24h", ttl="2d")
    check(len(r["candidates"]) >= 2, "应发现候选: %s" % r)
    check(r["registered"] == 0, "不带 apply 不应登记")
    check(eng.load()["items"] == [], "scan 提议不应落地")

    r2 = eng.scan(paths=[root], older="24h", ttl="2d", apply=True)
    check(r2["registered"] == len(r["candidates"]),
          "apply 后应全部登记: %s vs %s" % (r2, r["candidates"]))
    check(len(eng.load()["items"]) == r2["registered"], "登记数应与登记簿一致")


def test_resurrect_conflict(base):
    """复活不覆盖：原路径被占用时改名 .restored-N。"""
    eng = AgentClean(os.path.join(base, "state"))
    f = os.path.join(base, "work", "c.txt")
    write(f, "orig")
    eng.add(f, at=PAST)
    check(eng.reap()["results"][0]["ok"], "应成功下葬")
    write(f, "new")  # 原路径被新文件占用

    rr = eng.resurrect(last=True)
    check(rr["path"].endswith(".restored-1.txt"), "应改名 .restored-1: %s" % rr["path"])
    check(read(rr["path"]) == "orig", "墓地副本内容应原样")
    check(read(f) == "new", "占用原路径的新文件不应被动")


# ---------------- 运行器 ----------------

def run(name, fn):
    base = tempfile.mkdtemp(prefix="agent-clean-test-")
    try:
        fn(base)
        print("OK   %s" % name)
        return True
    except Exception as e:
        print("FAIL %s: %s: %s" % (name, type(e).__name__, e))
        return False
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main():
    print("Agent Clean 测试套件（状态根建于临时目录）")
    print("-" * 60)
    cases = [
        ("TTL 解析 30m/2h/1d/7d/1d12h", test_ttl),
        ("add→到期→reap→resurrect 全链路", test_full_chain),
        ("护栏拒绝 /、~/Desktop、状态根自身", test_guard),
        ("身份变更（inode 不符）跳过不动", test_identity_change),
        ("重复 add 合并不产生重复条目", test_add_merge),
        ("purge --keep 保留期内不火化", test_purge_keep),
        ("scan 提议不落地", test_scan),
        ("复活不覆盖，改名 .restored-N", test_resurrect_conflict),
    ]
    results = [(name, run(name, fn)) for name, fn in cases]
    passed = [n for n, ok in results if ok]
    failed = [n for n, ok in results if not ok]
    print("-" * 60)
    print("通过 %d 项 / 失败 %d 项" % (len(passed), len(failed)))
    for n in failed:
        print("FAIL 明细：%s" % n)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
