"""FastAPI 主入口"""
import os
import sys
import ctypes
import subprocess
from pathlib import Path

# ========== 1. 预加载 Fortran DLL（必须在 numpy/scipy 之前） ==========
# 作用：让 Fortran 库的 Ctrl+C 处理器先注册，Python 的后注册，命令行调试时 Ctrl+C 能干净退出
# 打包后点 X 不依赖这段，但保留无副作用
try:
    import numpy as _np
    _np_path = Path(_np.__file__).parent
    for dll in ("libmmd.dll", "libifcoremd.dll"):
        dll_path = _np_path / "core" / dll
        if dll_path.exists():
            ctypes.CDLL(str(dll_path))
except Exception:
    pass

# ========== 2. 启动前清理占用 8000 端口的旧进程 ==========
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

def _kill_stale_processes(port=8000):
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
                print(f"[自检] 已清理占用 {port} 端口的旧进程 PID={pid}")
            except Exception:
                pass
    except subprocess.CalledProcessError:
        pass
    except Exception as e:
        print(f"[自检] 清理旧进程失败（不影响启动）: {e}")

_kill_stale_processes(8000)


"""FastAPI 主入口"""
import faulthandler
_crash_log = open("crash.log", "a", encoding="utf-8")
faulthandler.enable(file=_crash_log)

import asyncio
import json
import atexit
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from backend.logic.strategy_manager import strategy_manager

from fastapi import FastAPI, WebSocket, UploadFile, File, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from io import BytesIO
import qrcode

from config import (
    CONFIG, reload_config, save_config, get,
    UPLOAD_DIR, BASE_DIR
)
from backend.ws.manager import manager
from backend.audio.capture import AudioCapture
from backend.asr.transcriber import Transcriber
from backend.speaker.voiceprint import Voiceprint
from backend.logic.question_detector import QuestionDetector
from backend.logic.answer_generator import AnswerGenerator
from backend.logic.strategy import decide_strategy, Strategy
from backend.rag.knowledge_base import KnowledgeBase
from backend.vision.vision_client import VisionClient
from backend.storage import history
from backend.logic.audio_utils import read_audio_from_bytes
from backend.audio.capture import AudioCapture, list_audio_devices
from fastapi import Body
from fastapi.responses import PlainTextResponse

# ---------------- 全局组件 ----------------

kb = KnowledgeBase()
transcriber = Transcriber()
voiceprint = Voiceprint()
detector = QuestionDetector()
generator = AnswerGenerator(kb=kb)
vision = VisionClient(generator)
capture = AudioCapture()
active_tasks = {}

# 每次启动都新建一个会话，避免一天多场面试的记录混在一起
CURRENT_SESSION_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
def _persist_actual_devices(actual: dict):
    """如果实际使用的设备和配置不一致，回写配置文件"""
    if not actual:
        return
    mic_changed = (
        actual.get("mic_id") != get("audio.mic_device_id", None)
        or (actual.get("mic_name") or "") != (get("audio.mic_device_name", "") or "")
    )
    loop_changed = (
        actual.get("loop_id") != get("audio.loop_device_id", None)
        or (actual.get("loop_name") or "") != (get("audio.loop_device_name", "") or "")
    )
    if not (mic_changed or loop_changed):
        return
    try:
        cfg = json.loads(json.dumps(CONFIG))
        cfg["audio"]["mic_device_id"] = actual.get("mic_id")
        cfg["audio"]["mic_device_name"] = actual.get("mic_name") or ""
        cfg["audio"]["loop_device_id"] = actual.get("loop_id")
        cfg["audio"]["loop_device_name"] = actual.get("loop_name") or ""
        save_config(cfg)
        reload_config()
        print(f"[配置] 已自动适配并写回：麦克风「{actual.get('mic_name')}」/ 回环「{actual.get('loop_name')}」")
    except Exception as e:
        print(f"[配置] 回写设备配置失败: {e}")

def _atexit_cleanup():
    """进程退出时兜底清理音频流（点 X 正常退出时会触发）"""
    try:
        if 'capture' in globals():
            capture.force_stop()
            print("[退出] 音频流已强制释放")
    except Exception:
        pass

atexit.register(_atexit_cleanup)

def _pin() -> str:
    return get("server.access_pin", "")


