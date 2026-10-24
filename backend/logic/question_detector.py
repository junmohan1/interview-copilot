"""问题检测：规则 + LLM 兜底"""
import re
from typing import Optional


QUESTION_KEYWORDS = [
    "请", "能不能", "可以", "介绍一下", "说说", "讲讲",
    "为什么", "如何", "怎么", "什么", "哪些", "有没有",
    "你觉得", "你当时", "举个例子", "谈谈", "解释",
    "描述", "如果", "是否", "对吗", "是吗"
]

TIME_KEYWORDS = ["最新", "最近", "2025", "2026", "新版本", "发布"]


class QuestionDetector:
    def __init__(self, llm_client=None):
        self.llm = llm_client

    def is_question(self, text: str) -> bool:
        if not text or len(text.strip()) < 4:
            return False
        if "?" in text or "？" in text:
            return True
        for kw in QUESTION_KEYWORDS:
            if kw in text:
                return True
        if self.llm:
            return self._llm_check(text)
        return False

    def is_trap_or_out_of_scope(self, text: str, kb_results: list) -> bool:
        """判断是否是陷阱题或超纲题：知识库几乎没素材，且问题偏"底层/实现原理/最新" """
        if kb_results:
            return False
        trap_signals = ["底层实现", "源码", "原理", "内部机制", "最新", "未来趋势"]
        return any(s in text for s in trap_signals)

    def needs_web_search(self, text: str, kb_results: list) -> bool:
        """是否需要联网搜索兜底"""
        if kb_results:
            return False
        return any(kw in text for kw in TIME_KEYWORDS)

    def _llm_check(self, text: str) -> bool:
        prompt = f'判断下面这句话是否在向对方提问，只回答"是"或"否"。\n句子：{text}'
        try:
            resp = self.llm.chat(prompt, max_tokens=4)
            return "是" in resp
        except Exception:
            return False