# Soul of Waifu — Signal Map & Call Flow Reference

> Comprehensive map of signal flows, call chains, logging touchpoints, and failure modes
> across all subsystems. Intended for AI agents and developers navigating the ~46k-line codebase.

---

## 1. Architecture Recap

Three-layer strict dependency graph:

```
gui  ──→  utils  ──→  configuration
  │         │            │
  │         │            └─ settings.json  (ConfigurationSettings)
  │         │            └─ api.json       (ConfigurationAPI)
  │         │            └─ characters.json (ConfigurationCharacters)
  │         │
  │         └─ ai_clients/  (10 providers + factory + prompt_engine + local_server + soul_stage)
  │         ─ soul_memory.py
  │         ─ text_to_speech.py  (6 engines)
  │         ─ speech_to_text.py  (STT pipeline)
  │         ─ web_server.py      (FastAPI + WebSocket)
  │         ─ discord_manager.py
  │         ─ soul_companion/    (overlay + proactive AI)
  │         ─ image_generator.py (5 providers)
  │         ─ translator.py
  │         ─ backend_updater.py
  │         ─ character_cards.py
  │         ─ emotions/detector/ (28-class classifier)
  │
  └─ interface_signals.py  (15 653 lines — THE HUB)
  └─ sow_system_signals.py (4 209 lines — voice call system)
  └─ custom_widgets.py     (8 889 lines — widgets + dialogs)
  └─ sowInterface.py       (6 706 lines — UI setup)
  └─ soul_stage_page.py    (3 356 lines — RPG UI)
```

**Key rule:** `utils` does NOT import from `gui`. All signals flow upward through PyQt6
signal/slot connections, not direct function calls from utils to gui.

---

## 2. Provider Layer — 10 AI Providers

### 2.1 BaseAIProvider Interface

**File:** `app/utils/ai_clients/base_provider.py` (51 lines)

Three abstract methods — every provider must implement all three:

```python
class BaseAIProvider(ABC):
    async def generate_stream(self, messages: list[dict], **kwargs) → AsyncGenerator[str, None]
    async def generate_summary(self, messages: list[dict], **kwargs) → AsyncGenerator[str, None]
    async def generate(self, messages: list[dict], tools: list = None, **kwargs) → dict
```

`generate()` return contract: `{"content": str|None, "tool_calls": list|None}`.

### 2.2 AIFactory — Provider Routing

**File:** `app/utils/ai_clients/ai_factory.py`
**Logger:** `"AI Factory"` (ERROR only — unknown method)

| `conversation_method` | Provider Class | API Token Key | Model Setting Key | Default Model |
|---|---|---|---|---|
| `"Open AI"` | `OpenAIProvider` | `OPEN_AI_API_TOKEN` | `openai_model` | `gpt-4o-mini` |
| `"OpenRouter"` | `OpenRouterProvider` | `OPENROUTER_API_TOKEN` | `openrouter_model` | *(user must set)* |
| `"Mistral AI"` | `MistralProvider` | `MISTRAL_AI_API_TOKEN` | `mistral_model_endpoint` | `mistral-small-latest` |
| `"Anthropic"` | `AnthropicProvider` | `ANTHROPIC_API_TOKEN` | `anthropic_model` | `claude-sonnet-4-6` |
| `"Google Gemini"` | `GeminiProvider` | `GEMINI_API_TOKEN` | `gemini_model` | `gemini-3.5-flash` |
| `"DeepSeek"` | `DeepSeekProvider` | `DEEPSEEK_API_TOKEN` | `deepseek_model` | `deepseek-v4-flash` |
| `"Grok"` | `GrokProvider` | `GROK_API_TOKEN` | `grok_model` | `grok-4.3` |
| `"Qwen"` | `QwenProvider` | `QWEN_API_TOKEN` | `qwen_model` | `qwen3.5-flash` |
| `"Z.AI"` | `ZAIProvider` | `ZAI_API_TOKEN` | `zai_model` | `glm-4.7` |
| `"Local LLM"` | `LocalProvider` | *(none)* | `adv_sampling` + sub-keys | `local-model` |

**Special factory logic:**
- **OpenAI:** If `CUSTOM_ENDPOINT_URL` set → appends `/v1` unless already present (self-hosted endpoints).
- **Local LLM:** If `adv_sampling` enabled → builds `advanced_params` dict with `min_p`, `xtc_probability`, `xtc_threshold`, `dry_multiplier`, `dry_base`, `dry_allowed_length`, optionally `dynatemp_range`.
- **Unknown method:** Returns `None` + logs error.

### 2.3 Per-Provider Details

#### OpenAIProvider

**File:** `providers/openai_provider.py`
**Logger:** `"OpenAI Provider"` (ERROR only)
**HTTP Client:** `openai.AsyncOpenAI` SDK → `httpx.AsyncClient(timeout=120)`
**Endpoint:** `self.base_url` (default `https://api.openai.com/v1`) → `client.chat.completions.create()`
**Auth:** `api_key` via SDK → `Authorization: Bearer <key>`

| Method | Streaming? | Notes |
|---|---|---|
| `generate_stream` | Yes | `stream=True`; yields `chunk.choices[0].delta.content`; stop tokens `["<|im_end|>"]` |
| `generate_summary` | Yes | `stream=True`; temp=0.5; adds `frequency_penalty`/`presence_penalty` unless model name contains "gemini" |
| `generate` | No | `stream=False`; if `tools` → `payload["tools"]` + `tool_choice="auto"` |

**Failure:** Generic `except Exception` → yields `⚠️ OpenAI API Error: {str(e)}` or returns `{None, None}`.

#### OpenRouterProvider

**File:** `providers/openrouter_provider.py`
**Logger:** `"OpenRouter Provider"` (ERROR only)
**HTTP Client:** `openai.AsyncOpenAI` SDK
**Endpoint:** `https://openrouter.ai/api/v1`
**Extra headers:** Always `HTTP-Referer: https://github.com/jofizcd/Soul-of-Waifu` + `X-Title: Soul of Waifu` (OpenRouter attribution ToS).

Identical pattern to OpenAI, but `extra_headers` always included. `generate_summary` omits penalties.

#### MistralProvider

**File:** `providers/mistral_provider.py`
**Logger:** `"Mistral Provider"` (ERROR only)
**HTTP Client:** `mistralai.Mistral` official SDK (not httpx)
**Endpoint:** `https://api.mistral.ai/v1/chat/completions` (SDK internal)
**Auth:** `api_key` via `Mistral(api_key=...)`

`generate_stream` → `client.chat.stream_async()`; `safe_prompt=False` (disables content moderation).
`generate_summary` → same but with `frequency_penalty=0.8`, `presence_penalty=0.3`.
No `stop` parameter sent.

#### AnthropicProvider

**File:** `providers/anthropic_provider.py`
**Logger:** `"Anthropic Provider"` (ERROR only)
**HTTP Client:** Raw `httpx.AsyncClient(timeout=120)` — **no SDK**
**Endpoint:** `https://api.anthropic.com/v1/messages`
**Auth:** Custom headers: `x-api-key: <key>`, `anthropic-version: 2023-06-01`

**Most complex provider:**
- `generate_stream` — Manual SSE parsing: separates system messages (Anthropic requires `system` as top-level field), `client.stream("POST", ...)` → `aiter_lines()` → parse `data:` lines → filter `type == "content_block_delta"` → yield `delta.text`. **Checks `response.status_code != 200`** — yields `⚠️ Anthropic API Error ({code}): {body}`.
- `generate` — **Vision/multimodal**: converts OpenAI `image_url` blocks to Anthropic `image` (base64). **Tool schema translation**: OpenAI `{"function": {...}}` → Anthropic `{"name", "description", "input_schema"}`. Parses response `text` + `tool_use` blocks → converts back to OpenAI-compatible format.
- Only provider with granular HTTP status code handling.

#### GeminiProvider

**File:** `providers/gemini_provider.py`
**Logger:** `"Gemini Provider"` (**defined but never used** — logs go to `"OpenAI Provider"` via parent)
**Inheritance:** `GeminiProvider(OpenAIProvider)` — **zero method overrides**

Uses Google's OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai`).
All methods inherited from OpenAIProvider. The OpenAI parent has a `"gemini" not in self.model.lower()` guard that skips penalties for Gemini.

**Bug:** Logger `"Gemini Provider"` is dead code — parent logs under `"OpenAI Provider"`.

#### DeepSeekProvider

**File:** `providers/deepseek_provider.py`
**Logger:** `"DeepSeek Provider"` (ERROR only)
**HTTP Client:** `openai.AsyncOpenAI` SDK
**Endpoint:** `https://api.deepseek.com`

