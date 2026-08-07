import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.database  # noqa: F401 - initialize model registry

from app.services.chapter_comparison_service import apply_chapter_candidate
from app.services.analysis_comparison_service import apply_analysis_candidate
from app.services.chapter_lifecycle_service import chapter_content_hash
from app.services.llm_comparison_service import adopt_candidate


class FakeDb:
    def __init__(self, scalar_values):
        self.scalar_values = list(scalar_values)
        self.added = []
        self.flush = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def scalar(self, _statement):
        return self.scalar_values.pop(0)

    def add(self, value):
        self.added.append(value)


class CandidateReintegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_chapter_candidate_delegates_formal_persistence_and_records_task(self):
        chapter = SimpleNamespace(
            id="chapter-1",
            project_id="project-1",
            content="before",
            updated_at=datetime(2026, 8, 7, 12, 0),
        )
        candidate = SimpleNamespace(
            output_text="after",
            output_data=None,
            provider_name="Provider",
            model="model-a",
        )
        batch = SimpleNamespace(
            target_id="chapter-1",
            project_id="project-1",
            user_id="user-1",
            input_snapshot={
                "formal_content_before": "before",
                "formal_updated_at": chapter.updated_at.isoformat(),
            },
        )
        task = SimpleNamespace(id="analysis-task-1")
        db = FakeDb([chapter])

        with patch(
            "app.services.chapter_comparison_service.persist_formal_chapter_content",
            AsyncMock(return_value=SimpleNamespace(analysis_task=task)),
        ) as persist:
            await apply_chapter_candidate(db, batch, candidate)

        persist.assert_awaited_once()
        self.assertFalse(persist.call_args.kwargs["commit"])
        self.assertEqual(
            persist.call_args.kwargs["expected_content_hash"],
            chapter_content_hash("before"),
        )
        self.assertEqual(candidate.output_data["formal_analysis_task_id"], task.id)

    async def test_analysis_candidate_delegates_standard_materialization(self):
        chapter = SimpleNamespace(
            id="chapter-1",
            project_id="project-1",
            chapter_number=1,
            content="formal",
            updated_at=datetime(2026, 8, 7, 12, 0),
        )
        candidate = SimpleNamespace(
            output_text='{"hooks": []}',
            output_data={"hooks": []},
        )
        batch = SimpleNamespace(
            target_id="chapter-1",
            project_id="project-1",
            user_id="user-1",
            input_snapshot={
                "content_hash": chapter_content_hash("formal"),
                "updated_at": chapter.updated_at.isoformat(),
            },
        )
        db = FakeDb([chapter, None])
        task = SimpleNamespace(id="analysis-task-2", chapter_id=chapter.id)

        with patch(
            "app.services.analysis_comparison_service.create_pending_analysis_task",
            return_value=task,
        ), patch(
            "app.services.analysis_comparison_service.materialize_chapter_analysis",
            AsyncMock(),
        ) as materialize:
            await apply_analysis_candidate(db, batch, candidate)

        materialize.assert_awaited_once()
        self.assertFalse(materialize.call_args.kwargs["commit"])
        self.assertEqual(materialize.call_args.kwargs["task"].chapter_id, chapter.id)
        self.assertEqual(candidate.output_data["formal_analysis_task_id"], task.id)

    async def test_stale_chapter_candidate_cannot_replace_newer_formal_content(self):
        chapter = SimpleNamespace(
            id="chapter-1",
            project_id="project-1",
            content="newer formal content",
            updated_at=datetime(2026, 8, 7, 13, 0),
        )
        candidate = SimpleNamespace(
            output_text="stale candidate",
            output_data=None,
            provider_name="Provider",
            model="model-a",
        )
        batch = SimpleNamespace(
            target_id=chapter.id,
            project_id=chapter.project_id,
            user_id="user-1",
            input_snapshot={
                "formal_content_before": "older formal content",
                "formal_updated_at": datetime(2026, 8, 7, 12, 0).isoformat(),
            },
        )

        with patch(
            "app.services.chapter_comparison_service.persist_formal_chapter_content",
            AsyncMock(),
        ) as persist:
            with self.assertRaisesRegex(ValueError, "已被修改"):
                await apply_chapter_candidate(FakeDb([chapter]), batch, candidate)

        persist.assert_not_awaited()

    async def test_adoption_is_idempotent_for_same_candidate(self):
        batch = SimpleNamespace(
            id="batch-1",
            user_id="user-1",
            adopted_candidate_id=None,
            status="completed",
        )
        candidate = SimpleNamespace(
            id="candidate-1",
            batch_id=batch.id,
            status="success",
            adopted_at=None,
        )
        db = FakeDb([batch, candidate, batch, candidate])
        callback = AsyncMock()

        _, _, first = await adopt_candidate(
            db,
            batch_id=batch.id,
            candidate_id=candidate.id,
            user_id=batch.user_id,
            apply_target=callback,
        )
        # The persisted state is what the second request observes.
        batch.adopted_candidate_id = candidate.id
        batch.status = "adopted"
        _, _, second = await adopt_candidate(
            db,
            batch_id=batch.id,
            candidate_id=candidate.id,
            user_id=batch.user_id,
            apply_target=callback,
        )

        self.assertTrue(first)
        self.assertFalse(second)
        callback.assert_awaited_once()
        self.assertEqual(db.commit.await_count, 1)

    async def test_failed_formal_application_keeps_batch_retryable(self):
        batch = SimpleNamespace(
            id="batch-1",
            user_id="user-1",
            adopted_candidate_id=None,
            status="completed",
        )
        candidate = SimpleNamespace(
            id="candidate-1",
            batch_id=batch.id,
            status="success",
            adopted_at=None,
        )
        db = FakeDb([batch, candidate])
        callback = AsyncMock(side_effect=RuntimeError("materialization failed"))

        with self.assertRaisesRegex(RuntimeError, "materialization failed"):
            await adopt_candidate(
                db,
                batch_id=batch.id,
                candidate_id=candidate.id,
                user_id=batch.user_id,
                apply_target=callback,
            )

        self.assertIsNone(batch.adopted_candidate_id)
        self.assertEqual(batch.status, "completed")
        self.assertEqual(db.commit.await_count, 0)
        db.rollback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