def _local_ip() -> str:
    """获取本机局域网 IP，用于生成手机端访问地址"""
    import socket as _s
    try:
        s = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _reload_components():
    """配置变更后重新初始化部分组件"""
    global transcriber, generator, vision
    try:
        transcriber = Transcriber()
    except Exception as e:
        print(f"[reload] ASR 重载失败: {e}")
    generator = AnswerGenerator(kb=kb)
    vision = VisionClient(generator)


def resolve_audio_devices():
    """设备 ID 会随插拔/重启漂移，这里做 ID 优先、名称兜底的解析。"""
    mic_id = get("audio.mic_device_id", None)
    loop_id = get("audio.loop_device_id", None)
    mic_name = get("audio.mic_device_name", None)
    loop_name = get("audio.loop_device_name", None)
    mics, loops = list_audio_devices()

    def pick(target_id, target_name, devices):
        # 1) ID 还存在，且仍指向同名设备 → 直接复用（保留用户选的 host API）
        if target_id is not None:
            for d in devices:
                if d["id"] == target_id:
                    if not target_name or d["name"] == target_name or target_name in d["name"]:
                        return target_id
                    break
        # 2) ID 漂移 / 已指向别的设备 → 按名称重新查找
        if target_name:
            for d in devices:
                if d["name"] == target_name:
                    return d["id"]
            for d in devices:
                if target_name in d["name"]:
                    return d["id"]
        return target_id

    return pick(mic_id, mic_name, mics), pick(loop_id, loop_name, loops)


@asynccontextmanager
async def lifespan(app: FastAPI):
    port = get("server.port", 8000)
    print("\n" + "=" * 50)
    print("  Interview Copilot 已启动")
    print(f"  电脑端: http://localhost:{port}/desktop")
    print(f"  手机端: http://<电脑IP>:{port}/m/{_pin()}")
    print(f"  访问 PIN: {_pin()}")
    print("=" * 50 + "\n")

    def _shutdown_handler(signum, frame):
        print("\n[退出] 收到中断信号，正在清理音频流...")
        capture.force_stop()      # 强制中止，不阻塞
        sys.exit(0)               # 立即退出，不等异步任务

    try:
        mic_id = get("audio.mic_device_id", None)
        loop_id = get("audio.loop_device_id", None)
        mic_name = get("audio.mic_device_name", "") or ""
        loop_name = get("audio.loop_device_name", "") or ""
        actual = capture.start(mic_id, loop_id, mic_name, loop_name)
        _persist_actual_devices(actual)
        asyncio.create_task(system_audio_loop())
        asyncio.create_task(mic_audio_loop())
    except Exception as e:
        print(f"[启动] 音频采集失败: {e}")

    yield
    capture.force_stop()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# ---------------- 音频处理 ----------------

async def system_audio_loop():
    """面试官回环通道：独立协程、独立 VAD，不阻塞麦克风通道。"""
    while True:
        try:
            if not capture.system_queue.empty():
                # 防雪崩：队列积压超过 5 块就丢弃旧音频，只处理最新
                if capture.system_queue.qsize() > 5:
                    print("[系统警告] 音频队列积压，正在丢弃旧音频！")
                    while not capture.system_queue.empty():
                        capture.system_queue.get()

                chunk = capture.system_queue.get()
                text = await asyncio.to_thread(transcriber.transcribe_chunk, chunk, "system")

                if text:
                    print(f"\n[面试官提问] {text}\n")
                    await manager.send_to_desktop({"type": "my_speech", "text": f"[面试官] {text}"})

                    if detector.is_question(text):
                        # 限制最大并发数，防止面试官连续追问把 API 刷爆
                        if len(active_tasks) >= 3:
                            oldest_id = next(iter(active_tasks))
                            active_tasks[oldest_id].cancel()
                            del active_tasks[oldest_id]
                            await manager.broadcast({
                                "type": "answer_cancelled",
                                "task_id": oldest_id,
                                "reason": "并发过多，已取消最早的等待项"
                            })

                        import uuid
                        task_id = str(uuid.uuid4())[:8]
                        task = asyncio.create_task(handle_interviewer_question(text, task_id))
                        active_tasks[task_id] = task

                        # 任务完成（无论成功还是报错）后，自动清理内存
                        def _clean_task(t, tid=task_id):
                            if tid in active_tasks:
                                del active_tasks[tid]
                        task.add_done_callback(_clean_task)

            await asyncio.sleep(0.01)
        except Exception as e:
            print(f"[系统音频循环] 错误: {e}")
            await asyncio.sleep(1)


