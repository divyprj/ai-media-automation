"""Unit tests for configuration management."""

import os
from unittest.mock import patch

from src.config import Settings, get_settings


class TestSettings:
    """Test Settings loading, defaults, and environment overrides."""

    def test_default_settings(self):
        settings = Settings()
        assert settings.database_url == "data/ai_media.db"
        assert settings.ollama_base_url == "http://localhost:11434"
        assert settings.ollama_model == "r1:latest"
        assert settings.server_host == "0.0.0.0"
        assert settings.server_port == 8000
        assert settings.log_level == "INFO"
        assert settings.enable_emergency_shutoff is False
        assert settings.x_api_key is None

    def test_environment_variable_override(self):
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "custom_path.db",
                "SERVER_PORT": "9000",
                "ENABLE_EMERGENCY_SHUTOFF": "true",
                "X_API_KEY": "test_key_123",
            },
        ):
            settings = Settings()
            assert settings.database_url == "custom_path.db"
            assert settings.server_port == 9000
            assert settings.enable_emergency_shutoff is True
            assert settings.x_api_key == "test_key_123"

    def test_get_settings_caching(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
