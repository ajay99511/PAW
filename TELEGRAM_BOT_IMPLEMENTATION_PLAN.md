# Telegram Bot Implementation Plan (Consolidated)

**Version:** 2.0 - Consolidated with Agent Routing
**Date:** March 28, 2026
**Status:** Ready for Implementation
**Total Effort:** 24-34 hours (infrastructure + agent routing)

---

## 📋 **Executive Summary**

This plan consolidates:
1. **Infrastructure fixes** (Requirements 1-5) - Config persistence, hot-reload, status, UI feedback
2. **Agent routing** (Requirements 6-7) - Agent selection, command routing, result formatting
3. **Technical review fixes** - 7 critical issues addressed

**Key Changes from Original Plan:**
- ✅ All 7 critical issues from technical review incorporated
- ✅ Agent routing and formatting added (Requirements 6-7)
- ✅ Lifespan integration for proper startup/shutdown
- ✅ Token redaction for security
- ✅ Deeper A2A registry integration

---

## 🏗️ **Architecture Overview**

### **Component Diagram**

```
┌─────────────────────────────────────────────────────────────────┐
│                        Telegram User                            │
└────────────────────────┬────────────────────────────────────────┘
                         │ Telegram Message
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   TelegramBotService                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  CommandHandler  │  MessageHandler  │  StatusTracker    │   │
│  └──────────────────┴──────────────────┴───────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┐
         │                               │
         ▼                               ▼
┌─────────────────────┐       ┌─────────────────────┐
│   Agent_Router      │       │   Bot_Manager       │
│  - Route to agent   │       │  - Start/Stop/Reload│
│  - Per-user state   │       │  - Status tracking  │
└─────────┬───────────┘       └─────────┬───────────┘
          │                             │
          ▼                             ▼
┌─────────────────────┐       ┌─────────────────────┐
│   A2A Registry      │       │   Config_Store      │
│  - Agent discovery  │       │  - Persist config   │
│  - Delegate calls   │       │  - Load on startup  │
└─────────┬───────────┘       └─────────────────────┘
          │
          ▼
┌─────────────────────┐
│  Agent_Formatter    │
│  - JSON → Text      │
│  - Severity order   │
│  - Chunking         │
└─────────────────────┘
```

### **Data Flow: Message → Agent → Response**

```
1. User sends: "Review my code in src/auth.py"
                ↓
2. TelegramBotService.handle_message()
                ↓
3. Agent_Router.get_user_agent(telegram_id) → "code-reviewer"
                ↓
4. A2A_Registry.delegate_to_agent("code-reviewer", task="Review...")
                ↓
5. Agent executes, returns: {findings: [...], scores: {...}}
                ↓
6. Agent_Formatter.format(result) → Readable text
                ↓
7. TelegramBotService.send_chunked_response(text)
                ↓
8. User receives formatted response (split if >4096 chars)
```

---

## 🎯 **Implementation Phases**

### **Phase 1: Config_Store (2-3 hours)**

**File:** `packages/messaging/config_store.py` (NEW)

**Purpose:** Persist bot token and DM policy to `~/.personalassist/telegram_config.env`

**Key Features:**
- Atomic writes (temp file + `os.replace`)
- Token validation (regex pattern)
- Graceful handling of missing file
- Token redaction in logs

**Implementation:**
```python
"""
Telegram Configuration Store

Persists bot configuration to ~/.personalassist/telegram_config.env
Uses atomic writes and token redaction.
"""

import os
import re
import tempfile
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

# Telegram bot token pattern (official format)
TELEGRAM_TOKEN_PATTERN = re.compile(r'^\d+:[A-Za-z0-9_-]{35,}$')


class TelegramConfig(TypedDict, total=False):
    """Telegram configuration with optional fields."""
    bot_token: str
    dm_policy: str


class ConfigStore:
    """Persistent storage for Telegram bot configuration."""
    
    def __init__(self):
        self.config_dir = Path.home() / ".personalassist"
        self.config_file = self.config_dir / "telegram_config.env"
    
    def validate_token(self, token: str) -> bool:
        """
        Validate Telegram bot token format.
        
        Returns True if token is empty or matches pattern.
        """
        if not token:
            return True  # Empty is valid (no token)
        return bool(TELEGRAM_TOKEN_PATTERN.match(token))
    
    def save(self, token: str, dm_policy: str) -> None:
        """
        Atomically save configuration.
        
        Args:
            token: Bot token (can be empty)
            dm_policy: DM policy (pairing|allowlist|open)
            
        Raises:
            ValueError: If token format is invalid
            OSError: If file write fails
        """
        # Validate token format
        if not self.validate_token(token):
            raise ValueError(
                f"Invalid bot token format. Expected pattern: {TELEGRAM_TOKEN_PATTERN.pattern}"
            )
        
        # Ensure directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Atomic write: temp file + rename
        fd, temp_path = tempfile.mkstemp(
            suffix='.env',
            prefix='telegram_',
            dir=self.config_dir,
        )
        
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                if token:
                    f.write(f"TELEGRAM_BOT_TOKEN={token}\n")
                f.write(f"TELEGRAM_DM_POLICY={dm_policy}\n")
            
            # Atomic rename (works on Windows)
            os.replace(temp_path, self.config_file)
            logger.info("Saved Telegram configuration")
            
        except Exception:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    
    def load(self) -> TelegramConfig:
        """
        Load configuration from file.
        
        Returns:
            Dict with bot_token and/or dm_policy keys if present.
            Empty dict if file doesn't exist.
        """
        if not self.config_file.exists():
            logger.debug("No Telegram config file found")
            return {}
        
        try:
            config = {}
            with open(self.config_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            config[key.strip()] = value.strip()
            
            result: TelegramConfig = {}
            if "TELEGRAM_BOT_TOKEN" in config:
                result["bot_token"] = config["TELEGRAM_BOT_TOKEN"]
            if "TELEGRAM_DM_POLICY" in config:
                result["dm_policy"] = config["TELEGRAM_DM_POLICY"]
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to load Telegram config: {e}")
            return {}
```

