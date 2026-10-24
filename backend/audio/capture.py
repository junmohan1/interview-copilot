"""音频采集：支持指定麦克风和系统回环设备"""
import queue
import threading
import sys
import numpy as np
import scipy.signal

try:
    import sounddevice as sd
    HAS_SD = True
except ImportError:
    HAS_SD = False


def _open_mic_stream(device, samplerate, callback):
    """以共享模式打开麦克风，显式声明 exclusive=False，确保不独占设备"""
    kwargs = dict(
        device=device,
        samplerate=samplerate,
        channels=1,
        dtype="float32",
        callback=callback,
    )
    if sys.platform == "win32":
        try:
            kwargs["extra_settings"] = sd.WasapiSettings(exclusive=False)
        except Exception:
            pass
    return sd.InputStream(**kwargs)

def list_audio_devices():
    """获取系统所有的麦克风和回环设备"""
    mics = []
    loops = []

    if not HAS_SD:
        return mics, loops

    try:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if d['max_input_channels'] > 0:
                mics.append({
                    "id": i,
                    "name": d['name'],
                    "channels": d['max_input_channels'],
                    "hostapi": sd.query_hostapis(d['hostapi'])['name']
                })
    except Exception as e:
        print(f"[音频] 扫描麦克风失败: {e}")

    if sys.platform == 'win32':
        try:
            import pyaudiowpatch as pyaudio
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                dev = p.get_device_info_by_index(i)
                if dev.get('isLoopbackDevice', False):
                    loops.append({
                        "id": dev['index'],
                        "name": dev['name'],
                        "channels": dev['maxInputChannels']
                    })
            p.terminate()
        except Exception as e:
            print(f"[音频] 扫描回环失败: {e}")

    return mics, loops

# ============================================================
# 设备解析：全局遍历 + 优先级回退
# ============================================================

MIC_EXCLUDE_KEYWORDS = [
    "stereo mix", "立体声混音", "virtual", "vb-audio", "cable",
    "line in", "loopback", "what u hear", "wave out mix",
]
MIC_PREFER_KEYWORDS = [
    "realtek", "high definition audio", "麦克风阵列", "microphone array",
    "内置", "internal", "built-in",
]


def _find_mic_by_name(name: str):
    """按名字找麦克风：精确 → 包含"""
    if not name:
        return None
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0 and d['name'] == name:
            return i, d
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0 and name in d['name']:
            return i, d
    return None


def _find_builtin_mic():
    """遍历所有输入设备，智能选内置麦克风"""
    devices = sd.query_devices()
    candidates = []
    for i, d in enumerate(devices):
        if d['max_input_channels'] <= 0:
            continue
        name_lower = d['name'].lower()
        if any(k in name_lower for k in MIC_EXCLUDE_KEYWORDS):
            continue
        candidates.append((i, d, name_lower))

    if not candidates:
        return None
    for i, d, name_lower in candidates:
        if any(k in name_lower for k in MIC_PREFER_KEYWORDS):
            return i, d
    i, d, _ = candidates[0]
    return i, d

def _find_realtek_mic():
    """找名字含 Realtek / 麦克风阵列 的内置麦克风"""
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d['max_input_channels'] <= 0:
            continue
        nl = d['name'].lower()
        if 'realtek' in nl or '麦克风阵列' in d['name'] or 'microphone array' in nl:
            return i, d
    return None


def _find_realtek_loopback(p):
    """找名字含 Realtek 的真实扬声器回环，排除虚拟声卡"""
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if not d.get('isLoopbackDevice', False):
            continue
        nl = d['name'].lower()
        if any(k in nl for k in ("cable", "vb-audio", "virtual", "voicemeeter")):
            continue
        if 'realtek' in nl or '扬声器' in d['name']:
            return d
    return None


