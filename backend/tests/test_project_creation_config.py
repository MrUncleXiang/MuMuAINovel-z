import json
import unittest
from types import SimpleNamespace

import app.database  # noqa: F401 - initialize model registry
from pydantic import ValidationError

from app.schemas.project_creation_config import ProjectCreationConfigData
from app.services.project_creation_config_service import freeze_project_creation_config


class FakeScalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class FakeSession:
    def __init__(self, scalar_values):
        self.scalar_values = list(scalar_values)

    async def scalar(self, _statement):
        return self.scalar_values.pop(0)

    async def scalars(self, _statement):
        return FakeScalars([])


class ProjectCreationConfigSchemaTests(unittest.TestCase):
    def test_rejects_provider_api_key(self):
        with self.assertRaises(ValidationError):
            ProjectCreationConfigData.model_validate({
                "chapter": {"provider_config_id": "provider-1", "api_key": "secret"}
            })

    def test_rejects_mcp_credentials(self):
        with self.assertRaises(ValidationError):
            ProjectCreationConfigData.model_validate({
                "mcp": {"enabled": True, "headers": {"Authorization": "secret"}}
            })

    def test_nested_defaults_are_independent(self):
        first = ProjectCreationConfigData()
        second = ProjectCreationConfigData()

        first.mcp.plugin_ids.append("plugin-1")

        self.assertEqual(second.mcp.plugin_ids, [])


class ProjectCreationRuntimeSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_freeze_never_exposes_provider_credentials(self):
        config = ProjectCreationConfigData.model_validate({
            "chapter": {"provider_config_id": "provider-1", "model": "chapter-model"},
            "analysis": {"provider_config_id": "provider-2", "model": "analysis-model"},
            "mcp": {"enabled": False, "plugin_ids": []},
        })
        row = SimpleNamespace(
            config_version=3,
            config=config.model_dump(mode="json"),
            updated_at=None,
        )
        chapter_provider = SimpleNamespace(
            id="provider-1",
            name="Chapter Provider",
            protocol="openai",
            default_model="fallback",
            enabled=True,
            api_key="chapter-secret",
        )
        analysis_provider = SimpleNamespace(
            id="provider-2",
            name="Analysis Provider",
            protocol="anthropic",
            default_model="fallback",
            enabled=True,
            api_key="analysis-secret",
        )
        db = FakeSession([
            row,
            chapter_provider,
            analysis_provider,
            chapter_provider,
            analysis_provider,
        ])
        project = SimpleNamespace(id="project-1")

        snapshot = await freeze_project_creation_config(
            db,
            project=project,
            user_id="user-1",
        )
        encoded = json.dumps(snapshot.model_dump(mode="json"))

        self.assertNotIn("chapter-secret", encoded)
        self.assertNotIn("analysis-secret", encoded)
        self.assertEqual(snapshot.chapter.model, "chapter-model")
        self.assertEqual(snapshot.analysis.model, "analysis-model")


if __name__ == "__main__":
    unittest.main()
