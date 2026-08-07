import unittest
from datetime import datetime
import os
import uuid
from unittest.mock import AsyncMock

import app.database  # noqa: F401 - initialize model registry
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.analysis_task import AnalysisTask
from app.models.career import Career, CharacterCareer
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.generation_history import GenerationHistory
from app.models.memory import PlotAnalysis, StoryMemory
from app.models.novel_pipeline import NovelPipeline, PipelineStatus
from app.models.outline import Outline
from app.models.project import Project
from app.models.project_creation_config import ProjectCreationConfig
from app.models.project_state_checkpoint import ProjectStateCheckpoint
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.schemas.project_clone import ProjectCloneRequest
from app.schemas.project_state_checkpoint import ProjectStateSnapshotV1
from app.services.chapter_lifecycle_service import chapter_content_hash
from app.services.chapter_lifecycle_service import check_previous_analysis_ready
from app.services.project_clone_service import clone_project
from app.services.project_state_checkpoint_service import serialize_snapshot_entity


class FakeMemoryService:
    def __init__(self, inserted_count=None):
        self.inserted_count = inserted_count
        self.records = []
        self.batch_add_memories = AsyncMock(side_effect=self._add)
        self.delete_project_memories = AsyncMock(return_value=True)

    async def _add(self, _user_id, _project_id, records):
        self.records = records
        return len(records) if self.inserted_count is None else self.inserted_count


class ProjectCloneDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _seed_source(self, db: AsyncSession):
        project = Project(
            id="source-project",
            user_id="user-1",
            title="源书",
            description="完整简介",
            theme="成长",
            genre="奇幻",
            current_words=14,
            wizard_status="completed",
            wizard_step=4,
            world_time_period="旧历",
            world_location="北境",
            world_atmosphere="紧张",
            world_rules="魔法守恒",
            chapter_count=2,
            narrative_perspective="第三人称",
            character_count=2,
        )
        career = Career(
            id="career-source",
            project_id=project.id,
            name="剑士",
            type="main",
            stages='[{"level": 1, "name": "学徒"}]',
            max_stage=10,
        )
        alice = Character(
            id="character-alice",
            project_id=project.id,
            name="阿梨",
            role_type="protagonist",
            status="active",
            current_state="第二章后警觉",
            state_updated_chapter=2,
            main_career_id=career.id,
            main_career_stage=3,
            sub_careers='[{"career_id": "career-source", "stage": 3}]',
        )
        bob = Character(
            id="character-bob",
            project_id=project.id,
            name="柏舟",
            role_type="supporting",
            status="active",
        )
        character_career = CharacterCareer(
            id="character-career-source",
            character_id=alice.id,
            career_id=career.id,
            career_type="main",
            current_stage=3,
            stage_progress=60,
        )
        relationship = CharacterRelationship(
            id="relationship-source",
            project_id=project.id,
            character_from_id=alice.id,
            character_to_id=bob.id,
            relationship_name="同伴",
            intimacy_level=78,
            status="active",
        )
        org_character = Character(
            id="character-org",
            project_id=project.id,
            name="北境盟",
            is_organization=True,
            status="active",
        )
        organization = Organization(
            id="organization-source",
            character_id=org_character.id,
            project_id=project.id,
            power_level=72,
            member_count=1,
        )
        member = OrganizationMember(
            id="member-source",
            organization_id=organization.id,
            character_id=alice.id,
            position="斥候",
            loyalty=80,
            contribution=25,
        )
        outline = Outline(
            id="outline-source",
            project_id=project.id,
            title="第一卷",
            content="出发",
            structure='{"lead": "character-alice"}',
            order_index=1,
        )
        chapter1 = Chapter(
            id="chapter-source-1",
            project_id=project.id,
            outline_id=outline.id,
            chapter_number=1,
            sub_index=1,
            title="起点",
            content="第一章正文",
            summary="第一章",
            word_count=6,
            status="completed",
        )
        chapter2 = Chapter(
            id="chapter-source-2",
            project_id=project.id,
            outline_id=outline.id,
            chapter_number=2,
            sub_index=2,
            title="同行",
            content="第二章正文更长",
            summary="第二章",
            word_count=8,
            status="completed",
            expansion_plan='{"focus": "character-bob"}',
        )
        task1 = AnalysisTask(
            id="task-source-1",
            chapter_id=chapter1.id,
            user_id=project.user_id,
            project_id=project.id,
            content_hash=chapter_content_hash(chapter1.content),
            status="completed",
            progress=100,
            completed_at=datetime.now(),
            materialized_at=datetime.now(),
        )
        task2 = AnalysisTask(
            id="task-source-2",
            chapter_id=chapter2.id,
            user_id=project.user_id,
            project_id=project.id,
            content_hash=chapter_content_hash(chapter2.content),
            status="completed",
            progress=100,
            completed_at=datetime.now(),
            materialized_at=datetime.now(),
        )
        memory1 = StoryMemory(
            id="memory-source-1",
            vector_id="memory-source-1",
            project_id=project.id,
            chapter_id=chapter1.id,
            memory_type="plot_point",
            title="出发",
            content="阿梨从北境出发",
            related_characters=[alice.id],
            importance_score=0.8,
            story_timeline=1,
        )
        memory2 = StoryMemory(
            id="memory-source-2",
            vector_id="memory-source-2",
            project_id=project.id,
            chapter_id=chapter2.id,
            memory_type="character_event",
            title="结伴",
            content="阿梨与柏舟结伴",
            related_characters=[alice.id, bob.id],
            importance_score=0.7,
            story_timeline=2,
        )
        analysis1 = PlotAnalysis(
            id="analysis-source-1",
            project_id=project.id,
            chapter_id=chapter1.id,
            plot_stage="开端",
            character_states=[{"character_id": alice.id, "state_after": "坚定"}],
        )
        analysis2 = PlotAnalysis(
            id="analysis-source-2",
            project_id=project.id,
            chapter_id=chapter2.id,
            plot_stage="发展",
            character_states=[{"character_id": bob.id, "state_after": "信任"}],
        )
        db.add_all([
            project,
            ProjectCreationConfig(
                project_id=project.id,
                config_version=3,
                config={"skill_key": "novel", "chapter": {"model": "model-a"}},
            ),
            career,
            alice,
            bob,
            org_character,
            character_career,
            relationship,
            organization,
            member,
            outline,
            chapter1,
            chapter2,
            task1,
            task2,
            memory1,
            memory2,
            analysis1,
            analysis2,
            GenerationHistory(
                id="history-source-1",
                project_id=project.id,
                chapter_id=chapter1.id,
                prompt="写第一章",
                generated_content=chapter1.content,
                model="model-a",
            ),
            GenerationHistory(
                id="history-source-2",
                project_id=project.id,
                chapter_id=chapter2.id,
                prompt="写第二章",
                generated_content=chapter2.content,
                model="model-a",
            ),
            NovelPipeline(
                id="pipeline-source",
                project_id=project.id,
                status="running",
                current_stage="chapter_loop",
                chapter_count=2,
                config_snapshot={"checkpoint_every_n_chapters": 2},
                progress_json={"current": 2},
                checkpoint_history=[{"chapter": 2}],
                budget_used_tokens=999,
                budget_used_amount_cents=88,
            ),
        ])
        await db.flush()

        snapshot1 = ProjectStateSnapshotV1(
            chapter_number=1,
            careers=[serialize_snapshot_entity(career)],
            characters=[
                serialize_snapshot_entity(Character(
                    id=alice.id,
                    project_id=project.id,
                    name=alice.name,
                    role_type=alice.role_type,
                    status="active",
                    current_state="第一章后坚定",
                    state_updated_chapter=1,
                    main_career_id=career.id,
                    main_career_stage=2,
                    sub_careers='[{"career_id": "career-source", "stage": 2}]',
                )),
                serialize_snapshot_entity(bob),
                serialize_snapshot_entity(org_character),
            ],
            character_careers=[serialize_snapshot_entity(CharacterCareer(
                id=character_career.id,
                character_id=alice.id,
                career_id=career.id,
                career_type="main",
                current_stage=2,
                stage_progress=10,
            ))],
            relationships=[serialize_snapshot_entity(relationship)],
            organizations=[serialize_snapshot_entity(organization)],
            organization_members=[serialize_snapshot_entity(member)],
            story_memories=[serialize_snapshot_entity(memory1)],
        )
        snapshot2 = ProjectStateSnapshotV1(
            chapter_number=2,
            careers=[serialize_snapshot_entity(career)],
            characters=[serialize_snapshot_entity(alice), serialize_snapshot_entity(bob), serialize_snapshot_entity(org_character)],
            character_careers=[serialize_snapshot_entity(character_career)],
            relationships=[serialize_snapshot_entity(relationship)],
            organizations=[serialize_snapshot_entity(organization)],
            organization_members=[serialize_snapshot_entity(member)],
            story_memories=[serialize_snapshot_entity(memory1), serialize_snapshot_entity(memory2)],
        )
        checkpoint1 = ProjectStateCheckpoint(
            id="checkpoint-source-1",
            project_id=project.id,
            chapter_id=chapter1.id,
            chapter_number=1,
            analysis_task_id=task1.id,
            content_hash=task1.content_hash,
            schema_version=1,
            status="valid",
            config_version=3,
            state_json=snapshot1.model_dump(mode="json"),
        )
        checkpoint2 = ProjectStateCheckpoint(
            id="checkpoint-source-2",
            project_id=project.id,
            chapter_id=chapter2.id,
            chapter_number=2,
            analysis_task_id=task2.id,
            content_hash=task2.content_hash,
            schema_version=1,
            status="valid",
            config_version=3,
            state_json=snapshot2.model_dump(mode="json"),
        )
        db.add_all([checkpoint1, checkpoint2])
        await db.commit()
        return project, checkpoint1, checkpoint2

    async def test_settings_only_resets_progress_and_remaps_all_writable_ids(self):
        memory = FakeMemoryService()
        async with self.sessions() as db:
            source, _, _ = await self._seed_source(db)
            result = await clone_project(
                db,
                source_project_id=source.id,
                user_id=source.user_id,
                request=ProjectCloneRequest(title="源书-DeepSeek", mode="settings_only"),
                memory_service=memory,
            )

            target = await db.get(Project, result.project_id)
            chapters = list((await db.scalars(select(Chapter).where(Chapter.project_id == target.id))).all())
            target_characters = list((await db.scalars(select(Character).where(Character.project_id == target.id))).all())
            target_career = await db.scalar(select(Career).where(Career.project_id == target.id))
            target_outline = await db.scalar(select(Outline).where(Outline.project_id == target.id))
            pipeline = await db.scalar(select(NovelPipeline).where(NovelPipeline.project_id == target.id))

            self.assertEqual(target.title, "源书-DeepSeek")
            self.assertEqual(target.current_words, 0)
            self.assertTrue(all(chapter.content is None and chapter.status == "draft" for chapter in chapters))
            self.assertNotEqual(target_career.id, "career-source")
            self.assertNotIn("character-alice", {item.id for item in target_characters})
            alice = next(item for item in target_characters if item.name == "阿梨")
            self.assertEqual(alice.main_career_id, target_career.id)
            self.assertEqual(alice.main_career_stage, 1)
            self.assertIsNone(alice.current_state)
            self.assertNotIn("career-source", alice.sub_careers)
            self.assertNotIn("character-alice", target_outline.structure)
            self.assertIn(alice.id, target_outline.structure)
            target_second = next(item for item in chapters if item.chapter_number == 2)
            target_bob = next(item for item in target_characters if item.name == "柏舟")
            self.assertNotIn("character-bob", target_second.expansion_plan)
            self.assertIn(target_bob.id, target_second.expansion_plan)
            self.assertEqual(pipeline.status, PipelineStatus.IDLE)
            self.assertEqual(pipeline.chapter_count, 0)
            self.assertEqual(pipeline.budget_used_tokens, 0)
            memory.batch_add_memories.assert_not_awaited()

    async def test_inherit_uses_selected_checkpoint_not_source_latest_state(self):
        memory = FakeMemoryService()
        async with self.sessions() as db:
            source, checkpoint1, _ = await self._seed_source(db)
            result = await clone_project(
                db,
                source_project_id=source.id,
                user_id=source.user_id,
                request=ProjectCloneRequest(
                    title="源书-第一章分支",
                    mode="inherit_checkpoint",
                    checkpoint_id=checkpoint1.id,
                ),
                memory_service=memory,
            )

            target_chapters = list((await db.scalars(
                select(Chapter).where(Chapter.project_id == result.project_id).order_by(Chapter.chapter_number)
            )).all())
            alice = await db.scalar(select(Character).where(
                Character.project_id == result.project_id,
                Character.name == "阿梨",
            ))
            memories = list((await db.scalars(select(StoryMemory).where(
                StoryMemory.project_id == result.project_id
            ))).all())
            task_count = await db.scalar(select(func.count(AnalysisTask.id)).where(
                AnalysisTask.project_id == result.project_id
            ))
            checkpoint_count = await db.scalar(select(func.count(ProjectStateCheckpoint.id)).where(
                ProjectStateCheckpoint.project_id == result.project_id
            ))
            target_analysis = await db.scalar(select(PlotAnalysis).where(
                PlotAnalysis.project_id == result.project_id
            ))

            self.assertEqual(result.inherited_through_chapter, 1)
            self.assertEqual(target_chapters[0].content, "第一章正文")
            self.assertIsNone(target_chapters[1].content)
            self.assertEqual(alice.current_state, "第一章后坚定")
            self.assertEqual(alice.main_career_stage, 2)
            self.assertEqual(len(memories), 1)
            self.assertNotEqual(memories[0].id, "memory-source-1")
            self.assertEqual(memories[0].vector_id, memories[0].id)
            self.assertEqual(task_count, 1)
            self.assertEqual(checkpoint_count, 1)
            self.assertEqual(len(memory.records), 1)
            self.assertEqual(memory.records[0]["id"], memories[0].id)
            self.assertNotIn("character-alice", memories[0].related_characters)
            self.assertIn(alice.id, memories[0].related_characters)
            self.assertNotEqual(
                target_analysis.character_states[0]["character_id"],
                "character-alice",
            )
            ready, reason = await check_previous_analysis_ready(db, target_chapters[1])
            self.assertTrue(ready, reason)

            alice.current_state = "副本独立修改"
            await db.commit()
            source_alice = await db.get(Character, "character-alice")
            self.assertEqual(source_alice.current_state, "第二章后警觉")

    async def test_vector_failure_rolls_back_database_and_cleans_target_collection(self):
        memory = FakeMemoryService(inserted_count=0)
        async with self.sessions() as db:
            source, checkpoint1, _ = await self._seed_source(db)
            with self.assertRaisesRegex(RuntimeError, "向量记忆重建不完整"):
                await clone_project(
                    db,
                    source_project_id=source.id,
                    user_id=source.user_id,
                    request=ProjectCloneRequest(
                        title="失败副本",
                        mode="inherit_checkpoint",
                        checkpoint_id=checkpoint1.id,
                    ),
                    memory_service=memory,
                )

            failed = await db.scalar(select(Project).where(Project.title == "失败副本"))
            self.assertIsNone(failed)
            memory.delete_project_memories.assert_awaited_once()