**Tests:**
- `test_validate_token_valid()` - Valid tokens pass
- `test_validate_token_invalid()` - Invalid tokens fail
- `test_save_load_round_trip()` - Written config reads back correctly
- `test_load_missing_file()` - Returns empty dict, doesn't crash
- `test_atomic_write_on_error()` - Temp file cleaned up on failure

---

### **Phase 2: Token Redaction (1-2 hours)**

**File:** `packages/shared/redaction.py` (EXTEND)

**Purpose:** Prevent bot token from appearing in logs (Requirement 1.4)

**Implementation:**
```python
# Add to existing redaction patterns in packages/shared/redaction.py

TELEGRAM_TOKEN_PATTERN = re.compile(r'\b\d+:[A-Za-z0-9_-]{35,}\b')

def redact_telegram_tokens(text: str) -> str:
    """Redact Telegram bot tokens from text."""
    return TELEGRAM_TOKEN_PATTERN.sub('[TELEGRAM_TOKEN_REDACTED]', text)


# Add logging filter class
class TelegramTokenFilter(logging.Filter):
    """Filter that redacts Telegram tokens from log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Redact tokens from message and args."""
        if isinstance(record.msg, str):
            record.msg = redact_telegram_tokens(record.msg)
        if record.args:
            record.args = tuple(
                redact_telegram_tokens(str(arg)) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


# Usage in telegram_bot.py and bot_manager.py
logger = logging.getLogger(__name__)
logger.addFilter(TelegramTokenFilter())
```

**Tests:**
- `test_redact_token_in_message()` - Token replaced with `[TELEGRAM_TOKEN_REDACTED]`
- `test_redact_token_in_args()` - Token in log args redacted
- `test_no_redact_normal_text()` - Normal text unchanged

---

### **Phase 3: TelegramBotService Refactor (4-5 hours)**

**File:** `packages/messaging/telegram_bot.py` (REFACTOR)

**Purpose:** Enable external lifecycle control, add agent routing hooks

**Key Changes:**
1. Token and DM policy as constructor parameters
2. Add `stop()` method (idempotent)
3. Add status tracking (state, started_at, error_message)
4. Add `update_dm_policy()` method
5. Add agent routing integration points
6. Add structured logging

**Implementation (Key Sections):**
```python
class TelegramBotService:
    """Telegram bot service for PersonalAssist."""
    
    def __init__(
        self,
        token: str,
        dm_policy: str = "pairing",
        agent_router: Optional['AgentRouter'] = None,
    ):
        self.token = token
        self.dm_policy = dm_policy
        self.agent_router = agent_router
        
        # Status tracking
        self.state = "stopped"
        self.started_at: Optional[datetime] = None
        self.error_message: Optional[str] = None
        
        # Application state
        self.application: Optional[Application] = None
        self.auth_store = get_auth_store()
        self.api_base = f"http://{API_BASE_URL}:{API_PORT}"
        
        # Structured logging with token redaction
        self.logger = logging.getLogger(__name__)
        self.logger.addFilter(TelegramTokenFilter())
    
    async def start(self) -> None:
        """Start the bot polling loop."""
        self.state = "starting"
        self.logger.info("Starting Telegram bot...")
        
        try:
            if not self.token:
                raise ValueError("Bot token not provided")
            
            # Build application
            self.application = (
                Application.builder()
                .token(self.token)
                .build()
            )
            
            # Add handlers
            self._setup_handlers()
            
            # Initialize and start
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            self.state = "running"
            self.started_at = datetime.now()
            self.logger.info(
                "Telegram bot started",
                extra={
                    "event": "bot_started",
                    "dm_policy": self.dm_policy,
                }
            )
            
        except Exception as e:
            self.state = "error"
            self.error_message = str(e)
            self.logger.error(f"Failed to start Telegram bot: {e}")
            raise
    
    async def stop(self) -> None:
        """
        Stop the bot polling loop.
        
        Idempotent: safe to call multiple times.
        """
        if self.state == "stopped":
            return
        
        self.state = "stopping"
        self.logger.info("Stopping Telegram bot...")
        
        try:
            if self.application:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            
            self.state = "stopped"
            self.logger.info("Telegram bot stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping bot: {e}")
            raise
    
    def update_dm_policy(self, dm_policy: str) -> None:
        """
        Update DM policy without restart.
        
        Args:
            dm_policy: New DM policy (pairing|allowlist|open)
        """
        self.dm_policy = dm_policy
        self.logger.info(f"Updated DM policy to: {dm_policy}")
    
    def _setup_handlers(self) -> None:
        """Set up command and message handlers."""
        if not self.application:
            return
        
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("new", self.new_command))
        
        # Agent routing commands (Requirement 6)
        self.application.add_handler(CommandHandler("agents", self.agents_command))
        self.application.add_handler(CommandHandler("agent", self.agent_command))
        
        # Message handler
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages with agent routing."""
        if not update.message or not update.message.text:
            return
        
        telegram_id = str(update.effective_user.id)
        user_message = update.message.text
        
        self.logger.info(f"Received message from {telegram_id}: {user_message[:50]}...")
        
        # Check authentication
        if not self.auth_store.is_approved(telegram_id):
            await update.message.reply_text(
                "🔐 Your account is pending approval. "
                f"Please contact the administrator with code: `{telegram_id}`"
            )
            return
        
        # Check rate limit
        if _rate_limiter.is_rate_limited(telegram_id):
            await update.message.reply_text(
                "⏳ Rate limit exceeded. Please wait a moment before sending more messages."
            )
            return
        
        # Update last message time
        if telegram_id in self.auth_store.auth_data:
            self.auth_store.auth_data[telegram_id]["last_message_at"] = datetime.now().isoformat()
            self.auth_store.save()
        
        # Get user_id
        user_id = self.auth_store.get_user_id(telegram_id) or "default"
        
        # Show typing indicator
        await update.message.chat.send_action(action="typing")
        
        try:
            # Route to agent (Requirement 6)
            if self.agent_router:
                response = await self.agent_router.route_message(
                    user_id=user_id,
                    telegram_id=telegram_id,
                    message=user_message,
                )
            else:
                # Fallback to smart chat
                response = await self.call_agent_api(user_id, user_message)
            
            # Send response (chunk if long)
            await self.send_chunked_response(update, response)
            
        except Exception as exc:
            self.logger.error(f"Failed to process message: {exc}")
            await update.message.reply_text(
                "⚠️ Sorry, I encountered an error processing your message. "
                "Please try again in a moment."
            )
    
    # ... [agent command handlers in Phase 6] ...
```

**Tests:**
- `test_start_stop_lifecycle()` - Start and stop without errors
- `test_stop_idempotent()` - Multiple stops don't crash
- `test_update_dm_policy()` - Policy changes without restart
- `test_status_tracking()` - State, started_at, error_message tracked
- `test_handle_message_with_agent_router()` - Routes to agent correctly

---

### **Phase 4: Agent_Router (3-4 hours)**

**File:** `packages/messaging/agent_router.py` (NEW)

**Purpose:** Route messages to selected agent, manage per-user agent state

