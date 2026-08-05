# Chat Template Strategy for Multi-Model RP Clients

> Target application class: SillyTavern / Backyard AI / Soul of Waifu — multi-user roleplay frontends where users connect to arbitrary LLMs across many backends, with new models released continuously.

---

## Update Log

| Version | Date | Author | Changes |
|---|---|---|---|
| 2026-07-29 | iter-9-consolidation-contradictions-resolved | SoW agent (consolidation audit vs new HF primary-source research) | **Targeted refinements based on consolidated engineering report** covering 4 new nuances (KV-cache date_string, offline HF cache with TTL+commit_hash, UI autogeneration from template variables, author-error vocab validation) and resolution of 6 architectural contradictions. Edits: §7.2 + §9 clarify `date_string` is bound to **chat session** (stored in `chat.created_at`), not app session; §8.5 NEW — HF Source-of-Truth Files Cache (4-file local cache with TTL + `commit_hash` verification, distinct from §8 patch registry); §11.2 explicit exclusion of reasoning tags (``) from spoofing sanitization — they are content markers handled by §17.3 history stripping (assistant turns only); §12 new UI requirement #9 — capability-aware UI auto-hide/show (e.g., Thinking toggle hidden when template lacks `enable_thinking`); §17.3 Family B clarified — API messages list MUST use separate `reasoning_content` field (no synthesized tags), UI display MAY render inline tags with `is_native_reasoning=True` flag, storage format preferred separate fields; §22 sources expanded with llama.cpp Wiki Templates, chujiezheng/chat_templates library, gpt-oss and Mistral v7-Tekken HF links. No new KI raised — strategy confirmed accurate, only ambiguities resolved. |
| 2026-07-28 | iter-4-research-problematic-models | SoW agent (verified via primary sources) | **Major additions.** New §17 (Known Problematic Models Reference — verified against HF model cards), §18 (Reasoning Mode Handling — R1/Qwen3/gpt-oss/Nemotron/Phi-4/Skyfall), §19 (MoE Architecture Considerations), §20 (Mistral Version Disambiguation — v1/v2/v3/v3-Tekken/v7-Tekken via `[SYSTEM_PROMPT]` token), §21 (llama.cpp Runtime Flags — `--jinja` default behavior, `--chat-template-kwargs`), §22 (DeepSeek Fullwidth-Pipe Byte-Level Matching — U+FF5C vs ASCII `|`). Minor corrections: §1.1 Gemma 3/4 system-role synthesis note; §3 Layer 1.5 HF `chat_template.jinja` separate-file path; §10 DeepSeek byte-level warning; §16 sources expanded. Also: brought this document INTO the repo (was previously external). |
| (initial) | iter-3 | previous LLM agent | Initial 517-line specification: layered pipeline, sandboxed Jinja, signed patch registry, RP hardening, KV-cache, streaming stop, vocab validation, UI, testing. |

---

## 0. Executive Summary

There is **no universal chat template**. ChatML is correct only for models trained on it (Qwen, Yi, OpenHermes); for Llama 3, Mistral, Command R, Gemma, DeepSeek it causes silent quality degradation because their vocabularies do not contain `<|im_start|>` / `<|im_end|>` as atomic tokens — BPE splits them into 5–7 subwords and the model receives an out-of-distribution input. This is not a crash; it is invisible quality loss that surfaces as "the model became stupid" after 2–3 turns.

The correct architecture is a **layered detection pipeline** with an explicit preference for native backend APIs where possible, paired with a sandboxed Jinja renderer, a signed external patch registry, and a set of RP-specific hardening measures that are unique to this application class.

This document consolidates the underlying theory, the layered pipeline, security constraints, performance requirements, and operational concerns into a single implementable specification.

---

## 1. Background: Why Chat Templates Are a Protocol, Not a Convenience

A chat template (typically Jinja2) is a deterministic function that converts a list of `{role, content}` messages into a single string for tokenization. The model only sees a token stream — therefore the template is the wire protocol between the inference runner and the model.

Naive message concatenation fails for four concrete reasons:

1. **Boundary / role special tokens.** Models are trained on atomic identifiers of turn boundaries (`<|im_start|>`, `[INST]`, `<|eot_id|>`, etc.). Without them, the tokenizer splits these constructs into subwords — the model receives OOD input.
2. **Generation prompt.** Generation must begin after a strictly defined sequence (e.g. `<|im_start|>assistant\n`). Without it, the model may continue the user's turn.
3. **System prompt position.** Different formats place system differently: as a separate block, inside the first `[INST]`, or merged with user. Misplacement silently drops instructions.
4. **Whitespace sensitivity.** BPE depends on whitespace: an extra or missing `\n` changes token boundaries.

### 1.1 Common Template Formats

| Template | Markup | Notes |
|---|---|---|
| **ChatML** (Qwen, Yi, OpenHermes) | `<\|im_start\|>system\n...<\|im_end\|>\n<\|im_start\|>user\n...<\|im_end\|>\n<\|im_start\|>assistant\n` | Atomic only in vocabs that explicitly add these tokens (Qwen2.5: IDs 151644/151645) |
| **Llama 3.x** | `<\|begin_of_text\|><\|start_header_id\|>system<\|end_header_id\|>\n\n...<\|eot_id\|>...` | Header structure stable across 3.0–3.3; 3.1+ adds `ipython` header for tool-calling — additive |
| **Llama 2 / Mistral v0.1–v0.2** | `<s>[INST] <<SYS>>\n...\n<</SYS>>\nuser message [/INST] assistant response </s>` | System embedded in first `[INST]`. v0.2 changes whitespace handling vs v0.1. No tool-calling support in either |
| **Mistral v0.3** | v0.2 + `[TOOL_CALLS]` / `[/TOOL_CALLS]` / `[TOOL_RESULTS]` / `[/TOOL_RESULTS]` | Native tool-calling |
| **Mistral Tekken** (Nemo, Large-2) | tiktoken-based BPE | Incompatible with v0.x at the encoding level |
| **Command R** (Cohere) | `<\|START_OF_TURN_TOKEN\|><\|USER_TOKEN\|>...<\|END_OF_TURN_TOKEN\|>` | Separate blocks for RAG citation and tool use |
| **DeepSeek V2/V3/R1** | `<｜begin▁of▁sentence｜><｜User｜>...<｜Assistant｜>...<｜end▁of▁sentence｜>` | R1 adds `<think>...</think>` blocks |
| **Gemma 1.1/2** | `<start_of_turn>{role}\n{content}<end_of_turn>\n` | Assistant role is `model`, not `assistant`. No separate system role — embedded in first user turn |
| **Gemma 3 / Gemma 4** | `<start_of_turn>user\n{first_user_prefix_with_system}<end_of_turn>\n<start_of_turn>model\n...<end_of_turn>\n` | Gemma 3+ ships a Jinja template that **synthesizes a system role** by prepending system content to the first user turn as `first_user_prefix`. Requires `--jinja` in llama.cpp (now default — see §21). Multimodal (Gemma 3 vision) adds `<start_of_image>` token. Gemma 4 (current generation as of 2026-04) extends the same pattern with thinking-mode support in select variants. |
| **Mistral v7-Tekken** (Mistral Small 3+, 2026) | `[SYSTEM_PROMPT]\n{system}\n[/SYSTEM_PROMPT]\n[INST]\n{user}\n[/INST]\n{assistant}</s>\n` | Adds explicit `[SYSTEM_PROMPT]` / `[/SYSTEM_PROMPT]` tags. Tiktoken BPE (different encoding from v0.x sentencepiece). Discriminator from v3-Tekken: presence of `[SYSTEM_PROMPT]` token in vocab. Some community finetunes (Rocinante-X, The-Omega-Directive) explicitly require **v3-Tekken without `[SYSTEM_PROMPT]`** — applying v7 breaks them. See §20. |

### 1.2 Failure Modes With Wrong Template

| Failure | Cause | Symptom |
|---|---|---|
| System prompt loss | System inserted in wrong position / wrong wrapping | Persona and instructions lost after 2–3 turns |
| Role hallucination | No clear role boundaries or wrong generation prompt | Model writes user turns |
| Garbage tokens / language mixing | Wrong whitespace around special tokens distorts BPE | Language switching, unicode garbage (Qwen, DeepSeek, Command R) |
| Repetition / looping | EOS/EOT mismatch, no explicit stop signal | Infinite phrase repetition |
| Truncated generation | Stray stop token in template | Answer cut mid-word |
| Long-context degradation | No header tokens as positioning anchors | Model confuses turns, replies to itself |
| Tool-calling breakage | Wrong tool-call block structure | Model writes JSON as plain text |
| Reasoning destruction (DeepSeek-R1) | `<think>` from previous turns not stripped, leaks into context | Infinite reasoning, tag leakage into final answer |

---

## 2. The Core Architectural Problem

The application must serve **many users**, each potentially using **different models**, across **different backends** (koboldcpp, text-generation-webui, llama.cpp server, Ollama, OpenAI-compatible cloud APIs), with **new models released continuously**. The architecture must not require manual per-model maintenance.

Two structural facts shape the solution:

1. **The template is the model author's responsibility, not the application's.** It ships inside the model artifact (GGUF metadata or `tokenizer_config.json`). The application's job is to read it correctly, not to maintain its own copy.
2. **RP clients need raw prompt assembly, not just `/v1/chat/completions`.** SillyTavern-style depth injection of character cards, world info, and author's notes requires positional control that chat-completions APIs do not expose. Therefore the application must sometimes render templates itself.

These two facts together drive the layered design below.

---

## 3. Detection Pipeline