**Special: Reasoning/thinking mode:**
- If `"pro"` in model name → `reasoning_effort="high"` + `extra_body={"thinking": {"type": "enabled"}}`
- Tracks `thinking_active` state; `delta.reasoning_content` (DeepSeek-specific) → wrapped in `<ocre>\n...\n</ocre>` tags
- Ensures thinking block properly closed if stream ends mid-thinking
- Conditional `frequency_penalty`/`presence_penalty` from kwargs

#### GrokProvider

**File:** `providers/grok_provider.py`
**Logger:** `"Grok Provider"` (ERROR only)
**Endpoint:** `https://api.x.ai/v1`
**Pattern:** Standard streaming; `generate_summary` is **non-streaming** (`stream=False`, yields entire response as single chunk). Nearly identical to QwenProvider and ZAIProvider — could share a common `OpenAICompatibleProvider` base class.

#### QwenProvider

**File:** `providers/qwen_provider.py`
**Logger:** `"Qwen Provider"` (ERROR only)
**Endpoint:** `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` (Alibaba international)
**Pattern:** Identical to GrokProvider. `generate_summary` non-streaming.

#### ZAIProvider

**File:** `providers/zai_provider.py`
**Logger:** `"Z.AI Provider"` (ERROR only)
**Endpoint:** `https://api.z.ai/api/paas/v4/`
**Quirk:** `base_url` ends with `/api/paas/v4/` — SDK appends `/chat/completions`.
**Pattern:** Identical to GrokProvider and QwenProvider.

#### LocalProvider

**File:** `providers/local_provider.py`
**Logger:** `"Local Provider"` (ERROR only)
**HTTP Client:** `openai.AsyncOpenAI` → `httpx.AsyncClient(timeout=None)` — **no timeout**
**Endpoint:** `http://127.0.0.1:{port}/v1` (default port 48596)
**Auth:** `"no-key-required"`

**Special: Advanced sampling params** via `extra_body`: `min_p`, `xtc_probability`, `xtc_threshold`, `dry_multiplier`, `dry_base`, `dry_allowed_length`, `dynatemp_range` — all llama.cpp-specific samplers.
`generate_summary` includes higher penalties (0.8 freq, 0.3 pres).

### 2.4 Cross-Provider Summary

#### HTTP Client & SDK

| Provider | SDK | Timeout | Auth |
|---|---|---|---|
| OpenAI | `openai.AsyncOpenAI` | 120s | Bearer token (SDK) |
| OpenRouter | `openai.AsyncOpenAI` | 120s | Bearer token (SDK) |
| Mistral | `mistralai.Mistral` | SDK default | SDK internal |
| Anthropic | raw httpx | 120s | `x-api-key` header |
| Gemini | inherited | 120s | Bearer token (SDK) |
| DeepSeek | `openai.AsyncOpenAI` | 120s | Bearer token (SDK) |
| Grok | `openai.AsyncOpenAI` | SDK default | Bearer token |
| Qwen | `openai.AsyncOpenAI` | SDK default | Bearer token |
| Z.AI | `openai.AsyncOpenAI` | SDK default | Bearer token |
| Local | `openai.AsyncOpenAI` | **None** | `"no-key-required"` |

#### Method Implementation

| Provider | generate_stream | generate_summary | generate | tool_calls | vision |
|---|---|---|---|---|---|
| OpenAI | ✅ stream | ✅ stream | ✅ non-stream | ✅ | ❌ |
| OpenRouter | ✅ stream | ✅ stream | ✅ non-stream | ✅ | ❌ |
| Mistral | ✅ stream | ✅ stream | ✅ non-stream | ✅ | ❌ |
| Anthropic | ✅ manual SSE | ✅ non-stream | ✅ non-stream | ✅ (translated) | ✅ (base64) |
| Gemini | ✅ (inherited) | ✅ (inherited) | ✅ (inherited) | ✅ (inherited) | ❌ |
| DeepSeek | ✅ stream+thinking | ✅ stream | ✅ non-stream | ✅ | ❌ |
| Grok | ✅ stream | ✅ non-stream | ✅ non-stream | ✅ | ❌ |
| Qwen | ✅ stream | ✅ non-stream | ✅ non-stream | ✅ | ❌ |
| Z.AI | ✅ stream | ✅ non-stream | ✅ non-stream | ✅ | ❌ |
| Local | ✅ stream | ✅ stream | ✅ non-stream | ✅ | ❌ |

#### Failure Handling

| Provider | Stream error display | Summary error | Generate error | Granular HTTP codes? |
|---|---|---|---|---|
| OpenAI | Yields `⚠️ ...` string | Yields `""` | `{None, None}` | ❌ |
| OpenRouter | Yields `⚠️ ...` | Yields `""` | `{None, None}` | ❌ |
| Mistral | Yields `⚠️ ...` | Yields `""` | `{None, None}` | ❌ |
| Anthropic | Yields `⚠️ Error ({code})` | Yields `""` | `{None, None}` | ✅ status check |
| Gemini | Yields `⚠️ ...` (via OpenAI) | Yields `""` | `{None, None}` | ❌ |
| DeepSeek | Yields `⚠️ ...` | Yields `""` | `{None, None}` | ❌ |
| Grok/Qwen/ZAI | Yields `⚠️ ...` | Yields `""` | `{None, None}` | ❌ |
| Local | Yields `⚠️ ...` | Yields `""` | `{None, None}` | ❌ |

**Architectural issues:**
1. No granular error handling (401/429/503/timeout indistinguishable) — only Anthropic checks HTTP codes.
2. No retry logic for transient failures.
3. GeminiProvider logger is dead code (logs go to parent `"OpenAI Provider"`).
4. Grok/Qwen/ZAI are near-identical copy-paste — could share `OpenAICompatibleProvider` base.
5. Inconsistent `generate_summary` streaming (5 stream, 4 non-stream, 1 inherited).

---

## 3. PromptEngine

**File:** `app/utils/ai_clients/prompt_engine.py` (656 lines)
**Logger:** `"Prompt Engine"` (INFO, WARNING, ERROR)

### 3.1 Methods

| # | Method | Signature | Purpose |
|---|---|---|---|
| 1 | `count_tokens` | `(text: str) → int` | Uses `tiktoken cl100k_base`; returns 0 if encoder unavailable |
| 2 | `get_activated_lorebook_entries` | `(lorebook_name, chat_messages, char, user, user_msg) → dict` | Keyword, semantic (>0.72 cosine), always_on, range, random, chain, sticky triggers |
| 3 | `get_merged_lorebook_entries` | `(char_info, chat_messages, ...) → dict` | Iterates all selected lorebooks |
| 4 | `log_prompt_structure` | `(messages) → None` | **KI#20 dedup target** — formats `[BLOCK i | ROLE | chars]` header |
| 5 | `build_system_prompt_blocks` | `(char, user, user_desc, chat_msgs, user_msg, lorebook?) → (list, dict)` | **THE CORE PIPELINE** — see §3.2 |
| 6 | `build_summary_prompt_blocks` | `(summary, msgs, char, user) → list` | Narrative summarization prompt |
| 7 | `_memory_llm_call` | `(provider, msgs) → str` | Wraps `provider.generate_stream()` with temp=0.1, top_p=0.95, max_tokens=1500 |
| 8 | `update_memory_after_response` | `(provider, msgs, char, user, lorebook?, force?) → None` | Delegates to `SoulMemoryAgent(llm_fn)` |

### 3.2 Core Pipeline: `build_system_prompt_blocks`