**Implementation:**
```python
"""
Agent Router

Routes Telegram messages to the correct agent based on per-user selection.
Integrates with A2A registry for agent discovery and delegation.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AgentRouter:
    """
    Routes messages to agents based on per-user selection.
    
    Features:
    - Per-user agent selection (persists across restarts)
    - Integration with A2A registry
    - Fallback to smart-chat
    """
    
    def __init__(self, a2a_registry=None):
        """
        Initialize agent router.
        
        Args:
            a2a_registry: A2A registry instance for agent discovery
        """
        self.a2a_registry = a2a_registry
        self.logger = logging.getLogger(__name__)
    
    def get_user_agent(self, telegram_id: str) -> str:
        """
        Get the agent selected by a user.
        
        Args:
            telegram_id: User's Telegram ID
            
        Returns:
            Agent ID (default: "smart-chat")
        """
        from packages.messaging.telegram_bot import get_auth_store
        
        auth_store = get_auth_store()
        user_data = auth_store.auth_data.get(telegram_id, {})
        return user_data.get("selected_agent", "smart-chat")
    
    def set_user_agent(self, telegram_id: str, agent_id: str) -> bool:
        """
        Set the agent for a user.
        
        Args:
            telegram_id: User's Telegram ID
            agent_id: Agent ID to select
            
        Returns:
            True if agent was set successfully
        """
        from packages.messaging.telegram_bot import get_auth_store
        
        auth_store = get_auth_store()
        
        # Add user if not exists
        if telegram_id not in auth_store.auth_data:
            auth_store.add_user(telegram_id)
        
        # Set agent selection
        auth_store.auth_data[telegram_id]["selected_agent"] = agent_id
        auth_store.save()
        
        self.logger.info(f"Set agent {agent_id} for user {telegram_id}")
        return True
    
    def list_available_agents(self) -> list[dict[str, str]]:
        """
        List all available agents.
        
        Returns:
            List of agents with id, name, description
        """
        agents = []
        
        # Add smart-chat as default
        agents.append({
            "id": "smart-chat",
            "name": "Smart Chat",
            "description": "Default conversational AI with memory",
        })
        
        # Add A2A agents from registry
        if self.a2a_registry:
            try:
                registry_agents = self.a2a_registry.list_agents()
                for agent in registry_agents:
                    agents.append({
                        "id": agent.get("id", "unknown"),
                        "name": agent.get("name", "Unknown"),
                        "description": agent.get("description", "No description"),
                    })
            except Exception as e:
                self.logger.error(f"Failed to list A2A agents: {e}")
        
        return agents
    
    async def route_message(
        self,
        user_id: str,
        telegram_id: str,
        message: str,
    ) -> str:
        """
        Route a message to the user's selected agent.
        
        Args:
            user_id: Internal user ID
            telegram_id: User's Telegram ID
            message: User's message text
            
        Returns:
            Agent response text
            
        Raises:
            Exception: If agent call fails
        """
        agent_id = self.get_user_agent(telegram_id)
        self.logger.info(f"Routing message to agent: {agent_id}")
        
        try:
            if agent_id == "smart-chat":
                # Use smart chat endpoint
                return await self.call_smart_chat(user_id, message)
            else:
                # Use A2A registry
                return await self.call_a2a_agent(agent_id, user_id, message)
                
        except Exception as e:
            self.logger.error(f"Agent {agent_id} failed: {e}")
            raise
    
    async def call_smart_chat(self, user_id: str, message: str) -> str:
        """Call the smart chat endpoint."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.api_base}/chat/smart",
                    json={
                        "message": message,
                        "model": "local",
                        "thread_id": None,
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("response", "I don't have a response for that.")
                
            except httpx.TimeoutException:
                return "⏱️ The request timed out. Please try again."
            except httpx.HTTPError as exc:
                return f"⚠️ API error: {str(exc)[:200]}"
    
    async def call_a2a_agent(
        self,
        agent_id: str,
        user_id: str,
        task: str,
    ) -> str:
        """
        Call an A2A agent via the registry.
        
        Args:
            agent_id: Agent ID from registry
            user_id: Internal user ID
            task: Task description
            
        Returns:
            Formatted agent response
        """
        if not self.a2a_registry:
            raise ValueError("A2A registry not available")
        
        # Delegate to agent
        result = await self.a2a_registry.delegate_to_agent(
            agent_id=agent_id,
            task=task,
            user_id=user_id,
        )
        
        # Format result (Phase 5)
        from packages.messaging.agent_formatter import AgentFormatter
        formatter = AgentFormatter()
        return formatter.format(result, agent_id)
```

**Tests:**
- `test_get_user_agent_default()` - Returns "smart-chat" for new users
- `test_set_user_agent()` - Persists agent selection
- `test_list_available_agents()` - Includes smart-chat + A2A agents
- `test_route_message_to_smart_chat()` - Routes correctly
- `test_route_message_to_a2a_agent()` - Delegates to registry

---

### **Phase 5: Agent_Formatter (3-4 hours)**

**File:** `packages/messaging/agent_formatter.py` (NEW)

**Purpose:** Convert structured A2A agent JSON output to readable text

**Implementation:**
```python
"""
Agent Formatter

Converts structured A2A agent results into human-readable text for Telegram.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AgentFormatter:
    """
    Formats A2A agent results for Telegram.
    
    Features:
    - Findings sorted by severity
    - Scores as labelled values
    - Recommendations as bullet points
    - Metrics as key-value pairs
    - Chunking support (preserves structure)
    """
    
    SEVERITY_ORDER = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
        "info": 4,
    }
    
    def format(self, result: dict[str, Any], agent_id: str) -> str:
        """
        Format an A2A agent result.
        
        Args:
            result: Agent result dict (findings, scores, etc.)
            agent_id: Agent ID for error messages
            
        Returns:
            Formatted text response
        """
        # Handle failed tasks
        if result.get("status") == "failed":
            error = result.get("error", "Unknown error")
            return f"❌ **Agent {agent_id} Failed**\n\n{error}"
        
        sections = []
        
        # Summary (first paragraph)
        if "summary" in result and result["summary"]:
            sections.append(result["summary"])
        
        # Findings (sorted by severity)
        if "findings" in result and result["findings"]:
            findings_text = self._format_findings(result["findings"])
            sections.append(findings_text)
        
        # Scores (labelled values)
        if "scores" in result and result["scores"]:
            scores_text = self._format_scores(result["scores"])
            sections.append(scores_text)
        
        # Metrics (key-value pairs)
        if "metrics" in result and result["metrics"]:
            metrics_text = self._format_metrics(result["metrics"])
            sections.append(metrics_text)
        
        # Recommendations (bullet points)
        if "recommendations" in result and result["recommendations"]:
            recs_text = self._format_recommendations(result["recommendations"])
            sections.append(recs_text)
        
        # Join sections
        if not sections:
            return f"✅ **Agent {agent_id} Completed**\n\nNo specific findings."
        
        return "\n\n".join(sections)
    
    def _format_findings(self, findings: list[dict[str, Any]]) -> str:
        """Format findings array, sorted by severity."""
        # Sort by severity (critical first)
        sorted_findings = sorted(
            findings,
            key=lambda f: self.SEVERITY_ORDER.get(f.get("severity", "info").lower(), 4),
        )
        
        lines = ["📋 **Findings:**"]
        for i, finding in enumerate(sorted_findings, 1):
            severity = finding.get("severity", "unknown").upper()
            file_loc = finding.get("file", "")
            if finding.get("line"):
                file_loc += f":{finding['line']}"
            message = finding.get("message", "")
            
            # Severity emoji
            emoji = {
                "CRITICAL": "🔴",
                "HIGH": "🟠",
                "MEDIUM": "🟡",
                "LOW": "🔵",
                "INFO": "⚪",
            }.get(severity, "⚪")
            
            lines.append(f"{i}. {emoji} **{severity}** {file_loc}: {message}")
        
        return "\n".join(lines)
    
    def _format_scores(self, scores: dict[str, Any]) -> str:
        """Format scores object as labelled values."""
        lines = ["📊 **Scores:**"]
        for key, value in scores.items():
            # Format key (capitalize)
            label = key.replace("_", " ").title()
            lines.append(f"• {label}: {value}/100")
        return "\n".join(lines)
    
    def _format_metrics(self, metrics: dict[str, Any]) -> str:
        """Format metrics object as key-value pairs."""
        lines = ["📈 **Metrics:**"]
        for key, value in metrics.items():
            label = key.replace("_", " ").title()
            lines.append(f"• {label}: {value}")
        return "\n".join(lines)
    
    def _format_recommendations(self, recommendations: list[str]) -> str:
        """Format recommendations array as bullet points."""
        lines = ["💡 **Recommendations:**"]
        for rec in recommendations:
            lines.append(f"• {rec}")
        return "\n".join(lines)
```

**Tests:**
- `test_format_findings_sorted_by_severity()` - Critical findings first
- `test_format_scores_labelled()` - Scores as "Security: 82/100"
- `test_format_recommendations_bullets()` - Bullet points
- `test_format_failed_task()` - Error message with agent ID
- `test_format_empty_result()` - Graceful handling
- `test_round_trip_content_integrity()` - All findings/scores/recs preserved

---

### **Phase 6: Bot_Manager (5-6 hours)**

**File:** `packages/messaging/bot_manager.py` (NEW)

**Purpose:** Own bot lifecycle, coordinate with API, expose status

