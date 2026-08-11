"""章节正文审查引擎：3 步流水线（错别字 → 表达/细节/AI味 → 剧情/伏笔/人设）

流程：审查（SKILL 注入 + 问题 JSON 提取）→ 原地最小修改（minor）→ 打回重写（major）
"""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.logger import get_logger
from app.services.skill_loader import build_skill_system_prompt

logger = get_logger(__name__)

# 审查步骤定义（每步：审查项 + 使用的 SKILL + 默认输出类型）
REVIEW_STEPS = [
    {
        "key": "proofread",
        "label": "错别字/标点",
        "skill_key": "SKILL_PROOFREAD",
        "types": ["错别字", "标点", "敏感词"],
    },
    {
        "key": "expression",
        "label": "表达/细节/AI味",
        "skill_key": "SKILL_AIDETECT",
        "extra_skill_key": "SKILL_HUMAN",
        "types": ["AI味", "表达细节", "信息缺失"],
    },
    {
        "key": "plot",
        "label": "剧情/伏笔/人设",
        "skill_key": "SKILL_REVIEW",
        "types": ["剧情漏洞", "伏笔问题", "人设不一致", "爽点节奏"],
    },
]


@dataclass
class ReviewReport:
    """单章审查报告"""
    chapter_id: str = ""
    problems: List[Dict[str, Any]] = field(default_factory=list)  # {type, description, suggestion, level, step}
    major: bool = False
    rounds: int = 0
    final_content: str = ""
    step_errors: List[str] = field(default_factory=list)


def _build_review_prompt(content: str, step: Dict) -> str:
    types = "、".join(step["types"])
    return (
        f"【任务】审查以下章节正文的「{step['label']}」问题（{types}等）。\n"
        f"逐句/逐段扫描，列出所有问题。\n"
        f"输出 JSON（不要输出其他文字）：\n"
        f"{{\"problems\": [{{\"type\": \"错别字|AI味|表达细节|信息缺失|剧情漏洞|伏笔问题|人设不一致|爽点节奏\", "
        f"\"description\": \"问题描述（引用原文片段）\", \"suggestion\": \"具体修改建议\", "
        f"\"level\": \"minor|major\"}}]}}\n"
        f"level 说明：minor=表达/字词级，可原地小修；major=情节/逻辑/结构级，需重写该处。\n"
        f"无问题输出 {{\"problems\": []}}。\n\n"
        f"【正文】\n{content}"
    )


def _build_fix_prompt(content: str, problems: List[Dict], major: bool) -> str:
    items = "\n".join(
        f"- [{p['type']}] {p['description']}（建议：{p['suggestion']}）"
        for p in problems
    )
    if major:
        return (
            f"【任务】根据以下审查发现的问题，对正文做修改。这些是结构/情节级问题，"
            f"可以重写涉及的段落/情节，使其合理自洽。\n"
            f"【问题清单】\n{items}\n\n"
            f"【要求】只修改与问题相关的部分，其余内容尽可能保留；保持叙事视角与文风；"
            f"直接输出修改后的完整正文，不要解释。\n\n"
            f"【正文】\n{content}"
        )
    return (
        f"【任务】根据以下审查问题对正文做最小修改：只修改问题涉及的段落/句子，其余内容一字不动。\n"
        f"【问题清单】\n{items}\n\n"
        f"【要求】保持叙事视角与文风；直接输出修改后的完整正文，不要解释。\n\n"
        f"【正文】\n{content}"
    )


def _parse_problems(raw: str) -> List[Dict]:
    """解析审查输出 JSON（容错：取第一个 JSON 块）"""
    raw = raw.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    try:
        data = json.loads(raw)
        problems = data.get("problems", []) if isinstance(data, dict) else []
        return [
            {
                "type": str(p.get("type", "其他")),
                "description": str(p.get("description", "")),
                "suggestion": str(p.get("suggestion", "")),
                "level": "major" if str(p.get("level", "minor")) == "major" else "minor",
            }
            for p in problems
            if isinstance(p, dict) and (p.get("description") or p.get("suggestion"))
        ]
    except Exception:
        return []


async def _ai_text(ai_service, prompt: str, system_prompt: Optional[str] = None) -> str:
    """非流式调用 AI（审查/修改）"""
    result = await ai_service.generate_text(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=0.4,
        auto_mcp=False,
    )
    return str(result.get("content") or "").strip()


async def review_and_fix(
    db,
    *,
    chapter,
    user_id: str,
    ai_service,
    max_rounds: int = 2,
    enabled: bool = True,
) -> ReviewReport:
    """对章节正文执行审查流水线，返回报告（含最终正文）。

    - enabled=False：跳过审查，返回原正文
    - 每轮：3 步审查 → 合并问题
      - 有 major → 打回重写（带 major 清单）→ 下一轮
      - 仅 minor → 原地最小修改 → 返回
    """
    report = ReviewReport(chapter_id=str(chapter.id), final_content=chapter.content or "")
    if not enabled or not (chapter.content or "").strip():
        return report

    content = chapter.content
    for round_no in range(1, max_rounds + 1):
        report.rounds = round_no
        all_problems: List[Dict] = []
        for step in REVIEW_STEPS:
            try:
                system_prompt = build_skill_system_prompt(step["skill_key"])
                raw = await _ai_text(ai_service, _build_review_prompt(content, step), system_prompt)
                problems = _parse_problems(raw)
                for p in problems:
                    p["step"] = step["key"]
                all_problems.extend(problems)
            except Exception as e:
                report.step_errors.append(f"{step['key']}: {e}")
                logger.warning(f"⚠️ 审查步骤 {step['key']} 失败: {e}")

        # 合并问题、去重（同位置/同描述的）
        seen = set()
        deduped = []
        for p in all_problems:
            key = (p["type"], p["description"][:40])
            if key not in seen:
                seen.add(key)
                deduped.append(p)
        all_problems = deduped

        report.problems = all_problems
        major_problems = [p for p in all_problems if p["level"] == "major"]
        minor_problems = [p for p in all_problems if p["level"] == "minor"]

        if not all_problems:
            logger.info(f"✅ 审查通过（第{round_no}轮）：无问题")
            report.final_content = content
            report.major = False
            return report

        # 打回重写（major）
        if major_problems:
            report.major = True
            if round_no >= max_rounds:
                logger.warning(f"⚠️ 第{round_no}轮仍存在 major 问题，停止并保留原正文")
                return report
            logger.info(f"🔄 第{round_no}轮发现 {len(major_problems)} 个 major 问题，打回重写...")
            content = await _ai_text(ai_service, _build_fix_prompt(content, major_problems, major=True))
            continue

        # 原地最小修改（minor）
        logger.info(f"✏️ 第{round_no}轮 {len(minor_problems)} 个 minor 问题，原地修改...")
        try:
            fixed = await _ai_text(ai_service, _build_fix_prompt(content, minor_problems, major=False))
            if fixed.strip():
                content = fixed
        except Exception as e:
            report.step_errors.append(f"fix: {e}")
        report.final_content = content
        report.major = False
        return report

    report.final_content = content
    return report
