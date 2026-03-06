"""
TTS Tool — Text-to-Speech with provider abstraction.

Supports:
  - edge-tts   (free, no API key, Microsoft Azure voices)
  - elevenlabs (premium, API key required, high-quality)

The provider is selected via the TTS_PROVIDER config setting.
Audio stitching uses FFmpeg (must be installed on the system).

Usage:
    from packages.tools.tts import synthesize_script, stitch_audio

    audio_files = await synthesize_script(paragraphs, output_dir)
    final = await stitch_audio(audio_files, Path("~/Downloads/podcast.mp3"))
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Provider Abstraction ─────────────────────────────────────────────


class TTSProvider(ABC):
    """Abstract base for TTS providers."""

    @abstractmethod
    async def synthesize(self, text: str, output_path: Path) -> Path:
        """
        Convert text to speech and save as an audio file.

        Args:
            text: The text to synthesize.
            output_path: Where to save the audio file.

        Returns:
            The path to the saved audio file.
        """
        ...


class EdgeTTSProvider(TTSProvider):
    """
    Free TTS using Microsoft Edge's online TTS service.

    No API key required. Decent quality for podcast-style content.
    """

    def __init__(self, voice: str = "en-US-GuyNeural"):
        self.voice = voice

    async def synthesize(self, text: str, output_path: Path) -> Path:
        import edge_tts

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        communicate = edge_tts.Communicate(text, self.voice)
        await communicate.save(str(output_path))

        logger.info("EdgeTTS synthesized %d chars -> %s", len(text), output_path)
        return output_path


class ElevenLabsProvider(TTSProvider):
    """
    Premium TTS using ElevenLabs API.

    Requires ELEVENLABS_API_KEY and optional ELEVENLABS_VOICE_ID in config.
    """

    def __init__(self, api_key: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM"):
        if not api_key:
            raise ValueError(
                "ElevenLabs requires ELEVENLABS_API_KEY. "
                "Set it in .env or switch TTS_PROVIDER to 'edge-tts'."
            )
        self.api_key = api_key
        self.voice_id = voice_id

    async def synthesize(self, text: str, output_path: Path) -> Path:
        from elevenlabs.client import AsyncElevenLabs

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        client = AsyncElevenLabs(api_key=self.api_key)
        audio_generator = await client.text_to_speech.convert(
            voice_id=self.voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )

        # Write chunks to file
        with open(output_path, "wb") as f:
            async for chunk in audio_generator:
                f.write(chunk)

        logger.info("ElevenLabs synthesized %d chars -> %s", len(text), output_path)
        return output_path


# ── Factory ──────────────────────────────────────────────────────────


def get_tts_provider() -> TTSProvider:
    """
    Create a TTS provider based on config settings.

    Returns EdgeTTSProvider by default. Switches to ElevenLabs if
    TTS_PROVIDER="elevenlabs" and ELEVENLABS_API_KEY is set.
    """
    from packages.shared.config import settings

    provider_name = getattr(settings, "tts_provider", "edge-tts").lower()

    if provider_name == "elevenlabs":
        api_key = getattr(settings, "elevenlabs_api_key", "")
        voice_id = getattr(settings, "elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
        return ElevenLabsProvider(api_key=api_key, voice_id=voice_id)
    else:
        return EdgeTTSProvider()


# ── High-Level API ───────────────────────────────────────────────────


def _check_ffmpeg() -> str:
    """Check that FFmpeg is available and return its path."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg is required for audio stitching but was not found. "
            "Install it from https://ffmpeg.org/download.html and ensure "
            "it is on your system PATH."
        )
    return ffmpeg


async def synthesize_script(
    paragraphs: list[str],
    output_dir: Path,
    provider: TTSProvider | None = None,
    max_concurrent: int = 4,
) -> list[Path]:
    """
    Synthesize a list of text paragraphs into individual audio files.

    Uses asyncio.Semaphore for controlled parallelism to avoid
    overwhelming the TTS service.

    Args:
        paragraphs: List of text paragraphs to synthesize.
        output_dir:  Directory to save audio segment files.
        provider:    TTS provider (auto-detected from config if None).
        max_concurrent: Max parallel synthesis tasks.

    Returns:
        Ordered list of audio file paths.
    """
    if provider is None:
        provider = get_tts_provider()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _synth_one(idx: int, text: str) -> Path:
        async with semaphore:
            filename = f"segment_{idx:04d}.mp3"
            out_path = output_dir / filename
            return await provider.synthesize(text, out_path)

    tasks = [_synth_one(i, p) for i, p in enumerate(paragraphs) if p.strip()]
    results = await asyncio.gather(*tasks)

    logger.info("Synthesized %d segments to %s", len(results), output_dir)
    return list(results)


async def stitch_audio(
    audio_files: list[Path],
    output_path: Path,
) -> Path:
    """
    Concatenate multiple audio files into one MP3 using FFmpeg.

    Uses the FFmpeg concat demuxer for lossless concatenation.

    Args:
        audio_files: Ordered list of audio file paths to concatenate.
        output_path: Where to save the final MP3.

    Returns:
        Path to the final stitched audio file.
    """
    ffmpeg = _check_ffmpeg()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Create a temporary concat list file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for af in audio_files:
            # FFmpeg concat requires escaped paths
            escaped = str(af).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        concat_list = f.name

    try:
        cmd = [
            ffmpeg,
            "-y",                          # overwrite output
            "-f", "concat",                # concat demuxer
            "-safe", "0",                  # allow absolute paths
            "-i", concat_list,             # input list
            "-c", "copy",                  # stream copy (fast, lossless)
            output_path.as_posix(),
        ]

        import subprocess
        
        process = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            check=False,
        )
        stdout = process.stdout
        stderr = process.stderr

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else str(stderr)
            raise RuntimeError(f"FFmpeg failed (exit {process.returncode}): {error_msg}")

        logger.info(
            "Stitched %d files -> %s (%.1f MB)",
            len(audio_files),
            output_path,
            output_path.stat().st_size / (1024 * 1024),
        )
        return output_path

    finally:
        # Cleanup temp concat list
        try:
            Path(concat_list).unlink()
        except OSError:
            pass