def _resolve_mic(mic_device_id, mic_device_name):
    """
    麦克风优先级：
    1. 配置的 ID 有效 → 用（带耳机时就是耳机麦）
    2. 配置的名字匹配 → 用（ID 漂移但名字还在）
    3. Realtek / 麦克风阵列 内置麦 → 用（耳机拔了，ID 和名字都找不到时）
    4. 智能内置（排除虚拟设备）→ 用
    5. 系统默认
    来源说明：config_id / config_name / realtek / builtin / default / none
    """
    # 1. 配置的 ID 有效
    if mic_device_id is not None:
        try:
            mic_device_id = int(mic_device_id)
            dev_info = sd.query_devices(mic_device_id)
            if dev_info['max_input_channels'] > 0:
                return mic_device_id, dev_info, "config_id"
        except Exception:
            pass

    # 2. 用配置的名字找
    found = _find_mic_by_name(mic_device_name)
    if found:
        i, d = found
        return i, d, "config_name"

    # 3. 显式回退到 Realtek / 麦克风阵列
    found = _find_realtek_mic()
    if found:
        i, d = found
        return i, d, "realtek"

    # 4. 智能选内置麦克风（排除虚拟）
    found = _find_builtin_mic()
    if found:
        i, d = found
        return i, d, "builtin"

    # 5. 系统默认
    try:
        dev_info = sd.query_devices(kind='input')
        return None, dev_info, "default"
    except Exception:
        return None, None, "none"


def _find_loopback_by_name(p, name: str):
    """在 pyaudiowpatch 的设备列表里按名字找 loopback"""
    if not name:
        return None
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if d.get('isLoopbackDevice', False) and d['name'] == name:
            return d
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if d.get('isLoopbackDevice', False) and name in d['name']:
            return d
    return None


def _find_default_output_loopback(p):
    """找默认输出设备对应的 loopback"""
    import pyaudiowpatch as pyaudio
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
        for dev in p.get_loopback_device_info_generator():
            if default_out["name"] in dev["name"]:
                return dev
    except Exception:
        pass
    return None


def _find_any_loopback(p):
    """遍历所有 loopback，排除虚拟的，选第一个"""
    exclude = ["cable", "vb-audio", "virtual"]
    first = None
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if not d.get('isLoopbackDevice', False):
            continue
        name_lower = d['name'].lower()
        if any(k in name_lower for k in exclude):
            continue
        if first is None:
            first = d
    return first


def _resolve_loopback(p, loop_device_id, loop_device_name):
    """
    回环优先级（关键：默认输出优先，实现“插耳机用耳机，拔耳机用 Realtek”）：
    1. 默认输出设备对应的 loopback → 永远最优先
       （Windows 默认输出 = 声音实际从哪出，插耳机是耳机，拔耳机是 Realtek）
    2. 配置的 ID（排除虚拟声卡）
    3. 配置的名字（排除虚拟声卡）
    4. Realtek 真实扬声器回环
    5. 任意非虚拟 loopback
    来源说明：default_output / config_id / config_name / realtek / any / none
    """
    VIRTUAL_KEYWORDS = ["cable", "vb-audio", "virtual", "voicemeeter", "what u hear", "stereo mix"]

    def is_virtual(name):
        nl = name.lower()
        return any(k in nl for k in VIRTUAL_KEYWORDS)

    # 1. 默认输出设备的 loopback —— 永远优先
    d = _find_default_output_loopback(p)
    if d:
        return d, "default_output"

    # 2. 配置 ID（排除虚拟声卡）
    if loop_device_id is not None:
        try:
            d = p.get_device_info_by_index(int(loop_device_id))
            if d.get('isLoopbackDevice', False) and not is_virtual(d['name']):
                return d, "config_id"
        except Exception:
            pass

    # 3. 配置名字（排除虚拟声卡）
    d = _find_loopback_by_name(p, loop_device_name)
    if d and not is_virtual(d['name']):
        return d, "config_name"

    # 4. Realtek 真实扬声器回环
    d = _find_realtek_loopback(p)
    if d:
        return d, "realtek"

    # 5. 任意非虚拟 loopback
    d = _find_any_loopback(p)
    if d:
        return d, "any"

    return None, "none"



