"""
Tests for the TTS tool.

Validates provider factory, FFmpeg detection, and synthesis logic.
Tests that don't require network/service access.
"""

import asyncio
import shutil
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from packages.tools.tts import (
    EdgeTTSProvider,
    ElevenLabsProvider,
    TTSProvider,
    get_tts_provider,
    _check_ffmpeg,
)


# ── Provider Factory Tests ──────────────────────────────────────────


class TestProviderFactory:
    """Test TTS provider selection based on config."""

    def test_default_is_edge_tts(self):
        mock_settings = MagicMock()
        mock_settings.tts_provider = "edge-tts"
        mock_settings.elevenlabs_api_key = ""

        with patch("packages.tools.tts.settings", mock_settings, create=True):
            with patch("packages.shared.config.settings", mock_settings):
                provider = get_tts_provider()
                assert isinstance(provider, EdgeTTSProvider)

    def test_elevenlabs_provider_requires_key(self):
        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
            ElevenLabsProvider(api_key="", voice_id="test")

    def test_elevenlabs_provider_accepts_key(self):
        provider = ElevenLabsProvider(api_key="sk-test-key", voice_id="voice123")
        assert provider.api_key == "sk-test-key"
        assert provider.voice_id == "voice123"

    def test_edge_tts_default_voice(self):
        provider = EdgeTTSProvider()
        assert provider.voice == "en-US-GuyNeural"

    def test_edge_tts_custom_voice(self):
        provider = EdgeTTSProvider(voice="en-US-JennyNeural")
        assert provider.voice == "en-US-JennyNeural"


# ── FFmpeg Detection Tests ──────────────────────────────────────────


class TestFFmpegDetection:
    """Test FFmpeg availability checks."""

    def test_ffmpeg_found(self):
        # Should find FFmpeg (we confirmed it's installed)
        result = _check_ffmpeg()
        assert result is not None
        assert "ffmpeg" in result.lower()

    def test_ffmpeg_missing_raises(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="FFmpeg is required"):
                _check_ffmpeg()


# ── Provider Abstraction Tests ──────────────────────────────────────


class TestTTSProviderAbstraction:
    """Test that both providers implement the same interface."""

    def test_edge_tts_is_tts_provider(self):
        assert issubclass(EdgeTTSProvider, TTSProvider)

    def test_elevenlabs_is_tts_provider(self):
        assert issubclass(ElevenLabsProvider, TTSProvider)

    def test_providers_have_synthesize_method(self):
        edge = EdgeTTSProvider()
        assert hasattr(edge, "synthesize")
        assert asyncio.iscoroutinefunction(edge.synthesize)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
