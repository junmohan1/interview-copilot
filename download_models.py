import os
import urllib.request
from pathlib import Path

# 设置 HuggingFace 镜像加速
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

BASE_DIR = Path(__file__).parent.resolve()
MODEL_DIR = BASE_DIR / "data" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

def download_file(url, target_path):
    if target_path.exists():
        print(f"✓ 已存在，跳过: {target_path.name}")
        return
    print(f"正在下载: {url}")
    try:
        urllib.request.urlretrieve(url, target_path)
        print(f"✓ 下载完成: {target_path.name}")
    except Exception as e:
        print(f"❌ 下载失败: {target_path.name} - {e}")

def main():
    print("=== 开始下载 Interview Copilot 依赖模型 ===")

    # 1. 下载 Silero VAD 模型
    print("\n[1/4] 准备 Silero VAD 模型...")
    vad_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
    download_file(vad_url, MODEL_DIR / "silero_vad.onnx")

    # 2. 下载 HuggingFace 上的模型（向量和声纹）
    print("\n[2/4] 准备 HuggingFace 模型 (向量模型 & 声纹模型)...")
    try:
        from huggingface_hub import snapshot_download
        # 向量模型
        print("正在拉取 BAAI/bge-small-zh-v1.5 ...")
        snapshot_download(repo_id="BAAI/bge-small-zh-v1.5", local_dir=MODEL_DIR / "bge-small-zh-v1.5")
        
        # 声纹模型 (SpeechBrain)
        print("正在拉取 speechbrain/spkrec-ecapa-voxceleb ...")
        snapshot_download(repo_id="speechbrain/spkrec-ecapa-voxceleb", local_dir=MODEL_DIR / "spkrec-ecapa")
    except ImportError:
        print("❌ 缺少 huggingface_hub，请先运行: pip install huggingface_hub")
    except Exception as e:
        print(f"❌ HuggingFace 模型下载失败: {e}")

    # 3. 下载 Sherpa-onnx 中英双语流式模型（如果你用了的话）
    print("\n[3/4] 准备 Sherpa-onnx 模型...")
    sherpa_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2"
    sherpa_tar = MODEL_DIR / "sherpa-bilingual.tar.bz2"
    # 如果没下载过，就下
    if not (MODEL_DIR / "sherpa-bilingual-zh-en").exists():
        download_file(sherpa_url, sherpa_tar)
        if sherpa_tar.exists():
            print("正在解压 Sherpa 模型...")
            import tarfile
            import shutil
            with tarfile.open(sherpa_tar, "r:bz2") as tar:
                tar.extractall(MODEL_DIR)
            # 重命名文件夹
            old_dir = MODEL_DIR / "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
            if old_dir.exists():
                shutil.move(str(old_dir), str(MODEL_DIR / "sherpa-bilingual-zh-en"))
            os.remove(sherpa_tar)
            print("✓ Sherpa 模型解压完成")
    else:
        print("✓ Sherpa 模型已存在，跳过")

    # 4. 下载 Paraformer 模型
    print("\n[4/4] 准备 Paraformer 模型...")
    para_url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-zh-2024-03-09.tar.bz2"
    para_tar = MODEL_DIR / "paraformer.tar.bz2"
    if not (MODEL_DIR / "sherpa-paraformer-zh").exists():
        download_file(para_url, para_tar)
        if para_tar.exists():
            print("正在解压 Paraformer 模型...")
            import tarfile
            import shutil
            with tarfile.open(para_tar, "r:bz2") as tar:
                tar.extractall(MODEL_DIR)
            old_dir = MODEL_DIR / "sherpa-onnx-paraformer-zh-2024-03-09"
            if old_dir.exists():
                shutil.move(str(old_dir), str(MODEL_DIR / "sherpa-paraformer-zh"))
            os.remove(para_tar)
            print("✓ Paraformer 模型解压完成")
    else:
        print("✓ Paraformer 模型已存在，跳过")

    print("\n=== 所有模型准备完毕！可以启动后端了 ===")

if __name__ == "__main__":
    main()