class AudioCapture:
    def __init__(self):
        self.system_queue: queue.Queue = queue.Queue()
        self.mic_queue: queue.Queue = queue.Queue()
        self._system_buffer = np.zeros(0, dtype=np.float32)
        self._mic_buffer = np.zeros(0, dtype=np.float32)
        self._streams = []
        self._lock = threading.Lock()
        self.chunk_size = 1536
        self._running = False
        self.mic_sr = 16000    # 必须是 512 的倍数
        self.system_sr = 16000  # 记录回环采样率
        self._system_rms = 0.0  # 用于“设备自检”电平监测
        self._mic_rms = 0.0
        self._pa_instance = None  # 保存 PyAudio 实例，防止被 GC 回收

    def start(self, mic_device_id=None, loop_device_id=None,
              mic_device_name="", loop_device_name=""):
        if not HAS_SD:
            raise RuntimeError("缺少 sounddevice")

        print(f"\n[音频系统] 正在解析设备并重启音频流...")
        self.stop()
        self._running = True
        while not self.system_queue.empty(): self.system_queue.get()
        while not self.mic_queue.empty(): self.mic_queue.get()

        # ===== 解析麦克风 =====
        actual_mic_id, mic_info, mic_src = _resolve_mic(mic_device_id, mic_device_name)
        if mic_info is None:
            print("[音频] ❌ 找不到任何可用麦克风")
            self.actual_mic_id = None
            self.actual_mic_name = ""
        else:
            self.actual_mic_id = actual_mic_id
            self.actual_mic_name = mic_info['name']
            src_desc = {
                "config_id": "配置 ID",
                "config_name": "配置名称",
                "realtek": "Realtek 内置麦克风（自动回退）",
                "builtin": "智能内置麦克风（自动回退）",
                "default": "系统默认",
            }.get(mic_src, mic_src)
            print(f"  -> 麦克风: [{actual_mic_id}] {mic_info['name']} （来源：{src_desc}）")
            self._start_mic(actual_mic_id)

        # ===== 解析回环 =====
        self.actual_loop_id = None
        self.actual_loop_name = ""
        if sys.platform == "win32":
            try:
                import pyaudiowpatch as pyaudio
                p = pyaudio.PyAudio()
                loop_dev, loop_src = _resolve_loopback(p, loop_device_id, loop_device_name)
                if loop_dev:
                    self.actual_loop_id = loop_dev['index']
                    self.actual_loop_name = loop_dev['name']
                    src_desc = {
                        "config_id": "配置 ID",
                        "config_name": "配置名称",
                        "default_output": "默认输出设备回环（自动跟随系统输出）",
                        "realtek": "Realtek 内置扬声器回环",
                        "any": "任意可用回环",
                    }.get(loop_src, loop_src)
                    print(f"  -> 系统回环: [{loop_dev['index']}] {loop_dev['name']} （来源：{src_desc}）")
                    self._start_system(loop_dev['index'])
                else:
                    print("[音频] ⚠ 未找到任何系统回环设备，面试官声音将无法采集")
                p.terminate()
            except Exception as e:
                print(f"[音频] 回环启动失败: {e}")

        print(f"[音频系统] 音频流重启完毕\n")
        return {
            "mic_id": self.actual_mic_id,
            "mic_name": self.actual_mic_name,
            "mic_src": mic_src,
            "loop_id": self.actual_loop_id,
            "loop_name": self.actual_loop_name,
        }

    def stop(self):
        self._running = False
        for s in self._streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._streams.clear()
        if getattr(self, "_pa_instance", None) is not None:
            try:
                self._pa_instance.terminate()
            except Exception:
                pass
            self._pa_instance = None

    def force_stop(self):
        """强制中止所有音频流，用于 Ctrl+C / 点 X 关闭等场景。
        与 stop() 的区别：用 abort() 而非 stop()，不等待缓冲区排空，避免阻塞。
        """
        self._running = False
        for s in self._streams:
            try:
                s.abort()  # 强制中止，不等待缓冲区
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass
        self._streams.clear()
        if getattr(self, "_pa_instance", None) is not None:
            try:
                self._pa_instance.terminate()
            except Exception:
                pass
            self._pa_instance = None

    def _start_system(self, loop_device_id: int = None):
        # ★ 修复：Windows 下 sys.platform 是 'win32'
        if sys.platform != "win32":
            return
        try:
            import pyaudiowpatch as pyaudio
            p = pyaudio.PyAudio()
            
            target_dev = None
            if loop_device_id is not None:
                target_dev = p.get_device_info_by_index(loop_device_id)
            else:
                wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
                for dev in p.get_loopback_device_info_generator():
                    if default_out["name"] in dev["name"]:
                        target_dev = dev
                        break

            if not target_dev:
                print("[音频] 未找到系统回环设备")
                return

            def callback(in_data, frame_count, time_info, status):
                if not self._running: return (None, pyaudio.paComplete)
                audio = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
                if len(audio) % 2 == 0:
                    audio = audio.reshape(-1, 2).mean(axis=1)
                self._push_system(audio)
                return (None, pyaudio.paContinue)

            # 记录回环原生采样率
            self.system_sr = int(target_dev["defaultSampleRate"])
            
            stream = p.open(
                format=pyaudio.paInt16,
                channels=target_dev["maxInputChannels"],
                rate=self.system_sr,
                input=True,
                input_device_index=target_dev["index"],
                frames_per_buffer=1024,
                stream_callback=callback
            )
            self._pa_instance = p
            self._streams.append(stream)
        except Exception as e:
            print(f"[音频] 系统回环启动失败: {e}")

    def _start_mic(self, mic_device_id: int = None):
        try:
            if mic_device_id is not None:
                try:
                    mic_device_id = int(mic_device_id)
                    dev_info = sd.query_devices(mic_device_id)
                    if dev_info['max_input_channels'] <= 0:
                        raise ValueError("not an input device")
                except Exception:
                    print(f"[音频警告] 麦克风 ID {mic_device_id} 失效，回退到系统默认")
                    mic_device_id = None
                    dev_info = sd.query_devices(kind='input')
            else:
                dev_info = sd.query_devices(kind='input')

            def callback(indata, frames, time_info, status):
                if not self._running: return
                audio = indata[:, 0].astype(np.float32)
                self._push_mic(audio)

            try:
                stream = _open_mic_stream(mic_device_id, 16000, callback)
                stream.start()
                self.mic_sr = 16000
                self._streams.append(stream)
                
            except Exception:
                native_sr = int(dev_info['default_samplerate'])
                stream = _open_mic_stream(mic_device_id, native_sr, callback)
                stream.start()
                self.mic_sr = native_sr
                self._streams.append(stream)
                
        except Exception as e:
            print(f"[音频] 麦克风彻底启动失败: {e}")

    def _push_system(self, audio: np.ndarray):
        # 系统回环重采样
        if self.system_sr != 16000:
            audio = scipy.signal.resample_poly(audio, 16000, self.system_sr)
            audio = audio.astype(np.float32)

        if len(audio):
            self._system_rms = 0.9 * self._system_rms + 0.1 * float(np.sqrt(np.mean(audio ** 2)))

        with self._lock:
            self._system_buffer = np.concatenate([self._system_buffer, audio])
            while len(self._system_buffer) >= self.chunk_size:
                chunk = self._system_buffer[:self.chunk_size]
                self._system_buffer = self._system_buffer[self.chunk_size:]
                self.system_queue.put(chunk)

    def _push_mic(self, audio: np.ndarray):
        if self.mic_sr != 16000:
            audio = scipy.signal.resample_poly(audio, 16000, self.mic_sr)
            audio = audio.astype(np.float32)

        if len(audio):
            self._mic_rms = 0.9 * self._mic_rms + 0.1 * float(np.sqrt(np.mean(audio ** 2)))

        with self._lock:
            self._mic_buffer = np.concatenate([self._mic_buffer, audio])
            while len(self._mic_buffer) >= self.chunk_size:
                chunk = self._mic_buffer[:self.chunk_size]
                self._mic_buffer = self._mic_buffer[self.chunk_size:]
                self.mic_queue.put(chunk)

    def get_levels(self) -> dict:
        """返回系统回环与麦克风的近期音量（RMS），供前端设备自检显示。"""
        return {"system_rms": round(self._system_rms, 5), "mic_rms": round(self._mic_rms, 5)}