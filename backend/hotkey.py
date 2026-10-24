"""老板键：全局热键隐藏/恢复 pywebview 工作台窗口"""
import ctypes
import os
from ctypes import wintypes

try:
    from pynput import keyboard as pynput_keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False

# Windows 下才有 user32
user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

SW_HIDE = 0
SW_SHOW = 5
SW_RESTORE = 9


def _find_windows_by_title(keyword: str, exclude_pid: int = None):
    """按标题包含关键词找窗口，排除指定进程"""
    if user32 is None:
        return []
    result = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, lParam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if keyword not in buf.value:
            return True
        if exclude_pid is not None:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == exclude_pid:
                return True
        result.append(hwnd)
        return True

    user32.EnumWindows(enum_proc, 0)
    return result


def _parse_hotkey(hotkey_str: str) -> str:
    """把 'ctrl+shift+h' 转成 pynput 格式 '<ctrl>+<shift>+h'"""
    parts = [p.strip().lower() for p in hotkey_str.split("+") if p.strip()]
    special = {"ctrl", "shift", "alt", "cmd", "win"}
    out = []
    for p in parts:
        if p in special:
            if p == "win":
                p = "cmd"
            out.append(f"<{p}>")
        else:
            out.append(p)
    return "+".join(out)


class BossKeyManager:
    """
    toggle_launcher: callable，可选。由调用方传入，用于隐藏/显示启动器窗口
    window_keyword: 按标题关键词匹配工作台窗口
    exclude_pid: 排除的进程 ID，pywebview 单窗口模式下传 None
    """

    def __init__(self, hotkey: str = "ctrl+shift+h",
                 toggle_launcher=None,
                 window_keyword: str = "Interview Copilot",
                 exclude_pid: int = None):
        self.hotkey = hotkey
        self.toggle_launcher = toggle_launcher
        self.window_keyword = window_keyword
        self.exclude_pid = exclude_pid
        self._hidden_hwnds = []
        self._is_hidden = False
        self._listener = None

    def start(self):
        if not HAS_PYNPUT:
            print("[老板键] 缺少 pynput，功能未启用")
            return
        if user32 is None:
            print("[老板键] 非 Windows 平台，功能未启用")
            return
        combo = _parse_hotkey(self.hotkey)
        try:
            self._listener = pynput_keyboard.GlobalHotKeys({
                combo: self._on_trigger
            })
            self._listener.start()
            print(f"[老板键] 已启用：{self.hotkey}")
        except Exception as e:
            print(f"[老板键] 启动失败: {e}")

    def _on_trigger(self):
        try:
            if self.toggle_launcher:
                self.toggle_launcher()

            if self._is_hidden:
                for hwnd in self._hidden_hwnds:
                    user32.ShowWindow(hwnd, SW_SHOW)
                    user32.ShowWindow(hwnd, SW_RESTORE)
                self._hidden_hwnds = []
                self._is_hidden = False
                print("[老板键] 窗口已恢复")
            else:
                hwnds = _find_windows_by_title(
                    self.window_keyword, exclude_pid=self.exclude_pid
                )
                self._hidden_hwnds = hwnds
                for hwnd in hwnds:
                    user32.ShowWindow(hwnd, SW_HIDE)
                self._is_hidden = True
                print(f"[老板键] 已隐藏 {len(hwnds)} 个窗口")
        except Exception as e:
            print(f"[老板键] 切换失败: {e}")