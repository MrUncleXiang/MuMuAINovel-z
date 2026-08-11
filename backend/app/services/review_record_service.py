"""章节审查记录：保存与查询（供生成链、卷检查调用）"""
import json
from datetime import datetime
import uuid

from app.models.chapter_review_record import ChapterReviewRecord


async def save_review_record(db, *, project_id: str, chapter, report, source: str = "auto"):
    """保存一次审查结果（问题列表 JSON）。失败不抛出（记录不阻断主流程）。"""
    try:
        record = ChapterReviewRecord(
            id=str(uuid.uuid4()),
            project_id=project_id,
            chapter_id=str(chapter.id),
            chapter_number=chapter.chapter_number,
            problems=json.dumps(report.problems, ensure_ascii=False) if report.problems else None,
            major=report.major,
            rounds=report.rounds,
            source=source,
            created_at=datetime.utcnow(),
        )
        db.add(record)
        await db.commit()
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(f"保存审查记录失败（不阻断）: {e}")