```
build_system_prompt_blocks(char, user, user_desc, chat_msgs, user_msg, lorebook?)
│
├─ 1. Re-read context_size → self.max_context_tokens
├─ 2. Load config: user_data, character_data, character_information
├─ 3. Build sow_variables → state_prompt_block
│      └─ If char has sow_variables: format [CURRENT STATE CHARACTERISTICS]
│      └─ Add <state_update> directive with allowed JSON keys
│
├─ 4. Resolve system prompt template → order list
│      └─ Default order: ["System prompt", "Character's information",
│         "Lorebook", "Story Summary", "Persona information", "Author's notes"]
│
├─ 5. {{user}}, {{char}}, {{user_description}} replacements
│
├─ 6. get_merged_lorebook_entries() → activated_entries
│      └─ Per lorebook: keyword, semantic (>0.72), always_on, range, random, chain, sticky
│      └─ Semantic uses EmbeddingCache.get_model() → cosine_similarity
│      └─ Returns {"classic": [...], "scenario": [...]}
│
├─ 7. Build system_blocks in order
│      └─ Each section → match/case → format content → apply replacements → token count
│
├─ 8. Append state_prompt_block (if present)
│
├─ 9. Append scenario lorebook to user message
│      └─ If scenario entries: wrap as [SYSTEM DIRECTIVE / NARRATION]
│
├─ 10. Soul Memory Processing (if enabled)
│      ├─ SoulMemoryAgent(None) — read-only instance
│      ├─ get_memory_index() → MEMORY.md → [CHARACTER PSYCHOLOGY & COGNITIVE CACHE]
│      ├─ get_user_profile() → USER.md → [USER PROFILE & RELATIONSHIP HISTORIC METADATA]
│      ├─ Topic RAG (inline, NOT SoulMemoryAgent.TopicRAG):
│      │   ├─ query: last 4 msgs + final user msg
│      │   ├─ EmbeddingCache.get_model() → encode
│      │   ├─ For each .md in topics_dir:
│      │   │   ├─ explicit_topics (MEMORY.md regex) → always included
│      │   │   ├─ diary_ → last 2500 chars
│      │   │   ├─ others → cosine_similarity > 0.42
│      │   │   └─ Top 3 topics
│      │   └─ → [RELEVANT DEEP MEMORY TOPICS]
│      └─ On exception → logger.error("[Soul Memory] Semantic Search Error")
│
├─ 11. Token budgeting & history truncation
│      ├─ available_tokens = max_context - current_count - response_reserve(500)
│      ├─ If available ≤ 128 → DRASTIC: system_blocks + last user_msg only
│      │   └─ logger.warning("Context full! Drastic compression triggered")
│      ├─ Else: reverse-iterate chat_msgs, accumulate until budget exhausted
│      │   ├─ Merge consecutive same-role msgs ("\n\n" concat)
│      │   ├─ Ensure history starts with "user" role
│      │   └─ Ensure history ends with "assistant"
│      └─ Return: system_blocks + final_history + [{"role":"user","content":msg}]
│
└─ RETURN: (final_messages, activated_entries)
```

### 3.3 Callers

| Caller | File | Method Called |
|---|---|---|
| InterfaceSignals | `interface_signals.py` L13360 | `build_system_prompt_blocks` (main chat) |
| InterfaceSignals | `interface_signals.py` L13649 | `build_system_prompt_blocks` (alternate flow) |
| InterfaceSignals | `interface_signals.py` L2102, L2510 | `build_system_prompt_blocks` (character preview) |
| InterfaceSignals | `interface_signals.py` L13444 | `update_memory_after_response` (fire-and-forget task) |
| InterfaceSignals | `interface_signals.py` L5428 | `update_memory_after_response` (manual, force=True) |
| InterfaceSignals | `interface_signals.py` L13773 | `build_summary_prompt_blocks` (auto-summary) |
| SOW_Dialog | `sow_system_signals.py` L894 | `build_system_prompt_blocks` (character preview) |
| SOW_Dialog | `sow_system_signals.py` L8148 | `build_summary_prompt_blocks` (auto-summary) |
| LorebookPreview | `custom_widgets.py` L7786 | `build_summary_prompt_blocks` |
| SoulCompanion | `soul_companion.py` L1351 | `update_memory_after_response` |
| SoulStageEngine | `soul_stage_engine.py` L1489 | `update_memory_after_response` (multi-char sync) |

**PromptEngine instantiated in 4 places** (each has own `embedding_cache` state):
- `interface_signals.py` L201
- `sow_system_signals.py` L97
- `custom_widgets.py` L7786
- `soul_stage_engine.py` L753

### 3.4 KI#20 — `log_prompt_structure` Duplication

Exists in **3 places**:
1. `PromptEngine.log_prompt_structure()` (prompt_engine.py L236-261)
2. `SOW_System.log_prompt_structure()` (interface_signals.py L13249-13274) — **exact copy**
3. Called from `SOW_System` at L13368, L13655, L2108, L2516 — uses the LOCAL copy, not `self.prompt_engine.log_prompt_structure()`

**Result:** Two identical implementations that could diverge. Should consolidate to `self.prompt_engine.log_prompt_structure(messages)` everywhere.

### 3.5 EmbeddingCache (inline)

```python
class EmbeddingCache:
    _model = None  # class-level singleton

    @classmethod get_model() → SentenceTransformer('app/utils/all-MiniLM-L6-v2')
    @classmethod clear()     → del _model, gc.collect()
```

**Used by:** prompt_engine.py for lorebook semantic triggers AND topic RAG.
**Separate from:** `SoulMemoryAgent._get_embedder()` which loads `all-MiniLM-L6-v2` independently (two copies in memory).

### 3.6 Failure Modes

| Failure | Trigger | Handling |
|---|---|---|
| Token overflow | `available ≤ 128` | Drastic compression: system blocks + last user msg only |
| Unlimited context | `max_context_tokens == -1` | No truncation; all msgs included |
| tiktoken unavailable | `get_encoding()` fails | `encoder = None`; `count_tokens()` → always 0 |
| Soul memory exception | Any error in §3.2 step 10 | Error logged; **silently skips** soul memory block |
| Lorebook not found | `lorebook_name` not in lorebooks | Returns `{classic:[], scenario:[]}` — empty |
| Embedding model fail | `EmbeddingCache.get_model()` fails | Semantic triggers fall back to keyword-only |
| Provider failure | `generate_stream()` throws | `_memory_llm_call` catches → returns `""` |

---

## 4. LocalServerManager

**File:** `app/utils/ai_clients/local_server_manager.py`
**Logger:** `"Local Server Manager"` (INFO, WARNING, ERROR, DEBUG — most verbose in AI infra)

### 4.1 Methods

| Method | Async? | Purpose |
|---|---|---|
| `is_port_available(port)` | No | TCP connect probe to `localhost:port` (2s timeout) |
| `is_server_already_running()` | No | Checks lock file (PID + cmdline) or port occupancy |
| `create_lock_file()` | No | Writes `{pid, port, timestamp}` to `backend/_temp/llama_server_48596.lock` |
| `start_server_async()` | Yes | Full startup sequence (see lifecycle) |
| `log_stream(stream, log_func)` | Yes | Reads stdout/stderr line-by-line; logs + drives UI progress |
| `ensure_server_running()` | Yes | Guarded by `restart_lock`; starts if not running; polls `model_loaded` |
| `stop_server()` | Yes | Terminates subprocess, cleans lock, resets state |
| `shutdown_server_and_model()` | Yes | `stop_server()` + UI update |

### 4.2 Lifecycle

```
INIT:
  SERVER_PORT = 48596 (hardcoded)
  lock_file = backend/_temp/llama_server_48596.lock
  restart_lock = asyncio.Lock()
  model_loaded = False
  server_process = None

START (ensure_server_running → start_server_async):
  1. Acquire restart_lock
  2. is_server_already_running()? → yes: set model_loaded=True, return
  3. Read config: 15+ keys (local_llm, llm_device, llm_backend, reasoning_mode,
     gpu_layers, context_size, mlock, flash_attention, chat_template,
     kv_cache_type, batch_size, cpu_moe_layers, custom_args)
  4. Resolve backend binary: llm_device=0 → cpu/; llm_device=1 → vulkan|cuda|hip|sycl/
  5. Build command with all flags
  6. create_lock_file()
  7. asyncio.create_subprocess_exec(*command, stdout=PIPE, stderr=PIPE)
  8. Spawn TWO log_stream tasks (stdout + stderr → logger.info)
  9. sleep(1) → check returncode → RuntimeError if crashed
  10. ensure_server_running polls model_loaded until True

HEALTH CHECK (log_stream → "all slots are idle"):
  "main: loading model"           → 20% → UI: model_loading_step_1
  "print_info: file format"       → 40% → UI: model_loading_step_2
  "load_tensors: loading tensors" → 50% → UI: model_loading_step_3
  "llama_context: constructing"   → 70% → UI: model_loading_step_4
  "main: model loaded"            → 85% → UI: model_loading_step_5
  "all slots are idle"            → 100% → UI: "MODEL ONLINE"
    → model_loaded = True
    → update_ui_for_server_state(True)

STOP:
  1. server_process.terminate() + await wait()
  2. Catch ProcessLookupError
  3. server_process = None, model_loaded = False
  4. cleanup_lock_file()
  5. update_ui_for_server_state(False)
```

### 4.3 Inbound Calls

