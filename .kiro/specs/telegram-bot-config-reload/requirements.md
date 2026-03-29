# Requirements Document

## Introduction

This feature implements proper Telegram bot configuration persistence and hot-reload for the PersonalAssist application. Currently, the `POST /telegram/config` endpoint validates but never saves the bot token, the bot reads `TELEGRAM_BOT_TOKEN` once at startup and cannot pick up changes, and the UI misleads users by saying "restart required" even though nothing was saved. This feature closes all four gaps: persist the token, reload the bot without a full process restart, coordinate the API and bot service, and give the user accurate feedback.

## Glossary

- **Config_Store**: The persistence layer responsible for reading and writing Telegram configuration (bot token, DM policy) to a `.env`-style file at `~/.personalassist/telegram_config.env`.
- **Bot_Manager**: The in-process controller that owns the `TelegramBotService` lifecycle — start, stop, and restart with a new token.
- **API**: The FastAPI backend (`apps/api/main.py`) that exposes the `/telegram/config` endpoints.
- **Bot_Service**: The `TelegramBotService` class in `packages/messaging/telegram_bot.py` that runs the polling loop.
- **UI**: The Tauri/React desktop frontend page `TelegramPage.tsx`.
- **Reload_Signal**: An in-process asyncio `Event` used by the API to notify the Bot_Manager that configuration has changed.
- **Agent_Router**: Component that maps incoming Telegram messages to the correct agent endpoint based on per-user agent selection state.
- **Agent_Formatter**: Component that converts structured A2A agent output (JSON) into human-readable Telegram message text.

---

## Requirements

### Requirement 1: Persist Bot Configuration

**User Story:** As a user, I want my bot token and DM policy to be saved when I click "Save Configuration", so that the settings survive application restarts.

#### Acceptance Criteria

1. WHEN the API receives a `POST /telegram/config` request with a non-empty `bot_token`, THE Config_Store SHALL write the token and DM policy to `~/.personalassist/telegram_config.env`.
2. WHEN the API receives a `POST /telegram/config` request with an empty `bot_token`, THE Config_Store SHALL preserve the existing token and only update the DM policy.
3. WHEN the application starts, THE Bot_Service SHALL read the bot token from `~/.personalassist/telegram_config.env` if the file exists, falling back to the `TELEGRAM_BOT_TOKEN` environment variable.
4. THE Config_Store SHALL store the bot token in the config file using a format that prevents the token from being logged in plaintext at INFO level or above.
5. IF the Config_Store fails to write the config file, THEN THE API SHALL return HTTP 500 with a descriptive error message.

---

### Requirement 2: Hot-Reload Bot on Token Change

**User Story:** As a user, I want the bot to pick up a new token immediately after saving, so that I do not need to restart the entire application.

#### Acceptance Criteria

1. WHEN the API successfully persists a new bot token, THE Bot_Manager SHALL stop the running Bot_Service instance within 5 seconds.
2. WHEN the Bot_Manager stops the running Bot_Service, THE Bot_Manager SHALL start a new Bot_Service instance using the updated token within 5 seconds of the stop completing.
3. WHILE the Bot_Manager is restarting the Bot_Service, THE API SHALL respond to the `POST /telegram/config` request with `{"status": "reloading"}` before the restart completes.
4. IF the new Bot_Service fails to start (e.g., invalid token), THEN THE Bot_Manager SHALL set the bot status to `"error"` and SHALL preserve the error message for retrieval via `GET /telegram/status`.
5. WHEN the DM policy changes but the bot token does not change, THE Bot_Manager SHALL apply the new policy to the running Bot_Service without restarting the polling loop.

---

### Requirement 3: Bot Status Endpoint

**User Story:** As a user, I want to see the current bot status in the UI, so that I know whether the bot is running, reloading, or in an error state.

#### Acceptance Criteria

1. THE API SHALL expose a `GET /telegram/status` endpoint that returns the current bot state: one of `"stopped"`, `"starting"`, `"running"`, `"reloading"`, or `"error"`.
2. WHEN the bot state is `"error"`, THE `GET /telegram/status` response SHALL include an `"error_message"` field containing the failure reason.
3. WHEN the bot state is `"running"`, THE `GET /telegram/status` response SHALL include a `"started_at"` ISO-8601 timestamp.
4. THE `GET /telegram/status` endpoint SHALL respond within 200 ms under normal operating conditions.

---

### Requirement 4: Accurate UI Feedback

**User Story:** As a user, I want the UI to show me the real outcome of saving configuration, so that I am not misled by incorrect status messages.

#### Acceptance Criteria