async def mic_audio_loop():
    """麦克风通道：独立协程，声纹在“完整一句话”级别过滤。"""
    while True:
        try:
            if not capture.mic_queue.empty():
                if capture.mic_queue.qsize() > 5:
                    while capture.mic_queue.qsize() > 1:
                        capture.mic_queue.get()

                chunk = capture.mic_queue.get()
                text = await asyncio.to_thread(
                    transcriber.transcribe_chunk, chunk, "mic", voiceprint.is_me
                )
                if text:
                    await manager.send_to_desktop({"type": "my_speech", "text": f"[我] {text}"})
                    # 异步保存到数据库
                    asyncio.create_task(asyncio.to_thread(
                        history.save_message, CURRENT_SESSION_ID, "me", text, None, "interview"
                    ))

            await asyncio.sleep(0.01)
        except Exception as e:
            print(f"[麦克风音频循环] 错误: {e}")
            await asyncio.sleep(1)



async def handle_interviewer_question(question: str, task_id: str):
    # 异步存库
    asyncio.create_task(asyncio.to_thread(
        history.save_message, CURRENT_SESSION_ID, "interviewer", question, None, "interview"
    ))

    try:
        kb_results = await asyncio.to_thread(kb.search, question, top_k=get("rag.top_k", 3))
        strategy = decide_strategy(question, kb_results, detector)

        # 通知前端：新问题来了，请新建气泡
        await manager.broadcast({
            "type": "new_question", 
            "task_id": task_id,
            "text": question, 
            "strategy": strategy.value
        })

        content_buffer = ""
        async for event in generator.generate_stream(question, strategy=strategy, kb_results=kb_results):
            if event["type"] == "thinking":
                await manager.broadcast({"type": "thinking_chunk", "task_id": task_id, "text": event["text"]})
            elif event["type"] == "content":
                content_buffer = event["text"]
                await manager.broadcast({"type": "answer_chunk", "task_id": task_id, "text": content_buffer})
                
        await manager.broadcast({"type": "answer_done", "task_id": task_id})
        
        asyncio.create_task(asyncio.to_thread(
            history.save_message, CURRENT_SESSION_ID, "assistant", content_buffer, None, "interview"
        ))
        
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await manager.broadcast({"type": "answer_error", "task_id": task_id, "message": str(e)})

# ---------------- WebSocket ----------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, pin: str = "", role: str = "mobile"):
    if pin != _pin():
        await ws.close(code=4003)
        return

    await manager.connect(ws, role)
    print(f"[WS] {role} 已连接")

    try:
        while True:
            msg = await ws.receive_json()
            await handle_client_message(msg, role, ws)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] 异常: {e}")
    finally:
        manager.disconnect(ws, role)
        print(f"[WS] {role} 已断开")