| Caller | File | How |
|---|---|---|
| InterfaceSignals | `interface_signals.py` L202 | `self.local_server_manager = LocalServerManager(self.ui)` — **canonical instance (only one, post-iter-44)** |
| InterfaceSignals | `interface_signals.py` L985 | `on_pushButton_launch_server_clicked()` → `ensure_server_running()` |
| MainWindow | `main.py` L907 (post-iter-44) | `log_session_context()` → `self.interface_signals.local_server_manager.get_llama_version()` — instance B reused (iter-44 redirect from former orphan instance A) |
| SoulStageEngine | `soul_stage_engine.py` L1472 | `_stream_llm()` → `ensure_server_running()` before Local generation — receives instance B via constructor from `interface_signals.py:208` |

**Single instance (post-iter-44):** iter-44 consolidated the previous 3-instance architectural smell (instances A/B/C, documented in `AGENT_NAVIGATION.md` Pitfall #14). Instance A (former `MainWindow.local_server_manager` at `main.py:403`) and instance C (former `Soul_Of_Waifu_System.local_server_manager` at `sow_system_signals.py:98`) were removed; instance B (`InterfaceSignals.local_server_manager`) is the only one. The KI#50 iter-41 → iter-42 reopen was the only real manifestation of the multi-instance bug; iter-42 fixed the lookup, iter-44 made the bug class structurally impossible.

### 4.4 KI#22 — `log_stream` Split Target

`log_stream` mixes two responsibilities:
1. Logging subprocess output (stdout + stderr → `logger.info` — indistinguishable)
2. Driving UI progress bar (6-step loading progress)

Should be split into `SubprocessLogger` (log only) and `LoadingProgressTracker` (UI only).

### 4.5 Failure Modes

| Failure | Detection | Handling | User Feedback |
|---|---|---|---|
| Port busy | `is_port_available()` False | Assumes existing server usable; sets `model_loaded=True` | UI: "online" |
| Model not found | `returncode != 0` after 1s | `RuntimeError`; lock cleaned; UI: "offline" | UI: offline |
| VRAM OOM | Subprocess crashes mid-load | `model_loaded` stays False; **ensure_server_running hangs forever** | ⚠️ **No timeout!** |
| Subprocess crash mid-session | `returncode` becomes non-None later | **Not monitored** — no periodic health check | UI stays "online" |
| Lock file stale | PID doesn't exist | Deleted; falls through to port check | Transparent |
| Custom args parse error | `shlex.split()` fails | Logged; continues without custom args | Silent |

**Critical gaps:**
1. **No timeout in `ensure_server_running`** — `while not model_loaded: await sleep(1)` hangs forever if server crashes silently.
2. **No post-startup health check** — if llama-server crashes mid-session, UI stays "online".

---

## 5. GUI Signal Flow

### 5.1 InterfaceSignals — Top 20 Methods

**File:** `app/gui/interface_signals.py` (15 653 lines, class `InterfaceSignals`)
**Logger:** `"Interface Signals"` (INFO, WARNING, ERROR, DEBUG — highest error count: 53)

| # | Method | Line | Purpose |
|---|---|---|---|
| 1 | `__init__` | 91–256 | Master initializer: all scroll areas, PromptEngine, AIFactory, LocalServerManager, SoulStageEngine, configuration, translations |
| 2 | `handle_user_message` | 13282–13548 | **CORE CHAT FLOW** — full pipeline: text → prompt → provider → stream → TTS → emotion → memory |
| 3 | `open_chat` | 11775–12390 | Opens character chat tab; builds container, loads history, HUD |
| 4 | `set_main_tab` | 2585–2752 | Refreshes main character list; rebuilds card grid |
| 5 | `add_character` | 1123–1306 | Adds character via dialog; validates; saves to config |
| 6 | `check_main_character_information` | 3102–4133 | Character settings dashboard (Identity/Scenario/Examples/Notes tabs) |
| 7 | `save_changes_main_menu` | 4134–4180 | Saves character edits to characters.json |
| 8 | `open_more_button` | 12790–13153 | Compact settings editor dialog |
| 9 | `add_message` | 13790–13950 | Creates chat bubble (QFrame with avatar, name, text) |
| 10 | `render_messages` | 15333–15420 | Re-renders all chat messages by diffing IDs |
| 11 | `detect_emotion` | 15421–15500 | HuggingFace classifier → 28 emotions → avatar expression |
| 12 | `regenerate_message` | 13549–13716 | Deletes messages after target → re-calls `handle_user_message` |
| 13 | `perform_auto_summary` | 13716–13790 | Auto-summary via PromptEngine + provider |
| 14 | `load_combobox` | 5580–5778 | **Loads ALL settings to UI** — every combo/checkbox/spin from config |
| 15 | `on_toggle_web_server` | 987–1008 | Starts/stops uvicorn WebBridge on port 8000 |
| 16 | `stop_generation` | 13276–13280 | Sets `abort_generation = True`; swaps send/stop buttons |
| 17 | `clear_mode` | 13154–13236 | Chat mode: no TTS, no emotions |
| 18 | `clear_text_to_speech_mode` | 13175 | Chat mode: TTS but no calls/emotions |
| 19 | `clear_expression_mode` | 13196 | Chat mode: emotions but no TTS |
| 20 | `full_mode` | 13217 | Chat mode: TTS + calls + emotions |

### 5.2 Primary Chat Flow Signal Chain

```
User types in TextEditUserMessage
  │
  ├─ Enter key → handle_enter_key.emit()
  ├─ Send button → clicked signal
  │
  └─► handle_user_message_sync()
       │  asyncio.create_task(handle_user_message())
       │
       ├─ Read text from textEdit_write_user_message
       ├─ Create user message bubble via add_message()
       ├─ Show TypingIndicatorWidget
       ├─ prompt_engine.build_system_prompt_blocks() → messages list
       ├─ AIFactory.get_provider(conversation_method) → provider
       ├─ provider.generate_stream(messages) → async generator
       │    │
       │    ├─ Per chunk:
       │    │    ├─ TypewriterEffect.write(delta) → timer-driven reveal
       │    │    ├─ Sentence buffer → TTSWorker.add_text() [if TTS active]
       │    │    ├─ WebBridge broadcast_chunk() [if web server active]
       │    │    └─ await asyncio.sleep(0.016)
       │    │
       │    └─ After stream ends:
       │        ├─ Parse <state_update> JSON → modify_variable_value() → HUD
       │        ├─ prompt_engine.update_memory_after_response()
       │        ├─ detect_emotion() → expression/Live2D/VRM
       │        ├─ perform_auto_summary() [if enabled]
       │        ├─ Save messages to ConfigurationCharacters
       │        └─ render_messages() → final HTML display
```

### 5.3 SoW System (Voice Call) Flow

**File:** `app/gui/sow_system_signals.py` (4 209 lines, class `Soul_Of_Waifu_System`)
**Logger:** `"SOW System Interface Signals"` (INFO: 57, WARNING: 4, ERROR: 17, DEBUG: 19)

```
User clicks "Call" on character card
  → open_sow_system(character_name)
  → Create Soul_Of_Waifu_System instance

  pushButton_play.clicked → toggle_voice_interaction()
    ├─ audio_worker.audio_packet_ready → stt_worker.add_audio
    ├─ audio_worker.voice_detected → interrupt_ai()
    ├─ audio_worker.volume_signal → waveform_widget.push_volume
    ├─ stt_worker.text_ready_signal → on_user_speech_recognized()
    │    └─ handle_user_message(external_text=recognized_text)
    ├─ tts_worker.playback_worker.queue_empty → on_audio_finished()
    ├─ tts_worker.playback_worker.lipsync_signal → update_avatar_lips()
    ├─ tts_worker.audio_ready_signal → on_tts_audio_ready()

  StateSignaler.state_changed_signal → _update_state_ui()
    States: STOPPED → LISTENING → PROCESSING → SPEAKING

  Companion timers (overlay mode):
    _eye_tracker_timer → _update_eye_tracking()
    _idle_timer → _check_idle_action()
    _sleep_check_timer → _check_sleep_state()
    _breath_timer → _breath_sway_tick()
```

### 5.4 Combo Box State Machines

| Combo | Setting Key | Conditional Behavior |
|---|---|---|
| `comboBox_conversation_method` | `conversation_method` | Routes to AIFactory; shows/hides API token fields |
| `comboBox_openrouter_models` | `openrouter_model` | Saves selected model ID |
| `comboBox_translator` | translator | Index 0 = disabled (hides target_language); >0 = shows it |
| `comboBox_live2d_mode` | `live2d_mode` | 0 = GUI mode; 1 = No-GUI companion mode |
| `comboBox_llm_devices` | `llm_device` | 0 = CPU (hides GPU combos, flash attention); >0 = GPU |
| `comboBox_model_background` | model_background | 0 = color; 1 = image |
| `comboBox_kv_cache` | `kv_cache_type` | Maps {f16→0, q8_0→1, q4_1→2, q4_0→3} |
| `comboBox_soul_memory_mode` | `soul_memory_mode` | 0=Full, 1=Index+Diary, 2=Index only, 3=Diary only |

### 5.5 Settings Save/Load Flow

**Save pattern (all `save_*_in_real_time` methods):**

```
Widget changed → on_*_changed() handler
  ├─ ConfigurationSettings().update_main_setting(key, value)
  │    ├─ load_configuration() → read JSON
  │    ├─ set data["main_settings"][key] = value
  │    └─ save_configuration_edit(data) → write JSON
  └─ (For API tokens):
       ConfigurationAPI().save_api_token(key, value)
```

~40 such methods (lines 5935–6456) covering: API tokens, LLM params, advanced sampling, chat template, checkboxes.

**Load pattern (`load_combobox`, L5580):**

```
For each widget:
  ├─ ConfigurationSettings().get_main_setting(key)
  ├─ widget.setCurrentText/SetCurrentIndex/SetValue/SetChecked(value)
  └─ Conditional show/hide based on dependent settings
```

### 5.6 Custom Widget Signals

| Widget | Signal | Purpose |
|---|---|---|
| `TextEditUserMessage` | `handle_enter_key = pyqtSignal()` | Emits on Enter (not Shift+Enter) |
| `TypewriterEffect` | *(uses QTimer internally)* | Timer-driven character reveal |
| `SowToast` | `closed = pyqtSignal()` | Auto-close notification |
| `AudioPlaybackWorker` | `lipsync_signal(float)` | RMS-based mouth open (0.0–1.0) |
| `AudioPlaybackWorker` | `queue_empty_signal()` | Audio playback finished |
| `TTSWorker` | `audio_ready_signal(str)` | b64 audio for web client |
| `STTWorker` | `text_ready_signal(str)` | Recognized text |
| `AudioInputWorker` | `voice_detected_signal()` | VAD trigger |
| `AudioInputWorker` | `volume_signal(float)` | Volume meter |
| `AudioInputWorker` | `audio_packet_ready(bytes)` | Raw audio for STT |

### 5.7 Appearance Signal Chain

```
AppearanceSettingsTab emits:
  ├─ chatAppearanceChanged(dict) → on_chat_appearance_changed()
  ├─ windowThemeChanged(dict) → on_window_theme_changed()
  │    └─ update_main_setting("window_theme", dict)
  ├─ uiAppearanceChanged(dict) → on_ui_appearance_changed()
  ├─ requestChatPreviewUpdate → on_request_chat_preview_update()
  ├─ resetAppearanceRequested → on_reset_appearance()
  └─ saveChatAppearanceRequested(dict) → on_save_chat_appearance()
```

---

## 6. Soul Memory Agent Lifecycle

**File:** `app/utils/soul_memory.py` (1 032 lines)
**Logger:** `"SoulMemory"` (INFO: 15, WARNING: 11, ERROR: 9, DEBUG: 2)

### 6.1 Methods

| Method | Purpose |
|---|---|
| `get_memory_paths(char, chat_id)` → `(mem_dir, idx_path, usr_path, topics_dir, log_path, backup_dir)` | Computes `.soul/<char>/chats/<chat_id>/memory/...` paths |
| `get_memory_index(char, chat_id)` → str | Reads MEMORY.md (truncated 5000 chars) |
| `get_user_profile(char, chat_id)` → str | Reads USER.md (truncated 3000 chars) |
| `update_memory_after_response(msgs, char, user, lorebook?, force?)` | **Main entry** — acquires lock → `_run_update_pipeline` |
| `get_memory_stats(char, chat_id)` → dict | Stats for UI viewer |
| `list_topic_files(char, chat_id)` → list[dict] | Topic file listing |
| `restore_backup(char, backup_filename)` → bool | Revert from backup |
| `list_backups(char, chat_id)` → list[str] | Available backups |

**Key private methods:**
- `_call_router_agent()` → LLM call → JSON parse → `{updated_index, updated_user_profile, topic_plan}`
- `_call_archivist_agent()` → LLM call → `[TOPIC_CONTENT_START]...[TOPIC_CONTENT_END]` extraction
- `_update_daily_diary()` → LLM call → append to `Diary_YYYY-MM-DD.md`
- `_run_update_pipeline()` → **Core orchestration** (batch check → Router → writes → Diary → Archivist loop)
- `_safe_write_index()` → atomic `.tmp` → `replace()`, min 100 chars
- `_safe_write_user_profile()` → atomic, min 50 chars
- `_safe_write_topic()` → atomic, min 50 chars

**Constants:** `BATCH_SIZE=4`, `MAX_DELTA_MSGS=14`, `MSG_OVERLAP=2`, `MAX_BACKUP_COUNT=5`, `MIN_INDEX_CHARS=100`

### 6.2 .soul/ Directory Structure

```
.soul/
  <character_name>/            # sanitized
    chats/
      <chat_id>/
        memory/
          MEMORY.md            # Character psychology (core_identity, internal_state, cognitive_drive, dissonance)
          USER.md              # User profile & relationship metadata
          last_mem_update.txt  # Last processed message count (integer)
          agent_logs.txt       # Append-only pipeline log
          topics/
            *.md               # Per-topic lore (location_forest.md, npc_elder.md, etc.)
            Diary_YYYY-MM-DD.md  # First-person daily reflections
          backups/
            MEMORY_YYYYMMDD_HHMMSS.md  # Rolling backups (max 5)
```

### 6.3 Two-Phase Lifecycle

#### Phase 1: MEMORY RETRIEVAL (before AI generation)

```
PromptEngine.build_system_blocks()
  → SoulMemoryAgent(None)  [read-only]
  → get_memory_paths()     → .soul/... paths
  → get_memory_index()     → MEMORY.md → [CHARACTER PSYCHOLOGY & COGNITIVE CACHE]
  → get_user_profile()     → USER.md → [USER PROFILE & RELATIONSHIP HISTORIC METADATA]
  → EmbeddingCache.get_model() [NOT SoulMemory's embedder!]
  → encode(query from last 4 msgs + current user text)
  → cosine_similarity(query_vec, topic_vecs) > 0.42 → top 3
  → [RELEVANT DEEP MEMORY TOPICS]
  → Append to system_blocks → injected into LLM context
```

#### Phase 2: MEMORY UPDATE (after AI response)

```
PromptEngine.update_memory_after_response(provider, msgs, ...)
  → SoulMemoryAgent(lambda msgs: _memory_llm_call(provider, msgs))
  → Acquires asyncio.Lock (per character+chat)
  → _run_update_pipeline():
      1. Batch check: msg_count vs last_mem_update.txt
         - If batch=0 (manual) and not force → SKIP
         - If diff < batch and not force → SKIP ("Accumulating batch")
      2. Slice delta: messages from (last_count - MSG_OVERLAP) to end, cap MAX_DELTA_MSGS=14
      3. Build RAG query from last 2 turns
      4. TopicRAG.get_relevant_topics() (SoulMemory's own embedder)
      5. ROUTER AGENT (modes 0, 1, 2):
         - Mode 0 → _ROUTER_SYSTEM (full: includes topic_plan)
         - Modes 1,2 → _ROUTER_SYSTEM_LITE (no topic_plan)
         - LLM call → JSON parse → MEMORY.md + USER.md
      6. _safe_write_index() (atomic, backup, min 100 chars)
      7. _safe_write_user_profile() (atomic, min 50 chars)
      8. DIARY AGENT (modes 0, 1, 3):
         - _DIARY_SYSTEM prompt → LLM call → append Diary_YYYY-MM-DD.md
      9. ARCHIVIST AGENT (mode 0 only):
         - Per topic_plan action → _call_archivist_agent()
         - _safe_write_topic() → atomic
      10. Log: "Pipeline complete"
```

### 6.4 Operation Modes

| Mode | Name | Router | Archivist | Diary |
|---|---|---|---|---|
| 0 | Full | Full (with topic_plan) | ✅ | ✅ |
| 1 | Index+Diary (Soul Link) | Lite (no topic_plan) | ❌ | ✅ |
| 2 | Index only (Mind Spark) | Lite (no topic_plan) | ❌ | ❌ |
| 3 | Diary only (Reflection Flow) | ❌ | ❌ | ✅ |

### 6.5 Two Embedding Model Issue

| Instance | Location | Model Path | Purpose |
|---|---|---|---|
| PromptEngine `EmbeddingCache` | `prompt_engine.py:20-37` | `app/utils/all-MiniLM-L6-v2/` (local disk) | Lorebook semantic + topic RAG in system prompt |
| SoulMemory `_EMBEDDER` | `soul_memory.py:37-47` | `"all-MiniLM-L6-v2"` (HuggingFace hub) | TopicRAG for Router Agent input |

**Two copies in memory (~100MB duplicated)** when both features are active. `EmbeddingCache.clear()` exists but `_EMBEDDER` has no unload mechanism.

### 6.6 Failure Modes

| Failure | Handling |
|---|---|
| File lock contention | `asyncio.Lock` per character+chat; serialized pipeline |
| Embedding model missing | Falls back to truncation (return first N topics) |
| LLM Router failure | Returns `{}`; pipeline aborts |
| Router JSON parse failure | Falls back to regex `[UPDATE_INDEX_START]...[UPDATE_INDEX_END]` |
| Degenerate LLM output (too short) | Write REJECTED; old file preserved (min 100/50 chars) |
| Atomic write failure | `.tmp` cleaned; old file unchanged |
| Hallucinated topic filename | `_BAD_TOPIC_NAMES` filter; skipped |
| Diary too short (<20 chars) | Not written |

---

## 7. TTS & STT Pipeline

### 7.1 TTS — 6 Engines

**File:** `app/utils/text_to_speech.py`
**Logger:** `"Text-To-Speech Module"` (INFO: 16, WARNING: 5, ERROR: 16)

| # | Engine | Class | Mode | Key Method |
|---|---|---|---|---|
| 1 | Edge TTS | `EdgeTTS` | Cloud (free) | `generate_speech_with_edge_tts_sow_system(text, char)` → WAV |
| 2 | ElevenLabs | `ElevenLabs` | Cloud (paid) | `generate_speech_with_elevenlabs_sow_system(text, voice_id)` → WAV |
| 3 | Silero TTS | `SileroTTS_SOW_System` | Local | `generate_speech_with_silero(text, char)` → WAV |
| 4 | Kokoro TTS | `KokoroTTS_SOW_System` | Local | `generate_speech_with_kokoro(text, char)` → WAV |
| 5 | Qwen-3 TTS | `Qwen3TTS_SOW_System` | Local (3 modes) | `generate_speech_with_qwen3(text, char)` → WAV |
| 6 | XTTSv2 | `XTTSv2_SOW_System` | Local (Coqui) | `generate_speech_with_xttsv2_sow_system(text, lang, char)` → WAV |

All 6 support optional **RVC** (voice cloning) post-processing: if `rvc_enabled` + `rvc_file` → `RVCInference` on base WAV.

### 7.2 TTS Signal Chain

```
AI response text (full_text)
  → TTSWorker.add_text(text)
    → Sentence splitting (regex on .!?;: max 450 chars)
    → Queue of chunks
    → TTSWorker.run() loop:
      → Pop chunk → dispatch by tts_method string
      → Engine generates WAV
      → audio_ready_signal.emit(b64_audio)  [for web client]
      → AudioPlaybackWorker.add_audio_file(wav_path)
        → sounddevice.play() + lipsync_signal.emit(rms) per 50ms
        → queue_empty_signal.emit() when done
```

### 7.3 STT Pipeline

**File:** `app/utils/speech_to_text.py`
**Logger:** `"Speech-To-Text Module"` (INFO: 18, WARNING: 1, ERROR: 5)

Two-worker architecture:
- `AudioInputWorker(QThread)` — microphone + Silero VAD → `audio_packet_ready(bytes)`
- `STTWorker(QThread)` — Faster-Whisper transcription → `text_ready_signal(str)`

```
Microphone → AudioInputWorker
  → Silero VAD (speech_prob > 0.5)
  → Collect frames until silence (45 chunks)
  → audio_packet_ready.emit(full_audio_bytes)
  → STTWorker.add_audio()
  → Faster-Whisper transcribe
  → Hallucination filter (60+ known patterns)
  → text_ready_signal.emit(text)
  → handle_user_message(external_text=text)
```

**Failure modes:** VAD model load failure → loop sleeps 1s; CUDA OOM → auto-fallback to CPU+int8; hallucination filter removes 60+ known Russian/English patterns; short text (<2 chars) filtered.

---

## 8. Web Server / WebBridge

**File:** `app/utils/web_server.py` (FastAPI)
**Logger:** `"WebBridge"` (ERROR only: 3 calls)
**⚠️ NO AUTHENTICATION** — see SECURITY.md

### 8.1 Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Serve index.html |
| GET | `/api/config` | Active character + user name |
| GET | `/api/characters` | List character names |
| GET | `/api/avatar_config/{char}` | Expression mode, image paths |
| GET | `/api/avatar/{char}` | Avatar image file |
| GET | `/api/background` | Chat background |
| GET | `/api/history/{char}` | Chat history (paginated) |
| POST | `/api/character/switch` | Switch active character |
| DELETE/PATCH | `/api/messages/{id}` | Delete/edit message |
| POST | `/api/messages/{id}/regenerate` | Regenerate message |
| POST | `/api/generation/stop` | Stop current generation |
| POST | `/api/voice/stt` | Upload audio → Whisper → AI |
| WebSocket | `/ws` | Real-time bidirectional |

### 8.2 Signal Flow

```
WebSocket /ws receives {"type": "user_input", "text": ...}
  → signals.textEdit_write_user_message.setPlainText(text)
  → load character config → get conversation_method
  → manager.broadcast({"type": "user_message", ...}, exclude=sender)
  → asyncio.create_task(signals.handle_user_message(char, conv_method))
  → [AI pipeline generates response]
  → signals calls web_bridge.broadcast_chunk(chunk) per streaming token
  → signals calls web_bridge.broadcast_audio(b64_audio) for TTS
  → signals calls web_bridge.broadcast({"type": "emotion_changed", ...})
```

---

## 9. Discord Bot

**File:** `app/utils/discord_manager.py`
**Logger:** `__name__` (resolves to `app.utils.discord_manager`; INFO: 6, WARNING: 3, ERROR: 6, DEBUG: 5)

### 9.1 Signal Flow

```
Discord on_message(message)
  → Filter: ignore self, non-DM non-mentioned
  → process_ai_response(message, message.content)
    → Read current_active_character from interface_signals
    → signals.handle_user_message(char, conv_method, external_text=text)
    → [AI pipeline generates response]
    → discord_response_callback sends reply to Discord
```

### 9.2 Failure Modes

- **No token:** `start_bot()` logs warning, returns silently.
- **No active character:** Sends "*No character is currently loaded.*"
- **chat_lock:** `asyncio.Lock()` — only one AI request at a time.
- **Missing Send Messages permission:** `_safe_reply` tries `channel.send()`, logs error if fails.

---

## 10. Soul Companion (Overlay)

**File:** `app/utils/soul_companion/soul_companion.py`
**Logger:** `"SoulCompanion"` (INFO: 34, WARNING: 12, ERROR: 17, DEBUG: 3 — **most log calls of any module**)

### 10.1 Initialization

```
SoulCompanion(system_ref)  # = sow_system_signals
  → NeurohormoneSystem()   (oxytocin=0.70, dopamine=0.60, cortisol=0.10, energy=0.85)
  → EmotionState()         (current="neutral")
  → Scratchpad()           (max 8 entries)
  → PluginLoader()         (6 built-in + user plugins)
  → SoulCompanionEventBus() (async queue on daemon thread)
  → MCPManager()           (MCP tool servers)
  → QTimer x4: _os_poll(20s), _heartbeat(30s), _hormone_tick(60s), _idle_check(15s)
```

### 10.2 Proactive AI Signal Flow

```
QTimer _os_poll_timer (20s):
  → _qt_poll_os() → Win32 API _get_window_title()
  → Privacy filter → Debounce (4s)
  → hormones.on_new_os_event()
  → event_bus.emit_threadsafe("os_context", {"window_title": ...})

QTimer _hormone_timer (60s):
  → hormones.tick() → emotion.from_hormones()
  → If changed: _apply_emotion_to_avatar()

Event Loop (SoulCompanionEventBus):
  → _event_loop(bus) → _handle_event(event)
    → Route to reactive plugins
    → Build COMPANION_SYSTEM_PROMPT (hormones, emotion, scratchpad, memory, tools)
    → _call_companion() → _llm_call() → AIFactory.get_provider() → provider.generate()
    → Parse JSON → action dispatch:
      "idle"         → nothing
      "micro_react"  → _apply_emotion_to_avatar()
      "inner_thought"→ scratchpad.add() + hormones.on_inner_thought()
      "use_tool"     → _execute_tool() / _call_native_tools_selection()
      "speak"        → _speak() → QMetaObject.invokeMethod(sys, "_sc_speak_slot")
                       → TTS + update_memory_after_response()
```

### 10.3 Built-in Tools

| Tool | Action |
|---|---|
| `media_control` | Win32 keybd_event (play/pause/next/prev) |
| `web_search` | DDGS → Brave → SearXNG fallback chain |
| `open_url` | webbrowser.open() |
| `get_system_info` | Date/time/weekday |
| `take_screenshot` | mss + PIL → base64 JPEG |
| `read_clipboard` | QApplication.clipboard() |

### 10.4 Failure Modes

- **JSON parse failure:** `_strip_json()` regex rescue, then `None`.
- **Tool loop detection:** `_executed_tools_in_chain` set prevents re-executing same tool.
- **Windows-only:** `_get_window_title()` uses `ctypes.windll`; returns "" on Linux/Mac.
- **Sleep mode:** `hormones.is_sleeping` (energy ≤ 0.08) blocks all speech.
- **MCP init failure:** Errors logged per-server, skipped.

---

## 11. Soul Stage (RPG)

**File:** `app/utils/ai_clients/soul_stage_engine.py` (1 509 lines)
**Logger:** `"SoulStage"` (INFO: 12, WARNING: 3, ERROR: 3)

### 11.1 Turn Flow: `run_turn()`

```
1. GM Planner Phase:
   → _call_gm_planner(party, player_msg, ...)
     → GM_PLANNER_SYSTEM prompt (world, party, NPCs, backgrounds)
     → _stream_llm() → AIFactory.get_provider() → provider.generate_stream()
     → PlannerParser.parse(raw_json) → {narration_plan, next_actor, spawns, key_facts, ...}

2. World State Update:
   → world_state.update_from_plan(plan)
   → NPC spawns/despawns

3. Narrator Phase:
   → _call_gm_executor(narration_plan)
     → GM_EXECUTOR_SYSTEM prompt
     → _stream_llm() → [NARRATION] tags → on_narrator_chunk()

4. Actor Loop (max depth 3):
   while next_actor != "PLAYER" and depth < 3:
     if party → _call_character(name, ...) → character_stream_fn()
     elif NPC → _call_npc(npc, ...) → _stream_llm()
     → _call_gm_routing() → next_actor decision

5. Cleanup:
   → _summarize_history() (compress old events)
   → on_turn_complete()
```

### 11.2 Failure Modes

- **JSON parse failure:** PlannerParser falls back to EMPTY_PLAN (safe defaults).
- **Unknown actor:** Routes to PLAYER with warning.
- **Cancel race:** `_cancel_flag` checked at every stream chunk.
- **Infinite actor loop:** `max_actor_depth=3` hard cap.
- **History overflow:** LLM compression; if fails, raw events with 600-char truncation.

---

## 12. Emotion Detection

**No separate file** — embedded in `interface_signals.py` and `sow_system_signals.py`.
**Model:** `AutoModelForSequenceClassification` from `app/utils/emotions/detector/` (28 classes).

### 12.1 Signal Flow

```
AI response text (full_text)
  → asyncio.create_task(detect_emotion(char, text))
    → Lazy load tokenizer + model (first call)
    → model(**inputs) → argmax(logits) → 28-class emotion
    → Save to config: chats[current_chat]["current_emotion"]
    → Dispatch by mode:
      "Expressions Images" → show_emotion_image(folder, char)
      "Live2D Model" → update_model_json() + play_motion_safely()
      "VRM" → set_expression_vrm(emotion) + play_vrm_animation()
    → WebBridge broadcast: {"type": "emotion_changed", "emotion": emotion}
```

### 12.2 VRM Expression Mapping

| 28-class emotions | VRM blend shape |
|---|---|
| anger/disapproval/annoyance/disgust | `"angry"` |
| admiration/amusement/approval/desire/gratitude/love/optimism/pride/joy | `"happy"` |
| neutral | `"neutral"` |
| caring/relief | `"relaxed"` |
| disappointment/grief/remorse/sadness | `"sad"` |
| confusion/curiosity/embarrassment/fear/nervousness/realization/surprise | `"surprised"` |

---

## 13. Image Generator

**File:** `app/utils/image_generator.py`
**Logger:** `"ImageGenerator"` (INFO: 3, WARNING: 1, ERROR: 22, DEBUG: 8, EXCEPTION: 4 — **only logger using `.exception()`**)

### 13.1 Providers

| Provider | Method | Endpoint | Auth |
|---|---|---|---|
| A1111/ComfyUI | `generate_a1111()` | `http://127.0.0.1:7860/sdapi/v1/txt2img` | None |
| DALL-E 3 | `generate_dalle()` | `https://api.openai.com/v1/images/generations` | `OPEN_AI_API_TOKEN` |
| NovelAI | `generate_novelai()` | `https://image.novelai.net/ai/generate-image` | `NOVELAI_API_TOKEN` |
| FLUX | `generate_flux()` | `https://fal.run/fal-ai/flux-pro/v1.1` | `FAL_API_TOKEN` |

### 13.2 Signal Chain

```
[Triggered from sow_system_signals or interface_signals]
  → ImageGenerator().generate_image(core_prompt, character_name)
    → Read settings: image_provider, prefix/negative prompt, width, height, steps
    → Dispatch → provider method → save to app/gallery/{char}/img_{timestamp}.png
```

---

## 14. Logging Touchpoints Inventory

**Root logger setup (main.py):** `logging.getLogger()` at INFO level; `FileHandler` only (no console); `sys.excepthook → logger.critical(...)`.

### 14.1 Full Logger Table (34 loggers, 35 `getLogger()` calls)

| # | Logger Name | File | Subsystem | INFO | WARN | ERROR | DEBUG | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | *(root)* | main.py | App Entry | 4 | 1 | 2 | 0 | Global exception handler |
| **AI Providers** |
| 2 | `OpenAI Provider` | providers/openai_provider.py | AI | 0 | 0 | 3 | 0 | Error only |
| 3 | `Anthropic Provider` | providers/anthropic_provider.py | AI | 0 | 0 | 4 | 0 | Most granular |
| 4 | `Gemini Provider` | providers/gemini_provider.py | AI | 0 | 0 | 0 | 0 | **Dead code** |
| 5 | `Mistral Provider` | providers/mistral_provider.py | AI | 0 | 0 | 3 | 0 | |
| 6 | `OpenRouter Provider` | providers/openrouter_provider.py | AI | 0 | 0 | 3 | 0 | |
| 7 | `Qwen Provider` | providers/qwen_provider.py | AI | 0 | 0 | 3 | 0 | |
| 8 | `DeepSeek Provider` | providers/deepseek_provider.py | AI | 0 | 0 | 3 | 0 | |
| 9 | `Grok Provider` | providers/grok_provider.py | AI | 0 | 0 | 3 | 0 | |
| 10 | `Local Provider` | providers/local_provider.py | AI | 0 | 0 | 3 | 0 | |
| 11 | `Z.AI Provider` | providers/zai_provider.py | AI | 0 | 0 | 3 | 0 | |
| **AI Infrastructure** |
| 12 | `AI Factory` | ai_factory.py | AI Infra | 0 | 0 | 1 | 0 | Unknown method only |
| 13 | `MCP Client` | mcp_client.py | AI Infra | 4 | 2 | 8 | 0 | SSE protocol |
| 14 | `Prompt Engine` | prompt_engine.py | AI Infra | 5 | 1 | 3 | 0 | Embedding, truncation, memory |
| 15 | `Local Server Manager` | local_server_manager.py | AI Infra | 21 | 4 | 3 | 2 | Most verbose AI infra |
| 16 | `SoulStage` | soul_stage_engine.py | RPG | 12 | 3 | 3 | 0 | Planner, routing, party |
| **Memory & Soul** |
| 17 | `SoulMemory` | soul_memory.py | Memory | 15 | 11 | 9 | 2 | Router/Archivist/Diary |
| 18 | `SoulCompanion` | soul_companion.py | Companion | 34 | 12 | 17 | 3 | **Most calls overall** |
| 19 | `CustomPlugin` | soul_companion.py:712 | Companion | 0 | 0 | 0 | 0 | **Dead code** |
| **TTS & Speech** |
| 20 | `Text-To-Speech Module` | text_to_speech.py | TTS | 16 | 5 | 16 | 0 | 6 engines + RVC |
| 21 | `Speech-To-Text Module` | speech_to_text.py | STT | 18 | 1 | 5 | 0 | VAD + Whisper |
| **Web & Network** |
| 22 | `WebBridge` | web_server.py | Web Server | 0 | 0 | 3 | 0 | FastAPI |
| 23 | `app.utils.discord_manager` | discord_manager.py | Discord | 6 | 3 | 6 | 5 | Only `__name__` logger |
| **Configuration** |
| 24 | `Configuration` | configuration.py | Config | 2 | 2 | 15 | 0 | CRUD validation |
| **GUI** |
| 25 | `Interface Signals` | interface_signals.py | GUI | 22 | 12 | 53 | 3 | **Highest error count** |
| 26 | `Interface Signals` | custom_widgets.py | GUI Widgets | 27 | 0 | 7 | 4 | **Shared name** with #25 |
| 27 | `SOW System Interface Signals` | sow_system_signals.py | GUI System | 57 | 4 | 17 | 19 | Voice/overlay/companion |
| **Utilities** |
| 28 | `ImageGenerator` | image_generator.py | Images | 3 | 1 | 22 | 8 | **Only `.exception()` user** |
| 29 | `Characters Card Client` | character_cards.py | Cards | 0 | 0 | 11 | 0 | HTTP/JSON errors |
| 30 | `Translator Module` | translator.py | Translation | 0 | 0 | 4 | 0 | |
| 31 | `Models Hub Client` | models_hub.py | Models Hub | 2 | 5 | 0 | 0 | |
| 32 | `LlamaUpdater` | backend_updater.py | Backend | 1 | 0 | 0 | 0 | |
| 33 | `Ambient Player Client` | ambient_client.py | Ambient | 0 | 0 | 0 | 0 | **Dead code** |
| 34 | *(root)* — main.py | main.py | App | *(same as #1)* | | | | |

### 14.2 Statistics

| Metric | Value |
|---|---|
| Total `getLogger()` calls | 35 (34 unique names) |
| Loggers with zero log calls | 3 (`Gemini Provider`, `CustomPlugin`, `Ambient Player Client`) |
| Duplicate logger name | `Interface Signals` (shared by interface_signals.py + custom_widgets.py) |
| Logger using `__name__` | 1 (`discord_manager.py`) |
| Total log calls across app/ | ~588 (INFO: 245, ERROR: 231, WARNING: 66, DEBUG: 46, EXCEPTION: 4) |
| Most verbose logger | `SoulCompanion` (~66 calls) |
| Highest error count | `Interface Signals` (53 errors) |
| Root logger level | INFO |
| Handler | FileHandler only (no console) |
| Only `.exception()` user | `ImageGenerator` |
| Only `.critical()` user | main.py (sys.excepthook) |

### 14.3 Subsystem Mapping

| Subsystem | Loggers | Count |
|---|---|---|
| AI Providers | OpenAI, Anthropic, Gemini, Mistral, OpenRouter, Qwen, DeepSeek, Grok, Local, Z.AI | 10 |
| AI Infrastructure | AI Factory, MCP Client, Prompt Engine, Local Server Manager | 4 |
| Soul Stage (RPG) | SoulStage | 1 |
| Soul Memory | SoulMemory | 1 |
| Soul Companion | SoulCompanion, CustomPlugin | 2 |
| TTS & Speech | Text-To-Speech, Speech-To-Text | 2 |
| Web Server | WebBridge | 1 |
| Discord Bot | discord_manager | 1 |
| Configuration | Configuration | 1 |
| GUI | Interface Signals (×2), SOW System Interface Signals | 3 |
| Image Generation | ImageGenerator | 1 |
| Utilities | Characters Card, Translator, Models Hub, LlamaUpdater, Ambient Player | 5 |
| Application Root | *(root)* | 1 |
| **Total** | | **34** |

### 14.4 Key Observations

1. **Silent loggers:** `Gemini Provider`, `CustomPlugin`, `Ambient Player Client` — dead code or stubs.
2. **Duplicate name:** `Interface Signals` shared by interface_signals.py and custom_widgets.py — logs indistinguishable.
3. **Provider uniformity:** All 10 providers follow identical pattern: 3 ERROR-only calls (stream/summary/generate), except Anthropic (4) and Gemini (0).
4. **No `logging.basicConfig()`** — manual root logger setup with FileHandler only.
5. **No console output** — all logs go to `logs/sow_<timestamp>.log`.
6. **KI#20 target:** `log_prompt_structure` has 2 identical implementations — should consolidate to PromptEngine method.

---

## 15. Cross-Subsystem Signal Connection Map

```
                    ┌─────────────────────────────────┐
                    │     MAIN GUI (InterfaceSignals)    │
                    │     THE HUB — all signal wiring     │
                    └──┬──────────┬──────────┬──────────┘
                       │          │          │
          ┌────────────┘          │          └────────────┐
          ▼                       ▼                       ▼
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  STT Worker     │  │  AI Pipeline     │  │  Discord Bot     │
│  audio→text     │  │  (PromptEngine)  │  │  on_message→AI   │
│  text_ready_    │──│  →provider.      │──│  →handle_user_   │
│  signal ────────│  │   generate_stream│  │  message()       │
└─────────────────┘  └──┬───┬───┬───┬───┘  └──────────────────┘
                        │   │   │   │
         ┌──────────────┘   │   │   └──────────────────┐
         ▼                  ▼   ▼                      ▼
┌──────────────────┐ ┌──────────────┐ ┌──────────────────────────┐
│ TTSWorker        │ │ Emotion      │ │ SoulCompanion            │
│ add_text()→queue │ │ Detector     │ │ EventBus→_handle_event() │
│ →engine→WAV     │ │ 28 classes   │ │ →_call_companion()→LLM   │
│ →PlaybackWorker  │ │ →Image/L2D/  │ │ →_speak()→TTS            │
│ →lipsync_signal  │ │  VRM         │ │ →update_memory()         │
└─────────────────┘ └──────────────┘ └──────────────────────────┘
                          │
         ┌────────────────┼──────────────┐
         ▼                ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ WebBridge    │ │ ImageGen     │ │ SoulStage    │
│ WS broadcast │ │ 5 providers  │ │ Orchestrator │
│ chunk/audio/ │ │ A1111/DALL-E │ │ GM Planner→  │
│ emotion      │ │ NAI/FLUX     │ │ Executor→    │
└─────────────┘ └─────────────┘ │ Routing→NPC  │
                                └──────────────┘
```

---

## 16. Future — iter-13 Debug Tab Hooks

This section sketches where a future debug tab (iter-13) could hook into the signal map
for real-time monitoring of subsystems during development.

### Proposed Hook Points

| Subsystem | Hook Target | What to Monitor |
|---|---|---|
| AI Providers | `provider.generate_stream()` yield loop | Per-chunk latency, total tokens, error rate |
| PromptEngine | `build_system_prompt_blocks()` return | System block structure, token budget, activated lorebooks |
| PromptEngine | `log_prompt_structure()` (consolidated) | Final prompt dump — replace INFO log with debug tab |
| LocalServerManager | `model_loaded` flag + `server_process.returncode` | Server state, health, loading progress |
| Soul Memory | `_run_update_pipeline()` stages | Router/Archivist/Diary agent timing, batch progress |
| TTS | `TTSWorker` queue depth + engine latency | Queue size, generation time per chunk |
| Companion | `SoulCompanionEventBus` event queue | Event types, hormone levels, decision JSON |
| SoulStage | `run_turn()` callbacks | Planner JSON, actor routing, narration chunks |
| Logging | All 34 loggers → live stream | Real-time log viewer in debug tab |

### Integration Strategy

The debug tab should be a `QWidget` added to `tabWidget_options` in `sowInterface.py`, with
a `DebugTabController` in `app/gui/` that connects to existing signals without modifying
the core pipeline. It should:

1. **Subscribe to existing PyQt6 signals** (e.g., `lipsync_signal`, `text_ready_signal`) to display real-time data.
2. **Replace `log_prompt_structure` INFO logs** with structured debug tab output (consolidating KI#20).
3. **Monitor `LocalServerManager.model_loaded`** via a periodic health check callback.
4. **Stream all 34 loggers** to a live log viewer widget via a custom `logging.Handler`.
5. **Display hormone/emotion state** from `SoulCompanion.NeurohormoneSystem` via a new signal.

---

*End of SIGNAL_MAP.md — iter-7.5*
