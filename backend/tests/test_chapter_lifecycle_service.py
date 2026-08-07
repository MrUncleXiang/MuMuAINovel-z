import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.database  # noqa: F401 - initialize the model registry as production does

from app.services.chapter_lifecycle_service import (
    analysis_task_matches_content,
    chapter_content_hash,
    check_previous_analysis_ready,
    create_pending_analysis_task,
)
from app.services.chapter_analysis_materialization_service import (
    materialize_chapter_analysis,
)
from app.services.plot_analyzer import PlotAnalyzer
from app.services.prompt_service import PromptService
from app.services.formal_chapter_service import (
    FormalChapterConflictError,
    persist_formal_chapter_content,
)


class FakeSession:
    def __init__(self, *scalar_results):
        self.scalar_results = list(scalar_results)

    async def scalar(self, _statement):
        return self.scalar_results.pop(0)


class MaterializationSession(FakeSession):
    def __init__(self, *scalar_results):
        super().__init__(*scalar_results)
        self.added = []
        self.commit_count = 0

    def add(self, value):
        self.added.append(value)

    async def execute(self, _statement):
        return None

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _value):
        return None

    async def flush(self):
        return None


class FakeAnalyzer:
    def generate_analysis_summary(self, _analysis):
        return "report"

    def extract_memories_from_analysis(self, **_kwargs):
        return [{
            "type": "chapter_summary",
            "content": "summary",
            "title": "chapter summary",
            "metadata": {"chapter_id": "chapter-1", "chapter_number": 1},
        }]


class FakeForeshadowService:
    async def clean_chapter_analysis_foreshadows(self, **_kwargs):
        return {"cleaned_count": 0}

    async def auto_update_from_analysis(self, **_kwargs):
        return {"errors": []}

    async def auto_plant_pending_foreshadows(self, **_kwargs):
        return {"planted_count": 0}


class FakeMemoryService:
    def __init__(self, added_count=1):
        self.added_count = added_count
        self.delete_count = 0

    async def delete_chapter_memories(self, **_kwargs):
        self.delete_count += 1
        return True

    async def batch_add_memories(self, **_kwargs):
        return self.added_count


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


class ChapterAnalysisMaterializationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.chapter = SimpleNamespace(
            id="chapter-1",
            project_id="project-1",
            chapter_number=1,
            title="第一章",
            content="formal content",
            word_count=14,
        )
        self.task = SimpleNamespace(
            id="task-1",
            content_hash=chapter_content_hash(self.chapter.content),
            status="running",
            progress=60,
            error_message=None,
            completed_at=None,
            materialized_at=None,
        )

    async def test_materializes_relational_and_vector_state_before_completion(self):
        db = MaterializationSession(self.chapter, None, None)

        with patch(
            "app.services.chapter_analysis_materialization_service.create_project_state_checkpoint",
            AsyncMock(),
        ) as create_checkpoint:
            result = await materialize_chapter_analysis(
                db=db,
                user_id="user-1",
                chapter=self.chapter,
                task=self.task,
                analysis={"plot_stage": "发展", "hooks": [], "foreshadows": []},
                analyzer=FakeAnalyzer(),
                memory_service=FakeMemoryService(),
                foreshadow_service=FakeForeshadowService(),
            )

        self.assertEqual(result.memory_count, 1)
        self.assertEqual(self.task.status, "completed")
        self.assertIsNotNone(self.task.materialized_at)
        self.assertEqual(db.commit_count, 1)
        self.assertEqual(len(db.added), 2)
        create_checkpoint.assert_awaited_once()

    async def test_vector_failure_does_not_mark_task_completed(self):
        db = MaterializationSession(self.chapter, None, None)
        memory = FakeMemoryService(added_count=0)

        with patch(
            "app.services.chapter_analysis_materialization_service.create_project_state_checkpoint",
            AsyncMock(),
        ) as create_checkpoint:
            with self.assertRaisesRegex(RuntimeError, "向量记忆写入不完整"):
                await materialize_chapter_analysis(
                    db=db,
                    user_id="user-1",
                    chapter=self.chapter,
                    task=self.task,
                    analysis={"hooks": [], "foreshadows": []},
                    analyzer=FakeAnalyzer(),
                    memory_service=memory,
                    foreshadow_service=FakeForeshadowService(),
                )

        self.assertEqual(self.task.status, "running")
        self.assertEqual(db.commit_count, 0)
        self.assertEqual(memory.delete_count, 2)
        create_checkpoint.assert_not_awaited()

    async def test_same_content_is_not_materialized_twice(self):
        prior = SimpleNamespace(id="task-prior")
        db = MaterializationSession(self.chapter, prior)

        result = await materialize_chapter_analysis(
            db=db,
            user_id="user-1",
            chapter=self.chapter,
            task=self.task,
            analysis={},
            analyzer=FakeAnalyzer(),
            memory_service=FakeMemoryService(),
            foreshadow_service=FakeForeshadowService(),
        )

        self.assertTrue(result.already_materialized)
        self.assertEqual(self.task.status, "completed")
        self.assertEqual(db.added, [])
        self.assertEqual(db.commit_count, 1)


class ChapterAnalysisPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_canonical_prompt_contains_dynamic_story_context(self):
        template = (
            "{chapter_number}|{title}|{word_count}|{content}|"
            "{existing_foreshadows}|{characters_info}"
        )
        with patch.object(
            PromptService,
            "get_template",
            AsyncMock(return_value=template),
        ):
            prompt = await PlotAnalyzer.build_analysis_prompt(
                chapter_number=2,
                title="第二章",
                word_count=4,
                content="正文",
                user_id="user-1",
                db=object(),
                existing_foreshadows=[{
                    "id": "foreshadow-1",
                    "title": "旧伏笔",
                    "content": "秘密",
                    "plant_chapter_number": 1,
                }],
                characters_info="角色甲 | 主职业: 剑客",
            )

        self.assertIn("foreshadow-1", prompt)
        self.assertIn("角色甲 | 主职业: 剑客", prompt)


class FormalChapterServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_persists_content_history_and_analysis_task_together(self):
        chapter = SimpleNamespace(
            id="chapter-1",
            project_id="project-1",
            chapter_number=1,
            title="第一章",
            content=None,
            word_count=0,
            status="draft",
            summary=None,
        )
        project = SimpleNamespace(current_words=0)
        db = MaterializationSession(chapter, project)

        result = await persist_formal_chapter_content(
            db=db,
            chapter_id=chapter.id,
            user_id="user-1",
            content="正式正文",
            prompt="prompt",
            model="model-1",
            foreshadow_service=FakeForeshadowService(),
            expected_content_hash=chapter_content_hash(None),
        )

        self.assertEqual(result.chapter.content, "正式正文")
        self.assertEqual(result.analysis_task.content_hash, chapter_content_hash("正式正文"))
        self.assertEqual(project.current_words, 4)
        self.assertEqual(db.commit_count, 1)
        self.assertEqual(len(db.added), 2)

    async def test_rejects_concurrent_content_change(self):
        chapter = SimpleNamespace(id="chapter-1", content="user edit")
        db = MaterializationSession(chapter)

        with self.assertRaisesRegex(FormalChapterConflictError, "生成期间已被修改"):
            await persist_formal_chapter_content(
                db=db,
                chapter_id=chapter.id,
                user_id="user-1",
                content="generated",
                prompt="prompt",
                model="model-1",
                foreshadow_service=FakeForeshadowService(),
                expected_content_hash=chapter_content_hash("old"),
            )

        self.assertEqual(db.commit_count, 0)

    async def test_rejects_replacing_content_with_materialized_analysis(self):
        chapter = SimpleNamespace(
            id="chapter-1",
            project_id="project-1",
            content="analyzed content",
        )
        db = MaterializationSession(chapter, "analysis-task-id")

        with self.assertRaisesRegex(FormalChapterConflictError, "不能直接覆盖"):
            await persist_formal_chapter_content(
                db=db,
                chapter_id=chapter.id,
                user_id="user-1",
                content="replacement",
                prompt="prompt",
                model="model-1",
                foreshadow_service=FakeForeshadowService(),
                expected_content_hash=chapter_content_hash(chapter.content),
            )

        self.assertEqual(db.commit_count, 0)


if __name__ == "__main__":
    unittest.main()
