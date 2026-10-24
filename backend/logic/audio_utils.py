import io
import av
import numpy as np


def read_audio_from_bytes(audio_bytes: bytes, target_sr: int = 16000) -> np.ndarray:
    """将上传的 webm/wav 字节流转换为 16k float32 numpy 数组"""
    try:
        container = av.open(io.BytesIO(audio_bytes))
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format='flt', layout='mono', rate=target_sr)

        frames = []
        for frame in container.decode(stream):
            for resampled_frame in resampler.resample(frame):
                frames.append(resampled_frame.to_ndarray())

        if not frames:
            return np.zeros(0, dtype=np.float32)

        # av 返回的 flt 格式是 [channels, samples]，mono 时直接 flatten
        audio = np.concatenate(frames, axis=-1).flatten()
        return audio.astype(np.float32)
    except Exception as e:
        print(f"[audio_utils] 解析音频失败: {e}")
        return np.zeros(0, dtype=np.float32)