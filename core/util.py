"""通用工具：目录体积统计与人类可读大小。"""

import os


def dirsize(path):
    """统计文件或目录占用字节数（尽力而为，忽略不可读条目）。"""
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for dp, _, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def human(n):
    """字节数 → 人类可读大小。"""
    n = float(n)
    for u in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return "%.0f%s" % (n, u) if u == "B" else "%.1f%s" % (n, u)
        n /= 1024.0
    return "%.1fP" % n
