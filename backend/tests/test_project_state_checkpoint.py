import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.database  # noqa: F401 - initialize model registry
from pydantic import ValidationError

from app.models.character import Character
from app.models.foreshadow import Foreshadow
from app.models.memory import StoryMemory
from app.schemas.project_state_checkpoint import ProjectStateSnapshotV1
from app.services.project_state_checkpoint_service import serialize_snapshot_entity
from app.services.project_state_checkpoint_service import create_project_state_checkpoint
from app.services.project_state_checkpoint_service import invalidate_checkpoints_from_chapter
from app.services.project_state_checkpoint_service import prepare_project_state_for_chapter_rewrite
from app.services.project_state_checkpoint_service import list_valid_project_checkpoints
from app.services.project_state_checkpoint_service import register_latest_reliable_checkpoint
from app.services.chapter_lifecycle_service import chapter_content_hash


class FakeCheckpointSession:
    def __init__(self, *scalar_values):
        self.scalar_values = list(scalar_values)
        self.added = []

    async def scalar(self, _statement):
        return self.scalar_values.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def execute(self, statement):
        self.executed = statement
        return SimpleNamespace(rowcount=2)


class FakeScalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeRestoreSession:
    def __init__(self, previous, chapters):
        self.previous = previous
        self.chapters = chapters
        self.executed = []

    async def scalar(self, _statement):
        return self.previous

    async def scalars(self, _statement):
        return FakeScalars(self.chapters)

    async def execute(self, statement):
        self.executed.append(statement)
        return SimpleNamespace(rowcount=1)


class SequencedSession:
    def __init__(self, scalar_values=None, scalar_lists=None):
        self.scalar_values = list(scalar_values or [])
        self.scalar_lists = list(scalar_lists or [])
        self.added = []
        self.commit = AsyncMock()

    async def scalar(self, _statement):
        return self.scalar_values.pop(0)

    async def scalars(self, _statement):
        return FakeScalars(self.scalar_lists.pop(0))

    def add(self, value):
        self.added.append(value)

    async def refresh(self, _value):
        return None


class ProjectStateSnapshotSchemaTests(unittest.TestCase):
    def test_serializes_mutable_entity_state_with_stable_source_id(self):
        character = Character(
            id="character-1",
            project_id="project-1",
            name="林川",
            current_state="警觉",
            state_updated_chapter=8,
            main_career_id="career-1",
            main_career_stage=3,
        )

        entity = serialize_snapshot_entity(character)

        self.assertEqual(entity.id, "character-1")
        self.assertNotIn("id", entity.data)
        self.assertEqual(entity.data["project_id"], "project-1")
        self.assertEqual(entity.data["current_state"], "警觉")
        self.assertEqual(entity.data["main_career_stage"], 3)

    def test_snapshot_round_trip_preserves_future_sensitive_state(self):
        foreshadow = Foreshadow(
            id="foreshadow-1",
            project_id="project-1",
            title="旧钥匙",
            content="尚未回收",
            status="planted",
            plant_chapter_number=3,
            actual_resolve_chapter_number=None,
        )
        memory = StoryMemory(
            id="memory-1",
            project_id="project-1",
            chapter_id="chapter-8",
            memory_type="foreshadow",
            content="主角发现旧钥匙",
            story_timeline=8,
            is_foreshadow=1,
        )
        snapshot = ProjectStateSnapshotV1(
            chapter_number=8,
            foreshadows=[serialize_snapshot_entity(foreshadow)],
            story_memories=[serialize_snapshot_entity(memory)],
        )

        restored = ProjectStateSnapshotV1.model_validate_json(snapshot.model_dump_json())

        self.assertEqual(restored, snapshot)
        self.assertEqual(restored.foreshadows[0].data["status"], "planted")
        self.assertIsNone(
            restored.foreshadows[0].data["actual_resolve_chapter_number"]
        )
        self.assertNotIn("尚未回收", json.dumps(restored.story_memories[0].data))

    def test_rejects_unknown_snapshot_contract_fields(self):
        with self.assertRaises(ValidationError):
            ProjectStateSnapshotV1.model_validate({
                "schema_version": 1,
                "chapter_number": 1,
                "unknown_entities": [],
            })


class ProjectStateCheckpointCreationTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_chapter_creates_valid_checkpoint(self):
        db = FakeCheckpointSession(None, None, 4)
        chapter = SimpleNamespace(
            id="chapter-1",
            project_id="project-1",
            chapter_number=1,
        )
        task = SimpleNamespace(id="task-1", content_hash="hash-1")
        snapshot = ProjectStateSnapshotV1(chapter_number=1)

        with patch(
            "app.services.project_state_checkpoint_service.capture_project_state",
            AsyncMock(return_value=snapshot),
        ):
            checkpoint = await create_project_state_checkpoint(
                db,
                chapter=chapter,
                analysis_task=task,
            )

        self.assertEqual(checkpoint.status, "valid")
        self.assertIsNone(checkpoint.invalid_reason)
        self.assertEqual(checkpoint.config_version, 4)
        self.assertEqual(checkpoint.state_json["schema_version"], 1)
        self.assertEqual(db.added, [checkpoint])

    async def test_non_continuous_historical_analysis_is_not_exposed(self):
        db = FakeCheckpointSession(None, None, "later-task", None)
        chapter = SimpleNamespace(
            id="chapter-3",
            project_id="project-1",
            chapter_number=3,
        )
        task = SimpleNamespace(id="task-3", content_hash="hash-3")

        with patch(
            "app.services.project_state_checkpoint_service.capture_project_state",
            AsyncMock(return_value=ProjectStateSnapshotV1(chapter_number=3)),
        ):
            checkpoint = await create_project_state_checkpoint(
                db,
                chapter=chapter,
                analysis_task=task,
            )

        self.assertEqual(checkpoint.status, "invalid")
        self.assertIn("缺少上一章", checkpoint.invalid_reason)
        self.assertIn("后续分析", checkpoint.invalid_reason)

    async def test_stale_previous_checkpoint_breaks_continuity(self):
        previous = SimpleNamespace(
            chapter_id="chapter-1",
            content_hash=chapter_content_hash("old"),
            status="valid",
            invalid_reason=None,
            invalidated_at=None,
        )
        previous_chapter = SimpleNamespace(id="chapter-1", content="changed")
        db = FakeCheckpointSession(None, previous, previous_chapter, None, None)
        chapter = SimpleNamespace(
            id="chapter-2",
            project_id="project-1",
            chapter_number=2,
        )
        task = SimpleNamespace(id="task-2", content_hash="hash-2")

        with patch(
            "app.services.project_state_checkpoint_service.capture_project_state",
            AsyncMock(return_value=ProjectStateSnapshotV1(chapter_number=2)),
        ):
            checkpoint = await create_project_state_checkpoint(
                db,
                chapter=chapter,
                analysis_task=task,
            )

        self.assertEqual(previous.status, "invalid")
        self.assertEqual(checkpoint.status, "invalid")
        self.assertIn("缺少上一章", checkpoint.invalid_reason)

    async def test_chapter_change_invalidates_all_dependent_checkpoints(self):
        db = FakeCheckpointSession()

        count = await invalidate_checkpoints_from_chapter(
            db,
            project_id="project-1",
            chapter_number=8,
            reason="第8章正文被修改",
        )

        self.assertEqual(count, 2)
        compiled = str(db.executed.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("chapter_number >= 8", compiled)
        self.assertIn("status = 'valid'", compiled)

    async def test_rewrite_restores_previous_boundary_and_clears_future_vectors(self):
        snapshot = ProjectStateSnapshotV1(chapter_number=2)
        previous = SimpleNamespace(state_json=snapshot.model_dump(mode="json"))
        affected = [
            SimpleNamespace(id="chapter-3", chapter_number=3),
            SimpleNamespace(id="chapter-4", chapter_number=4),
        ]
        db = FakeRestoreSession(previous, affected)
        memory_service = SimpleNamespace(delete_chapter_memories=AsyncMock(return_value=True))
        chapter = SimpleNamespace(
            id="chapter-3",
            project_id="project-1",
            chapter_number=3,
        )

        with (
            patch(
                "app.services.project_state_checkpoint_service.restore_project_state",
                AsyncMock(),
            ) as restore,
            patch(
                "app.services.project_state_checkpoint_service.invalidate_checkpoints_from_chapter",
                AsyncMock(return_value=2),
            ) as invalidate,
        ):
            result = await prepare_project_state_for_chapter_rewrite(
                db,
                user_id="user-1",
                chapter=chapter,
                memory_service=memory_service,
            )

        self.assertIs(result, previous)
        self.assertEqual(memory_service.delete_chapter_memories.await_count, 2)
        restore.assert_awaited_once()
        invalidate.assert_awaited_once()
        self.assertEqual(len(db.executed), 2)

    async def test_read_filter_invalidates_checkpoint_with_changed_content(self):
        checkpoint = SimpleNamespace(
            chapter_id="chapter-1",
            content_hash=chapter_content_hash("old"),
            status="valid",
            invalid_reason=None,
            invalidated_at=None,
        )
        chapter = SimpleNamespace(id="chapter-1", content="new")
        db = SequencedSession(scalar_lists=[[checkpoint], [chapter]])

        result = await list_valid_project_checkpoints(db, project_id="project-1")

        self.assertEqual(result, [])
        self.assertEqual(checkpoint.status, "invalid")
        db.commit.assert_awaited_once()

    async def test_legacy_registration_requires_every_chapter_analysis(self):
        chapters = [
            SimpleNamespace(
                id="chapter-1", chapter_number=1, sub_index=1, content="one"
            ),
            SimpleNamespace(
                id="chapter-2", chapter_number=2, sub_index=1, content="two"
            ),
        ]
        first_task = SimpleNamespace(
            id="task-1",
            status="completed",
            materialized_at=object(),
            content_hash=chapter_content_hash("one"),
        )
        stale_second = SimpleNamespace(
            id="task-2",
            status="completed",
            materialized_at=object(),
            content_hash=chapter_content_hash("old two"),
        )
        db = SequencedSession(
            scalar_values=[first_task, stale_second],
            scalar_lists=[chapters],
        )

        with self.assertRaisesRegex(ValueError, "第2章"):
            await register_latest_reliable_checkpoint(db, project_id="project-1")

        self.assertEqual(db.added, [])


if __name__ == "__main__":
    unittest.main()
