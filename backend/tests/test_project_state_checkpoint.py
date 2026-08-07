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


if __name__ == "__main__":
    unittest.main()
