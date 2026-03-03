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

    # --- Embedding ---
    embedding_model: str = Field(
        default="nomic-embed-text",
        alias="EMBEDDING_MODEL",
        description="Ollama embedding model for vector generation",
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
        """Resolve a short model key ('local', 'gemini', 'claude') to a LiteLLM model string."""
        model_map = {
            "local": self.default_local_model,
            "gemini": self.default_remote_model,
            "claude": "anthropic/claude-sonnet-4-20250514",
        }
        return model_map.get(model_key, model_key)


# Singleton instance — import this everywhere
settings = Settings()