async def handle_client_message(msg: dict, role: str, ws: WebSocket):
    global CURRENT_SESSION_ID

    msg_type = msg.get("type")

    if msg_type == "ping":
        return

    # 手机端请求当前会话历史（连上 WS 后首次拉取）
    if msg_type == "load_current_history" and role == "mobile":
        messages = history.load_session(CURRENT_SESSION_ID)
        await ws.send_json({
            "type": "history_loaded",
            "messages": messages
        })
        return

    # 手机端手动输入
    if msg_type == "manual_question" and role == "mobile":
        question = msg["text"].strip()
        if not question:
            return
        thinking_mode = msg.get("thinking_mode", "off")
        asyncio.create_task(asyncio.to_thread(
            history.save_message, CURRENT_SESSION_ID, "interviewer", f"[手动] {question}", None, "interview"
        ))
        await manager.send_to_desktop({"type": "manual_sync", "text": question})
        
        # ★ 补上 task_id 的生成和并发任务创建
        import uuid
        task_id = str(uuid.uuid4())[:8]
        asyncio.create_task(handle_interviewer_question(question, task_id))

    # 手机端切换思考模式
    elif msg_type == "set_thinking":
        mode = msg.get("mode", "off")
        scope = msg.get("scope", "code")
        cfg = json.loads(json.dumps(CONFIG))
        cfg["thinking"][f"{scope}_default"] = mode
        save_config(cfg)
        reload_config()
        await manager.broadcast({
            "type": "thinking_changed",
            "scope": scope,
            "mode": mode
        })

    # 电脑端讨论
    elif msg_type == "discuss" and role == "desktop":
        text = msg["text"]
        thinking_mode = msg.get("thinking_mode")
        history_msgs = msg.get("history", [])
        asyncio.create_task(asyncio.to_thread(
            history.save_message, CURRENT_SESSION_ID, "user", text, None, "prepare"
        ))

        thinking_buf = ""
        content_buf = ""
        
        # ★ 用于拦截策略卡更新的正则
        import re
        update_pattern = re.compile(r'<strategy_update file="([^"]+)">\n?(.*?)\n?</strategy_update>', re.DOTALL)
        strategy_saved = False  # 防止在同一个回复里重复保存

        try:
            async for event in generator.generate_discuss_stream(
                text, history_msgs, thinking_mode=thinking_mode
            ):
                if event["type"] == "thinking":
                    thinking_buf = event["text"]
                    await ws.send_json({
                        "type": "discuss_thinking_chunk",
                        "text": thinking_buf
                    })
                elif event["type"] == "content":
                    content_buf = event["text"]
                    
                    # ★ 实时检测是否生成了完整的 strategy_update 标签
                    match = update_pattern.search(content_buf)
                    if match and not strategy_saved:
                        file_path = match.group(1).strip()
                        card_content = match.group(2).strip()
                        try:
                            from backend.logic.strategy_manager import strategy_manager
                            strategy_manager.save_card(file_path, card_content)
                            strategy_saved = True
                            
                            # 通知前端刷新树状图
                            await ws.send_json({"type": "strategy_updated"})
                        except Exception as e:
                            print(f"保存策略卡失败: {e}")

                    # 如果已经保存了，就不把 XML 标签发给前端；否则原样发送
                    if strategy_saved and match:
                        # 替换掉 XML 标签，变成一句友好的提示
                        display_text = content_buf.replace(match.group(0), "\n\n*(🤖 已自动将以上内容保存至策略卡)*")
                        await ws.send_json({"type": "discuss_chunk", "text": display_text})
                    else:
                        # 流式输出过程中，如果标签还没闭合，先原样输出，这样用户能看到 AI 在写卡片
                        await ws.send_json({"type": "discuss_chunk", "text": content_buf})
                        
            await ws.send_json({"type": "discuss_done"})
            
            # 存入历史记录时，如果包含策略更新标签，最好存清理后的文本
            final_history_text = content_buf
            if strategy_saved and match:
                final_history_text = content_buf.replace(match.group(0), "\n\n*(已保存至策略卡)*")
            asyncio.create_task(asyncio.to_thread(
                history.save_message, CURRENT_SESSION_ID, "assistant", final_history_text, None, "prepare"
            ))
            
        except Exception as e:
            await ws.send_json({"type": "discuss_error", "message": str(e)})

    elif msg_type == "list_history" and role == "desktop":
        await ws.send_json({
            "type": "history_list",
            "sessions": history.list_sessions()
        })

    elif msg_type == "load_history" and role == "desktop":
        await ws.send_json({
            "type": "history_loaded",
            "messages": history.load_session(msg["session_id"])
        })

    elif msg_type == "new_session" and role == "desktop":
        CURRENT_SESSION_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
        await ws.send_json({"type": "history_loaded", "messages": []})
        # 通知所有手机端清空面板，准备接收新会话
        await manager.send_to_mobile({"type": "session_reset"})

    elif msg_type == "pregenerate" and role == "desktop":
        await ws.send_json({"type": "pregenerate_started"})
        result = await generator.warmup_cache()
        if result == "success":
            await ws.send_json({"type": "pregenerate_done", "status": "success"})
        else:
            await ws.send_json({"type": "pregenerate_done", "status": "error", "message": result})
            
    elif msg_type == "simulate_interview" and role == "desktop":
        text = msg.get("text", "").strip()
        if text:
            await manager.send_to_desktop({"type": "my_speech", "text": "[模拟输入] " + text})
            import uuid
            task_id = str(uuid.uuid4())[:8]
            asyncio.create_task(handle_interviewer_question(text, task_id))

# ---------------- HTTP 接口 ----------------

@app.get("/api/config")
async def api_get_config(mask: bool = True):
    cfg = json.loads(json.dumps(CONFIG))
    if mask and cfg["deepseek"]["api_key"]:
        key = cfg["deepseek"]["api_key"]
        cfg["deepseek"]["api_key"] = (
            key[:6] + "***" + key[-4:] if len(key) > 12 else "***"
        )
    return cfg


@app.post("/api/config")
async def api_set_config(payload: dict = Body(...)):
    current = json.loads(json.dumps(CONFIG))

    def merge(cur, new):
        for k, v in new.items():
            if k == "api_key" and v in ("***", "") and cur.get(k):
                continue
            if isinstance(v, dict) and isinstance(cur.get(k), dict):
                merge(cur[k], v)
            else:
                cur[k] = v

    merge(current, payload)
    save_config(current)
    reload_config()
    _reload_components()
    return {"status": "ok"}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    path = Path(UPLOAD_DIR) / file.filename
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)
    try:
        n = kb.load_file(str(path))
        await manager.send_to_desktop({
            "type": "kb_updated",
            "file": file.filename,
            "chunks": n
        })
        return {"status": "ok", "file": file.filename, "chunks": n}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/vision/upload")
async def vision_upload(
    file: UploadFile = File(...),
    thinking_mode: str = "high",
    question: str = ""
):
    image_bytes = await file.read()
    
    # ★ 生成 task_id
    import uuid
    task_id = str(uuid.uuid4())[:8]
    
    # 注意：这里要改成 broadcast 并且带上 task_id
    await manager.broadcast({
        "type": "new_question",
        "task_id": task_id,
        "text": "[图片题] " + (question or "识别中…")
    })

    thinking_buf = ""
    content_buf = ""
    try:
        async for event in vision.ask_image_stream(
            image_bytes, question=question, thinking_mode=thinking_mode
        ):
            if event["type"] == "thinking":
                thinking_buf = event["text"]
                await manager.broadcast({"type": "thinking_chunk", "task_id": task_id, "text": thinking_buf})
            elif event["type"] == "content":
                content_buf = event["text"]
                await manager.broadcast({"type": "answer_chunk", "task_id": task_id, "text": content_buf})
        await manager.broadcast({"type": "answer_done", "task_id": task_id})
        asyncio.create_task(asyncio.to_thread(
            history.save_message, CURRENT_SESSION_ID, "interviewer", "[图片题]", None, "interview"
        ))
        asyncio.create_task(asyncio.to_thread(
            history.save_message, CURRENT_SESSION_ID, "assistant", content_buf, None, "interview"
        ))
        return {"status": "ok"}
    except Exception as e:
        await manager.broadcast({"type": "answer_error", "task_id": task_id, "message": str(e)})
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/api/sources")
async def api_sources():
    return {"sources": kb.list_sources()}

@app.delete("/api/sources/{name}")
async def api_delete_source(name: str):
    try:
        n = kb.delete_source(name)
        # 删除磁盘上的上传文件
        from pathlib import Path
        file_path = Path(UPLOAD_DIR) / name
        if file_path.exists():
            file_path.unlink()
        await manager.send_to_desktop({"type": "kb_updated"})
        return {"status": "ok", "deleted_chunks": n}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
    
#声纹测试接口    
@app.get("/api/pin")
async def api_pin():
    return {"pin": _pin()}


@app.get("/api/mobile_url")
async def api_mobile_url():
    """返回手机端完整访问地址"""
    port = get("server.port", 8000)
    return {"url": f"http://{_local_ip()}:{port}/m/{_pin()}"}


@app.get("/api/qrcode")
async def api_qrcode():
    """本地生成二维码 PNG，不依赖任何第三方服务"""
    port = get("server.port", 8000)
    url = f"http://{_local_ip()}:{port}/m/{_pin()}"
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/api/audio/devices")
async def api_audio_devices():
    mics, loops = list_audio_devices()
    return {"mics": mics, "loops": loops}


