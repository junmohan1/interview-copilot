"""历史记录：SQLite 存储"""
import json
import sqlite3
import threading
from datetime import datetime
from typing import List, Dict

from config import DB_PATH
import threading

# 全局线程锁
db_lock = threading.Lock()

def _conn():
    c = sqlite3.connect(str(DB_PATH))
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT,
            messages TEXT
        )
    """)
    c.commit()
    return c


def save_message(session_id: str, role: str, content: str, thinking: str = None, scene: str = "interview"):
    # ★ 核心修复：把所有的数据库操作全部塞进锁里面！
    with db_lock:
        c = _conn()
        try:
            row = c.execute("SELECT messages FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row:
                messages = json.loads(row[0])
            else:
                messages = []
                c.execute(
                    "INSERT INTO sessions (id, title, created_at, messages) VALUES (?, ?, ?, ?)",
                    (session_id, content[:30], datetime.now().isoformat(), "[]")
                )
            
            messages.append({
                "role": role,
                "content": content,
                "thinking": thinking or "",
                "scene": scene,  # ★ 必须加这个，区分 prepare 和 interview
                "time": datetime.now().isoformat()
            })
            
            c.execute("UPDATE sessions SET messages=? WHERE id=?", 
                      (json.dumps(messages, ensure_ascii=False), session_id))
            c.commit()
        except Exception as e:
            print(f"[DB] 保存消息失败: {e}")
        finally:
            c.close()  # 确保无论报错与否，连接必须关闭


def list_sessions() -> List[Dict]:
    c = _conn()
    rows = c.execute(
        "SELECT id, title, created_at FROM sessions ORDER BY created_at DESC LIMIT 100"
    ).fetchall()
    c.close()
    return [{"id": r[0], "title": r[1], "date": r[2][:10]} for r in rows]


def load_session(session_id: str) -> List[Dict]:
    c = _conn()
    row = c.execute("SELECT messages FROM sessions WHERE id=?", (session_id,)).fetchone()
    c.close()
    return json.loads(row[0]) if row else []


def delete_session(session_id: str):
    c = _conn()
    c.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    c.commit()
    c.close()