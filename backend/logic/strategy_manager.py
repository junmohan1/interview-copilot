import re
from pathlib import Path

from config import DATA_DIR

STRATEGY_DIR = DATA_DIR / "strategy"


class StrategyManager:
    def __init__(self):
        self._ensure_files()

    def _ensure_files(self):
        """自动创建默认策略卡文件"""
        (STRATEGY_DIR / "projects").mkdir(parents=True, exist_ok=True)
        (STRATEGY_DIR / "topics").mkdir(parents=True, exist_ok=True)

        parent = STRATEGY_DIR / "parent.md"
        if not parent.exists():
            parent.write_text(
                "# 父策略（最高优先级）\n"
                "- 绝对不能编造没做过的经历。\n"
                "- 遇到不会的直接承认，展现学习意愿。\n"
                "- 不要透露你是 AI 或辅助工具。\n",
                encoding="utf-8"
            )

        style = STRATEGY_DIR / "style.md"
        if not style.exists():
            style.write_text(
                "# 回答风格\n"
                "- 先给结论，再给背景，最后说量化结果。\n"
                "- 用第一人称口语化表达，不要像写报告。\n"
                "- 每次回答不超过 200 字。\n",
                encoding="utf-8"
            )

        # 给一个示例项目子卡
        example = STRATEGY_DIR / "projects" / "example.md"
        if not example.exists():
            example.write_text(
                "# 项目：电商重构\n"
                "## 匹配关键词\n"
                "电商, 重构, 订单, QPS\n\n"
                "## 强调\n"
                "- 强调是我主动发起的重构。\n\n"
                "## 避讳\n"
                "- 别提中间换过三次方案，显得没主见。\n",
                encoding="utf-8"
            )

    def load_parent_and_style(self) -> str:
        """加载父卡和风格卡（固定前缀）"""
        parts = []
        
        p = STRATEGY_DIR / "parent.md"
        if p.exists():
            parts.append("【父策略（最高优先级，必须遵守）】\n" + p.read_text(encoding="utf-8"))

        s = STRATEGY_DIR / "style.md"
        if s.exists():
            parts.append("【回答风格】\n" + s.read_text(encoding="utf-8"))

        return "\n\n".join(parts)

    def get_dynamic_cards(self, question: str) -> str:
        """根据问题匹配子卡"""
        matched_cards = []
        question_lower = question.lower()  # 统一转小写，忽略大小写差异

        # 遍历 projects 和 topics 目录
        for category in ["projects", "topics"]:
            folder = STRATEGY_DIR / category
            if not folder.exists():
                continue

            for file in folder.glob("*.md"):
                content = file.read_text(encoding="utf-8")
                
                # ★ 修复：兼容 Windows 的 \r\n 换行符
                keywords_match = re.search(r"##\s*匹配关键词\s*\n(.*?)(?:\n\n|\Z)", content, re.DOTALL)
                if keywords_match:
                    keywords = [k.strip().lower() for k in keywords_match.group(1).split(",")]
                    # 如果问题中包含任何一个关键词，则命中
                    if any(kw and kw in question_lower for kw in keywords):
                        matched_cards.append(content)

        if not matched_cards:
            return ""

        return "【当前场景附加策略（若与父策略冲突，无条件服从父策略）】\n" + "\n\n".join(matched_cards)

    def build_full_system_prompt(self, base_prompt: str, question: str) -> str:
        """构建完整的 System Prompt"""
        parent_style = self.load_parent_and_style()
        dynamic = self.get_dynamic_cards(question)

        prompt = f"{parent_style}\n\n"
        if dynamic:
            prompt += f"{dynamic}\n\n"
        
        prompt += f"【基础任务指令】\n{base_prompt}"
        return prompt
    
    def get_all_cards(self) -> dict:
        """获取树状策略卡数据，供前端展示"""
        result = {
            "parent": "",
            "style": "",
            "projects": {},
            "topics": {}
        }
        
        p = STRATEGY_DIR / "parent.md"
        if p.exists(): result["parent"] = p.read_text(encoding="utf-8")
        
        s = STRATEGY_DIR / "style.md"
        if s.exists(): result["style"] = s.read_text(encoding="utf-8")
        
        for category in ["projects", "topics"]:
            folder = STRATEGY_DIR / category
            if folder.exists():
                for file in folder.glob("*.md"):
                    result[category][file.stem] = file.read_text(encoding="utf-8")
                    
        return result

    def save_card(self, file_rel_path: str, content: str):
        """保存卡片内容，file_rel_path 例如 'projects/ecommerce.md' 或 'parent.md'"""
        # 防止路径穿越攻击
        target_path = (STRATEGY_DIR / file_rel_path).resolve()
        if not str(target_path).startswith(str(STRATEGY_DIR.resolve())):
            raise ValueError("非法的文件路径")
            
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return True    


# 全局实例
strategy_manager = StrategyManager()