The pipeline runs in strict order. Each layer either resolves the template or falls through to the next.

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 0: Backend capability negotiation                     │
│   Two questions:                                            │
│     (a) Does the backend expose a native                    │
│         /v1/chat/completions endpoint?                      │
│     (b) Does the current request need raw injection         │
│         (world info, depth prompts, author's notes)?        │
│   → If (a)=yes AND (b)=no: SKIP template selection.         │
│     Backend renders natively.                               │
│   → If (b)=yes OR (a)=no: continue to Layer 1.              │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Read embedded chat_template                        │
│   Source priority:                                          │
│     a. Backend API exposing template metadata               │
│        (llama-server /props, Ollama /api/show)              │
│     b. GGUF metadata: tokenizer.chat_template               │
│     c. tokenizer_config.json (HF format)                    │
│   Render via sandboxed Jinja2 (see §6) with                 │
│   add_generation_prompt=True.                               │
│   Validate against actual tokenizer vocab (see §13).        │
└─────────────────────────────────────────────────────────────┘
                          │  (no template / validation fail)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Architecture-based heuristic                       │
│   Read general.architecture from GGUF (present in ~all      │
│   modern files). Map:                                       │
│     llama      → Llama 3.x                                  │
│     qwen2      → ChatML                                      │
│     gemma2     → Gemma                                       │
│     command-r  → Command R                                   │
│     deepseek2  → DeepSeek                                    │
│   Also fall back to filename substring matching as last     │
│   resort.                                                   │
└─────────────────────────────────────────────────────────────┘
                          │  (no match)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: ChatML fallback WITH MANDATORY UI WARNING          │
│   Never silent. Banner: "Template not identified — quality  │
│   may degrade. Select a template manually."                 │
│   Override button immediately visible.                      │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 4: Manual override (always available, not just on     │
│   fallback). Preset dropdown + free-form Jinja input field. │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 Why this resolves the "new models keep coming" problem

When Llama 4 / Qwen 3 / Mistral Nemo 2 ship, they already carry `chat_template` in their metadata. The application's runtime is a generic Jinja renderer + smart fallback — nothing in the application needs to change for new models. The only thing requiring ongoing maintenance is a **patch registry** for known-buggy templates (see §8).

### 3.2 Layer priority caveat — finetunes

A custom community RP-finetune may keep `general.architecture = llama` but change the special tokens. In that case the embedded template **must** win over the architectural heuristic — but the embedded template must also be **validated against the actual tokenizer vocabulary** (see §13). An empty or default-looking `chat_template` field combined with a non-standard vocab is a strong signal that the finetune ships a broken template and the user must override manually.

### 3.2.1 Layer 1.5 — `chat_template.jinja` as a separate file

Modern HuggingFace repos (Qwen3, Gemma 3, Skyfall, DavidAU, many official model cards) ship `chat_template.jinja` as a **standalone file alongside `tokenizer_config.json`**, not (only) as a `chat_template` string field inside `tokenizer_config.json`. The two are usually kept in sync, but in some community merges only the standalone file is updated — `tokenizer_config.json` still carries the base model's stale template.

Detection procedure for Layer 1 must therefore check, in this order:
1. `tokenizer_config.json` → `chat_template` field (string or list of strings for multi-template models).
2. `chat_template.jinja` (standalone file in the same directory) — overrides (1) if present and (1) looks stale or default-looking.
3. GGUF metadata → `tokenizer.chat_template` field (llama.cpp's `gguf-set-metadata` writes here; llama-server reads here).
4. Backend API metadata (`/props` on llama-server, `/api/show` on Ollama) — exposes whatever the backend resolved from (3).

For client-to-remote-backend mode (§4.2) where the backend does not expose template metadata, the patch registry (§8) is the only authoritative source. When the user manually downloads a HF repo to a known local path (e.g. `assets/local_llm/<repo>/`), the client can read (1) and (2) directly from disk even when the backend is remote.

Multi-template models (Qwen3, Mistral 2024+) declare a *list* of templates and a default selector. The renderer must accept `{"name": "qwen3-thinking"}` or `{"name": "qwen3-non-thinking"}` style selection — see §18 for the `enable_thinking` shortcut that is more ergonomic.

---

## 4. Client vs Embedded Inference — Two Modes

A clean separation is mandatory because the application may run in either mode, sometimes simultaneously for different users.

### 4.1 Embedded inference mode (Backyard AI model)
- Application has direct access to GGUF / HF artifact.
- Layer 1 reads metadata locally.
- Stop tokens read from `generation_config.json` directly.

### 4.2 Client-to-remote-backend mode (SillyTavern model)
- Application has **no** direct access to the model file.
- Backend may or may not expose template metadata:
  - **Exposes** (modern `llama-server` `/props`, Ollama `/api/show`) → Layer 1 reads via API.
  - **Does not expose** (older builds, some cloud proxies) → application falls back to a **local template cache keyed by model name + vocab hash**, synchronized from the external patch registry (§8). The registry serves double duty: bug fixes for known templates, **and** template definitions for backends that do not expose them.

### 4.3 Backend capability discovery
On first connection to a backend, probe:
- `/v1/chat/completions` (native chat rendering)
- `/props` or `/api/show` (template metadata exposure)
- `/v1/completions` (raw completion for injection mode)

Cache the capability profile per backend URL.

### 4.4 Template format heterogeneity across backends
Not all backends expose templates in Jinja2 format. **Ollama** uses Go `text/template` (not Jinja2) in its Modelfile `TEMPLATE` directive. If the application's renderer is Jinja2-based and it reads a Go template from Ollama's `/api/show`, it cannot render it directly. Practical resolution:

1. **If Ollama is the backend, prefer Ollama's native `/api/chat` endpoint** (which handles Go templating internally) — this is the native chat path (§5) and the format mismatch is irrelevant.
2. **If raw rendering is required with an Ollama backend**, the application must obtain a Jinja2 template from an alternative source: the patch registry (§8), or by reading the original GGUF metadata directly if the file is locally accessible.
3. **Never attempt to transpile Go `text/template` → Jinja2** automatically — the two languages have different escaping, whitespace control, and function semantics; automated conversion is fragile and a source of subtle bugs.

The same principle applies to any backend with a non-Jinja template format: prefer the backend's native rendering, or fall back to a registry-provided Jinja equivalent.

---

## 5. Native chat-completions vs Raw Rendering

**Default to native `/v1/chat/completions` whenever possible.** Only switch to raw rendering when the request actually needs positional injection that the chat API cannot express.

| Feature | Native chat API | Raw rendering |
|---|---|---|
| Character card at top of context | ✅ (as system message) | ✅ |
| World info / lorebook depth injection (e.g. 4 messages before end) | ❌ | ✅ |
| Author's note at specific depth | ❌ | ✅ |
| Tool calling | ✅ (native) | ⚠️ (template must support) |
| Backend KV-cache prefix reuse | ✅ (backend handles) | ⚠️ (see §7) |
| Template maintenance burden | None (backend owns it) | Full (this document) |

The application surface that needs the entire detection pipeline is therefore much smaller than it first appears — typically only the "advanced RP" mode with depth injections.

---

## 6. Security: Sandboxed Jinja Rendering

### 6.1 Threat model
Templates come from untrusted sources: GGUF files and `tokenizer_config.json` downloaded from Hugging Face, torrents, or community finetunes. Full Jinja2 allows attribute access on objects and is a known SSTI (server-side template injection) class of vulnerability. **This is mandatory, not optional, for a multi-user application.**

### 6.2 Required hardening (multi-layer — `SandboxedEnvironment` alone is insufficient)

1. **`jinja2.sandbox.SandboxedEnvironment`** — blocks unsafe attribute access (`__class__`, `__globals__`, etc.).
2. **No `FileSystemLoader` / no `PackageLoader`.** Construct the environment with `loader=None` and render templates from in-memory strings. This prevents `{% include %}` and `{% import %}` from loading external files.
3. **AST-level pre-render check.** Walk the parsed AST and reject any `Include`, `Import`, `FromImport`, or `Extends` nodes before rendering. The sandbox does not block these by default.
4. **`autoescape=False`.** The output is prompt text, not HTML. Autoescaping would mangle special tokens like `<|im_start|>` into `&lt;|im_start|&gt;`, breaking the template entirely.
5. **Restricted globals.** Provide only a curated subset: `range`, `len`, `tojson`, and a custom `now()` / `format_date()` helper (do NOT expose raw `datetime` or `time` modules — they enable file system access via `datetime.__class__.__init__.__globals__`). No `__builtins__`, no `os`, no `sys`.
6. **Render timeout.** Wrap render in a hard timeout (e.g. 2 seconds) — pathological templates can loop.

### 6.3 Why autoescape matters
The output of the renderer is fed directly to the tokenizer. Any HTML-style escaping of `<`, `>`, `|`, `&` will break special tokens whose names literally contain these characters. `autoescape=False` is the correct setting.

---

## 7. Caching: Prefix Stability, Not Render Caching

### 7.1 What does NOT matter
Jinja rendering of a string template against a message list is milliseconds even on long histories. A `sha256(template+messages) → rendered_string` cache as a performance optimization is **not justified** — it adds complexity for negligible gain.

### 7.2 What DOES matter — KV-cache prefix reuse
Backends (llama.cpp, vLLM) reuse already-computed token prefixes when a new prompt shares its beginning with the previous one. This is the single largest performance lever in long conversations.

**Practical requirement:** the rendered prompt must have a **stable prefix** across consecutive turns. Specifically:

- Do **not** insert volatile content (wall-clock timestamps, random UUIDs, nondeterministic dict iteration order) into the system prompt or early message positions.
- If a timestamp is required by the template (Llama 3.1's `date_string`), **we cannot control where the template places it** — Llama 3.1 puts it in the system header at the very beginning, so any change invalidates the prefix. Mitigation: bind `date_string` to the **chat session** (not the app session, not per-request). Concretely: derive `date_string` once from `chat.created_at` (an ISO timestamp already stored in SoW's chat metadata — see `interface_signals.py:3357, 11863`) at chat creation time, format as `%d %b %Y`, and reuse the same value for every turn of that chat. The date is immutable per chat — even across app restarts, the same chat uses the same `date_string`, preserving KV-cache prefix across sessions. Do NOT use `datetime.now()` at render time. Do NOT attempt to move the variable within the template — that breaks the model's expected format.
- Ensure Jinja dict iteration is deterministic (Python 3.7+ dict ordering is insertion-order; do not iterate `**kwargs` whose order may vary).
- Verify with the debug view (§12) that consecutive prompts share an identical prefix up to the last user turn.

A single timestamp in the wrong position can invalidate the entire KV cache on every turn, multiplying inference cost by the full context length.

---

## 8. Patch Registry: Design and Governance

### 8.1 Purpose
Authors of models ship buggy templates. Canonical example: DeepSeek-R1's official template does not strip `<think>...</think>` from prior assistant turns, causing reasoning-tag leakage and infinite reasoning loops.

Fix:
```jinja
{% if '</think>' in content %}
  {{ content.split('</think>')[-1].strip() }}
{% else %}
  {{ content }}
{% endif %}
```

### 8.2 Registry structure
The registry is a separate JSON document, fetched over network, applied on top of the embedded template:

```json
{
  "version": "2026-07-28",
  "patches": [
    {
      "id": "deepseek-r1-think-strip",
      "match": {
        "architecture": "deepseek2",
        "model_name_regex": "DeepSeek-R1",
        "template_hash_sha256": "..."
      },
      "applies_when": "assistant_turn_in_history",
      "patch_jinja": "{% if '</think>' in content %}{{ content.split('</think>')[-1].strip() }}{% else %}{{ content }}{% endif %}",
      "patch_type": "content_pre_render_filter",
      "signed_by": "maintainer-key-1"
    }
  ]
}
```

The registry also doubles as the **template definition source** for backends that do not expose template metadata (§4.2), or that expose it in a non-Jinja format (§4.4). Each entry may either:

- **`patch_type: "content_pre_render_filter"`** — filters message `content` before the template renders (e.g. the DeepSeek-R1 `<think>` strip above).
- **`patch_type: "template_replacement"`** — replaces the entire template string with a known-good Jinja version (used when the embedded template is broken or when the backend exposes no Jinja template at all, e.g. Ollama Go templates).
- **`patch_type: "template_modifier"`** — applies a targeted string substitution to specific parts of the embedded template (used for surgical fixes that don't warrant a full replacement).

### 8.3 Supply-chain security (critical)
The registry contains executable Jinja code fetched over network and rendered with the same sandbox as model templates. A compromised registry = arbitrary template injection = potential sandbox escape via undiscovered Jinja bugs.

Required controls:

1. **Signed entries.** Each patch is signed by a maintainer's private key; the application verifies with a pinned public key bundled in the binary. Unsigned entries are rejected.
2. **Trusted publisher list.** Multiple maintainers may contribute; the application ships with their public keys.
3. **Commit-level pinning.** Fetch by commit SHA, not by branch HEAD, and require a signed manifest referencing that SHA.
4. **Notarization / transparency log.** Optional but recommended: every registry update is appended to an append-only log (e.g. a simple S3-backed Merkle tree) so that a historical compromise is detectable.
5. **TTL cache ≠ security.** A 24-hour TTL protects against registry unavailability, not against content tampering. Both layers are needed.

### 8.4 Failure behavior
If the registry cannot be fetched or signature verification fails, the application must **continue operating** with embedded templates only (no patches), and surface a non-blocking warning. It must not silently fall back to an unsigned cached copy.

### 8.5 HF Source-of-Truth Files Cache (offline-capable, TTL + commit_hash verification)

Distinct from §8 patch registry: the patch registry holds **SoW-maintained signed patches** for known-buggy templates; this subsection holds **model-author-provided source files** fetched directly from HuggingFace repos. Both can coexist — patches apply on top of the cached HF source.

**Why this is needed:** SoW's RP use case includes offline local-LLM sessions (user on a train, plane, or with metered connectivity). The detection pipeline (§3 Layer 1, §3.2.1 Layer 1.5) needs `tokenizer_config.json` + `chat_template.jinja` to do its job. Without a local cache, switching models offline is impossible — detection falls through to Layer 2 (architecture heuristic) or Layer 3 (ChatML fallback), losing accuracy.

**What to cache (4 small files per model, ~5 KB each, ~20 KB total per model):**

| File | Purpose | Used by |
|---|---|---|
| `tokenizer_config.json` | `chat_template` field, `added_tokens_decoder`, `bos_token`/`eos_token` strings | §3 Layer 1, §10 stop tokens, §13 vocab validation, §19 Mistral disambiguation |
| `chat_template.jinja` (if shipped separately) | Authoritative Jinja template — overrides stale `chat_template` field in (1) | §3.2.1 Layer 1.5 |
| `generation_config.json` | `eos_token_id` (may be an array — Llama 3.1 has three) | §10 stop tokens source priority 1 |
| `special_tokens_map.json` | `additional_special_tokens` list (reasoning tokens, tool tokens) | §11 sanitization, §17.2 reasoning-model detection |

**Storage layout:** `assets/template_cache/<repo_owner>__<repo_name>/<commit_hash_short>/`. SoW's `assets/` is already gitignored for content (`assets/*` + `!assets/.gitkeep` per directory) — the cache lives at runtime, not in git.

**Refresh protocol (on app startup, lightweight):**
1. For each known model (from `settings.json` + `characters.json` + active local LLM path), check if local cache exists and has a `commit_hash` marker file.
2. If network is available: query `https://huggingface.co/api/models/<repo>` (~1 KB JSON, returns `sha` field = current `commit_hash`).
3. If `sha` matches local `commit_hash` marker → cache is current, skip download.
4. If `sha` differs or no local cache → download the 4 files (parallel, ~20 KB total), atomically replace the cache directory, write new `commit_hash` marker.
5. If network unavailable → use existing cache as-is, surface a non-blocking INFO log line `template_cache: stale (offline, last sync=YYYY-MM-DD)`. Do NOT block startup.

**TTL:** 24 hours (default). On TTL expiry, force a `commit_hash` check on next startup. Users can manually trigger a refresh via a "Refresh template cache" button in the Debug tab (KI#17 future scope).

**Why `commit_hash` not version tags:** HF model authors frequently update `chat_template.jinja` without bumping a version tag. Example: DavidAU's Gemma-3-12b-it-vl-thinking had a Feb 2026 Jinja upgrade with no version bump. Comparing `commit_hash` is the only reliable change-detection signal.

**Security note:** HF files are unsigned and fetched over HTTPS. They are rendered through the same sandboxed Jinja environment as embedded templates (§6) — never executed as code. The cache is content-addressed by `commit_hash`, so a rollback attack (serving an older malicious version) would be detected by the user noticing a hash change without a corresponding model update. For higher assurance, the patch registry (§8) can override cached HF templates with signed patches.

**Relationship to §8 patch registry:** patches apply ON TOP of the HF cache. Order: (1) load HF cached template, (2) check patch registry for applicable patches, (3) apply patches, (4) render. If the HF cache is stale (network unavailable), patches still apply — they target template content, not commit hashes.

---

## 9. Template Variables: Beyond `messages`

Modern templates require context beyond `{messages, add_generation_prompt}`. The renderer must supply a safe superset with sane defaults; missing variables cause `UndefinedError` and render failures — a distinct failure class from silent quality degradation.

| Variable | Used by | Default if absent |
|---|---|---|
| `messages` | All | (required) |
| `add_generation_prompt` | All | `True` |
| `tools` | Llama 3.1+, Mistral v0.3, Command R | `[]` |
| `tool_choice` | tool-use models | `"auto"` or `None` |
| `date_string` | Llama 3.1 | Derived from `chat.created_at.strftime("%d %b %Y")` at **chat creation time** and stored in chat metadata — reused unchanged for every turn of that chat (see §7.2). NOT `datetime.now()` at render time, NOT app-session start — chat-session start. The template places it in the system header — we cannot move it. |
| `tools_in_user_message` | Llama 3.1 | `False` |
| `enable_thinking` | Qwen3, DeepSeek-R1 distills | `False` for RP scenarios unless explicitly enabled |
| `bos_token`, `eos_token` | Many | Read from tokenizer config |
| `system_message` | Gemma (synthesized from first user) | `""` |

The renderer should pre-populate the Jinja context with all of the above before invoking `template.render(**ctx)`, so that any template referencing any of them succeeds.

### 9.1 Multimodal considerations
Multimodal models (LLaVA, Qwen-VL, Pixtral, etc.) extend the message format with non-text content (images, audio). Their templates expect `content` to be either a string (text-only) or a list of typed content blocks (`{"type": "text", "text": ...}`, `{"type": "image_url", "image_url": {...}}`).

Key implications:

1. **The renderer must pass through typed content blocks without stringifying them.** The backend, not the client, is responsible for serializing image placeholders into the prompt. If the application stringifies an image block, the template receives garbage.
2. **Some backends ignore custom templates for multimodal models** — e.g. `llama-server` silently falls back to the GGUF-embedded template when `--mmproj` is passed, ignoring `--chat-template-file`. The application should detect this case and warn the user that manual template override will not take effect.
3. **Native chat API (§5) is strongly preferred for multimodal** — the backend handles image embedding, placeholder injection, and template rendering coherently. Raw rendering of multimodal templates is fragile and backend-specific.
4. **The patch registry (§8) may need multimodal-specific patches** — mark patch entries with a `"modalities": ["text", "image"]` field so text-only patches are not applied to multimodal contexts and vice versa.

---

## 10. Stop Tokens: Source of Truth

**Never extract stop tokens from the template.** The template is a presentation concern; stop tokens are an inference control concern.

Source priority:
1. `generation_config.json` → `eos_token_id` field (may be an array — Llama 3.1 has three: `[128001, 128008, 128009]`).
2. Tokenizer config `eos_token` string → resolve to ID via vocab.
3. As a last resort, derive from template's generation prompt suffix (fragile, do not rely on).

Stop tokens must be passed to the backend as the `stop` parameter (or equivalent), not embedded in the rendered prompt.

### 10.0 DeepSeek fullwidth-pipe stop token — byte-level warning

DeepSeek V2/V3/R1 family uses `<｜end▁of▁sentence｜>` as the EOS token. **This is NOT the same string as `<|end_of_sentence|>` written with ASCII characters.** The DeepSeek variant uses three Unicode codepoints that look identical to ASCII equivalents but have different byte representations:

| Char | Codepoint | UTF-8 bytes | Confused with |
|---|---|---|---|
| `｜` (FULLWIDTH VERTICAL LINE) | U+FF5C | `EF BD 9C` | ASCII `\|` (U+007C, byte `7C`) |
| `▁` (LOWER ONE EIGHTH BLOCK, SentencePiece space) | U+2581 | `E2 96 81` | ASCII `_` (U+005F, byte `5F`) |

A regex pattern like `[｜\|]` matches both, but **case-sensitive string equality does not**: `"<|end_of_sentence|>" == "<｜end▁of▁sentence｜>"` is `False`. A naive `stop = ["<|end_of_sentence|>"]` parameter sent to a DeepSeek-routed backend will **never match the model's actual EOS**.

Concrete byte sequences for the four DeepSeek special tokens (all use U+FF5C and U+2581):

| Token | String (use these literal bytes) | Token ID (DeepSeek V2/R1 vocab) |
|---|---|---|
| BOS / `<｜begin▁of▁sentence｜>` | `<\uFF5Cbegin\u2581of\u2581sentence\uFF5C>` | 151646 |
| EOS / `<｜end▁of▁sentence｜>` | `<\uFF5Cend\u2581of\u2581sentence\uFF5C>` | 151643 |
| User turn start / `<｜User｜>` | `<\uFF5CUser\uFF5C>` | 151653 |
| Assistant turn start / `<｜Assistant｜>` | `<\uFF5CAssistant\uFF5C>` | 151654 |

Detection and matching rules:
1. When comparing stop tokens, **always compare at the byte level** (`s.encode("utf-8") == expected_bytes`), never at the Unicode string level.
2. When loading `eos_token` from `tokenizer_config.json`, preserve the exact bytes — do not normalize.
3. When displaying stop tokens in the UI, show the actual Unicode characters (`｜`, `▁`) — they render as expected and signal to the user that this is a DeepSeek-family model. Do NOT substitute ASCII lookalikes.
4. The same byte-level rule applies to the DeepSeek reasoning tag `<think>...</think>` — these use ordinary ASCII `<` `>` (no fullwidth), so they are easy to confuse with stop tokens that use fullwidth pipes. See §18 for reasoning-tag handling.

See §22 for the full reference table of DeepSeek-family special tokens.

---

### 10.1 Streaming stop-sequence buffering

When generating in streaming mode, tokens arrive one at a time, but stop sequences may be multi-token (e.g. `<|eot_id|>` is a single special token in Llama 3 but a multi-subword sequence in ChatML-fallback mode).

Naive implementation: emit each token to the UI as soon as it arrives. Result: the user sees a fragment of the stop sequence for a fraction of a second before the stream is truncated.

Required: maintain a small buffer of the last N generated tokens (where N = max stop-sequence length in tokens). For each new token:
1. Append the new token to the buffer.
2. **Full match check**: does the buffer end with any complete stop sequence?
   - **Yes**: emit the portion of the buffer *before* the match to the UI, discard the match, end the stream.
   - **No**: continue to step 3.
3. **Partial prefix check**: does the buffer end with a *prefix* of any stop sequence (i.e. could the next tokens complete a stop sequence)?
   - **Yes**: retain that prefix-portion in the buffer, emit the rest to the UI.
   - **No**: emit the entire buffer to the UI, clear it.

This is the standard "Aho-Corasick-style" streaming match approach, simplified for the small number of stop sequences.

---

## 11. RP-Specific Hardening: Special Token Spoofing

This is the one vulnerability unique to RP clients and not shared with general-purpose LLM frontends.

### 11.1 Threat
Character cards, world info entries, and author's notes are user-downloaded content. A character card may literally contain the string `<|im_start|>assistant\n` or `[/INST]`. If the renderer inserts this content as a regular `user` or `system` message body without sanitization, the model may interpret the injected string as a real turn boundary — effectively allowing a character card to impersonate the assistant role, inject fake reasoning, or terminate the conversation early.

This is not hypothetical: community character card repositories have no content moderation, and adversarial cards are trivially constructable.

### 11.2 Mitigation
Before rendering, scan all `content` fields of `messages` for occurrences of any string that matches a known special token of the **target template** (not the source format of the card). Action policy (configurable per user, but with a secure default):

- **Recommended default:** strip the offending sequence entirely. Log to debug view.
- **Alternative:** replace with a visually similar safe sequence (e.g. `<|im_start|>` → `[im_start]`).
- **Never:** leave the sequence as-is unless the user has explicitly disabled sanitization for this conversation.

The list of special-token strings to scan for is derived from:
1. The active template's generation prompt and turn-boundary tokens.
2. The tokenizer's added-tokens vocabulary (special tokens that are atomic).
3. Common cross-format tokens (`<|im_start|>`, `<|im_end|>`, `[/INST]`, `<|eot_id|>`, `<｜end▁of▁sentence｜>`, `<end_of_turn>`, etc.) as a hardcoded baseline.

This sanitization runs **before** Jinja rendering, on the message list, not after.

### 11.3 Scope exclusion — reasoning tags are NOT special tokens

Reasoning tags (`<think>` / `</think>`) are **content markers**, not **structural special tokens**. They delimit a reasoning block *inside* an assistant message — they do not mark turn boundaries, cannot impersonate roles, and cannot terminate the conversation. Therefore they are explicitly **excluded** from §11.2 spoofing sanitization.

**Rationale:** a character card or lorebook entry may legitimately contain literal `<think>` or `</think>` strings as part of the narrative (e.g. a character who *is* an AI and "thinks" visibly, or a worldbuilding document that describes the reasoning format). Stripping these would silently damage user-authored RP content.

**Where reasoning tags ARE handled:** §17.3 history stripping — applied **only to prior assistant turns** (chat history), never to `system`, `user`, `character card`, `lorebook`, or `author's note` content. The history-stripping regex is the same (`<think>.*?</think>`), but its scope is restricted to `role == "assistant"` messages.

**Implementation note:** the `DEEPSEEK_SPECIAL_TOKENS` list in §21.3 includes `<think>` / `</think>` for completeness of the byte-level reference table, but the sanitization scanner (§11.2) must skip these entries when scanning non-assistant content. The scanner should mark each token entry with a `scope` field: `structural` (always sanitized) vs `reasoning` (sanitized only from assistant history, never from user content).

---

## 12. UI/UX Requirements

The application's UX must support the following features. These are not optional — without them users cannot debug template problems and will blame the model.

1. **Template preview before generation.** Show which template was detected (source: embedded / heuristic / fallback / manual) and the rendered prompt string with role boundaries highlighted.
2. **Override control.** Always visible, not hidden behind settings. Dropdown of presets + free-form Jinja text area.
3. **Debug view.** After rendering, show:
   - Final string passed to tokenizer.
   - Token IDs at role boundaries (to verify atomicity).
   - Whitespace markers (visible `\n`, leading/trailing spaces).
4. **Stop token display.** Show which stop tokens are active and their source.
5. **Sanitization log.** When special-token spoofing is detected and stripped, surface this in the debug view (not in the chat — would clutter UX).
6. **Patch registry status.** Show last sync time, signature verification status, and any applied patches for the current model.
7. **Capability profile per backend.** Show what the connected backend supports (native chat, raw completion, template metadata exposure).
8. **Warning, not silent fallback.** When Layer 3 (ChatML fallback) is reached, the UI must display a non-dismissable-until-acknowledged warning.
9. **Capability-aware UI auto-hide/show.** UI controls that map to template variables must auto-hide when the active template does not reference the corresponding variable, and auto-show when it does. This prevents the user from toggling a control that has no effect (a common source of "the checkbox doesn't do anything" confusion — see KI#19 for the `reasoning_mode` / `enable_thinking` variant of this problem).
   - **Thinking toggle** (Qwen3 `enable_thinking`, Skyfall `/think`): hidden when template's Jinja source does not reference `enable_thinking` or `reasoning_effort`. Detection: grep the cached `chat_template.jinja` (§8.5) for the variable name, or parse the Jinja AST.
   - **Tool-calling toggle**: hidden when template does not reference `tools` / `tool_choice`.
   - **`date_string` indicator** (Llama 3): hidden when template does not reference `date_string`. When shown, displays the chat-session-bound date (§7.2) so the user can verify it is not changing per turn.
   - **Reasoning budget slider** (Family A — `--reasoning-budget`): hidden when model is not Family A (detected via §17.2 signals).
   - When the active template is "Auto" (read from GGUF metadata), detection runs on the resolved template after Layer 1 lookup. If the lookup fails (offline, no cache), all capability-aware controls are shown (conservative default — let the user try, surface a tooltip "template capability unknown").

---

## 13. Validation Against Tokenizer Vocabulary

When reading an embedded template (Layer 1), the application must validate that the special tokens referenced in the template actually exist as atomic tokens in the tokenizer's vocabulary. This catches the case where a finetune ships a default-looking template but has modified the special tokens.

Validation procedure:
1. Parse the template's static text segments (non-Jinja parts) and extract candidate special-token strings (any `<...>` or `[...]` pattern).
2. For each candidate, check whether the tokenizer encodes it as a single token ID.
3. If any candidate token is encoded as multiple subword tokens, raise a validation warning: "Template references special tokens not present in this model's vocabulary — likely a wrong-template-for-finetune situation. Manual override recommended."
4. If validation fails, the pipeline falls through to Layer 2 (architecture heuristic) rather than trusting the broken embedded template.

This check is cheap (a few `tokenizer.encode()` calls) and prevents the most insidious class of silent degradation — finetune-with-wrong-template.

---

## 14. Testing and Versioning

### 14.1 Testing strategy
The template pipeline has multiple failure modes (crash on render, silent quality degradation, security bypass) that require distinct test approaches.

1. **Golden-file tests for known model+template combinations.** For each supported model family (Llama 3.1, Qwen 2.5, Mistral v0.3, Gemma 2, DeepSeek-R1, Command R), store a canonical message list and the expected rendered string. Regression-test on every release. Any change in rendered output is a signal that either the template or the renderer changed.

2. **Vocab validation tests.** For each golden model, verify that the template's special tokens are atomic in the tokenizer. This catches the finetune-with-wrong-template class (§13).

3. **Sandbox escape tests.** Maintain a corpus of known Jinja SSTI payloads (attribute traversal, `__class__`, `__globals__`, `{% include %}`, `{{ ''.__class__ }}`, etc.) and verify that the sandboxed renderer + AST check rejects all of them. Add new payloads as they are discovered in the wild.

4. **Special-token spoofing tests.** Construct adversarial character cards containing literal `<|im_start|>assistant`, `[/INST]`, `<|eot_id|>` strings and verify the sanitizer (§11) strips or neutralizes them before render.

5. **Prefix stability tests.** For each template, render the same conversation twice with only the last user message changed, and assert that the two rendered strings are byte-identical up to the start of the last user turn. This catches accidental timestamp/UUID insertion that would invalidate backend KV-cache.

6. **Streaming stop-sequence tests.** Feed a known multi-token stop sequence into the streaming buffer and verify it is never partially emitted to the UI, including edge cases (stop sequence split across buffer boundaries, multiple overlapping stop sequences).

7. **Registry signature tests.** Verify that tampered, unsigned, or wrong-key-signed registry entries are rejected and the application continues with embedded templates only (§8.4).

### 14.2 Versioning
- **Patch registry**: versioned by date (e.g. `"version": "2026-07-28"`) and by commit SHA. The application logs the applied registry version on startup and in the debug view.
- **Application preset templates** (Layer 4 dropdown): versioned with the application release. Each preset carries a `preset_version` field; breaking changes to a preset increment the major version and trigger a migration prompt for users who had customized that preset.
- **Template variable superset** (§9): versioned. When a new variable is added (e.g. a future `reasoning_effort`), the application ships a new minor version and continues to supply defaults for old variables — backward compatible.
- **Backend capability profile** (§4.3): cached per backend URL with a TTL. Re-probe on TTL expiry or on explicit user request ("refresh backend capabilities").

---

## 15. Implementation Checklist

A non-exhaustive but mandatory checklist for any implementation claiming compliance with this document.

### Detection pipeline
- [ ] Layer 0: backend capability negotiation (native chat vs raw)
- [ ] Layer 1: read `chat_template` from GGUF metadata, `tokenizer_config.json`, or backend API
- [ ] Layer 1: validate embedded template against tokenizer vocab
- [ ] Layer 2: architecture-based heuristic from `general.architecture`
- [ ] Layer 3: ChatML fallback with mandatory UI warning
- [ ] Layer 4: manual override (presets + free-form Jinja)
- [ ] Backend template format detection (Jinja2 vs Go text/template) — prefer native API for non-Jinja backends (§4.4)
- [ ] Multimodal content block passthrough (do not stringify image/audio blocks) (§9.1)
- [ ] Multimodal `--mmproj` override detection (warn user that manual template is ignored) (§9.1)

### Security
- [ ] `SandboxedEnvironment` for all Jinja rendering
- [ ] No `FileSystemLoader` / `PackageLoader` (loader=None, in-memory strings)
- [ ] AST pre-check rejecting `Include` / `Import` / `FromImport` / `Extends`
- [ ] `autoescape=False`
- [ ] Curated globals (no `__builtins__`, `os`, `sys`)
- [ ] Render timeout (≤2s)
- [ ] Special-token spoofing sanitization on message `content` before render
- [ ] Patch registry entries cryptographically signed; pinned public keys in binary
- [ ] Registry fetch by commit SHA with signed manifest

### Template context
- [ ] Pre-populate `messages`, `add_generation_prompt`, `tools`, `tool_choice`, `date_string`, `tools_in_user_message`, `enable_thinking`, `bos_token`, `eos_token` with defaults

### Stop tokens
- [ ] Read from `generation_config.json` `eos_token_id` (handle array case)
- [ ] Pass to backend as `stop` parameter, not embedded in prompt
- [ ] Streaming stop-sequence buffering (N-token sliding window)

### Performance
- [ ] No volatile content (timestamps, UUIDs) in early prompt positions
- [ ] Deterministic dict iteration in Jinja context
- [ ] Verify prefix stability across consecutive turns via debug view

### UI
- [ ] Template preview before generation
- [ ] Always-visible override control
- [ ] Debug view (rendered string + token IDs + whitespace markers)
- [ ] Stop-token display with source
- [ ] Sanitization log in debug view
- [ ] Patch registry status display
- [ ] Per-backend capability profile
- [ ] Non-dismissable warning on Layer 3 fallback

### Caching
- [ ] Compiled Jinja template cached per model (cheap, but still)
- [ ] **No** render-result cache (not worth the complexity)
- [ ] Backend KV-cache prefix stability verified

### Testing & versioning (see §14)
- [ ] Golden-file tests for each supported model family
- [ ] Vocab validation tests for each golden model
- [ ] Sandbox escape test corpus (SSTI payloads) with CI gate
- [ ] Special-token spoofing tests with adversarial character cards
- [ ] Prefix stability tests (byte-identical prefix across consecutive renders)
- [ ] Streaming stop-sequence tests (multi-token, boundary-split, overlapping)
- [ ] Registry signature rejection tests (tampered / unsigned / wrong-key)
- [ ] Patch registry version logged on startup and in debug view
- [ ] Preset templates carry `preset_version` with migration on breaking change

---

## 16. Known Problematic Models Reference (verified, 2026-07)

This section consolidates real-world model-specific template anomalies encountered in the wild. Every entry is **verified against the model's HuggingFace card, `tokenizer_config.json`, or `chat_template.jinja`**. Confidence levels: HIGH (primary source cited), MEDIUM (inferred from base model / merge graph), LOW (could not fully verify).

The goal of this section is to make detection-by-name-or-architecture reliable for the common cases, so that manual override is only needed for true edge cases. A detection pipeline implementing §3 + §17-§22 should correctly route every entry below without user intervention.

### 16.1 Critical anomalies (require non-default detection logic)

| # | Model | Architecture / base | Template actually used | Stop token(s) | `--jinja` required? | Reasoning? | Confidence | HF URL |
|---|---|---|---|---|---|---|---|---|
| 1 | **Fallen-Llama-3.3-R1-70B-v1** | Llama 3.3 70B (dense), DeepSeek-R1 distill | DeepSeek-R1-Distill-Llama (deepseek2 family Jinja) | `<｜end▁of▁sentence｜>` (U+FF5C) | Yes (default) | Yes — card instructs: prefill `<think>\n\n` to force multi-turn thinking | HIGH | https://huggingface.co/TheDrummer/Fallen-Llama-3.3-R1-70B-v1 |
| 2 | **Skyfall-31B-v4.2** | Mistral v7-Tekken base (Mistral-Small-3.1-24B-Instruct-2509 + merges), 31B | Custom Jinja with `[SYSTEM_PROMPT]` / `[/SYSTEM_PROMPT]` / `[INST]` / `[/INST]` and a `/think` toggle | `</s>` (Mistral Tekken EOS) | Yes (default) — uses `enable_thinking` Jinja var | Yes — `/think` and `/no_think` suffix commands; `enable_thinking` Jinja variable in template | HIGH | https://huggingface.co/TheDrummer/Skyfall-31B-v4.2 |
| 3 | **All Gemma 3 / Gemma 4 models** (8+ verified) | Gemma 3 (gemma3 arch), Gemma 4 (current gen as of 2026-04) | Gemma 3 Jinja — synthesizes system from first user turn via `first_user_prefix` | `<end_of_turn>` | Yes (default in modern llama.cpp — `--jinja` is on by default; `--no-jinja` would break Gemma) | Gemma 3 natively: no. DavidAU variants: yes (see #4). Gemma 4 select variants: yes. | HIGH | https://huggingface.co/google/gemma-3-12b-it, https://huggingface.co/google/gemma-4-12b-it |
| 4 | **DavidAU `gemma-3-12b-it-vl-*` variants** | Gemma 3 12B IT VL | Gemma 3 + custom "direct thinking logic" Jinja extensions (Feb 2026 upgrade per card) | `<end_of_turn>` | Yes (default) — and custom Jinja must be loaded from `chat_template.jinja` file | Yes — triggered by `think deeply:` prompt prefix in user message; card states verbatim "Feb 16 2026: Upgraded Jinja Template with direct thinking logic to improve thinking activation" | HIGH | https://huggingface.co/DavidAU/gemma-3-12b-it-vl-thinking |
| 5 | **AbominationScience-12B-v4**, **Prototype-X-12b** | Mistral NeMo 12B base (flowforge merges) | **Not specified** in either README or `tokenizer_config.json` — inherits base's Mistral v3 Tekken | `</s>` (Mistral Tekken) | Inherited from base | No | HIGH (negative result) | https://huggingface.co/InstructLab/AbominationScience-12B-v4 (and similar) |
| 6 | **Qwen3 family** (the previous analysis's "Qwen3.6-27B" appears to be a misread — current Qwen3 line includes Qwen3-7B/14B/32B and Qwen3-30B-A3B MoE) | qwen2 / qwen3-moe arch | ChatML base + `enable_thinking` Jinja variable (multi-template: `qwen3-thinking` and `qwen3-non-thinking`) | `<|im_end|>` (token 151645) | Yes (default) — built-in `chatml` template lacks `enable_thinking`; must use `--jinja` + `--chat-template-kwargs '{"enable_thinking":false}'` | Yes — `/think` and `/no_think` user-message suffixes toggle per-turn; Jinja var toggles globally; `</think>` token = 151668 | HIGH | https://huggingface.co/Qwen/Qwen3-14B |

### 16.2 Medium complexity (detection improvements)

| # | Model | Architecture / base | Template actually used | Notes | Confidence | HF URL |
|---|---|---|---|---|---|---|
| 7 | **Impish_Bloodmoon_12B** | Mistral NeMo 12B base | ChatML (card states "ChatML" explicitly) | `<|im_start|>` / `<|im_end|>` are atomic in this finetune's vocab even though arch is `llama` (NeMo's arch tag) — architecture heuristic alone would pick Mistral, but the model is ChatML-trained. **Tokenizer vocab validation (§13) is the only reliable signal here.** | HIGH | https://huggingface.co/TheDrummer/Impish_Bloodmoon-12B-Pre闪光 |
| 8 | **Impish_LLAMA_4B** | Llama 3.2 4B pruned to 4B (NVIDIA-pruned variant) | ChatML | Same as #7 — Llama arch but ChatML template. Detection must NOT use `general.architecture` alone. | HIGH | https://huggingface.co/TheDrummer/Impish_LLAMA-4B-Pre |
| 9 | **Rocinante-X-12B-v1** | Mistral NeMo 12B finetune | **Mistral v3 Tekken, explicitly WITHOUT `[SYSTEM_PROMPT]`** — card says verbatim: "Mistral v3 Tekken (NOT v7, REMOVE [SYSTEM_PROMPT])" | Applying v7-Tekken template breaks this model. Detection must distinguish v3-Tekken from v7-Tekken (see §20). | HIGH | https://huggingface.co/TheDrummer/Rocinante-X-12B-v1 |
| 10 | **The-Omega-Directive-M-12B-v1.0** | Mistral NeMo 12B finetune | Same as #9 — Mistral v3 Tekken, no `[SYSTEM_PROMPT]` | Same pitfall. | HIGH | https://huggingface.co/TheDrummer/The-Omega-Directive-M-12B-v1.0 |
| 11 | **L3.3-MS-Nevoria-70b** | Llama 3.3 70B merge (multi-way merge) | Llama 3 family — card recommends the "LLam@ception" preset (a Llama-3 variant) | Merge model — `chat_template` field may not be set in `tokenizer_config.json`. Architecture heuristic (`llama`) is correct, but verify via filename + Jinja file before trusting. | HIGH | https://huggingface.co/TheDrummer/L3.3-MS-Nevoria-70b |

### 16.3 Lower priority (UI / validation niceties)

| # | Model | Architecture / base | Template actually used | Notes | Confidence | HF URL |
|---|---|---|---|---|---|---|
| 12 | **Hearthfire-24B** | Mistral-Small-3.2-24B-Instruct-2506 (NOT Qwen, NOT OpenHermes) | ChatML — card states "This model was trained using ChatML." | Architecture heuristic (`llama` for Mistral Small) would NOT pick ChatML. Detection by `chat_template.jinja` file (which contains ChatML) is the only reliable signal. **Filename substring matching would fail** — no "Qwen" or "ChatML" in the name. | HIGH | https://huggingface.co/TheDrummer/Hearthfire-24B |
| 13 | **Midnight-Rose-70B-v2.0.3** | Llama 2 70B (via dare_ties merge of NousResearch/Llama-2-70b-hf) | Vicuna format (Llama 2 family) | `</s>` EOS. No "Llama" in filename — naive name substring matching fails. Architecture heuristic (`llama`) succeeds. | HIGH | https://huggingface.co/Sao10K/Midnight-Rose-70B-v2.0.3 |

### 16.4 Cross-cutting detection rules derived from the table above

1. **Architecture alone is insufficient.** #7, #8, #12 all have non-Qwen `general.architecture` but use ChatML. Always prefer `chat_template.jinja` file content (§3.2.1) over `general.architecture`.
2. **Filename substring matching is the WEAKEST signal.** #11, #12, #13 all have non-obvious names. Use only as a last resort.
3. **Tokenizer vocab validation (§13) is the only reliable detector** for finetunes that keep base arch but change special tokens (#7, #8).
4. **Mistral v3-Tekken vs v7-Tekken disambiguation** must check for `[SYSTEM_PROMPT]` token in vocab (§20). Applying v7 to a v3-Tekken model (#9, #10) breaks it.
5. **`--jinja` is now default** in modern llama.cpp — but the application must NOT pass `--no-jinja`. Documented in §21.
6. **Reasoning toggle is per-family** (§18). DeepSeek R1 auto-strips; Qwen3 / Skyfall / gpt-oss / Nemotron require client-side stripping.
7. **Gemma 3/4 system role is synthesized**, not native — the application must NOT inject a separate `system` role into the messages list for Gemma. The template handles it via `first_user_prefix`.
8. **DeepSeek family stop tokens use U+FF5C** (fullwidth pipe), not ASCII `|` (§22). Byte-level comparison is mandatory.

---

## 17. Reasoning Mode Handling

Reasoning models (DeepSeek-R1, Qwen3, gpt-oss, Nemotron reasoning variants, Phi-4-reasoning, Skyfall, and the growing class of "thinking" distills) emit a chain-of-thought before the final answer. The chain-of-thought appears in one of three places depending on the model family — and mishandling any of them causes either (a) infinite reasoning loops, (b) reasoning-tag leakage into the final answer, or (c) out-of-distribution history that degrades quality.

### 17.1 Three families of reasoning emission

| Family | Where the chain-of-thought lives | History-strip behavior | Examples |
|---|---|---|---|
| **A. Inline `<think>...</think>` tags in the assistant content** | Inside `choices[0].delta.content` (or the equivalent completion field). Tags appear literally in the streamed text. | DeepSeek-R1's official Jinja template **auto-strips** `<think>...</think>` from prior assistant turns via a content_pre_render_filter. **Other families using inline tags do NOT auto-strip** — the client must strip them. | DeepSeek-R1, DeepSeek-R1-Distill-* (Llama/Qwen), Fallen-Llama-3.3-R1-70B-v1, Phi-4-reasoning |
| **B. Separate `reasoning_content` field** | A dedicated field on the delta object: `delta.reasoning_content`. Streaming APIs (DeepSeek API, OpenAI o1-compatible, some Anthropic proxies) deliver reasoning as a parallel channel. | The cloud API does NOT include `reasoning_content` in the next-turn `messages` history by default. The client must NOT synthesize inline `<think>` tags from this field (SoW's `deepseek_provider.py:41-65` does this — KI#9). | DeepSeek API (`deepseek-reasoner`), gpt-oss-120b/20b (via OpenAI-compatible), some xAI proxies |
| **C. Jinja variable toggles (`enable_thinking`) with suffix commands (`/think`, `/no_think`)** | Chain-of-thought emitted inline in `content` between `<think>` and `</think>`, but template logic decides whether to emit it. The user controls via Jinja var or per-turn suffix. | The model's Jinja template typically does strip prior turns' `<think>` blocks when `enable_thinking=False`. But when `enable_thinking=True` is active for the current turn, prior `<think>` blocks may leak if the template is buggy. **Safer: client always strips.** | Qwen3, Skyfall-31B-v4.2, Mistral Magistral |

### 17.2 Detection — is this model a reasoning model?

Reliable signals, in priority order:

1. **GGUF metadata `reasoning_budget` or `think` field.** Newer GGUFs (post-2025) may carry this. If present and non-zero → reasoning model.
2. **`chat_template.jinja` references `enable_thinking` or `reasoning` variable.** Read the Jinja file; grep for `enable_thinking` / `reasoning_effort` / `think`.
3. **Tokenizer vocab contains `</think>` (Qwen3 token 151668) or `<think>` as atomic tokens.** Reliable signal that the model was trained with reasoning.
4. **Model filename or HF card mentions "R1", "reasoning", "think", "Magistral", "Nemotron reasoning", "Phi-4-reason".** Weak signal, prone to false positives (e.g. "thoughtful" models that aren't reasoning-trained).
5. **Cloud API model name returns a `reasoning_content` field on first non-streaming call.** Definitive for Family B.

A model that satisfies (1) OR (3) is definitely a reasoning model. (2) AND (4) together is a strong signal. (5) is only available after the first call.

### 17.3 History stripping rules

When building the next-turn message list, prior assistant turns' content must be sanitized:

```python
import re

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)

# Family A (DeepSeek-R1 official auto-strips, but client-side strip is harmless and idempotent)
# Family C (Qwen3, Skyfall, Magistral — same regex)
def strip_think_blocks(content: str, *, keep_after_think: bool = True) -> str:
    """Remove <think>...</think> blocks from prior assistant content.

    Args:
      content: the assistant message content from chat history.
      keep_after_think: if True (default), keep the post-`</think>` content (the actual answer).
                       If False, return empty string (use when the entire reasoning + answer
                       should be omitted — rare).

    Returns:
      Sanitized content. If no <think> tags present, returns input unchanged.
    """
    if "</think>" not in content:
        return content
    if keep_after_think:
        return content.split("</think>", 1)[-1].lstrip()
    return _THINK_PATTERN.sub("", content).strip()
```

**When to apply:**
- **Family A (DeepSeek-R1, Phi-4-reasoning, R1-distills):** apply on every prior assistant turn before sending to the API. Even if the model's template auto-strips, client-side stripping is idempotent and protects against buggy templates.
- **Family B (cloud APIs with `reasoning_content`):** the API never returns `reasoning_content` in the `messages` history. The client must NOT inject synthesized `<think>` tags into the stored history. **Hybrid storage and rendering (resolved iter-9 contradiction #2):**
  - **API messages list** (sent to backend): MUST use separate fields. Send `{"role": "assistant", "content": "<final answer>"}` only — do NOT include `reasoning_content` in the replayed history. The cloud API reconstructs reasoning server-side if needed; sending it back is both redundant and out-of-distribution.
  - **Local chat log / storage:** PREFERRED format is separate fields — `message.content` (final answer) + `message.reasoning_content` (the reasoning text). This preserves the native structure and makes the `is_native_reasoning=True` flag implicit. LEGACY format (single string with synthesized `<think>...</think>` wrap, as SoW's `deepseek_provider.py:41-65` currently does — KI#9) is acceptable ONLY IF `strip_think_blocks()` is applied to `content` before building the API messages list.
  - **UI display:** MAY render reasoning inline (collapsible `<think>` block in the chat window) for better UX — this is a presentation concern, not a storage or API concern. The UI reads `reasoning_content` (if stored separately) or extracts it from the legacy string via the `<think>...</think>` regex, then renders it with a "Thinking" visual treatment. The `is_native_reasoning=True` flag on the message object tells the UI this is Family-B reasoning (rendered collapsible) vs Family-A/C inline reasoning (rendered as part of the message).
  - **Critical invariant:** whatever the UI shows, the API MUST NEVER receive synthesized `<think>` tags in `content`. The boundary between UI display and API serialization is strict.
- **Family C (Qwen3, Skyfall, Magistral):** apply on every prior assistant turn. Even if the Jinja template strips, do it client-side too — defense in depth.

**When NOT to apply:**
- For the **current** turn's prefill (if the application prefill's `<think>\n\n` to force reasoning, e.g. Fallen-Llama-3.3-R1-70B-v1, do NOT strip the prefill).
- For DeepSeek-R1 when the user explicitly wants to see prior reasoning (rare; opt-in UI toggle).

### 17.4 Reasoning prefill (force thinking)

Some models (Fallen-Llama-3.3-R1-70B-v1, certain R1-distills) require the client to prefill the assistant turn with `<think>\n\n` to force multi-turn thinking. Without the prefill, the model produces a non-reasoning answer.

This is implemented as the first chunk of the assistant content sent to the API before the model continues. For OpenAI-compatible APIs, this is the `assistant_prefill` parameter (DeepSeek) or a trailing `{"role": "assistant", "content": "<think>\n\n"}` message in the history. For raw completion endpoints, it is literally appended to the prompt after the generation prompt.

UI implication: a "force reasoning" checkbox, per-model. When enabled, the client prefills `<think>\n\n` and strips it from the displayed response.

### 17.5 Reasoning budget

llama.cpp's `--reasoning-budget <N>` flag controls the maximum number of tokens the model spends on reasoning before producing a final answer (Family A only — for Family C, the Jinja template's `enable_thinking` is the on/off switch and there is no budget). N=0 disables reasoning entirely.

SoW currently passes `--reasoning-budget 0` when `reasoning_mode=False` in `local_server_manager.py:145-146`. This is correct for Family A models. It is a no-op for Family C models (the Jinja `enable_thinking` flag controls them — see §21 for `--chat-template-kwargs` usage).

---

## 18. MoE Architecture Considerations

Mixture-of-Experts (MoE) models route each token through a subset of "expert" feedforward networks. From a **chat-template perspective, MoE is irrelevant**: the template is determined by the tokenizer and the chat-format the model was instruction-tuned on, not by the FNN architecture. A MoE model and its dense counterpart from the same family use identical chat templates, special tokens, and stop tokens.

However, MoE affects **runtime configuration**, which the chat-template strategy must account for when launching local backends.

### 18.1 MoE models the application may encounter

| Model | Architecture tag | Total params | Active params | Stop token | Reasoning? | Notes |
|---|---|---|---|---|---|---|
| DeepSeek V2 / V3 / R1 | `deepseek2` / `deepseek3` | 236B / 671B / 671B | 21B / 37B / 37B | `<｜end▁of▁sentence｜>` (U+FF5C) | R1 yes | The reference MoE reasoning model. |
| Mixtral 8x7B / 8x22B | `llama` (arch is llama-derived; MoE in FFN) | 47B / 141B | 13B / 39B | `</s>` | No | Original open MoE. |
| Qwen3-30B-A3B | `qwen3-moe` | 30B | 3B | `<|im_end|>` | Yes (toggle) | Highly popular for local RP — fits in 24GB VRAM at Q4. |
| Qwen3-235B-A22B | `qwen3-moe` | 235B | 22B | `<|im_end|>` | Yes (toggle) | Cloud-only for most users. |
| gpt-oss-120b / gpt-oss-20b | `gpt-oss` (OpenAI open models) | 120B / 20B | 5B / 3B | `<|endoftext|>` | Yes (`reasoning_content` field) | OpenAI's "open" MoE family. gpt-oss-20b is desktop-runnable. |
| Granite 4 (IBM) | `granite` | 32B / 128B | 3B / 32B | `<|end_of_text|>` | Selective | Small MoE variants. |
| Gemma 4 26B-A4B | `gemma3` (with MoE FFN) | 26B | 4B | `<end_of_turn>` | Selective | Gemma 4's first MoE variant. |
| OLMoE | `llama` | 7B | 1B | `</s>` | No | Smallest MoE. |

### 18.2 MoE-specific runtime flags (llama.cpp)

These flags are NOT chat-template related, but they affect how the backend starts and must be coordinated with the template selection:

| Flag | Purpose | SoW status |
|---|---|---|
| `--n-cpu-moe <N>` | Keep experts of N layers in CPU RAM (offload the rest to GPU). Critical for fitting large MoE models in limited VRAM. | **Implemented** in `local_server_manager.py:186-189`. Reads `cpu_moe_layers` setting. |
| `--no-cuda-graphs` | Disable CUDA graphs (sometimes needed for MoE on certain GPUs — MoE routing can break graph capture). Optional. | NOT implemented. Users can pass via `custom_args` setting. |
| `--override-tensor` | Expert tensor overrides (rarely needed; for debugging). | NOT implemented. |

### 18.3 Why MoE does NOT affect chat-template detection

The detection pipeline (§3) reads `tokenizer.chat_template`, `tokenizer_config.json`, `chat_template.jinja`, and `general.architecture`. None of these change between a dense model and its MoE counterpart. A Qwen3-14B (dense) and Qwen3-30B-A3B (MoE) have **identical** tokenizer configs, identical `chat_template.jinja`, identical `enable_thinking` Jinja variable, and identical `<|im_end|>` stop token. The only difference is the FFN structure, which the tokenizer never sees.

Practical implication: the chat-template detection pipeline does NOT need a separate MoE branch. The architecture heuristic (Layer 2) can treat `qwen3` and `qwen3-moe` as the same family (both → ChatML with `enable_thinking` toggle). Similarly `deepseek2` and `deepseek3` both → DeepSeek family template.

### 18.4 Detection of MoE-ness (for runtime configuration, NOT template selection)

If the application wants to surface "MoE offload" UI options only for MoE models, detection signals are:
1. `general.architecture` ends with `-moe` (e.g. `qwen3-moe`, `gemma3-moe`).
2. GGUF metadata `llama.expert_count` field > 0.
3. Architecture is `deepseek2` / `deepseek3` / `gpt-oss` / `granite` (always MoE).
4. Filename contains `A3B`, `A22B`, `MoE`, `8x7B`, `8x22B`, `A4B`.

Signal (1) is the most reliable for new models. Signal (4) is fragile (community finetunes rename models).

---

## 19. Mistral Version Disambiguation

Mistral has shipped five template generations. They are NOT interchangeable — applying v7-Tekken to a v3-Tekken model breaks it (Rocinante-X, The-Omega-Directive explicitly warn against this). The previous strategy doc only mentioned "Mistral v0.3" and "Mistral Tekken" as two variants. The actual landscape is more complex.

### 19.1 The five Mistral template generations

| Version | Models | BPE | `[SYSTEM_PROMPT]` tag? | Tool tokens? | Discriminator |
|---|---|---|---|---|---|
| **v1** (Mistral 7B v0.1) | Mistral-7B-Instruct-v0.1 | SentencePiece (llama tokenizer) | No | No | `tokenizer.ggml.model == "llama"`, no `[INST]` tool tokens |
| **v2** (Mistral 7B v0.2) | Mistral-7B-Instruct-v0.2 | SentencePiece | No | No | Same as v1; whitespace handling differs in Jinja — read `chat_template.jinja` |
| **v3** (Mistral 7B v0.3) | Mistral-7B-Instruct-v0.3 | SentencePiece | No | Yes (`[TOOL_CALLS]`, `[/TOOL_CALLS]`, `[TOOL_RESULTS]`, `[/TOOL_RESULTS]`) | Presence of `[TOOL_CALLS]` token in vocab |
| **v3-Tekken** (Mistral Nemo, Large-2) | Mistral-Nemo-Instruct-2407, Mistral-Large-Instruct-2407 | **Tiktoken** (gpt2 tokenizer) | **No** | Yes | `tokenizer.ggml.model == "gpt2"`, absence of `[SYSTEM_PROMPT]` |
| **v7-Tekken** (Mistral Small 3+, 2026) | Mistral-Small-3.1-24B-Instruct-2509, Mistral-Small-3.2-24B-Instruct-2506 | Tiktoken | **Yes** (`[SYSTEM_PROMPT]`, `[/SYSTEM_PROMPT]`) | Yes | Presence of `[SYSTEM_PROMPT]` token in vocab |

### 19.2 Detection algorithm

```python
def detect_mistral_version(tokenizer_config: dict, gguf_metadata: dict | None = None) -> str:
    """Return one of: 'mistral-v1', 'mistral-v2', 'mistral-v3', 'mistral-v3-tekken', 'mistral-v7-tekken', 'unknown'."""
    added_tokens = {t["content"] for t in tokenizer_config.get("added_tokens_decoder", {}).values()}
    tokenizer_model = (gguf_metadata or {}).get("tokenizer.ggml.model", "")

    has_system_prompt_tag = "[SYSTEM_PROMPT]" in added_tokens
    has_tool_calls = "[TOOL_CALLS]" in added_tokens
    is_tekken = tokenizer_model == "gpt2"

    if has_system_prompt_tag and is_tekken:
        return "mistral-v7-tekken"
    if has_tool_calls and is_tekken:
        return "mistral-v3-tekken"
    if has_tool_calls and not is_tekken:
        return "mistral-v3"
    if is_tekken and not has_tool_calls:
        # Nemo/Large-2 with tools stripped (rare) — treat as v3-Tekken
        return "mistral-v3-tekken"
    if not is_tekken and not has_tool_calls:
        # v1 or v2 — disambiguate via chat_template.jinja whitespace handling
        # (v2 changed whitespace inside [INST]; the Jinja file is authoritative)
        return "mistral-v2"  # default to v2 for safety; v1 is rare in 2026
    return "unknown"
```

### 19.3 Mapping to llama.cpp `--chat-template` flag

llama.cpp's built-in template names (as of 2026-07) include: `mistral-v1`, `mistral-v2`, `mistral-v3`, `mistral-v3-tekken`, `mistral-v7-tekken`. Pass the detected string directly as `--chat-template <name>`.

For client-side rendering (raw mode, §5), the application's preset library must include all five variants. SoW's current `comboBox_chat_template` only has one "Mistral" option — this is a known gap (KI#11 partial, see audit doc).

### 19.4 Common pitfall: community finetunes that strip `[SYSTEM_PROMPT]`

Several community finetunes of Mistral Small 3 (Rocinante-X-12B-v1, The-Omega-Directive-M-12B-v1.0, others) explicitly remove the `[SYSTEM_PROMPT]` tag from their training data and recommend **v3-Tekken** template. Applying v7-Tekken (because the base was Mistral Small 3) injects `[SYSTEM_PROMPT]` tokens the model never saw during training → silent degradation.

Detection: read the model card. If the card says "v3 Tekken" or "REMOVE [SYSTEM_PROMPT]" → force v3-Tekken, regardless of base model. If `chat_template.jinja` is shipped with the model, prefer its content over the architecture heuristic.

---

## 20. llama.cpp Runtime Flags (template-related)

A consolidated reference of llama.cpp server flags that affect chat-template behavior. The application must coordinate these with template detection.

### 20.1 Flag reference

| Flag | Purpose | Default | When to use |
|---|---|---|---|
| `--jinja` | Enable Jinja template rendering (vs. built-in name-based templates only). | **ON by default** in modern llama.cpp (env `LLAMA_ARG_JINJA=1`). | Always. Do NOT pass `--no-jinja` — it breaks Gemma 3/4, Qwen3, Skyfall, DavidAU, and any model with a custom Jinja in `chat_template.jinja`. |
| `--no-jinja` | Disable Jinja, use only built-in name templates. | Off | **Never recommended.** Documented only because users may pass it via `custom_args`. |
| `--chat-template <name>` | Use a built-in template by name (e.g. `chatml`, `llama3`, `deepseek`, `gemma`, `qwen3-thinking`). | (from GGUF metadata) | When the user explicitly overrides. SoW currently uses this for non-"Auto" combo selections (`local_server_manager.py:149-155`). |
| `--chat-template-file <path>` | Use a custom Jinja template from a file. | (from GGUF metadata) | Advanced use — for users with a known-good Jinja file. Overrides `--chat-template` and GGUF metadata. |
| `--chat-template-kwargs '<json>'` | Pass JSON to the Jinja template context. | `{}` | **Required** for Qwen3 `enable_thinking` toggle, Skyfall `/think`, Mistral Magistral, and any multi-template model with a Jinja selector. Example: `--chat-template-kwargs '{"enable_thinking":false}'`. |
| `--special` | Allow special tokens in the prompt (don't strip them). | Off | Rarely needed. Useful for prompt-engineering with explicit `<|im_start|>` in the user message. |
| `--reasoning-budget <N>` | Maximum tokens for reasoning (Family A models). | 0 (disabled) | Set > 0 to enable reasoning; 0 disables. SoW uses this when `reasoning_mode=False`. |
| `--system-prompt-file <path>` | Inject a system prompt server-side (not from chat-completions API). | None | Rarely needed. Use only when the application wants the backend to own system prompt construction. |
| `--mmproj <path>` | Multimodal projector file (for vision models). | None | When the GGUF is a vision model. **Caveat:** when `--mmproj` is passed, llama-server may ignore `--chat-template` / `--chat-template-file` and use the GGUF-embedded template only. Warn the user that manual template override will not take effect. |

### 20.2 Built-in template names (54 as of 2026-07)

llama.cpp's built-in chat-template registry includes (partial list, see llama.cpp `tools/server` source for the authoritative list):

`chatml`, `chatml-bos`, `llama2`, `llama3`, `llama3.1`, `llama3.2`, `llama3.3`, `mistral-v1`, `mistral-v2`, `mistral-v3`, `mistral-v3-tekken`, `mistral-v7-tekken`, `deepseek`, `deepseek-r1`, `deepseek-v2`, `deepseek-v3`, `qwen3-thinking`, `qwen3-non-thinking`, `gemma`, `gemma2`, `gemma3`, `command-r`, `phi-3`, `phi-4`, `zephyr`, `openchat`, `alpaca`, `vicuna`, `yi`, `orion`, `openhermes`, `magicoder`, `saiga`, `sauerkraut`, `stablelm-zephyr`, `polyglot-ko`, `evidently`, `telechat`, `opencoder`, `nemotron-nano`, `nemotron-ultra`, `gpt-oss`, `granite-3`, `granite-4`, `smol_lm`, `falcon3`, `exaone-3`, `olmo`, `tulu`, `chatglm`, `qwen2.5`, `qwen2.5-coder`, `zai-glm-4`, `zai-glm-4.5`.

For SoW's `comboBox_chat_template`, this list is the source of truth — the combo should ideally match these names. Current SoW combo (`Auto`, `ChatML`, `Llama-3`, `DeepSeek`, `Qwen`, `Mistral`, `Alpaca`) is a subset; missing options include `mistral-v3-tekken` vs `mistral-v7-tekken` (critical for §19), `gemma3`, `qwen3-thinking`/`qwen3-non-thinking`, `deepseek-r1`.

### 20.3 SoW-specific wiring recommendations

- SoW currently does NOT pass `--jinja` explicitly (relies on default). This is correct as long as the bundled llama-server build is recent (post-2025). **Recommendation:** verify in `backend_updater.py` that downloaded builds are recent. Document in the UI tooltip that `--jinja` is implicit.
- SoW does NOT pass `--chat-template-kwargs` — this means Qwen3's `enable_thinking` toggle has no effect via the combo box. **Recommendation for iter-6 or iter-11:** add a per-model `enable_thinking` checkbox in the LLM settings, wired to `--chat-template-kwargs '{"enable_thinking": <bool>}'`.
- SoW passes `--reasoning-budget 0` when `reasoning_mode=False` — correct for Family A. Family C is unaffected (the Jinja `enable_thinking` controls them, see §17.5).
- SoW's `--n-cpu-moe` is correctly wired (KI not raised) — see §18.2.

---

## 21. DeepSeek Family Special Token Reference (byte-level)

A self-contained reference table for the DeepSeek V2/V3/R1 family's special tokens. **All use U+FF5C (fullwidth vertical line) and U+2581 (SentencePiece space marker), NOT ASCII equivalents.** See §10.0 for the byte-level matching rules.

### 21.1 Token table

| Token (Unicode, render-safe) | UTF-8 bytes | Codepoints used | Token ID (DeepSeek V2/R1 vocab) | Purpose |
|---|---|---|---|---|
| `<｜begin▁of▁sentence｜>` | `3C EF BD 9C 62 65 67 69 6E E2 96 81 6F 66 E2 96 81 73 65 6E 74 65 6E 63 65 EF BD 9C 3E` | `<` `｜` `begin` `▁` `of` `▁` `sentence` `｜` `>` | 151646 | BOS |
| `<｜end▁of▁sentence｜>` | `3C EF BD 9C 65 6E 64 E2 96 81 6F 66 E2 96 81 73 65 6E 74 65 6E 63 65 EF BD 9C 3E` | `<` `｜` `end` `▁` `of` `▁` `sentence` `｜` `>` | 151643 | EOS / stop token |
| `<｜User｜>` | `3C EF BD 9C 55 73 65 72 EF BD 9C 3E` | `<` `｜` `User` `｜` `>` | 151653 | User turn start |
| `<｜Assistant｜>` | `3C EF BD 9C 41 73 73 69 73 74 61 6E 74 EF BD 9C 3E` | `<` `｜` `Assistant` `｜` `>` | 151654 | Assistant turn start |
| `<｜tool▁calls▁begin｜>` | (analogous) | `｜` + `▁` | 151657 | Tool call block begin |
| `<｜tool▁calls▁end｜>` | (analogous) | `｜` + `▁` | 151658 | Tool call block end |
| `<｜tool▁call▁begin｜>` | (analogous) | `｜` + `▁` | 151659 | Single tool call begin |
| `<｜tool▁call▁end｜>` | (analogous) | `｜` + `▁` | 151661 | Single tool call end |
| `<think>` | `3C 74 68 69 6E 6B 3E` | ASCII `<` `think` `>` (no fullwidth) | 151667 | Reasoning block begin (R1 only) |
| `</think>` | `3C 2F 74 68 69 6E 6B 3E` | ASCII `</think>` (no fullwidth) | 151668 | Reasoning block end (R1 only) |

### 21.2 Common confusion patterns

1. **String equality without byte-level comparison.** Python `"<|end_of_sentence|>" == "<｜end▁of▁sentence｜>"` returns `False`. The strings look identical in many fonts but differ at the byte level. **Always compare UTF-8 bytes.**
2. **Regex with character class.** `[｜|]` matches both U+FF5C and ASCII `|`. This is fine for tolerant matching but can produce false positives if you're trying to distinguish DeepSeek from non-DeepSeek templates.
3. **HTML rendering.** The fullwidth pipe `｜` renders as a single character in most monospace fonts, but some terminals show it as a tofu box. The SentencePiece space `▁` may render as a low underscore block — easily confused with `_`.
4. **API-side normalization.** Some cloud API proxies (notably OpenAI-compatible wrappers around DeepSeek) normalize the fullwidth pipe to ASCII on the wire. This breaks the model's training distribution. If using a proxy, verify that the raw bytes reach the model unchanged.

### 21.3 Sanitization (for special-token spoofing, §11)

When sanitizing user-supplied content (character cards, world info) against DeepSeek-family templates, the sanitizer must scan for **both** the fullwidth and ASCII variants:

```python
DEEPSEEK_SPECIAL_TOKENS = [
    "<｜begin▁of▁sentence｜>",  # fullwidth
    "<｜end▁of▁sentence｜>",
    "<｜User｜>",
    "<｜Assistant｜>",
    "<｜tool▁calls▁begin｜>",
    "<｜tool▁calls▁end｜>",
    "<｜tool▁call▁begin｜>",
    "<｜tool▁call▁end｜>",
    "<think>",  # ASCII (reasoning tag)
    "</think>",
    # Tolerant variants — strip these even though they're not "real" DeepSeek tokens
    "<|begin_of_sentence|>",  # ASCII lookalike
    "<|end_of_sentence|>",
    "<|User|>",
    "<|Assistant|>",
]
```

Scan content for each token (case-sensitive, exact byte match), strip or replace. The tolerant variants are included because adversarial character cards may use ASCII lookalikes that the BPE would split into subwords — even though they don't match the model's true EOS, they can still cause out-of-distribution input.

---

## 22. Sources

- [Qwen2.5 tokenizer_config.json](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/blob/main/tokenizer_config.json)
- [Qwen3-14B model card](https://huggingface.co/Qwen/Qwen3-14B) — `enable_thinking` Jinja variable, `/think` and `/no_think` suffix commands, token 151668 = `</think>`.
- [Qwen3 chat_template.jinja](https://huggingface.co/Qwen/Qwen3-14B/blob/main/chat_template.jinja) — multi-template model with `qwen3-thinking` and `qwen3-non-thinking` selectors.
- [Meta Llama 3 tokenizer](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct)
- [meta-llama/Llama-3.1-8B-Instruct — Tool Calling](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct)
- [meta-llama/Llama-3.1-8B-Instruct generation_config.json](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct/blob/main/generation_config.json)
- [OpenAI ChatML proposal](https://github.com/openai/openai-python/blob/main/chatml.md)
- [llama.cpp PR #7399 — Jinja support](https://github.com/ggerganov/llama.cpp/pull/7399)
- [llama.cpp server README — chat templates](https://github.com/ggerganov/llama.cpp/tree/master/tools/server) — authoritative list of 54 built-in template names.
- [llama.cpp `--jinja` env variable (LLAMA_ARG_JINJA)](https://github.com/ggerganov/llama.cpp/blob/master/tools/server/server.cpp) — default-on behavior.
- [DeepSeek-R1 model card](https://huggingface.co/deepseek-ai/DeepSeek-R1) — `<think>...</think>` history stripping, `reasoning_content` field.
- [DeepSeek-V3 technical report](https://github.com/deepseek-ai/DeepSeek-V3)
- [DeepSeek-R1 tokenizer_config.json](https://huggingface.co/deepseek-ai/DeepSeek-R1/blob/main/tokenizer_config.json) — fullwidth pipe tokens (U+FF5C).
- [vLLM issue #10993 — DeepSeek-R1 think leakage](https://github.com/vllm-project/vllm/issues/10993)
- [vLLM chat_utils.py](https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/chat_utils.py)
- [llama.cpp issue #11861 — DeepSeek think tag leakage](https://github.com/ggerganov/llama.cpp/issues/11861)
- [llama.cpp issue #12107 — DeepSeek reasoning strip in Jinja](https://github.com/ggerganov/llama.cpp/issues/12107)
- [GGUF spec — general.architecture](https://github.com/ggerganov/ggml/blob/master/docs/gguf.md)
- [Ollama template.go](https://github.com/ollama/ollama/blob/main/template.go)
- [Ollama Modelfile docs](https://github.com/ollama/ollama/blob/main/docs/modelfile.md#template)
- [mistralai/Mistral-Nemo-Instruct-2407](https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407) — v3-Tekken reference.
- [mistralai/Mistral-Small-3.1-24B-Instruct-2509](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2509) — v7-Tekken reference, `[SYSTEM_PROMPT]` tag.
- [Mistral cookbook — tool calling](https://github.com/mistralai/cookbook)
- [google/gemma-2-9b-it model card](https://huggingface.co/google/gemma-2-9b-it)
- [google/gemma-3-12b-it chat_template.jinja](https://huggingface.co/google/gemma-3-12b-it/blob/main/chat_template.jinja) — `first_user_prefix` system synthesis.
- [unsloth/gemma-3-12b-it chat_template.jinja](https://huggingface.co/unsloth/gemma-3-12b-it/blob/main/chat_template.jinja) — alternate Gemma 3 Jinja (used by SillyTavern preset).
- [TheDrummer/Skyfall-31B-v4.2](https://huggingface.co/TheDrummer/Skyfall-31B-v4.2) — custom Jinja with `/think` toggle.
- [TheDrummer/Fallen-Llama-3.3-R1-70B-v1](https://huggingface.co/TheDrummer/Fallen-Llama-3.3-R1-70B-v1) — DeepSeek-R1-distill-on-Llama-3.3-70B.
- [TheDrummer/Rocinante-X-12B-v1](https://huggingface.co/TheDrummer/Rocinante-X-12B-v1) — Mistral v3-Tekken (NOT v7) recommendation.
- [TheDrummer/The-Omega-Directive-M-12B-v1.0](https://huggingface.co/TheDrummer/The-Omega-Directive-M-12B-v1.0) — Mistral v3-Tekken.
- [TheDrummer/L3.3-MS-Nevoria-70b](https://huggingface.co/TheDrummer/L3.3-MS-Nevoria-70b) — Llama 3.3 merge, "LLam@ception" preset.
- [TheDrummer/Hearthfire-24B](https://huggingface.co/TheDrummer/Hearthfire-24B) — ChatML, Mistral-Small-3.2 base.
- [TheDrummer/Impish_Bloodmoon-12B-Pre闪光](https://huggingface.co/TheDrummer/Impish_Bloodmoon-12B-Pre闪光) — Mistral NeMo + ChatML.
- [TheDrummer/Impish_LLAMA-4B-Pre](https://huggingface.co/TheDrummer/Impish_LLAMA-4B-Pre) — Llama 3.2 + ChatML.
- [Sao10K/Midnight-Rose-70B-v2.0.3](https://huggingface.co/Sao10K/Midnight-Rose-70B-v2.0.3) — Llama 2 / Vicuna.
- [DavidAU/gemma-3-12b-it-vl-thinking](https://huggingface.co/DavidAU/gemma-3-12b-it-vl-thinking) — "direct thinking logic" custom Jinja.
- [Jinja2 SandboxedEnvironment docs](https://jinja.palletsprojects.com/en/stable/sandbox/)
- [SillyTavern source — depth prompt injection](https://github.com/SillyTavern/SillyTavern)
- [Backyard AI documentation](https://backyard.ai)
- [OpenAI gpt-oss model card](https://huggingface.co/openai/gpt-oss-120b) — `reasoning_content` field, MoE.
- [IBM Granite 4 model card](https://huggingface.co/ibm-granite/granite-4.0-small-a3b) — MoE variant.
- [NVIDIA Nemotron Nano model card](https://huggingface.co/nvidia/Nemotron-Nano-8B-v1) — reasoning toggle via prompt prefix.

### 22.1 Additional sources added iter-9 (consolidation audit)

Primary HuggingFace template references (verified 2026-07-29, grouped by family):

- [Qwen/Qwen2.5-7B-Instruct tokenizer_config.json](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/blob/main/tokenizer_config.json) — ChatML canonical source (Qwen, Yi, OpenHermes family).
- [Qwen/Qwen3-14B chat_template.jinja](https://huggingface.co/Qwen/Qwen3-14B/blob/main/chat_template.jinja) — single-template with `enable_thinking` variable (both thinking and non-thinking modes selected at runtime via `--chat-template-kwargs`).
- [meta-llama/Llama-3.1-8B-Instruct tokenizer_config.json](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct/blob/main/tokenizer_config.json) — header-based template with `date_string` variable (see §7.2 for KV-cache implication).
- [mistralai/Mistral-7B-Instruct-v0.2 tokenizer_config.json](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.2/blob/main/tokenizer_config.json) — Llama 2 / Mistral v0.1–v0.2 `[INST]...[/INST]` format.
- [mistralai/Mistral-Nemo-Instruct-2407 tokenizer_config.json](https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/blob/main/tokenizer_config.json) — v3-Tekken reference (Nemo, community finetunes like Rocinante-X).
- [mistralai/Mistral-Small-3.1-24B-Instruct-2509 tokenizer_config.json](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2509/blob/main/tokenizer_config.json) — v7-Tekken reference, `[SYSTEM_PROMPT]` token disambiguator.
- [google/gemma-3-12b-it chat_template.jinja](https://huggingface.co/google/gemma-3-12b-it/blob/main/chat_template.jinja) — system role synthesized into first user turn via `first_user_prefix` (see §16.4 rule 7, §1.1).
- [deepseek-ai/DeepSeek-R1 tokenizer_config.json](https://huggingface.co/deepseek-ai/DeepSeek-R1/blob/main/tokenizer_config.json) — fullwidth pipe U+FF5C, `added_tokens_decoder` for `mid`/`/mid` reasoning tags.
- [CohereForAI/c4ai-command-r-plus tokenizer_config.json](https://huggingface.co/CohereForAI/c4ai-command-r-plus/blob/main/tokenizer_config.json) — Command R template reference.
- [openai/gpt-oss-120b chat_template.jinja](https://huggingface.co/openai/gpt-oss-120b/blob/main/chat_template.jinja) — harmony-format with `reasoning_content` field (Family B reference, see §17.1).

Auxiliary template collections:

- [llama.cpp Wiki — Templates supported by `llama_chat_apply_template`](https://github.com/ggml-org/llama.cpp/wiki/Templates-supported-by-llama_chat_apply_template) — authoritative list of 50+ built-in template names accepted by `--chat-template <name>`. Source of truth for `comboBox_chat_template` preset expansion (iter-12 / KI#11).
- [chujiezheng/chat_templates](https://github.com/chujiezheng/chat_templates) — community-maintained library of ready-to-copy `.jinja` files. Fallback for the patch registry (§8) when a model ships a broken or missing `chat_template` and no HF cached version is available. **MUST be sandboxed (§6) before rendering — community-provided, not signed.**

HuggingFace API references (for §8.5 offline cache `commit_hash` verification):

- [HuggingFace Hub API — get model metadata](https://huggingface.co/api/models/{repo_id}) — returns `sha` field = current `commit_hash`. ~1 KB JSON response, no auth required for public models.