**Implementation:**
```python
"""
Bot Manager

Owns the TelegramBotService lifecycle and coordinates with API.
Provides singleton pattern with lifespan integration.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Singleton Pattern
# ─────────────────────────────────────────────────────────────────────

_bot_manager: Optional['BotManager'] = None
_initialized = False


def get_bot_manager() -> 'BotManager':
    """Get or create the global bot manager singleton."""
    global _bot_manager
    if _bot_manager is None:
        _bot_manager = BotManager()
    return _bot_manager


async def initialize_bot_manager() -> None:
    """Initialize bot manager at API startup."""
    global _bot_manager, _initialized
    
    if _initialized:
        logger.warning("Bot manager already initialized")
        return
    
    _bot_manager = get_bot_manager()
    
    # Load config and auto-start bot
    from packages.messaging.config_store import ConfigStore
    store = ConfigStore()
    config = store.load()
    
    token = config.get("bot_token")
    dm_policy = config.get("dm_policy", "pairing")
    
    if token:
        try:
            await _bot_manager.start(token, dm_policy)
            logger.info("Telegram bot auto-started with saved config")
        except Exception as e:
            logger.error(f"Failed to auto-start Telegram bot: {e}")
    else:
        logger.info("No saved bot token, bot not started")
    
    _initialized = True


async def shutdown_bot_manager() -> None:
    """Shutdown bot manager at API shutdown."""
    global _bot_manager
    
    if _bot_manager:
        try:
            await _bot_manager.stop()
            logger.info("Telegram bot manager shut down")
        except Exception as e:
            logger.error(f"Error shutting down bot manager: {e}")


# ─────────────────────────────────────────────────────────────────────
# Bot Manager Class
# ─────────────────────────────────────────────────────────────────────

class BotManager:
    """
    Manages TelegramBotService lifecycle.
    
    Features:
    - Start/Stop/Reload
    - Status tracking
    - Debounced reloads
    - Error recovery
    """
    
    def __init__(self):
        self.bot_service = None
        self.task: Optional[asyncio.Task] = None
        self.config = {}
        
        # Control
        self._stop_event = asyncio.Event()
        self._reload_lock = asyncio.Lock()
        self._last_reload_time = 0
    
    async def start(self, token: str, dm_policy: str = "pairing") -> None:
        """
        Start bot with configuration.
        
        Args:
            token: Bot token
            dm_policy: DM policy (pairing|allowlist|open)
        """
        if self.task and not self.task.done():
            logger.warning("Bot already running, ignoring start request")
            return
        
        self.config = {"bot_token": token, "dm_policy": dm_policy}
        
        # Create agent router
        from packages.messaging.agent_router import AgentRouter
        from packages.agents.a2a.registry import get_a2a_registry
        
        try:
            registry = get_a2a_registry()
            agent_router = AgentRouter(registry)
        except Exception as e:
            logger.warning(f"A2A registry not available, agent routing disabled: {e}")
            agent_router = None
        
        # Create bot service
        from packages.messaging.telegram_bot import TelegramBotService
        self.bot_service = TelegramBotService(
            token=token,
            dm_policy=dm_policy,
            agent_router=agent_router,
        )
        
        # Start bot loop
        self._stop_event.clear()
        self.task = asyncio.create_task(self._run_bot_loop())
        logger.info("Bot manager start request completed")
    
    async def _run_bot_loop(self) -> None:
        """Run bot with restart capability."""
        while not self._stop_event.is_set():
            try:
                await self.bot_service.start()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Bot crashed: {e}")
                if self.bot_service:
                    self.bot_service.state = "error"
                    self.bot_service.error_message = str(e)
                # Don't auto-restart on error - wait for explicit reload
                break
    
    async def stop(self) -> None:
        """Stop the bot."""
        self._stop_event.set()
        
        if self.bot_service:
            await self.bot_service.stop()
        
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        self.bot_service = None
        self.task = None
    
    async def reload(self, token: str, dm_policy: str) -> None:
        """
        Reload bot with new configuration (debounced).
        
        Args:
            token: New bot token
            dm_policy: New DM policy
        """
        async with self._reload_lock:
            # Debounce: ignore reloads within 2 seconds
            now = datetime.now().timestamp()
            if now - self._last_reload_time < 2:
                logger.info("Ignoring rapid reload request (debouncing)")
                return
            
            self._last_reload_time = now
            
            logger.info(f"Reloading bot with new config (dm_policy={dm_policy})")
            
            # Stop existing
            if self.bot_service:
                await self.stop()
            
            # Start new
            await self.start(token, dm_policy)
    
    def update_dm_policy(self, dm_policy: str) -> None:
        """
        Update DM policy in running bot service.
        
        Args:
            dm_policy: New DM policy
        """
        self.config["dm_policy"] = dm_policy
        if self.bot_service:
            self.bot_service.update_dm_policy(dm_policy)
        logger.info(f"Updated DM policy to: {dm_policy}")
    
    def get_status(self) -> dict:
        """Get current bot status."""
        if not self.bot_service:
            return {"state": "stopped"}
        
        status = {
            "state": self.bot_service.state,
            "dm_policy": self.bot_service.dm_policy,
        }
        
        if self.bot_service.state == "error" and self.bot_service.error_message:
            status["error_message"] = self.bot_service.error_message
        elif self.bot_service.state == "running" and self.bot_service.started_at:
            status["started_at"] = self.bot_service.started_at.isoformat()
        
        return status
```

**Tests:**
- `test_singleton_pattern()` - get_bot_manager returns same instance
- `test_start_stop_lifecycle()` - Start and stop cleanly
- `test_reload_debouncing()` - Rapid reloads ignored
- `test_get_status_running()` - Returns state, started_at
- `test_get_status_error()` - Returns error_message
- `test_update_dm_policy_propagates()` - Changes reach bot service

---

### **Phase 7: API Endpoints (3-4 hours)**

**File:** `apps/api/main.py` (UPDATE)

**Purpose:** Add `/telegram/status`, update `/telegram/config`, add health integration