@app.post("/api/audio/restart")
async def api_audio_restart():
    """当配置更改时，重启音频流，并回写实际使用的设备"""
    mic_id = get("audio.mic_device_id", None)
    loop_id = get("audio.loop_device_id", None)
    mic_name = get("audio.mic_device_name", "") or ""
    loop_name = get("audio.loop_device_name", "") or ""
    try:
        actual = capture.start(mic_id, loop_id, mic_name, loop_name)
        _persist_actual_devices(actual)
        await manager.send_to_desktop({
            "type": "audio_devices_adapted",
            "mic": actual.get("mic_name") or "",
            "loop": actual.get("loop_name") or "",
        })
        return {"status": "ok", "actual": actual}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/api/audio/levels")
async def api_audio_levels():
    """返回回环与麦克风的近期音量，供前端设备自检"""
    return capture.get_levels()

@app.delete("/api/history/{session_id}")
async def api_delete_history(session_id: str):
    try:
        history.delete_session(session_id)
        await manager.send_to_desktop({
            "type": "history_list",
            "sessions": history.list_sessions()
        })
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.post("/api/test_asr")
async def api_test_asr(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    audio = read_audio_from_bytes(audio_bytes)
    if len(audio) == 0:
        return JSONResponse({"status": "error", "message": "音频解析失败"}, status_code=400)
    
    # 在后台线程跑，避免阻塞主循环
    text, rms = await asyncio.to_thread(transcriber.transcribe_test, audio)
    return {"status": "ok", "text": text, "rms": round(rms, 5), "duration": round(len(audio)/16000, 1)}


@app.post("/api/voiceprint/register")
async def api_vp_register(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    audio = read_audio_from_bytes(audio_bytes)
    try:
        await asyncio.to_thread(voiceprint.register_from_audio, audio)
        return {"status": "ok", "message": "声纹注册成功"}
    except Exception as e:
        import traceback
        traceback.print_exc()  # ★ 打印完整报错栈到终端
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

@app.post("/api/voiceprint/verify")
async def api_vp_verify(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    audio = read_audio_from_bytes(audio_bytes)
    try:
        sim = await asyncio.to_thread(voiceprint.verify_from_audio, audio)
        return {"status": "ok", "similarity": round(sim, 3)}
    except Exception as e:
        import traceback
        traceback.print_exc()  # ★ 打印完整报错栈到终端
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

@app.post("/api/voiceprint/clear")
async def api_vp_clear():
    try:
        voiceprint.clear_disk()
        return {"status": "ok", "message": "声纹已清除"}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

#-------------------- 策略 --------------
@app.get("/api/strategy")
async def api_get_strategy():
    return strategy_manager.get_all_cards()

@app.post("/api/strategy/save")
async def api_save_strategy(payload: dict = Body(...)):
    try:
        file_rel_path = payload.get("file")
        content = payload.get("content")
        strategy_manager.save_card(file_rel_path, content)
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
    
# -------------会话保存txt------------
@app.get("/api/history/{session_id}/export")
async def api_export_history(session_id: str):
    messages = history.load_session(session_id)
    if not messages:
        return JSONResponse({"status": "error", "message": "会话为空"}, status_code=404)

    lines = []
    lines.append(f"=== 面试复盘记录 (会话 ID: {session_id}) ===\n")
    
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        
        if role == "interviewer":
            lines.append(f"【面试官提问】\n{content}\n")
        elif role == "assistant":
            lines.append(f"【AI 建议回答】\n{content}\n")
        elif role == "me":
            lines.append(f"【我的真实回答】\n{content}\n")
            
        lines.append("-" * 40 + "\n")
        
    text_content = "\n".join(lines)
    
    # 返回纯文本供浏览器下载
    return PlainTextResponse(
        content=text_content, 
        headers={
            "Content-Disposition": f"attachment; filename=interview_{session_id}.txt"
        }
    )
    
# ---------------- 静态页面 ----------------

import os
RESOURCE_DIR = Path(os.environ.get("IC_RESOURCE_DIR", str(BASE_DIR)))
WEB_DIR = RESOURCE_DIR / "web"


@app.get("/desktop")
async def desktop_page():
    return FileResponse(WEB_DIR / "desktop" / "index.html")


@app.get("/m/{pin}")
async def mobile_page(pin: str):
    if pin != _pin():
        return JSONResponse({"error": "invalid pin"}, status_code=403)
    return FileResponse(WEB_DIR / "mobile" / "index.html")


app.mount(
    "/desktop-assets",
    StaticFiles(directory=str(WEB_DIR / "desktop")),
    name="desktop-assets"
)