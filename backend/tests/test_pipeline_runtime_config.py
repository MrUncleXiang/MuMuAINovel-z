import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.database  # noqa: F401 - initialize model registry

from app.services.pipeline_service import build_pipeline_runtime_config
from app.services.pipeline_service import _generate_one_chapter
from app.services.pipeline_service import _next_pending_chapter
from app.services.pipeline_service import merge_config
from app.services.pipeline_service import PipelineStateError


class FakeScalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeChapterSession:
    def __init__(self, chapters):
        self.chapters = chapters

    async def scalars(self, _statement):
        return FakeScalars(self.chapters)


class PipelineRuntimeConfigTests(unittest.TestCase):
    def test_nested_overrides_do_not_discard_other_defaults(self):
        config = merge_config({
            "models": {"chapter": {"model": "chapter-model"}},
            "params": {"chapter": {"target_word_count": 4200}},
        })

        self.assertEqual(config["models"]["chapter"]["model"], "chapter-model")
        self.assertIn("analysis", config["models"])
        self.assertEqual(config["params"]["chapter"]["target_word_count"], 4200)
        self.assertEqual(config["params"]["chapter"]["temperature"], 0.8)

    def test_project_snapshot_owns_creation_resources(self):
        runtime_snapshot = {
            "config_version": 7,
            "chapter": {"id": "chapter-provider", "model": "chapter-model"},
            "analysis": {"id": "analysis-provider", "model": "analysis-model"},
            "skill": {"id": "skill-key", "name": "Skill"},
            "writing_style": {"id": "42", "name": "Style"},
            "mcp_plugins": [{"id": "plugin-1", "name": "Plugin"}],
            "parameters": {
                "mcp_enabled": True,
                "narrative_perspective": "第一人称",
                "target_word_count": 3600,
                "temperature": 0.65,
                "max_tokens": 9000,
                "pipeline": {
                    "budget_limit": 12.5,
                    "checkpoint_every_n_chapters": 4,
                    "milestone_chapters": 24,
                    "checkpoint_on_volume_end": False,
                    "auto_advance": False,
                },
            },
        }

        config = build_pipeline_runtime_config(
            runtime_snapshot,
            {"models": {"chapter": {"model": "stale-model"}}},
        )

        self.assertEqual(config["config_version"], 7)
        self.assertEqual(config["models"]["chapter"], {
            "provider_config_id": "chapter-provider",
            "model": "chapter-model",
        })
        self.assertEqual(config["models"]["analysis"], {
            "provider_config_id": "analysis-provider",
            "model": "analysis-model",
        })
        self.assertEqual(config["skill_key"], "skill-key")
        self.assertEqual(config["style_id"], 42)
        self.assertTrue(config["enable_mcp"])
        self.assertEqual(config["mcp_plugin_ids"], ["plugin-1"])
        self.assertEqual(config["params"]["chapter"]["target_word_count"], 3600)
        self.assertEqual(config["params"]["chapter"]["temperature"], 0.65)
        self.assertEqual(config["params"]["chapter"]["max_tokens"], 9000)
        self.assertEqual(config["checkpoint_every_n"], 4)
        self.assertEqual(config["milestone_chapters"], 24)
        self.assertFalse(config["checkpoint_on_volume_end"])
        self.assertEqual(config["budget"]["max_amount_cents"], 1250)
        self.assertEqual(config["creation_runtime_snapshot"], runtime_snapshot)


class PipelineChapterLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_chapter_waits_for_previous_analysis(self):
        chapter = SimpleNamespace(id="chapter-2")
        pipeline = SimpleNamespace(project_id="project-1", current_outline_id="outline-1")

        with (
            patch("app.api.chapters.check_prerequisites", AsyncMock(return_value=(True, "", []))),
            patch(
                "app.services.chapter_lifecycle_service.check_previous_analysis_ready",
                AsyncMock(return_value=(False, "第1章分析尚未完成")),
            ),
        ):
            with self.assertRaisesRegex(PipelineStateError, "分析尚未完成"):
                await _next_pending_chapter(FakeChapterSession([chapter]), pipeline)

    async def test_generation_uses_snapshot_and_waits_for_selected_analysis_model(self):
        pipeline = SimpleNamespace(
            id="pipeline-12345678",
            project_id="project-1",
            config_snapshot={
                "models": {
                    "chapter": {
                        "provider_config_id": "chapter-provider",
                        "model": "chapter-model",
                    },
                    "analysis": {
                        "provider_config_id": "analysis-provider",
                        "model": "analysis-model",
                    },
                },
                "params": {"chapter": {
                    "target_word_count": 3600,
                    "temperature": 0.6,
                    "max_tokens": 9000,
                }},
                "style_id": 42,
                "skill_key": "skill-key",
                "enable_mcp": True,
                "mcp_plugin_ids": ["plugin-1"],
                "narrative_perspective": "第一人称",
            },
        )
        chapter = SimpleNamespace(id="chapter-1")
        generate = AsyncMock(return_value=SimpleNamespace(id="analysis-task-1"))
        analyze = AsyncMock(return_value=True)
        create_service = AsyncMock(return_value=object())

        with (
            patch("app.api.chapters._run_chapter_generation_bg", generate),
            patch("app.api.chapters.analyze_chapter_background", analyze),
            patch("app.services.ai_provider_service.create_routed_ai_service", create_service),
            patch("app.services.background_task_service.TaskProgressTracker", return_value=object()),
        ):
            result = await _generate_one_chapter(
                object(), pipeline, chapter, "user-1", minimum_content_length=2520,
            )

        self.assertEqual(result, (True, "", False))
        create_kwargs = create_service.await_args.kwargs
        self.assertEqual(create_kwargs["provider_config_id"], "chapter-provider")
        self.assertEqual(create_kwargs["model"], "chapter-model")
        self.assertEqual(create_kwargs["allowed_mcp_plugin_ids"], ["plugin-1"])
        task_input = generate.await_args.kwargs["task_input"]
        self.assertEqual(task_input["style_id"], 42)
        self.assertEqual(task_input["skill_key"], "skill-key")
        self.assertTrue(task_input["enable_mcp"])
        self.assertFalse(task_input["schedule_analysis"])
        self.assertEqual(task_input["minimum_content_length"], 2520)
        analysis_kwargs = analyze.await_args.kwargs
        self.assertEqual(analysis_kwargs["provider_config_id"], "analysis-provider")
        self.assertEqual(analysis_kwargs["model"], "analysis-model")
        self.assertEqual(analysis_kwargs["allowed_mcp_plugin_ids"], ["plugin-1"])

    async def test_analysis_failure_stops_body_regeneration(self):
        pipeline = SimpleNamespace(
            id="pipeline-12345678",
            project_id="project-1",
            config_snapshot={"models": {}, "params": {"chapter": {}}},
        )
        generate = AsyncMock(return_value=SimpleNamespace(id="analysis-task-1"))

        with (
            patch("app.api.chapters._run_chapter_generation_bg", generate),
            patch("app.api.chapters.analyze_chapter_background", AsyncMock(return_value=False)),
            patch(
                "app.services.ai_provider_service.create_routed_ai_service",
                AsyncMock(return_value=object()),
            ),
            patch("app.services.background_task_service.TaskProgressTracker", return_value=object()),
        ):
            ok, error, retryable = await _generate_one_chapter(
                object(),
                pipeline,
                SimpleNamespace(id="chapter-1"),
                "user-1",
                minimum_content_length=1750,
            )

        self.assertFalse(ok)
        self.assertIn("分析", error)
        self.assertFalse(retryable)
        self.assertEqual(generate.await_count, 1)


if __name__ == "__main__":
    unittest.main()
