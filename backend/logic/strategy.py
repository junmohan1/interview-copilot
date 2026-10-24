"""回答策略：正常答 / 诚实承认 / 反问澄清"""
from enum import Enum


class Strategy(str, Enum):
    FULL = "full"
    HONEST = "honest"
    PARTIAL = "partial"
    CLARIFY = "clarify"


HONEST_TEMPLATES = {
    "tech_unknown": (
        "这个技术我了解过概念，是用{concept}来实现{goal}，但底层细节我没有深入实践过。"
        "我之前主要用的是{my_skill}，如果工作需要，我可以快速上手这块。"
    ),
    "experience_unknown": (
        "这个场景我没有直接经历过，但我遇到过类似的{similar_case}，"
        "当时的处理方式是{my_approach}。如果遇到您说的这种情况，"
        "我会从{my_thinking}角度去分析。"
    ),
    "trap_question": (
        "这个问题我确实没有深入研究过，我不想不懂装懂。"
        "不过我对{related_topic}有一定了解，如果和这个问题相关，我可以分享一下我的理解。"
    ),
    "too_broad": (
        "这个问题范围比较大，我想先确认一下您更关注的是{aspect_a}还是{aspect_b}？"
        "这样我可以更有针对性地回答。"
    )
}


def decide_strategy(question: str, kb_results: list, detector) -> Strategy:
    if kb_results and _max_sim(kb_results) > 0.7:
        return Strategy.FULL
    if kb_results and _max_sim(kb_results) > 0.4:
        return Strategy.PARTIAL
    if detector.is_trap_or_out_of_scope(question, kb_results):
        return Strategy.HONEST
    if len(question) < 8 and "?" in question:
        return Strategy.CLARIFY
    return Strategy.FULL


def _max_sim(results: list) -> float:
    if not results:
        return 0.0
    return min(0.9, 0.5 + 0.1 * len(results))