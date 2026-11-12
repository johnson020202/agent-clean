"""删除护栏：拒绝系统、家目录、凭据、源码与工具自身路径。

比蓝本更严：
- 精确拒绝：/、家目录、/tmp、/var、/private/tmp、~/Desktop|Documents|Downloads|Library
  以及 Windows 的系统盘根、%WINDIR%、C:\\Program Files 等；
- 整树拒绝：/System /Library /usr /bin /sbin /etc /Applications /opt、
  ~/Library、~/.ssh、~/.codex、~/.hermes/{skills,scripts,hermes-agent,vendor}、
  ~/.openclaw/workspace、工具自身状态根目录；
- Windows 对应：C:\\Windows、C:\\Program Files、%USERPROFILE%\\AppData、
  %USERPROFILE%\\.ssh、工具状态根；
- 路径层级过浅一律拒绝（疑似误传整盘/整树）。
"""

import os

from .paths import IS_WINDOWS, default_state_root, home_dir, windows_dir


class GuardError(Exception):
    """护栏拒绝或路径非法。"""


def _norm(p):
    """归一化用于比较的路径键（解析符号链接、Windows 下大小写不敏感）。"""
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def protected_exact(state_root=None):
    """绝不允许整体下葬的路径（精确匹配）。"""
    home = home_dir()
    entries = {_norm(os.sep), _norm(home)}
    entries |= {_norm(p) for p in (
        "/tmp", "/var", "/private", "/private/tmp", "/private/var",
        "/Users", "/Applications", "/Library", "/System",
        "/usr", "/bin", "/sbin", "/etc", "/opt", "/Volumes",
    )}
    entries |= {_norm(os.path.join(home, d)) for d in
                ("Desktop", "Documents", "Downloads", "Library")}
    if IS_WINDOWS:
        windir = windows_dir()
        if windir:
            entries.add(_norm(windir))
        entries |= {_norm(r"C:\Program Files"), _norm(r"C:\Program Files (x86)"),
                    _norm(os.path.join(home, "AppData"))}
        for env in ("TEMP", "TMP"):
            v = os.environ.get(env)
            if v:
                entries.add(_norm(v))
    if state_root:
        entries.add(_norm(state_root))
    return entries


def protected_trees(state_root=None):
    """其下所有内容都不许动（源码、系统、凭据、工具自身目录）。"""
    home = home_dir()
    trees = [
        "/System", "/Library", "/usr", "/bin", "/sbin", "/etc",
        "/Applications", "/opt",
        os.path.join(home, "Library"),
        os.path.join(home, ".ssh"),
        os.path.join(home, ".codex"),
        os.path.join(home, ".hermes", "skills"),
        os.path.join(home, ".hermes", "scripts"),
        os.path.join(home, ".hermes", "hermes-agent"),
        os.path.join(home, ".hermes", "vendor"),
        os.path.join(home, ".openclaw", "workspace"),
    ]
    if IS_WINDOWS:
        windir = windows_dir()
        if windir:
            trees.append(windir)
        trees += [r"C:\Program Files", r"C:\Program Files (x86)",
                  os.path.join(home, "AppData"),
                  os.path.join(home, ".ssh")]
    trees.append(state_root or default_state_root())
    return [_norm(t) for t in trees]


def _too_shallow(real):
    """层级过浅（如 /xx、C:\\xx）一律视为误传。"""
    if IS_WINDOWS:
        _, rest = os.path.splitdrive(real)
        parts = [p for p in rest.replace("\\", "/").split("/") if p]
        return len(parts) <= 2
    return real.count("/") <= 2


def guard_path(path, state_root=None):
    """校验并返回真实路径；违反护栏抛 GuardError。"""
    if not path or not str(path).strip():
        raise GuardError("拒绝：空路径")
    real = os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
    key = _norm(real)
    for p in protected_exact(state_root):
        if key == p:
            raise GuardError("拒绝：%s 属于受保护路径" % real)
    for t in protected_trees(state_root):
        if key == t or key.startswith(t.rstrip("\\/") + os.sep):
            raise GuardError("拒绝：%s 位于受保护目录 %s 下" % (real, t))
    if _too_shallow(real):
        raise GuardError("拒绝：%s 层级过浅，疑似误传" % real)
    if not os.path.exists(real):
        raise GuardError("不存在：%s" % real)
    return real


def ident(path):
    """记录文件身份：POSIX 用 st_dev+st_ino，Windows 用 st_ino（可回退 size+mtime）。"""
    st = os.stat(path)
    return {"dev": st.st_dev, "ino": st.st_ino,
            "size": st.st_size, "mtime": st.st_mtime}


def ident_matches(record, current):
    """身份比对：不符则绝不移动文件。

    POSIX：st_dev + st_ino 严格比对；
    Windows：st_ino 非零则比 ino，否则回退 size + mtime。
    """
    if not IS_WINDOWS:
        return (record.get("dev"), record.get("ino")) == (current["dev"], current["ino"])
    ino_r, ino_c = record.get("ino") or 0, current.get("ino") or 0
    if ino_r and ino_c:
        return ino_r == ino_c
    return (record.get("size"), round(float(record.get("mtime") or 0), 3)) == \
           (current.get("size"), round(float(current.get("mtime") or 0), 3))
