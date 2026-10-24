import sys
import os

# ==========================================
# ★ 终极防线：修复 console=False 时 stdout 为 None 导致的闪退
# ==========================================
if sys.stdout is None or sys.stderr is None:
    log_file = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime.log"), "a", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = log_file
    if sys.stderr is None:
        sys.stderr = log_file

import time
import socket
import subprocess
import threading
from pathlib import Path
import webview

# ========== 路径与端口 ==========
BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent.resolve()
RESOURCE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else BASE_DIR
PORT = 8000
WINDOW_TITLE = "Interview Copilot · 工作台"

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

def _kill_stale_processes(port=PORT):
    try:
        out = subprocess.check_output(
            f'netstat -ano | findstr :{port}',
            shell=True, text=True, errors="ignore",
            creationflags=_CREATE_NO_WINDOW
        )
        pids = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(f":{port}"):
                pid = parts[-1]
                if pid.isdigit() and pid != "0":
                    pids.add(int(pid))
        for pid in pids:
            try:
                subprocess.run(
                    f"taskkill /F /PID {pid}",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_CREATE_NO_WINDOW
                )
            except Exception:
                pass
    except Exception:
        pass

def _run_backend():
    import traceback
    import ctypes
    
    try:
        os.environ["IC_BASE_DIR"] = str(BASE_DIR)
        os.environ["IC_RESOURCE_DIR"] = str(RESOURCE_DIR)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        os.environ["HF_HUB_DISABLE_XET"] = "1"
        os.environ["ANONYMIZED_TELEMETRY"] = "False"

        sys.path.insert(0, str(RESOURCE_DIR))
        sys.path.insert(0, str(BASE_DIR))

        import uvicorn
        from config import CONFIG
        from backend.main import app

        host = CONFIG["server"]["host"]
        port = CONFIG["server"]["port"]

        uvicorn.run(app, host=host, port=port, log_level="warning", log_config=None)
        
    except Exception as e:
        # 1. 把完整报错写入 runtime.log
        error_msg = traceback.format_exc()
        with open("runtime.log", "a", encoding="utf-8") as f:
            f.write(f"\n--- 启动崩溃 ---\n{error_msg}\n")
        
        # 2. 弹出一个 Windows 系统级错误框，绝对不会被无视
        ctypes.windll.user32.MessageBoxW(0, f"后端启动失败，请查看 runtime.log\n\n{e}", "启动错误", 0x10)

def _wait_for_backend(port=PORT, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            return True
        except Exception:
            time.sleep(0.3)
    return False

class Launcher:
    def __init__(self):
        self.window = None
        self._boss_key = None

    def run(self):
        _kill_stale_processes(PORT)
        threading.Thread(target=_run_backend, daemon=True).start()

        if not _wait_for_backend(PORT, timeout=40):
            print("[启动] ❌ 后端 40 秒内未就绪")
            # 可以弹个 ctypes 的 MessageBox，这里简单起见就 return
            return

        self.window = webview.create_window(
            WINDOW_TITLE,
            f"http://localhost:{PORT}/desktop",
            width=1280,
            height=860,
            min_size=(960, 600),
        )

        self._start_boss_key()

        try:
            webview.start()
        except Exception as e:
            print(f"[窗口] pywebview 启动失败: {e}")
            import webbrowser
            webbrowser.open(f"http://localhost:{PORT}/desktop")
            while True:
                time.sleep(1)

    def _start_boss_key(self):
        try:
            from backend.hotkey import BossKeyManager
            from config import get as _cfg_get
            hotkey = _cfg_get("ui.boss_hotkey", "ctrl+shift+h") or "ctrl+shift+h"
            self._boss_key = BossKeyManager(
                hotkey=hotkey,
                toggle_launcher=None,
                window_keyword="Interview Copilot",
                exclude_pid=None,
            )
            self._boss_key.start()
        except Exception as e:
            print(f"[老板键] 初始化失败: {e}")

if __name__ == "__main__":
    Launcher().run()