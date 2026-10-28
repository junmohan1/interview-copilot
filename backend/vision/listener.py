"""pynput 全局监听：双击左键发送，双击中键暂存"""
import time
import threading
from pynput import mouse

class InputListener:
    def __init__(self, on_double_click, on_middle_double_click=None,
                 cooldown=10.0, double_threshold=0.35, middle_double_threshold=0.5):
        self.on_double_click = on_double_click
        self.on_middle_double_click = on_middle_double_click
        self.cooldown = cooldown
        self.double_threshold = double_threshold
        self.middle_double_threshold = middle_double_threshold
        self._last_click = 0.0
        self._last_trigger = 0.0
        self._last_middle_click = 0.0
        self._mouse_listener = None

    def start(self):
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.start()

    def stop(self):
        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass

    def _on_click(self, x, y, button, pressed):
        if not pressed:
            return
        now = time.time()

        if button == mouse.Button.left:
            if now - self._last_click < self.double_threshold:
                if now - self._last_trigger > self.cooldown:
                    self._last_trigger = now
                    threading.Thread(target=self.on_double_click, daemon=True).start()
            self._last_click = now

        elif button == mouse.Button.middle:
            if now - self._last_middle_click < self.middle_double_threshold:
                self._last_middle_click = 0.0
                if self.on_middle_double_click:
                    threading.Thread(target=self.on_middle_double_click, daemon=True).start()
            else:
                self._last_middle_click = now