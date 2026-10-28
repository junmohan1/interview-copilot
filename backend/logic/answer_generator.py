"""答案生成：流式输出（含思考过程）"""
import asyncio
from typing import AsyncGenerator, List
from openai import AsyncOpenAI

from config import get
from .strategy import Strategy


class AnswerGenerator:
    def __init__(self, kb=None):
        self.kb = kb

    def _client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=get("deepseek.api_key"),
            base_url=get("deepseek.base_url")
        )

    def _thinking_params(self, mode: str) -> dict:
        if mode == "off":
            return {"thinking": {"type": "disabled"}}
        elif mode == "low":
            return {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}
        else:
            return {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}

    def build_system_prompt(self, context: str, mode: str = "interview") -> str:
        base = get(f"prompts.{mode}_system", "")
        if mode == "interview":
            return f"{base}\n\n【个人素材】\n{context}"
        elif mode == "prepare":
            return f"{base}\n\n【我的资料】\n{context}"
        elif mode == "code":
            return base
        return base

    async def _stream_once(
        self,
        messages: list,
        model: str,
        thinking_mode: str,
        temperature: float,
        max_tokens: int
    ) -> AsyncGenerator[dict, None]:
        """统一流式调用，yield 事件：thinking / content"""
        stream = await self._client().chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=self._thinking_params(thinking_mode)
        )

        thinking_buffer = ""
        content_buffer = ""

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                thinking_buffer += reasoning
                yield {"type": "thinking", "text": thinking_buffer}

            if delta.content:
                content_buffer += delta.content
                yield {"type": "content", "text": content_buffer}

    async def generate_stream(
        self,
        question: str,
        system_override: str = None,
        strategy: Strategy = Strategy.FULL,
        max_tokens: int = 2000,
        thinking_mode: str = None,
        mode: str = "interview",
        kb_results: List[str] = None,
        history_messages: List[dict] = None
    ) -> AsyncGenerator[dict, None]:
        if thinking_mode is None:
            thinking_mode = get(f"thinking.{mode}_default", "off")

        if system_override is not None:
            system_prompt = system_override
        else:
            # 复用调用方已经检索好的结果，避免每个问题检索两次
            if kb_results is None:
                kb_results = await asyncio.to_thread(
                    self.kb.search, question, top_k=get("rag.top_k", 3)
                ) if self.kb else []
            context = "\n---\n".join(kb_results) if kb_results else "无相关素材"
            print(f"\n[RAG 检索结果]\n{context}\n")
            base_prompt = self.build_system_prompt(context, mode=mode)
            
            # ★ 注入策略卡
            from .strategy_manager import strategy_manager
            system_prompt = strategy_manager.build_full_system_prompt(base_prompt, question)

        if strategy == Strategy.HONEST:
            system_prompt += (
                "\n\n【本次回答策略】知识库无相关素材，"
                "请诚实说明没有深入研究，并给出相关思路或学习意愿，"
                "不要编造具体经历或数据。"
            )

        messages = [{"role": "system", "content": system_prompt}]
        if history_messages:
            messages.extend(history_messages)
        messages.append({"role": "user", "content": question})

        async for event in self._stream_once(
            messages,
            model=get("deepseek.interview_model"),
            thinking_mode=thinking_mode,
            temperature=0.6,
            max_tokens=max_tokens
        ):
            yield event

    async def warmup_cache(self) -> str:
        """预热缓存：发一个 dummy 请求，只缓存固定前缀"""
        from .strategy_manager import strategy_manager
        parent_style = strategy_manager.load_parent_and_style()
        
        messages = [
            {"role": "system", "content": parent_style},
            {"role": "user", "content": "预热"}
        ]
        
        try:
            stream = await self._client().chat.completions.create(
                model=get("deepseek.interview_model"),
                messages=messages,
                stream=True,
                max_tokens=1,
                extra_body=self._thinking_params("off")
            )
            async for _ in stream:
                pass
            return "success"
        except Exception as e:
            return f"error: {e}"

    async def generate_discuss_stream(
        self,
        text: str,
        history: List[dict] = None,
        thinking_mode: str = None
    ) -> AsyncGenerator[dict, None]:
        if thinking_mode is None:
            thinking_mode = get("thinking.prepare_default", "high")

        context_docs = await asyncio.to_thread(
            self.kb.search, text, top_k=get("rag.top_k", 3)
        ) if self.kb else []
        context = "\n---\n".join(context_docs) if context_docs else "无相关素材"
        system_prompt = self.build_system_prompt(context, mode="prepare")

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history[-10:])
        messages.append({"role": "user", "content": text})

        async for event in self._stream_once(
            messages,
            model=get("deepseek.prepare_model"),
            thinking_mode=thinking_mode,
            temperature=0.8,
            max_tokens=16000
        ):
            yield event

    async def generate_code_stream(
        self,
        question: str,
        image_bytes_list: list = None,  # ★ 改为接收列表
        thinking_mode: str = None
    ) -> AsyncGenerator[dict, None]:
        if thinking_mode is None:
            thinking_mode = get("thinking.code_default", "high")

        system_prompt = self.build_system_prompt("", mode="code")

        if image_bytes_list and len(image_bytes_list) > 0:
            import base64
            # 构造文本部分
            user_content = [
                {"type": "text", "text": question or "请综合解读这几张图片中的题目，给出代码解答"}
            ]
            # ★ 循环追加所有的图片
            for img_data in image_bytes_list:
                # 电脑端截图传过来的是 str，手机端拍照传过来的是 bytes
                if isinstance(img_data, bytes):
                    b64 = base64.b64encode(img_data).decode()
                else:
                    b64 = img_data  # 已经是 base64 字符串了，直接用
                    
                user_content.append({
                    "type": "image_url", 
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                })
        else:
            user_content = question

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        async for event in self._stream_once(
            messages,
            model=get("deepseek.interview_model"),
            thinking_mode=thinking_mode,
            temperature=0.3,
            max_tokens=4000
        ):
            yield event