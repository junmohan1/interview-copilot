"""基于 Silero VAD + Two-Pass 的工业级识别器（彻底解决切句问题）"""
import os
import glob
import threading
import numpy as np
import sherpa_onnx
import re

from config import MODEL_DIR

class Transcriber:
    def __init__(self):
        # 识别器在多通道间共享，但 VAD 每个通道独立，避免串台；
        # 识别器非线程安全，用锁串行保护。
        self._lock = threading.Lock()

        # ========== 1. 初始化 Silero VAD（系统回环 / 麦克风各一个） ==========
        vad_model_path = str(MODEL_DIR / "silero_vad.onnx")
        if not os.path.exists(vad_model_path):
            raise FileNotFoundError(f"找不到 VAD 模型 {vad_model_path}，请先下载！")

        print("[ASR] 加载 Silero VAD 模型...")
        vad_config = sherpa_onnx.VadModelConfig()
        vad_config.silero_vad.model = vad_model_path
        vad_config.silero_vad.min_silence_duration = 0.5  # 静音 0.5 秒就认为一句话结束
        vad_config.silero_vad.min_speech_duration = 0.15  # 说话 0.15 秒才会被记录
        vad_config.sample_rate = 16000

        # 缓冲区给 60 秒，防止长句溢出
        self.vad_system = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=60)
        self.vad_mic = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=60)

        # ========== 2. 离线 Paraformer（唯一识别引擎，单遍） ==========
        offline_dir = str(MODEL_DIR / "sherpa-paraformer-zh")
        int8_file = os.path.join(offline_dir, "model.int8.onnx")
        model_file = int8_file if os.path.exists(int8_file) else glob.glob(os.path.join(offline_dir, "*.onnx"))[0]

        self.offline_recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=model_file,
            tokens=os.path.join(offline_dir, "tokens.txt"),
            num_threads=2,
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
            provider="cpu",
        )

        self.correction_map = {
            "reduase": "Redis", "redister": "Redis", "redis": "Redis",
            "docker": "Docker", "python": "Python", "kafka": "Kafka",
            "kubernetes": "Kubernetes", "spark": "Spark", "mysql": "MySQL",
            "mongodb": "MongoDB", "java": "Java", "c加加": "C++", "多客": "Docker",
        }
        
        # 幻觉拦截
        self.hallucination_list = ["没有没有意见", "谢谢观看", "请关注", "字幕", "谢谢大家", "没有意见", "拜拜"]
        print("[ASR] Silero VAD + Two-Pass 彻底就绪！")

    def transcribe_chunk(self, audio: np.ndarray, channel: str = "system", speaker_verifier=None) -> str:
        """识别一段音频。

        channel: 'system'（面试官回环）或 'mic'（你的麦克风），各自使用独立的 VAD 状态。
        speaker_verifier: 可选 callable(audio)->bool，用于在“完整一句话”级别过滤说话人。
        """
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0

        vad = self.vad_mic if channel == "mic" else self.vad_system
        result_text = ""

        # 必须按 512 个采样点（32ms）逐帧喂给 VAD，否则底层指针会错乱
        chunk_size = 512
        for i in range(0, len(audio), chunk_size):
            frame = audio[i:i + chunk_size]
            if len(frame) < chunk_size:
                break  # 忽略最后不足 32ms 的碎片

            vad.accept_waveform(frame)

            while not vad.empty():
                segment = vad.front
                # 在 pop 之前，把底层 C++ 数组转成标准的 numpy 数组
                speech_samples = np.array(segment.samples, dtype=np.float32)
                vad.pop()

                # 如果音频太短，直接丢弃
                if len(speech_samples) < 16000 * 0.2:
                    continue

                # 声纹过滤：只在“完整一句话”上判断，避免对 0.1s 碎片做 embedding
                if speaker_verifier is not None and len(speech_samples) >= int(16000 * 0.5):
                    try:
                        if not speaker_verifier(speech_samples):
                            continue
                    except Exception:
                        pass  # 声纹出错时默认放行

                # 离线精修识别（单遍）
                text = self._run_offline(speech_samples)

                # 过滤和修正
                if text and len(text) >= 2:
                    text = self._post_process(text)
                    is_hallucination = any(bad in text for bad in self.hallucination_list)
                    if not is_hallucination:
                        result_text += text
                    else:
                        print(f"[ASR] 拦截到幻觉: {text}")

        return result_text

    def _run_offline(self, audio: np.ndarray) -> str:
        try:
            with self._lock:
                stream = self.offline_recognizer.create_stream()
                stream.accept_waveform(16000, audio)
                self.offline_recognizer.decode_stream(stream)
                return stream.result.text.strip()
        except Exception:
            return ""

    def transcribe_test(self, audio: np.ndarray):
        """整段离线识别，返回 (text, rms)，供桌面“录音测试”使用。"""
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32768.0
        text = self._run_offline(audio)
        text = self._post_process(text) if text else ""
        rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
        return text, rms

    def _post_process(self, text: str) -> str:
        if not text: return text
        for wrong, right in self.correction_map.items():
            text = re.sub(rf'\b{wrong}\b', right, text, flags=re.IGNORECASE)
        return text