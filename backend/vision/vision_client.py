"""图片识别 → 代码题通道（透传事件）"""
from typing import AsyncGenerator


class VisionClient:
    def __init__(self, generator):
        self.generator = generator

    async def ask_image_stream(
        self,
        image_bytes: bytes,
        question: str = None,
        thinking_mode: str = "high"
    ) -> AsyncGenerator[dict, None]:
        async for event in self.generator.generate_code_stream(
            question or "请解读图片中的题目并给出解答",
            image_bytes=image_bytes,
            thinking_mode=thinking_mode
        ):
            yield event