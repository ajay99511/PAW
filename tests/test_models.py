"""
Tests for the dynamic model registry.
"""

import pytest
from packages.model_gateway.registry import (
    ModelInfo,
    _static_remote_models,
    get_active_model,
    set_active_model,
    _EMBEDDING_MODELS,
)
from packages.shared.config import settings


class TestStaticRemoteModels:
    """Tests for static remote model definitions."""

    def test_returns_two_remote_models(self):
        models = _static_remote_models()
        assert len(models) == 2

    def test_includes_gemini(self):
        models = _static_remote_models()
        assert any(m.provider == "gemini" for m in models)

    def test_includes_anthropic(self):
        models = _static_remote_models()
        assert any(m.provider == "anthropic" for m in models)

    def test_all_remote_models_are_not_local(self):
        models = _static_remote_models()
        assert all(not m.is_local for m in models)


class TestActiveModel:
    """Tests for active model get/set logic."""

    def test_defaults_to_config(self):
        # Reset state
        import packages.model_gateway.registry as reg
        reg._active_model = None
        active = get_active_model()
        assert active == settings.default_local_model

    def test_set_and_get(self):
        set_active_model("ollama/codellama:latest")
        assert get_active_model() == "ollama/codellama:latest"
        # Reset
        import packages.model_gateway.registry as reg
        reg._active_model = None

    def test_static_models_reflect_active(self):
        set_active_model("anthropic/claude-sonnet-4-20250514")
        models = _static_remote_models()
        claude = next(m for m in models if m.provider == "anthropic")
        assert claude.is_active is True
        # Reset
        import packages.model_gateway.registry as reg
        reg._active_model = None


class TestResolveModelIntegration:
    """Tests for config.resolve_model with active model support."""

    def test_resolve_local(self):
        assert settings.resolve_model("local") == settings.default_local_model

    def test_resolve_gemini(self):
        assert settings.resolve_model("gemini") == settings.default_remote_model

    def test_resolve_active_uses_registry(self):
        set_active_model("ollama/mistral:latest")
        result = settings.resolve_model("active")
        assert result == "ollama/mistral:latest"
        # Reset
        import packages.model_gateway.registry as reg
        reg._active_model = None

    def test_resolve_passthrough(self):
        assert settings.resolve_model("ollama/phi3.5:latest") == "ollama/phi3.5:latest"


class TestEmbeddingClassification:
    """Tests for embedding model detection."""

    def test_known_embedding_models(self):
        assert "nomic-embed-text" in _EMBEDDING_MODELS
        assert "all-minilm" in _EMBEDDING_MODELS

    def test_chat_models_not_classified_as_embedding(self):
        assert "llama3.2" not in _EMBEDDING_MODELS
        assert "codellama" not in _EMBEDDING_MODELS
        assert "mistral" not in _EMBEDDING_MODELS