**Implementation:**
```python
# Add to apps/api/main.py

# ── Telegram Status Endpoint ─────────────────────────────────────────

@app.get("/telegram/status")
async def get_telegram_status():
    """
    Get current Telegram bot status.
    
    Returns:
        Bot state: stopped, starting, running, reloading, error
    """
    try:
        from packages.messaging.bot_manager import get_bot_manager
        manager = get_bot_manager()
        return manager.get_status()
    except Exception as exc:
        logger.error("Get Telegram status error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Update Telegram Config Endpoint ─────────────────────────────────

class TelegramConfigInput(BaseModel):
    """Input model for Telegram config update."""
    bot_token: str = Field(default="", description="Bot token (empty to preserve existing)")
    dm_policy: str = Field(default="pairing", description="DM policy")


@app.post("/telegram/config")
async def update_telegram_config(config: TelegramConfigInput):
    """
    Update Telegram configuration with persistence and hot-reload.
    
    Returns:
        status: "reloading" (token changed) or "saved" (DM policy only)
    """
    try:
        from packages.messaging.config_store import ConfigStore
        from packages.messaging.bot_manager import get_bot_manager
        
        # Validate token format
        store = ConfigStore()
        if not store.validate_token(config.bot_token):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid bot token format. Expected pattern: {store.TELEGRAM_TOKEN_PATTERN.pattern}"
            )
        
        # Persist configuration
        try:
            store.save(config.bot_token, config.dm_policy)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to save config: {e}")
        
        # Trigger reload or update
        manager = get_bot_manager()
        
        if config.bot_token:
            # Full reload with new token
            asyncio.create_task(manager.reload(config.bot_token, config.dm_policy))
            return {
                "status": "reloading",
                "message": "Bot is reloading with new token...",
            }
        else:
            # DM policy only - no restart needed
            manager.update_dm_policy(config.dm_policy)
            return {
                "status": "saved",
                "message": "Configuration saved.",
            }
            
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Update Telegram config error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Telegram Health Check (for Health Dashboard) ────────────────────

@app.get("/health/telegram")
async def telegram_health():
    """
    Telegram bot health check for health dashboard.
    
    Returns:
        Service status: healthy/unhealthy with details
    """
    try:
        from packages.messaging.bot_manager import get_bot_manager
        manager = get_bot_manager()
        status = manager.get_status()
        
        return {
            "service": "telegram_bot",
            "status": "healthy" if status.get("state") == "running" else "unhealthy",
            "details": status,
        }
    except Exception as exc:
        return {
            "service": "telegram_bot",
            "status": "unhealthy",
            "error": str(exc),
        }
```

**Tests:**
- `test_get_status_endpoint()` - Returns correct state
- `test_post_config_with_token()` - Persists and triggers reload
- `test_post_config_empty_token()` - Updates DM policy only
- `test_post_config_invalid_token()` - Returns 422
- `test_health_endpoint()` - Returns healthy/unhealthy

---

### **Phase 8: UI Updates (3-4 hours)**

**File:** `apps/desktop/src/pages/TelegramPage.tsx` (UPDATE)

**Purpose:** Dynamic status, accurate feedback, status polling

**Implementation:**
```typescript
// Add to TelegramPage.tsx

interface BotStatus {
  state: 'stopped' | 'starting' | 'running' | 'reloading' | 'error';
  error_message?: string;
  started_at?: string;
  dm_policy?: string;
}

// Add state
const [botStatus, setBotStatus] = useState<BotStatus | null>(null);
const [saveStatus, setSaveStatus] = useState<string | null>(null);

// Add status polling effect
useEffect(() => {
  loadBotStatus();
}, []);

const loadBotStatus = async () => {
  try {
    const response = await fetch('http://127.0.0.1:8000/telegram/status');
    const status = await response.json();
    setBotStatus(status);
  } catch (err) {
    console.error('Failed to load bot status:', err);
  }
};

// Poll status after reload
useEffect(() => {
  if (botStatus?.state !== 'reloading') {
    return;
  }

  let cancelled = false;
  const pollStatus = async () => {
    try {
      const response = await fetch('http://127.0.0.1:8000/telegram/status');
      const status = await response.json();
      if (!cancelled) {
        setBotStatus(status);
        if (status.state !== 'reloading') {
          return; // Stop polling
        }
      }
    } catch (err) {
      console.error('Failed to poll status:', err);
    }
    // Schedule next poll
    if (!cancelled) {
      setTimeout(pollStatus, 2000);
    }
  };

  pollStatus();

  return () => {
    cancelled = true;
  };
}, [botStatus?.state]);

// Update handleSaveConfig
const handleSaveConfig = async () => {
  setSaving(true);
  setSaveStatus(null);
  
  try {
    const response = await fetch('http://127.0.0.1:8000/telegram/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bot_token: botToken,
        dm_policy: dmPolicy,
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to save configuration');
    }

    const result = await response.json();
    
    // Show appropriate message based on status
    if (result.status === 'reloading') {
      setSaveStatus('Bot is reloading with new token...');
      // Start polling status
      loadBotStatus();
    } else if (result.status === 'saved') {
      setSaveStatus('Configuration saved.');
    }
    
    loadConfig();
    
  } catch (err) {
    setSaveStatus(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
  } finally {
    setSaving(false);
  }
};

// Update UI to show dynamic status
<section className="card">
  <h2>🤖 Bot Status</h2>
  {botStatus && (
    <div style={{
      padding: '12px',
      borderRadius: '8px',
      background: getStatusColor(botStatus.state),
      marginBottom: '16px',
    }}>
      <div style={{ fontSize: '14px', fontWeight: 600 }}>
        {getStatusEmoji(botStatus.state)} Bot is {botStatus.state}
      </div>
      {botStatus.error_message && (
        <div style={{ fontSize: '12px', marginTop: '8px' }}>
          Error: {botStatus.error_message}
        </div>
      )}
      {botStatus.started_at && (
        <div style={{ fontSize: '11px', marginTop: '4px' }}>
          Started: {new Date(botStatus.started_at).toLocaleString()}
        </div>
      )}
    </div>
  )}
  
  {/* Save status message */}
  {saveStatus && (
    <div style={{
      marginTop: '12px',
      padding: '12px',
      borderRadius: '8px',
      background: saveStatus.includes('Error') ? 'var(--error-bg)' : 'var(--success-bg)',
      color: saveStatus.includes('Error') ? 'var(--error-color)' : 'var(--success-color)',
    }}>
      {saveStatus}
    </div>
  )}
  
  {/* Remove static warning */}
  {/* DELETE: <div>⚠️ Bot token changes require restart to take effect</div> */}
</section>

function getStatusEmoji(state: string): string {
  const emojis = {
    stopped: '⏹️',
    starting: '🚀',
    running: '✅',
    reloading: '🔄',
    error: '❌',
  };
  return emojis[state as keyof typeof emojis] || '⚪';
}

function getStatusColor(state: string): string {
  const colors = {
    stopped: 'var(--bg-input)',
    starting: 'var(--warning-bg)',
    running: 'var(--success-bg)',
    reloading: 'var(--info-bg)',
    error: 'var(--error-bg)',
  };
  return colors[state as keyof typeof colors] || 'var(--bg-input)';
}
```

