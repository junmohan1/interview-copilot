"""面试前缓存预热脚本
用法：
  python warmup.py            # 预热一次
  python warmup.py --keepalive  # 预热并每 4 分钟保活
"""
import asyncio
import json
import sys
import time
from pathlib import Path

from config import get
from backend.logic.answer_generator import AnswerGenerator
from backend.rag.knowledge_base import KnowledgeBase

PROJECTS_FILE = Path(__file__).parent / "projects.json"


def load_projects():
    if not PROJECTS_FILE.exists():
        return []
    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


async def warmup_one(generator, project):
    system_prompt = generator.build_system_prompt(
        context=project["context"],
        mode="interview"
    )
    print(f"  预热: {project['name']} ...", end=" ", flush=True)
    try:
        async for _ in generator.generate_stream(
            "介绍一下这个项目",
            system_override=system_prompt,
            max_tokens=1,
            thinking_mode="off"
        ):
            pass
        print("✓")
    except Exception as e:
        print(f"✗ ({e})")


async def warmup_all(generator, projects):
    for p in projects:
        await warmup_one(generator, p)


async def keepalive_loop(generator, projects, interval=240):
    while True:
        await asyncio.sleep(interval)
        print(f"\n[{time.strftime('%H:%M:%S')}] 保活刷新...")
        await warmup_all(generator, projects)


async def main():
    if not get("deepseek.api_key"):
        print("错误：未配置 API Key，请先启动后端并在设置里填入")
        return

    kb = KnowledgeBase()
    generator = AnswerGenerator(kb=kb)
    projects = load_projects()

    if not projects:
        print("错误：projects.json 为空，请先编辑每个项目的 context")
        return

    print(f"开始预热 {len(projects)} 个项目...")
    await warmup_all(generator, projects)
    print("\n预热完成。5 分钟内开始面试效果最佳。")

    if "--keepalive" in sys.argv:
        print("保活模式启动，每 4 分钟刷新一次（Ctrl+C 停止）")
        await keepalive_loop(generator, projects)


if __name__ == "__main__":
    asyncio.run(main())