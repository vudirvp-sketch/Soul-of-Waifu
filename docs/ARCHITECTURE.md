# Soul of Waifu — Architecture

> Detailed module architecture. For high-level repo map — see `AGENT_NAVIGATION.md`.
> This document is for deep understanding before refactor tasks.

---

## 1. Differences from poe2-regex-ru (reference infrastructure)

Soul of Waifu is NOT a web storefront — it is a **desktop application**. This changes architectural priorities:

| Aspect | poe2-regex-ru (TS/Vite) | Soul of Waifu (Python/PyQt6) |
|--------|------------------------|------------------------------|
| Environment | Browser, any OS | Windows-only desktop |
| CI/CD | GitHub Actions: tsc + eslint + vitest + Pages deploy | No CI. Smoke-test manual. |
| Tests | 2400+ vitest unit tests | None. Only manual launch. |
| Entry point | `index.html` → `src/main.tsx` | `main.py` → `MainWindow` |
| Layers | core ← shared ← store ← data ← ui | configuration ← utils ← gui |
| Bundle | Vite build → static JS/CSS | Miniconda env + .py source files |
| Deploy | GitHub Pages (auto) | Releases ZIP with bundled Miniconda |
| File sizes | ≤500 lines per component | 5–15k lines per GUI file |
| Caches/secrets | In browser localStorage | JSON files in `app/configuration/` |

**Conclusion:** cannot blindly copy poe2-regex-ru agent infrastructure. Need:
- `.gitignore` for Python/Miniconda runtime (critical!).
- Pitfalls for PyQt6/qasync/signals/combo-indexes.
- Documentation without CI commands (nothing to run in CI).
- Smoke-test instead of unit tests as primary verification.

---

## 2. Layered Architecture

```
┌─────────────────────────────────────────────────────────┐
│  main.py  — entry point, QApplication, logging setup    │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  app/gui/  (PyQt6 UI + signals)                          │
│  - sowInterface.py (Ui_MainWindow — Qt Designer output)  │
│  - interface_signals.py (signal handlers, 15869 lines)    │
│  - custom_widgets.py (custom widgets, 8896 lines)        │
│  - soul_stage_page.py (RPG page, 3357 lines)             │
│  - sowSystem.py (Soul Companion voice-call overlay, 716 lines) │
│  - sow_system_signals.py (voice call signals, 4234 lines)│
│  - diagnostics_panel.py (read-only diagnostics panel, 360 lines) │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  app/utils/  (business logic without UI)                  │
│  ├─ ai_clients/                                          │
│  │   ├─ base_provider.py (BaseAIProvider ABC)            │
│  │   ├─ ai_factory.py (AIFactory.get_provider)           │
│  │   ├─ prompt_engine.py                                 │
│  │   ├─ local_server_manager.py (Llama.cpp subprocess)   │
│  │   ├─ mcp_client.py (MCP tools)                        │
│  │   ├─ soul_stage_engine.py (RPG game master)           │
│  │   └─ providers/ (10 files, one per provider)          │
│  ├─ soul_memory.py (long-term memory, embeddings)        │
│  ├─ soul_companion/ (desktop overlay, neurohormones)     │
│  ├─ text_to_speech.py (6 TTS engines + RVC)              │
│  ├─ speech_to_text.py (Faster Whisper + VAD)             │
│  ├─ image_generator.py (A1111/ComfyUI/FLUX/NovelAI/DALLE)│
│  ├─ models_hub.py (HF search + GGUF download)            │
│  ├─ web_server.py (FastAPI + WebSocket)                  │
│  ├─ discord_manager.py (Discord bot)                     │
│  ├─ character_cards.py (SillyTavern v2/v3 import)        │
│  ├─ ambient_client.py (ambient audio)                    │
│  ├─ backend_updater.py (Llama.cpp auto-update)           │
│  └─ translator.py (i18n wrapper)                         │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  app/configuration/  (leaf layer)                         │
│  - configuration.py (ConfigurationSettings/API/Chars)    │
│  - settings.json (UI settings + user_data)               │
│  - api.json (12 keys, empty in repo)                     │
│  - characters.json (character card array)                │
└──────────────────────────────────────────────────────────┘
```

**Dependency rule:** `gui → utils → configuration`. Utils do NOT import from `gui`. `configuration` is leaf layer (imports nothing from `app/`).

**Known violations:** in `app/utils/` there are hidden dependencies on `app/gui/` via `qasync` event loop (legitimate) and via `configuration` singleton. Full isolation not yet achieved — in backlog (see `STATUS.md`).

---

## 3. AI Provider Layer

### 3.1. BaseAIProvider (abstract)

`app/utils/ai_clients/base_provider.py`:

```python
class BaseAIProvider(ABC):
    @abstractmethod
    async def generate_stream(self, messages: list[dict], **kwargs) -> AsyncGenerator[str, None]:
        """Streaming chat completion. Yields text chunks."""

    @abstractmethod
    async def generate_summary(self, messages: list[dict], **kwargs) -> AsyncGenerator[str, None]:
        """Streaming summarization. Same signature, different prompt formatting."""

    @abstractmethod
    async def generate(self, messages: list[dict], tools: list = None, **kwargs) -> dict:
        """Non-streaming with optional tool-calling. Returns dict with 'content' and 'tool_calls'."""
```

### 3.2. AIFactory

`app/utils/ai_clients/ai_factory.py::AIFactory.get_provider(conversation_method: str)`:

- Accepts string from `settings.json` (e.g. `"Open AI"`, `"Local LLM"`, `"Anthropic"`).
- Reads API token via `ConfigurationAPI().get_token()`.
- Reads model via `ConfigurationSettings().get_main_setting()`.
- Returns instance of corresponding `*Provider`.

### 3.3. Providers (10 files in `providers/`)

| File | Provider | Cloud/Local | Streaming | Tools |
|------|----------|-------------|-----------|-------|
| `openai_provider.py` | OpenAI / custom OpenAI-compatible | Both | Yes | Yes |
| `openrouter_provider.py` | OpenRouter | Cloud | Yes | Yes |
| `anthropic_provider.py` | Anthropic Claude | Cloud | Yes | Yes |
| `gemini_provider.py` | Google Gemini | Cloud | Yes | Yes |
| `deepseek_provider.py` | DeepSeek | Cloud | Yes | Yes |
| `grok_provider.py` | xAI Grok | Cloud | Yes | Yes |
| `qwen_provider.py` | Alibaba Qwen | Cloud | Yes | Yes |
| `mistral_provider.py` | Mistral AI | Cloud | Yes | Yes |
| `zai_provider.py` | Z.AI | Cloud | Yes | Yes |
| `local_provider.py` | Local Llama.cpp | Local | Yes | Yes |

**Local provider** communicates with Llama.cpp HTTP server (launched by `local_server_manager.py` as separate process on `http://localhost:8080`).

### 3.4. Extension (see AGENT_NAVIGATION.md §3)

Adding a new provider = 3 steps:
1. `<name>_provider.py` inheriting `BaseAIProvider`.
2. Branch in `ai_factory.py::get_provider()`.
3. Option in `interface_signals.py` conversation combo + translations in `ru.yaml`/`en.yaml`.

---

## 4. Soul Memory Subsystem

`app/utils/soul_memory.py` (~1000 lines) — long-term memory, operates as autonomous background agent. **Runtime data written to `.soul/<character>/chats/<chat_id>/memory/`** (project root, relative to CWD). This directory is in `.gitignore` — private data, never commit.

### 4.1. Per-character cognitive files

| File | Contents |
|------|----------|
| `MEMORY.md` | Current mood, internal tension, hidden motives, character development (character_memory) |
| `USER.md` | User habits, preferences, promises, trust dynamics (user_memory / relationship_metadata) |
| `topics/*.md` | Episodic archive — one file per topic, indexed via `all-MiniLM-L6-v2` embeddings |
| `agent_logs.txt` | Background agent logs (Index Agent, Diary Agent, Healing Agent) |
| `backups/` | Previous MEMORY.md/USER.md versions (for self-healing) |
| `diary` | First-person entries after meaningful conversations |

### 4.2. Embeddings

- Model: `all-MiniLM-L6-v2` via `sentence-transformers`.
- Local download on first run (cached in `~/.cache/huggingface/`).
- Embedder singleton via `_EMBEDDER` global + `_check_embedder_available()`.

### 4.3. Cognitive Mechanics

- **Emotional Decay:** grudges/negative mood cool down over time if topic not revisited.
- **Memory Self-Healing:** detect logical contradictions between new response and past facts → overwrite + log correction.

### 4.4. Cognitive Profiles (hardware scalability)

- **Full Sync** — maximum depth, all 4 files + embeddings.
- **Soul Link** — balanced (partial files).
- **Mind Spark** — lightweight (only psychology + relationship).
- **Reflection Flow** — only diary.

Choice via `settings.json::cognitive_profile`.

---

## 5. Soul Stage (RPG Engine)

`app/gui/soul_stage_page.py` + `app/utils/ai_clients/soul_stage_engine.py`.

- Separate AI layer (Game Master) — independent from character's AI.
- **WorldState:** time of day, weather, location, key facts.
- **Inventory & Status:** items, health, condition effects, gold.
- **NPCs:** main party (via Soul Memory), temporary (one-scene).
- **Ambient:** auto background + audio loop switching (`ambient_client.py`).
- **Choices Bar:** branching dialogue options.
- **Event Cards:** random encounters.

GM prompt in `soul_stage_engine.py`. System prompt sets RPG rules, response format (JSON with state updates).

---

