"""图片识别 → 代码题通道（透传事件）"""
from typing import AsyncGenerator

class VisionClient:
    def __init__(self, generator):
        self.generator = generator

    async def ask_image_stream(
        self,
        image_bytes: bytes | list,  # ★ 兼容单张（bytes）和多张（list）
        question: str = None,
        thinking_mode: str = "high"
    ) -> AsyncGenerator[dict, None]:
        
        # 如果是单张 bytes，包成列表
        if isinstance(image_bytes, bytes):
            images_list = [image_bytes]
        else:
            images_list = image_bytes

        async for event in self.generator.generate_code_stream(
            question or "请解读图片中的题目并给出解答",
            image_bytes_list=images_list,  # ★ 传列表进去
            thinking_mode=thinking_mode
        ):
            yield event