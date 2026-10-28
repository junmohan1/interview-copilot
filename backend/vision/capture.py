"""dxcam 全屏截图，转 base64"""
import base64
import time
import threading
import dxcam
import cv2

_camera = None
_lock = threading.Lock()

def _get_camera():
    global _camera
    if _camera is None:
        with _lock:
            if _camera is None:
                _camera = dxcam.create(output_idx=0, output_color="BGR")
    return _camera

def capture_screen_base64(quality=85):
    """抓全屏，返回 base64 JPEG。失败返回空字符串"""
    try:
        cam = _get_camera()
        frame = cam.grab()
        for _ in range(5):
            if frame is not None:
                break
            time.sleep(0.1)
            frame = cam.grab()
        if frame is None:
            return ""
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            return ""
        return base64.b64encode(buf.tobytes()).decode("utf-8")
    except Exception as e:
        print(f"[截图] 异常: {e}")
        return ""