## 6. Soul Companion (Desktop Overlay)

`app/utils/soul_companion/`:

- **Neurohormonal system:** mood shifts over time based on activity, time of day, interaction patterns.
- **6 built-in tools:** Screen Reader (via `mss`), Clipboard Reader, Web Search (`ddgs`), Browser Control, Music Control, MCP Custom Server.
- **Proactive behavior:** initiates conversation when enough time/events on screen.
- **MCP integration:** `mcp_client.py` — connects external MCP servers.

---

## 7. TTS / STT

### 7.1. TTS (`text_to_speech.py`, ~970 lines)

| Engine | Type | Notes |
|--------|------|-------|
| Qwen3 TTS | Local | 1.7B and 0.6B, voice cloning 3s, voice design by prompt |
| XTTSv2 (Coqui) | Local | High-fidelity, zero-shot cloning |
| Kokoro 82M | Local | Lightweight, fast |
| Silero TTS | Local | Russian-first |
| EdgeTTS | Cloud | Microsoft neural voices |
| ElevenLabs | Cloud | Premium voices |

**RVC** — voice conversion (pitch shift, index rate, protection). Voice models in `app/voices/` (gitignored).

**Streaming:** sentence-by-sentence — playback starts after first generated sentence.

### 7.2. STT (`speech_to_text.py`)

- **Faster Whisper** — transcription.
- **Silero VAD** — Voice Activity Detection for full-duplex calls.
- **Full-duplex calls:** user can interrupt character at any moment (via `sow_system_signals.py`).

---

## 8. Web Server (mobile access)

`app/utils/web_server.py` (FastAPI + WebSocket):

- Runs on `http://<pc-ip>:8000`.
- WebSocket for real-time bidirectional sync (chat, voice input, avatars).
- Voice input from phone → processed by local Faster Whisper on PC.
- Custom chat backgrounds + avatar rendering.
- Static files: `app/web_client/` (HTML/CSS/JS).

---

## 9. Discord Gateway

`app/utils/discord_manager.py` (~190 lines):

- `discord.py` bot.
- Connect character to Discord server/DM.
- Preserve personality + system prompt + Soul Memory across platforms.
- Token in `api.json::DISCORD_BOT_TOKEN`.

---

## 10. Configuration Layer

`app/configuration/configuration.py` — 3 classes:

### 10.1. ConfigurationSettings

```python
settings = configuration.ConfigurationSettings()
data = settings.load_configuration()  # full dict
value = settings.get_main_setting("temperature")  # by key
settings.save_main_setting("temperature", 0.9)  # single field
settings.save_configuration_edit(data)  # entire dict
```

JSON structure: `{"main_settings": {...}, "user_data": {...}}`.

### 10.2. ConfigurationAPI

```python
api = configuration.ConfigurationAPI()
token = api.get_token("OPEN_AI_API_TOKEN")
api.save_token("OPEN_AI_API_TOKEN", "sk-...")
```

JSON structure: `{"OPEN_AI_API_TOKEN": "", "OPENROUTER_API_TOKEN": "", ...}`. 12 keys total.

### 10.3. ConfigurationCharacters

Character card array (SillyTavern v2/v3 spec). Supports PNG-embedded + JSON-only.

---

## 11. i18n (translations)

`app/translations/ru.yaml` + `en.yaml` — flat YAML key-value pairs.

`app/utils/translator.py` — `t("key")` wrapper with fallback to key if translation missing.

When adding UI text — add key to BOTH files. If key missing in one — UI shows raw key string in that language.

---

## 12. Known Couplings (where changes cascade)

| Change | Affects |
|---------|---------|
| Combo order in `interface_signals.py` | `settings.json` indexes + `ai_factory.py` (conversation_method) + `translations/*.yaml` |
| `BaseAIProvider` contract | All 10 `*_provider.py` files |
| `settings.json` structure | `configuration.py` (load/save) + `interface_signals.py` (read/write) |
| Soul Memory JSON schema | `soul_memory.py` (load/save) + GUI rendering in `interface_signals.py` |
| i18n key | `ru.yaml` + `en.yaml` + usage location in GUI |

---

## 13. Backlog (architectural improvements)

(see `STATUS.md` → Roadmap → backlog)

- Split `interface_signals.py` (15869 lines) into functional modules: `chat_signals.py`, `tts_signals.py`, `rpg_signals.py`, `config_signals.py`.
- Split `custom_widgets.py` (8896 lines) into separate widget files.
- Isolate `app/utils/` from `gui/` via dependency injection (remove hidden imports).
- Add `pytest` for pure-logic: `soul_memory.py`, `prompt_engine.py`, `ai_factory.py`, `character_cards.py`.
- GitHub Actions: `python -m compileall app/ main.py` on push.
- Migrate `settings.json` to unified type (strings OR numbers, not mixed).
- Type hints throughout `app/utils/` (currently partial).
