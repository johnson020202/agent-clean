"""TTL 解析与人类可读时长格式化。"""

import time


class TTLParseError(ValueError):
    """寿命格式非法。"""


_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_ttl(text):
    """解析 30m / 2h / 1d / 7d / 1d12h / 90s 形式的寿命，返回秒数。"""
    if not text or not str(text).strip():
        raise TTLParseError("寿命不能为空")
    s = str(text).strip().lower()
    total, num = 0, ""
    for ch in s:
        if ch.isdigit():
            num += ch
        elif ch in _UNITS:
            if not num:
                raise TTLParseError("寿命格式错误: %s" % text)
            total += int(num) * _UNITS[ch]
            num = ""
        else:
            raise TTLParseError("寿命格式错误: %s" % text)
    if num:
        raise TTLParseError("缺少单位: %s" % text)
    return total


def fmt_left(sec):
    """剩余秒数 → 人类可读文本。"""
    if sec <= 0:
        return "已到期"
    d, rem = divmod(int(sec), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return "%dd%dh" % (d, h)
    if h:
        return "%dh%dm" % (h, m)
    return "%dm" % m


def fmt_ts(ts):
    """时间戳 → 本地时间文本。"""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