**Tests:**
- Manual testing in dev mode
- Verify status polling stops when not reloading
- Verify save messages match API response

---

### **Phase 9: Integration & Testing (3-4 hours)**

**Tasks:**

1. **Wire up lifespan** (30 min)
   - Add bot manager init to `main.py:35` lifespan
   - Test startup/shutdown

2. **Test config persistence** (30 min)
   - Save config via API
   - Restart API
   - Verify bot auto-starts

3. **Test agent routing** (1 hour)
   - `/agents` command lists agents
   - `/agent code-reviewer` switches agent
   - Message routes to selected agent
   - `/new` resets to smart-chat

4. **Test result formatting** (1 hour)
   - A2A agent returns findings
   - Formatter sorts by severity
   - Long responses chunked

5. **Test hot-reload** (30 min)
   - Save new token
   - Bot stops and restarts
   - Status shows "reloading" → "running"

6. **Test token redaction** (30 min)
   - Check logs don't contain tokens
   - Verify redaction filter works

7. **Run full test suite** (30 min)
   - Ensure no regressions

---

## 📊 **Effort Summary**

| Phase | Component | Effort | Status |
|-------|-----------|--------|--------|
| 1 | Config_Store | 2-3h | ✅ Planned |
| 2 | Token Redaction | 1-2h | ✅ Planned |
| 3 | TelegramBotService | 4-5h | ✅ Planned |
| 4 | Agent_Router | 3-4h | ✅ Planned |
| 5 | Agent_Formatter | 3-4h | ✅ Planned |
| 6 | Bot_Manager | 5-6h | ✅ Planned |
| 7 | API Endpoints | 3-4h | ✅ Planned |
| 8 | UI Updates | 3-4h | ✅ Planned |
| 9 | Integration | 3-4h | ✅ Planned |
| **Total** | | **27-36h** | |

**Contingency (15%):** 4-5h

**Total with Contingency:** **31-41 hours**

---

## ✅ **Success Criteria**

### **Infrastructure (Requirements 1-5)**

- [ ] Config persists to `~/.personalassist/telegram_config.env`
- [ ] Bot hot-reloads on token change (<10 seconds)
- [ ] `/telegram/status` returns accurate state
- [ ] UI shows dynamic status, not static warning
- [ ] Token round-trip works (write → read = same)
- [ ] Token redacted in logs

### **Agent Routing (Requirements 6-7)**

- [ ] `/agents` lists all available agents
- [ ] `/agent <id>` switches agent
- [ ] Messages route to selected agent
- [ ] A2A results formatted as readable text
- [ ] Findings sorted by severity
- [ ] Long responses chunked

### **Quality**

- [ ] All 33 acceptance criteria met
- [ ] No critical bugs
- [ ] Token never logged in plaintext
- [ ] Graceful error handling throughout

---

## 🚀 **Next Step**

**Begin Phase 1: Config_Store** implementation.

Ready to proceed?
