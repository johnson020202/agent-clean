"""跨平台路径解析。不写死任何 macOS 专属路径，全部按 platform 判断。"""

import os
import platform

IS_WINDOWS = (os.name == "nt") or platform.system().lower().startswith("win")


def home_dir():
    """用户主目录的绝对路径。"""
    return os.path.abspath(os.path.expanduser("~"))


def default_state_root():
    """工具自身状态根目录（manifest、墓地、日志）。

    优先级：环境变量 AGENT_CLEAN_ROOT > 平台标准位置。
    Windows: %LOCALAPPDATA%\\AgentClean
    macOS / Linux: ~/.agent-clean
    """
    env = os.environ.get("AGENT_CLEAN_ROOT")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home_dir(), "AppData", "Local")
        return os.path.join(base, "AgentClean")
    return os.path.join(home_dir(), ".agent-clean")


def windows_dir():
    """Windows 系统目录（非 Windows 平台返回空串）。"""
    if not IS_WINDOWS:
        return ""
    return os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
