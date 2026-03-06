"""
Centralized configuration for PersonalAssist.
All settings are loaded from environment variables via .env file.
"""

import os
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- Model Configuration ---
    default_local_model: str = Field(
        default="ollama/llama3.2",
        alias="DEFAULT_LOCAL_MODEL",
        description="LiteLLM model identifier for local Ollama inference",
    )
    default_remote_model: str = Field(
        default="gemini/gemini-2.0-flash",
        alias="DEFAULT_REMOTE_MODEL",
        description="LiteLLM model identifier for remote inference",
    )

    # --- API Keys (optional) ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # --- Ollama ---
    ollama_api_base: str = Field(
        default="http://localhost:11434",
        alias="OLLAMA_API_BASE",
    )

    # --- Qdrant ---
    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, alias="QDRANT_PORT")
    qdrant_collection: str = Field(
        default="personal_memories", alias="QDRANT_COLLECTION"
    )

    # --- Mem0 ---
    mem0_collection: str = Field(
        default="mem0_memories",
        alias="MEM0_COLLECTION",
        description="Qdrant collection name for Mem0 memories",
    )

    # --- Learning Loop ---
    consolidation_threshold: int = Field(
        default=20,
        alias="CONSOLIDATION_THRESHOLD",
        description="Auto-consolidate memories every N conversation turns",
    )

    # --- Embedding ---
    embedding_model: str = Field(
        default="nomic-embed-text",
        alias="EMBEDDING_MODEL",
        description="Ollama embedding model for vector generation",
    )

    # --- Podcast Agent ---
    podcast_output_dir: str = Field(
        default="~/Downloads",
        alias="PODCAST_OUTPUT_DIR",
        description="Directory to save generated podcast MP3 files",
    )
    tts_provider: str = Field(
        default="edge-tts",
        alias="TTS_PROVIDER",
        description="TTS engine: 'edge-tts' (free) or 'elevenlabs' (premium)",
    )
    elevenlabs_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = Field(
        default="21m00Tcm4TlvDq8ikWAM",
        alias="ELEVENLABS_VOICE_ID",
        description="ElevenLabs voice ID (default: Rachel)",
    )
    podcast_qdrant_collection: str = Field(
        default="podcast_research",
        alias="PODCAST_QDRANT_COLLECTION",
        description="Separate Qdrant collection for podcast research data",
    )
    podcast_max_duration: int = Field(
        default=120,
        alias="PODCAST_MAX_DURATION",
        description="Hard cap on podcast duration in minutes",
    )

    # --- Server ---
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True  # Allow both alias and field name
        extra = "ignore"

    def resolve_model(self, model_key: str) -> str:
        """
        Resolve a model key to a LiteLLM model string.

        Priority: short alias → runtime active model → raw model string.
        """
        # Short aliases always resolve explicitly
        model_map = {
            "local": self.default_local_model,
            "gemini": self.default_remote_model,
            "claude": "anthropic/claude-sonnet-4-20250514",
        }
        if model_key in model_map:
            return model_map[model_key]

        # If "active" is passed, resolve from the registry
        if model_key == "active":
            try:
                from packages.model_gateway.registry import get_active_model
                return get_active_model()
            except ImportError:
                return self.default_local_model

        # Otherwise treat as a raw LiteLLM model string
        return model_key


# Singleton instance — import this everywhere
settings = Settings()