@unittest.skipUnless(
    os.getenv("RUN_POSTGRES_CLONE_TEST") == "1"
    and os.getenv("DATABASE_URL", "").startswith("postgresql"),
    "set RUN_POSTGRES_CLONE_TEST=1 against the challenge PostgreSQL database",
)
class ProjectClonePostgresSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_clone_on_postgres(self):
        database_url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        suffix = uuid.uuid4().hex[:10]
        source_id = str(uuid.uuid4())
        target_id = None
        memory = FakeMemoryService()
        try:
            async with sessions() as db:
                source = Project(
                    id=source_id,
                    user_id=f"clone-smoke-{suffix}",
                    title=f"clone-source-{suffix}",
                    description="postgres smoke",
                    outline_mode="one-to-many",
                )
                career = Career(
                    id=str(uuid.uuid4()),
                    project_id=source.id,
                    name="测试职业",
                    type="main",
                    stages="[]",
                    max_stage=1,
                )
                character = Character(
                    id=str(uuid.uuid4()),
                    project_id=source.id,
                    name="测试角色",
                    main_career_id=career.id,
                    main_career_stage=1,
                )
                outline = Outline(
                    id=str(uuid.uuid4()),
                    project_id=source.id,
                    title="测试大纲",
                    order_index=1,
                )
                chapter = Chapter(
                    id=str(uuid.uuid4()),
                    project_id=source.id,
                    outline_id=outline.id,
                    chapter_number=1,
                    title="测试章节",
                )
                db.add(source)
                await db.flush()
                db.add_all([career, outline])
                await db.flush()
                db.add_all([character, chapter])
                await db.commit()

                result = await clone_project(
                    db,
                    source_project_id=source.id,
                    user_id=source.user_id,
                    request=ProjectCloneRequest(
                        title=f"clone-target-{suffix}",
                        mode="settings_only",
                    ),
                    memory_service=memory,
                )
                target_id = result.project_id
                target = await db.get(Project, target_id)
                self.assertIsNotNone(target)
                self.assertNotEqual(target.id, source.id)
                self.assertEqual(result.counts.characters, 1)
                self.assertEqual(result.counts.chapters, 1)
        finally:
            async with sessions() as cleanup_db:
                ids = [item for item in (target_id, source_id) if item]
                await cleanup_db.execute(delete(Project).where(Project.id.in_(ids)))
                await cleanup_db.commit()
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
