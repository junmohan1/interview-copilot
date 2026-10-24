"""声纹识别：判断某段音频是不是用户本人（支持持久化）"""
import numpy as np

from config import DATA_DIR

VP_FILE = DATA_DIR / "voiceprint.npy"

class Voiceprint:
    def __init__(self):
        self._classifier = None
        self._load_failed = False
        self.registered = None
        self.threshold = 0.75
        
        # ★ 启动时自动尝试加载已保存的声纹
        self._load_from_disk()

    def _load_from_disk(self):
        if VP_FILE.exists():
            try:
                self.registered = np.load(VP_FILE)
                print("[声纹] 已从本地加载历史声纹特征")
            except Exception as e:
                print(f"[声纹] 加载历史声纹失败: {e}")

    def save_to_disk(self):
        if self.registered is not None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            np.save(VP_FILE, self.registered)
            print("[声纹] 声纹特征已保存到本地")

    def clear_disk(self):
        """清除已保存的声纹"""
        self.registered = None
        if VP_FILE.exists():
            VP_FILE.unlink()
            print("[声纹] 本地声纹特征已删除")

    def _ensure_loaded(self):
        if self._classifier is not None or self._load_failed:
            return
        try:
            from speechbrain.inference.speaker import EncoderClassifier
            from config import get
            model_name = get(
                "audio.voiceprint_model",
                "speechbrain/spkrec-ecapa-voxceleb"
            )
            self.threshold = get("audio.voiceprint_threshold", 0.75)
            
            # 强制使用 CPU 加载，避免显存冲突
            self._classifier = EncoderClassifier.from_hparams(
                source=model_name,
                savedir="./data/models/spkrec-ecapa",
                run_opts={"device": "cpu"} 
            )
            print("[声纹] 模型加载成功 (CPU)")
        except Exception as e:
            print(f"[声纹] 模型加载失败，将跳过声纹过滤: {e}")
            self._load_failed = True

    def register_from_audio(self, audio: np.ndarray):
        """从 numpy 数组注册声纹，并保存到本地"""
        self._ensure_loaded()
        if self._classifier is None:
            raise RuntimeError("声纹模型未加载")
        if len(audio) < 16000:
            raise ValueError("音频太短，无法提取声纹")
        
        self.registered = self._embed(audio)
        self.save_to_disk()  # ★ 注册成功后立即持久化
        return True

    def verify_from_audio(self, audio: np.ndarray) -> float:
        """从 numpy 数组计算与注册声纹的相似度"""
        self._ensure_loaded()
        if self._classifier is None:
            raise RuntimeError("声纹模型未加载")
        if self.registered is None:
            raise ValueError("尚未注册声纹，请先点“注册声纹”")
        if len(audio) < 16000:
            raise ValueError("音频太短，无法验证")
            
        emb = self._embed(audio)
        import torch
        sim = float(torch.nn.functional.cosine_similarity(
            torch.tensor(self.registered).unsqueeze(0),
            torch.tensor(emb).unsqueeze(0)
        ))
        return sim

    def is_me(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        """未注册或加载失败时，一律放行；音频太短（<0.5s）不做判别，放行"""
        if self.registered is None:
            return True
        if len(audio) < int(16000 * 0.5):
            return True
        self._ensure_loaded()
        if self._classifier is None:
            return True
        try:
            emb = self._embed(audio, sample_rate)
            import torch
            sim = float(torch.nn.functional.cosine_similarity(
                torch.tensor(self.registered).unsqueeze(0),
                torch.tensor(emb).unsqueeze(0)
            ))
            return sim > self.threshold
        except Exception as e:
            print(f"[声纹] 验证出错，默认放行: {e}")
            return True

    def _embed(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        import torch
        import torchaudio
        
        wav = torch.tensor(audio, dtype=torch.float32, device="cpu").unsqueeze(0)
        if sample_rate != 16000:
            wav = torchaudio.functional.resample(wav, sample_rate, 16000)
            
        with torch.no_grad():
            emb = self._classifier.encode_batch(wav)
        return emb.squeeze().cpu().numpy()