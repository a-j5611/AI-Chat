"""安全地打开网址 / 文件 / 目录 —— 专治「提权进程派生提权浏览器」。

现象：程序以管理员权限运行时，`webbrowser.open()` / `os.startfile()` 会派生一个
**提权的 Edge**，而桌面上已有普通权限的实例，Windows 不允许两者共存，于是弹出：
    「Microsoft Edge 未响应，因为现有实例正在以提升的权限运行…」
且系统"纠正"这个过程很慢 —— 实测 ShellExecute 这条路要 13 秒以上，用户侧常见 1 分钟。

结论（实测数据）：
    explorer.exe <url>   → 0.7 秒，浏览器落在普通权限（正确）
    os.startfile(url)    → 13 秒以上（慢，且可能派生提权实例）
    webbrowser.open(url) → 派生提权实例（会弹权限提示）

所以这里**只用 explorer.exe**，不做"验证—重试"（重试会走慢路径，导致重复打开、
或等一分钟才出现）。打开动作本身是异步的，函数立即返回，不阻塞界面。
"""
from __future__ import annotations

import ctypes
import os
import subprocess

IS_WINDOWS = os.name == "nt"


def is_elevated() -> bool:
    """当前进程是否以管理员权限运行。"""
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _via_explorer(target: str) -> bool:
    """让资源管理器代为打开：快，且浏览器/文件夹都落在普通权限。"""
    try:
        # 注意：不能带 DETACHED_PROCESS(0x8)，否则 explorer 会以 0xc0000142 崩溃
        proc = subprocess.Popen(["explorer.exe", target], close_fds=True)
        try:
            # explorer 正常会把请求转发给已运行的 shell 后立即退出；
            # 若它带着错误码秒退，说明启动失败（例如参数非法）
            proc.wait(timeout=0.4)
            if proc.returncode not in (0, 1, None):
                return False
        except subprocess.TimeoutExpired:
            pass        # 仍在运行 = 已交给资源管理器
        return True
    except Exception:
        return False


def _via_startfile(target: str) -> bool:
    try:
        os.startfile(target)        # noqa: S606  仅 Windows
        return True
    except Exception:
        return False


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url and not url.lower().startswith(("http://", "https://", "file://", "mailto:")):
        url = "https://" + url
    return url


def open_url(url: str) -> bool:
    """打开网址，立即返回（不等待浏览器）。"""
    url = _normalize_url(url)
    if not url:
        return False
    if IS_WINDOWS:
        # explorer 既快又不会派生提权实例；失败才退回 startfile
        return _via_explorer(url) or _via_startfile(url)
    try:
        import webbrowser

        return bool(webbrowser.open(url))
    except Exception:
        return False


def open_path(path: str) -> bool:
    """打开文件 / 文件夹（同样交给 explorer，避免提权资源管理器）。"""
    if not path:
        return False
    path = str(path)
    if not os.path.exists(path):
        return False
    if IS_WINDOWS:
        return _via_explorer(path) or _via_startfile(path)
    try:
        os.startfile(path)          # noqa: S606
        return True
    except Exception:
        return False


def copy_text(widget, text: str) -> bool:
    """把文本放进剪贴板（"打不开浏览器"时的兜底）。"""
    try:
        widget.clipboard_clear()
        widget.clipboard_append(text)
        widget.update_idletasks()
        return True
    except Exception:
        return False
