import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

import app.database  # noqa: F401 - initialize the model registry as production does

from app.services.chapter_lifecycle_service import (
    analysis_task_matches_content,
    chapter_content_hash,
    check_previous_analysis_ready,
    create_pending_analysis_task,
)


class FakeSession:
    def __init__(self, *scalar_results):
        self.scalar_results = list(scalar_results)

    async def scalar(self, _statement):
        return self.scalar_results.pop(0)


class ChapterLifecycleServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_pending_task_is_bound_to_exact_content(self):
        chapter = SimpleNamespace(id="chapter-1", project_id="project-1", content="正文 A")

        task = create_pending_analysis_task(chapter=chapter, user_id="user-1")

        self.assertEqual(task.content_hash, chapter_content_hash("正文 A"))
        self.assertNotEqual(task.content_hash, chapter_content_hash("正文 B"))
        self.assertTrue(analysis_task_matches_content(task, chapter))

    async def test_first_chapter_does_not_require_previous_analysis(self):
        chapter = SimpleNamespace(chapter_number=1, project_id="project-1")

        ready, message = await check_previous_analysis_ready(FakeSession(), chapter)

        self.assertTrue(ready)
        self.assertEqual(message, "")

    async def test_completed_analysis_for_current_content_is_ready(self):
        previous = SimpleNamespace(
            id="chapter-1",
            chapter_number=1,
            content="current",
            updated_at=datetime.now(),
        )
        task = SimpleNamespace(
            status="completed",
            content_hash=chapter_content_hash("current"),
            materialized_at=datetime.now(),
        )
        current = SimpleNamespace(chapter_number=2, project_id="project-1")

        ready, _ = await check_previous_analysis_ready(FakeSession(previous, task), current)

        self.assertTrue(ready)

    async def test_completed_analysis_for_replaced_content_is_not_ready(self):
        previous = SimpleNamespace(
            id="chapter-1",
            chapter_number=1,
            content="new content",
            updated_at=datetime.now(),
        )
        stale_task = SimpleNamespace(
            status="completed",
            content_hash=chapter_content_hash("old content"),
            materialized_at=datetime.now(),
        )
        current = SimpleNamespace(chapter_number=2, project_id="project-1")

        ready, message = await check_previous_analysis_ready(
            FakeSession(previous, stale_task), current
        )

        self.assertFalse(ready)
        self.assertIn("当前正文", message)

    async def test_legacy_task_requires_analysis_newer_than_chapter(self):
        now = datetime.now()
        previous = SimpleNamespace(
            id="chapter-1",
            chapter_number=1,
            content="legacy",
            updated_at=now,
        )
        legacy_task = SimpleNamespace(
            status="completed",
            content_hash=None,
            materialized_at=None,
        )
        old_analysis = SimpleNamespace(created_at=now - timedelta(seconds=1))
        current = SimpleNamespace(chapter_number=2, project_id="project-1")

        ready, _ = await check_previous_analysis_ready(
            FakeSession(previous, legacy_task, old_analysis), current
        )

        self.assertFalse(ready)


if __name__ == "__main__":
    unittest.main()