1. WHEN the `POST /telegram/config` response contains `{"status": "reloading"}`, THE UI SHALL display "Bot is reloading with new token..." instead of "restart required".
2. WHEN the `POST /telegram/config` response contains `{"status": "saved"}` (DM policy-only change), THE UI SHALL display "Configuration saved." without any restart warning.
3. WHEN the `POST /telegram/config` request fails, THE UI SHALL display the error message returned by the API.
4. THE UI SHALL poll `GET /telegram/status` every 2 seconds after a reload is triggered and SHALL update the displayed bot status until the state transitions out of `"reloading"`.
5. THE UI SHALL remove the static "⚠️ Bot token changes require restart to take effect" notice and replace it with a dynamic status indicator sourced from `GET /telegram/status`.

---

### Requirement 5: Config Round-Trip Integrity

**User Story:** As a developer, I want the config read/write cycle to be reliable, so that a token written by the API is always the token the bot reads back.

#### Acceptance Criteria

1. FOR ALL valid bot tokens written by the Config_Store, reading the config file back SHALL produce a token equal to the original written value (round-trip property).
2. THE Config_Store SHALL validate that a bot token matches the pattern `^\d+:[A-Za-z0-9_-]{35,}$` before persisting it.
3. IF a bot token fails validation, THEN THE API SHALL return HTTP 422 with a message indicating the expected token format.
4. THE Config_Store SHALL use atomic file writes (write to a temp file then rename) to prevent partial writes from corrupting the stored token.

---

### Requirement 6: Agent Routing and Selection

**User Story:** As a Telegram user, I want to select which agent handles my messages, so that I can use specialized agents (code reviewer, workspace analyzer, etc.) directly from Telegram without being limited to the default smart chat.

#### Acceptance Criteria

1. WHEN a Telegram user sends `/agents`, THE Bot_Service SHALL reply with a list of all available agents including their IDs, names, and one-line descriptions, sourced from the A2A registry and the smart-chat endpoint.
2. WHEN a Telegram user sends `/agent <agent_id>` with a valid agent ID, THE Agent_Router SHALL store the selected agent ID against that user's Telegram ID in the UserAuthStore and SHALL confirm the selection with a reply message.
3. WHEN a Telegram user sends `/agent <agent_id>` with an agent ID that does not exist in the registry, THE Bot_Service SHALL reply with an error message listing the valid agent IDs.
4. WHEN a Telegram user sends a text message, THE Agent_Router SHALL route the message to the agent previously selected by that user, defaulting to `smart-chat` if no selection has been made.
5. WHEN a Telegram user sends `/agent default` or `/new`, THE Agent_Router SHALL reset that user's agent selection to `smart-chat` and SHALL confirm the reset with a reply message.
6. WHILE a user has an A2A agent selected, THE Bot_Service SHALL pass the user's message text as the primary task input parameter to the selected A2A agent via the A2A registry delegate mechanism.
7. THE UserAuthStore SHALL persist the per-user agent selection across bot restarts by writing the selection to the existing `~/.personalassist/telegram_auth.json` file alongside the existing auth fields.
8. IF the A2A registry delegate call fails or times out after 60 seconds, THEN THE Bot_Service SHALL reply with an error message that includes the agent ID and the failure reason.

---

### Requirement 7: Agent Result Formatting

**User Story:** As a Telegram user, I want A2A agent results presented as readable messages, so that I can understand structured JSON output without needing to parse it myself.

#### Acceptance Criteria

1. WHEN an A2A agent returns a result containing a `findings` array, THE Agent_Formatter SHALL render each finding as a numbered entry showing severity, file/location, and message, with critical and high severity findings listed first.
2. WHEN an A2A agent returns a result containing a `summary` string, THE Agent_Formatter SHALL include the summary as the first paragraph of the formatted reply.
3. WHEN an A2A agent returns a result containing a `score` object, THE Agent_Formatter SHALL render each score field as a labelled value (e.g., `Security: 82/100`).
4. WHEN an A2A agent returns a result containing a `recommendations` array, THE Agent_Formatter SHALL render each recommendation as a bullet point.
5. WHEN an A2A agent returns a result containing a `metrics` object, THE Agent_Formatter SHALL render each metric as a labelled key-value pair.
6. WHEN the formatted output of an A2A agent result exceeds 4096 characters, THE Agent_Formatter SHALL pass the text to the existing chunked-response mechanism so that it is delivered as multiple sequential Telegram messages.
7. WHEN an A2A agent task completes with `status = "failed"`, THE Agent_Formatter SHALL produce a reply that includes the agent ID and the `error` field from the TaskHandle, prefixed with a clear failure indicator.
8. FOR ALL valid A2A agent result objects, formatting then parsing the formatted text SHALL preserve all finding severities, summary text, and recommendation items (round-trip content integrity property).
