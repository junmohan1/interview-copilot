"""配置系统：默认值 + data/config.json 用户覆盖"""
import json
import os
import secrets
from pathlib import Path

# 打包后数据目录放在 exe 同目录
if os.environ.get("IC_BASE_DIR"):
    BASE_DIR = Path(os.environ["IC_BASE_DIR"])
else:
    BASE_DIR = Path(__file__).parent.resolve()

DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma_db"
MODEL_DIR = DATA_DIR / "models"
DB_PATH = DATA_DIR / "history.db"
CONFIG_FILE = DATA_DIR / "config.json"

for d in [DATA_DIR, UPLOAD_DIR, CHROMA_DIR, MODEL_DIR]:
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "deepseek": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "interview_model": "deepseek-flash",
        "prepare_model": "deepseek-chat"
    },
    "thinking": {
        "interview_default": "off",
        "prepare_default": "high",
        "code_default": "high"
    },
    "audio": {
        "asr_model": "base",
        "asr_device": "cuda",
        "asr_compute_type": "int8_float16",
        "voiceprint_threshold": 0.75,
        "mic_device_name": "",
        "loop_device_name": ""
    },
    "server": {"host": "0.0.0.0", "port": 8000, "access_pin": ""},
    "ui": {"boss_hotkey": "ctrl+shift+h"},
    "prompts": {
        "interview_system": (
            "你是我的面试回答助手。只基于【个人素材】用第一人称口语化回答。"
            "结构：结论 → 背景/任务 → 行动 → 结果 → 反思。不超过 200 字。"
            "不知道就说不知道，不要编造。"
        ),
        "code_system": (
            "你是我的编程面试助手。请先理解题目，给出可运行的代码，"
            "再解释思路和时间复杂度。代码要用 Markdown 包裹。"
        ),
        "prepare_system": (
            "你是我的面试准备助手。帮我拆解项目、挖掘量化结果、预测追问。"
            "语气自然，像朋友聊天。"
        )
    }
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        cfg["server"]["access_pin"] = secrets.token_hex(3)
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return cfg
    try:
        user_cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        user_cfg = {}
    return _deep_merge(DEFAULT_CONFIG, user_cfg)


def save_config(cfg: dict):
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


CONFIG = load_config()


def reload_config():
    global CONFIG
    CONFIG = load_config()
    return CONFIG


def get(path: str, default=None):
    """get('deepseek.api_key')"""
    cur = CONFIG
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur