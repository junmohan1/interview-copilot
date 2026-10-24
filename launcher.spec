# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# 收集依赖
webview_datas, webview_binaries, webview_hiddenimports = collect_all("webview")
sherpa_datas, sherpa_binaries, sherpa_hiddenimports = collect_all("sherpa_onnx")
chroma_datas, chroma_binaries, chroma_hiddenimports = collect_all("chromadb")
sklearn_datas, sklearn_binaries, sklearn_hiddenimports = collect_all("sklearn")
# 👇 新增这一行：完整收集 speechbrain
speechbrain_datas, speechbrain_binaries, speechbrain_hiddenimports = collect_all("speechbrain")

a = Analysis(
    ["launcher.py"],
    pathex=[],
    # 👇 把 speechbrain 的文件和库加进去
    binaries=webview_binaries + sherpa_binaries + chroma_binaries + sklearn_binaries + speechbrain_binaries,
    datas=[
        ("web", "web"),
        ("backend", "backend"),
        ("config.py", "."),
        ("projects.json", "."),
    ] + webview_datas + sherpa_datas + chroma_datas + sklearn_datas + speechbrain_datas,
    # 👇 把 speechbrain 的隐藏依赖加进去
    hiddenimports=webview_hiddenimports + sherpa_hiddenimports + chroma_hiddenimports + sklearn_hiddenimports + speechbrain_hiddenimports + [
        "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan", "uvicorn.lifespan.on",
        "backend.main", "backend.audio.capture", "backend.asr.transcriber",
        "backend.speaker.voiceprint", "backend.logic.answer_generator",
        "backend.logic.question_detector", "backend.logic.strategy",
        "backend.logic.strategy_manager", "backend.logic.audio_utils",
        "backend.rag.knowledge_base", "backend.rag.file_parser",
        "backend.vision.vision_client", "backend.storage.history",
        "backend.ws.manager", "backend.hotkey",
        "pynput.keyboard", "pynput._util.win32",
        "webview.platforms.edgechromium", "webview.platforms.winforms",
        "pyaudiowpatch",
        "torch.distributed",
        "torch.utils.data",
        "sklearn",
        "sklearn.utils._typedefs",
        "sklearn.neighbors._partition_nodes",
        "scipy._lib.array_api_compat.numpy.fft"
    ],
    hookspath=[],
    runtime_hooks=[],
    # ★ 绝对不要在这里排除 torch 的任何东西，包括 torch.onnx
    excludes=[
        "matplotlib", "pandas", "IPython", "jupyter", "tkinter.test", "pytest", "nose",
        "tensorboard", "tensorflow", "keras", 
        "boto3", "botocore", "s3transfer",
        "sqlalchemy", "psycopg2", "pymysql", "docker", "kubernetes",
        "cv2", "opencv-python", "numba", "llvmlite", "nvidia"
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InterviewCopilot",
    debug=False,
    bootloader_ignore_signals=True,
    strip=False,
    upx=True,
    console=False,  # 保持 True 看日志
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version="version.txt" if __import__("os").path.exists("version.txt") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="InterviewCopilot",
)