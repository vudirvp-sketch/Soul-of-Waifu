# Chat Template Auto-Detection — Ultimate Design Plan (iter-15 research)

> ## ⚠️ STATUS (added iter-44-audit, 2026-07-31)
>
> This plan is **partially consumed**. The original 6 sub-iterations have been shipped as follows:
>
> | Plan §11 sub-iter | Real commit | Status | Notes |
> |---|---|---|---|
> | 1 (GGUF reader + HF cache) | `5bfff06 iter 28` | ✅ **DONE** | `template_detector.py` (714 LOC), `hf_template_cache.py` (420 LOC), `gguf>=0.10.0` in requirements.txt |
> | 2 (pipeline integration) | `1ec0b35 iter-29` | ✅ **DONE** | `detect_template()` called at `local_server_manager.py:377`; `_build_chat_template_kwargs()` consumes `capability_map` at `:465` |
> | 3 (stop-token tiers 2–4) | — | ⚠️ **PARTIAL** | Tier 1 closed iter-22 (KI#7 partial — settings.json `stop_strings` → LocalProvider API `stop`). Tiers 2–4 (generation_config.json → GGUF `eos_token_id` → template-implied default) NOT routed — `DetectionResult.stop_tokens`/`stop_token_ids`/`stop_token_source` fields exist in `DetectionResult` dataclass but no 4-tier precedence routing in `LocalProvider.__init__`. Plan body §11 sub-iter 3 needs revision: item 1 (`local_server_manager.py --stop` flag) is no longer required per iter-22 architecture deviation note. |
> | 4 (capability-aware UI replacing `_ENABLE_THINKING_TEMPLATES`) | — | ❌ **NOT STARTED** | `interface_signals.py:5399` still imports `ENABLE_THINKING_TEMPLATES` from `template_capabilities.py`; the latter's docstring (L8) explicitly says "iter-15 plan sub-iteration 4 `detection.capability_map` — when that lands...". Deferred — plan body §11 sub-iter 4 + §3.4 remain authoritative. |
> | 5 (vocab validation + Diagnostics panel) | `1c7e989 iter-26` | ⚠️ **PARTIAL** | `diagnostics_panel.py` (360 LOC) ships read-only state visibility (4 of 8 §7.1 blocks live). `validate_template_against_vocab()` not implemented — only `DetectionResult` fields declared. Free-form Jinja override deferred. |
> | 6 (cloud reasoning plumbing) | `515f346 iter-25` | ✅ **DONE** | All 7 cloud providers (`anthropic/gemini/grok/mistral/openai/openrouter/qwen/zai`) wired with `reasoning_mode`. KI#19 CLOSED. |
>
> Additionally shipped outside this plan: iter-29.1 (`3f200fd` — KI#40 GGUF reader bug + KI#41 `enable_thinking` → `--reasoning off`), iter-27 (`e4a6d98` — 3 duplicate `TEMPLATE_FAMILY_HINTS` + `ENABLE_THINKING_TEMPLATES` constants consolidated into canonical `template_capabilities.py`).
>
> **Bottom line:** 3/6 fully done, 2/6 partial (acknowledged in existing docs), 1/6 not started (deferred per `template_capabilities.py` L8 docstring). No hidden debt. When implementing sub-iter 4 in a future iteration, follow plan body §3.4 + §11 sub-iter 4 — they remain authoritative.
>
> ---

> **Iteration:** iter-15-research-auto-detection (research / exploratory — NO code changes).
> **Date:** 2026-07-30 (iter-24-doc-cleanup addendum: KI#7 partial closure noted in §0; §11 sub-iteration numbering collision with iter-16..iter-23 flagged in §11.0; §6.2 cloud capability table speculative entries annotated).
> **Author:** SoW agent.
> **Scope:** design-only iteration. Produces the architectural blueprint for the "ultimate automatic chat template detection system" requested by the user — maximally automated, with the existing UI combo box + stop-token field serving as fallback for exceptional cases only.
> **Predecessors:** iter-7 (KI#6 + KI#18 — stop tokens + chat-template normalization), iter-10 (KI#9 — `strip_think_blocks()`), iter-12 (KI#11 + KI#16 — combo expansion to 13 items + placeholder fix), iter-13 (KI#8 — `sanitize_special_tokens()`), iter-14 (KI#14 — `enable_thinking` toggle + capability-aware UI auto-hide). 
> ⚠️ **KI#14 dual-definition note.** In this plan and in `STATUS.md`, KI#14 = "enable_thinking toggle" (closed iter-14). In `docs/CHAT_TEMPLATE_STRATEGY_AUDIT.md` (iter-3 audit), KI#14 = "No streaming stop-sequence buffering" (resolved by KI#6 fix, iter-7). When cross-referencing KI#14 between documents, specify which definition: "KI#14-enable_thinking" (this plan + STATUS.md) vs "KI#14-streaming" (auditdoc). See auditdoc §8.7 for the full resolution.
> **Successor:** future code iterations (iter-24+ — see §11.0 roadmap collision note before reading §11). Each sub-iteration is sized to respect the 3–5 file soft limit.
> **Goal:** close all 6 remaining strategy-level KIs (#12, #13, #17, #19, #20 partial, #21 partial) as an integrated system rather than as disconnected patches. **KI#7 was partially closed in iter-22** (tier 1 of the 4-tier stop-token chain — settings.json `stop_strings` → LocalProvider API `stop` parameter); tiers 2–4 (generation_config.json → GGUF → template-implied defaults) remain pending and are included in this plan's stop-token chain sub-iteration (§3.5 + §11 sub-iteration 3).

---

## 0. Executive Summary

Today SoW ships a 13-item `comboBox_chat_template` plus a `lineEdit_stop_strings` field. Both are **manual controls**: the user must pick the right template name and the right stop sequences, and the application trusts the user's choice blindly. iter-14 introduced a tiny capability-aware hint (hide `enable_thinking` checkbox when the active template name is not in a hardcoded set of three), but that hint is **name-based**, not **capability-based** — it cannot detect what a model actually supports.

The user's request is to invert this: make detection **maximally automatic** with manual controls relegated to **exceptional fallback only**. The right architecture for this is the 4-layer pipeline already specified in `docs/chat-template-strategy.md` §3 — but the SoW codebase implements only Layer 4 (manual override). The other three layers (backend negotiation, embedded-template read, architecture heuristic, ChatML-with-warning fallback) are missing. The §8.5 HF source-of-truth cache (offline-capable, TTL + `commit_hash` verification) is also unimplemented; without it, "read the embedded template" means parsing GGUF binary blobs on every startup, which is slow and fragile.

This plan specifies how to ship the missing layers in 6 incremental sub-iterations (iter-16 through iter-21), each sized to a single PR. The end state: when a user picks a local model, SoW reads the GGUF metadata, resolves the template, validates the special tokens against the tokenizer vocab, auto-configures stop tokens, auto-shows/hides reasoning controls based on the *actual template variables* (not a hardcoded name list), and surfaces a live diagnostics panel. The combo box remains — but its label becomes **"Manual override (auto-detected: Qwen3-Thinking)"** instead of being the primary control.

A deliberate architectural choice: **the detection pipeline is read-only and advisory**. It populates defaults and shows diagnostics, but the user can always override. This keeps the existing UX backwards-compatible and preserves the iter-14 capability-aware auto-hide behavior as a downstream consumer of the new detection signals.

---

## 1. Goals and Non-Goals

### 1.1 Goals (in scope for the plan)

1. **Automatic template identification.** When a local model is loaded, identify the chat template from the highest-priority source available: (a) llama-server `/props` API, (b) GGUF metadata `tokenizer.chat_template`, (c) HF source files (via §8.5 cache), (d) `general.architecture` heuristic, (e) ChatML-with-warning fallback.
2. **Automatic stop-token resolution.** Read `eos_token` / `bos_token` / `pad_token` from `generation_config.json` (HF cache) or GGUF metadata; wire into `local_server_manager.py` `--stop` flag and into LocalProvider's `stop` parameter.
3. **Automatic capability detection.** Parse the resolved Jinja template once per model load; grep for `enable_thinking`, `reasoning_budget`, `tools`, `date_string`, `system_prompt` variable references. Show only the controls the template actually supports (generalization of iter-14's hardcoded set).
4. **Template-variable pre-population.** Compute `date_string` once per chat session (per §7.2 + iter-9 contradiction #6 resolution), pass to the backend via `--chat-template-kwargs`. Optional: surface `tools`, `system_prompt` to advanced users.
5. **Tokenizer vocab validation (KI#12).** When tokenizer vocab is accessible (HF cache or GGUF), verify that every special token referenced by the template is present in the vocab. If not — warn the user that the template ships a broken reference (common with community finetunes).
6. **UI diagnostics panel (KI#17).** Live tab showing: detection source + confidence, resolved template name, active stop tokens + source, capability profile, sanitization log (KI#8 already implemented in iter-13), template validation warnings (KI#30 partial — iter-17).
7. **Manual override as fallback.** Existing combo box + `lineEdit_stop_strings` retained, but labeled as override. Free-form Jinja text area added (KI#7 fix direction option B).
8. **Reasoning family integration.** Detection signals feed into the existing Family A/B/C logic (iter-10 / iter-14) — replace the iter-14 `_ENABLE_THINKING_TEMPLATES` hardcoded set with the live capability map.
9. **Cloud provider reasoning plumbing (KI#19).** Extend the capability map to cloud providers by model name (heuristic table). Wire `reasoning_mode` and `enable_thinking` into DeepSeek / OpenAI o-series / Anthropic / Qwen API calls.

### 1.2 Non-Goals (explicitly deferred)

1. **Client-side Jinja rendering (strategy §6 sandboxed rendering).** SoW's architecture delegates rendering to the backend (`/v1/chat/completions`). The sandboxed Jinja renderer is only needed if SoW ever switches to raw `/v1/completions` injection mode for depth prompts. Strategy §6 stays as a specification but is NOT implemented in this plan. The sanitization log (iter-13) + diagnostics panel cover the user-visible security posture.
2. **Signed patch registry (strategy §8).** The HF cache (§8.5) covers the "trust the source" use case. A signed SoW-controlled registry for known-buggy community templates is a future iteration if/when the cache proves insufficient.
3. **KV-cache prefix stability restructure (KI#13).** Architecturally incompatible with SoW's high-volatility system blocks (Soul Memory, lorebook activation, state tracking). Documented as accepted tradeoff in iter-3 audit. Only a future prompt-restructuring refactor would address this; out of scope.
4. **Full Ollama backend support (strategy §4.4).** SoW does not currently support Ollama. Adding it is its own multi-iteration effort.
5. **Multimodal template variants.** Already handled correctly per iter-3 audit §3. No template-detection work needed.

---

## 2. Current State (where we are now)

### 2.1 Code map — what handles templates today

| File | Lines | Role | iter-15 status |
|---|---|---|---|
| `app/gui/sowInterface.py:2502` | ~10 | `comboBox_chat_template` UI definition, 13 items (Auto + 12 named) | unchanged |
| `app/gui/sowInterface.py:2508` | ~5 | `lineEdit_stop_strings` UI definition (KI#7 orphan) | unchanged |
| `app/gui/sowInterface.py:2390-2394` | ~5 | `checkBox_enable_thinking` (iter-14) | unchanged |
| `app/gui/interface_signals.py:5268-5269` | ~2 | Save `chat_template` to settings.json | unchanged |
| `app/gui/interface_signals.py:5271-5272` | ~2 | Save `stop_strings` to settings.json (orphan, KI#7) | unchanged |
| `app/gui/interface_signals.py:5603-5604` | ~2 | Load `stop_strings` from settings.json (orphan) | unchanged |
| `app/gui/interface_signals.py` (iter-14 block) | ~55 | `_ENABLE_THINKING_TEMPLATES` hardcoded set + visibility logic | **replaced** by capability map (iter-19) |
| `app/utils/ai_clients/local_server_manager.py:149-155` | ~7 | Read `chat_template` setting, pass as `--chat-template <name>` (or none if Auto) | **extended** (iter-17) to pass kwargs + stop tokens |
| `app/utils/ai_clients/local_server_manager.py:255-266` | ~12 | `--chat-template-kwargs` wiring (iter-14) | unchanged |
| `app/utils/ai_clients/local_server_manager.py:186-189` | ~4 | `--n-cpu-moe` (correct, no KI) | unchanged |
| `app/utils/ai_clients/local_server_manager.py:110,145` | ~2 | `--reasoning-budget 0` for Family A | unchanged |
| `app/utils/prompt_engine.py` (`strip_think_blocks`, `sanitize_special_tokens`, `enforce_role_alternation`) | various | Family C history strip, structural-token sanitization, Anthropic alternation | unchanged |
| `app/configuration/settings.json` | 1 key | `enable_thinking: null` (iter-14, None = backward-compat) | extended |
| `app/configuration/settings.json` | 1 key | `chat_template: "Auto"` | unchanged |
| `app/configuration/settings.json` | 1 key | `stop_strings: "<\|im_end\|>"` (orphan, KI#7) | **consumed** (iter-18) |

### 2.2 What detection runs today

```
┌─────────────────────────────────────────────────────────────────┐
│ CURRENT DETECTION (iter-14 baseline)                            │
│                                                                 │
│  user picks "Auto" in comboBox_chat_template                    │
│        │                                                        │
│        ▼                                                        │
│  local_server_manager passes NO --chat-template                 │
│        │                                                        │
│        ▼                                                        │
│  llama-server reads GGUF metadata internally and renders       │
│  (correct behavior — backend is authoritative)                  │
│                                                                 │
│  user picks "Qwen3-Thinking" in comboBox                        │
│        │                                                        │
│        ▼                                                        │
│  local_server_manager passes --chat-template qwen3-thinking     │
│  (overrides GGUF metadata — risk of mismatch)                   │
│                                                                 │
│  user picks "ChatML" for a Llama-3 model → silent degradation   │
│  (no warning, no validation)                                    │
└─────────────────────────────────────────────────────────────────┘
```

The current pipeline is **Layer 0 implicit + Layer 4 manual** with no Layers 1–3. The "Auto" option is the closest thing to Layer 0 + Layer 1 — it lets llama-server do the work — but SoW has no visibility into what llama-server actually chose, so capability-aware UI (§12 #9) cannot fire for "Auto" today. iter-14 papered over this with a hardcoded `_ENABLE_THINKING_TEMPLATES = {"Qwen3-Thinking", "Qwen3-Non-Thinking", "Auto"}` — the "Auto" entry is a conservative default (assume Qwen3-style) rather than a real capability read.

### 2.3 What's missing — gap matrix

> ⚠️ **iter-16..iter-21 references in this table = VIRTUAL sub-iterations of the iter-15 plan, NOT real shipped iterations.** Real iter-16 = logging redesign, iter-17 = logging polish, iter-18 = f-string fix, iter-19 = logging analysis/impl, iter-20 = mlock/flash_attn delta, iter-21 = audit cleanup. When implementing this plan, use iter-24+ numbering (see §11.0 for the mapping table).

| Capability | iter-14 state | iter-15 plan target | Sub-iter |
|---|---|---|---|
| Read GGUF `tokenizer.chat_template` | NO (deferred to llama-server) | YES, with caching | iter-16 |
| Read GGUF `general.architecture` | NO | YES | iter-16 |
| Query llama-server `/props` for resolved template | NO | YES (optional, on-demand) | iter-16 |
| HF source-files cache (§8.5) | NO | YES (4 files per model) | iter-16 |
| Template name resolution pipeline | NO (binary: Auto OR user pick) | YES (4-layer, source-tracked) | iter-17 |
| Capability map (which Jinja vars the template references) | hardcoded 3 names | dynamic, per-template | iter-19 |
| Stop-token resolution chain | hardcoded in 5 providers (KI#6 closed in iter-7) | generation_config.json → GGUF → manual override | sub-iteration 3 (tiers 2–4 only; tier 1 closed iter-22) |
| `date_string` per-chat-session computation | NO (deferred §7.2) | YES, derived from `chat.created_at` | iter-17 |
| Template-variable pre-population (`--chat-template-kwargs`) | partial — only `enable_thinking` (iter-14) | full — `enable_thinking` + `date_string` + `reasoning_budget` (when supported) | iter-17 |
| Tokenizer vocab validation (KI#12) | NO | YES — special tokens must be in vocab | iter-20 |
| UI diagnostics panel (KI#17) | NO | YES — Debug tab in LLM settings | iter-20 |
| Manual override as labeled fallback (KI#7) | orphan `stop_strings` field | combo + free-form Jinja text area, labeled "Manual override" | iter-18 |
| Cloud provider reasoning plumbing (KI#19) | NO | heuristic table + per-provider wiring | iter-21 |
| `_ENABLE_THINKING_TEMPLATES` hardcoded set | YES (iter-14 stopgap) | **REMOVED** — replaced by capability map | iter-19 |

---

## 3. Architecture — the Detection Pipeline

The pipeline runs at three trigger points: (a) on app startup if a local model is already selected, (b) on user selection of a new local model file, (c) on chat session creation (for `date_string` recomputation). Each run is **idempotent** and **cached** — repeated triggers within the same chat session skip the work.

### 3.1 Trigger points

```
┌──────────────────────────────────────────────────────────────────┐
│ TRIGGER POINTS                                                   │
│                                                                  │
│  (T1) App startup                                                │
│       if settings.local_llm is set:                              │
│         run pipeline(model_path=settings.local_llm)              │
│                                                                  │
│  (T2) User selects new model file (models_hub download OR       │
│       manual path picker)                                        │
│       run pipeline(model_path=new_path)                          │
│                                                                  │
│  (T3) Chat session creation                                      │
│       recompute date_string from chat.created_at                 │
│       (cheap — does NOT re-run Layers 1–3)                       │
│                                                                  │
│  (T4) User clicks "Refresh detection" button in Debug tab       │
│       run pipeline(model_path=settings.local_llm, force=True)    │
│       (bypasses cache — for advanced users / changed GGUF)       │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 The 5-layer resolution chain

The pipeline is a strict-priority fallthrough. Each layer either resolves the template + emits a `DetectionResult` or falls through to the next. The final `DetectionResult` carries: resolved template name (or None for "use backend default"), source layer, confidence (HIGH/MED/LOW), Jinja source text (when available), capability map, stop tokens, and a list of validation warnings.

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 0: Backend capability negotiation                         │
│                                                                 │
│   if local_llm is None (cloud provider): SKIP (cloud path, §6)  │
│                                                                 │
│   probe llama-server /props endpoint (already running?):        │
│     GET http://127.0.0.1:<port>/props                           │
│     → returns { chat_template: <str>, ... }                     │
│                                                                 │
│   if /props reachable AND chat_template non-empty:              │
│     → DetectionResult(source="backend", confidence=HIGH, ...)   │
│   else: fall through to Layer 1                                 │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: Read embedded chat_template                            │
│                                                                 │
│   Sources, checked in order:                                    │
│     1a. §8.5 HF cache for this model                            │
│         (assets/template_cache/<repo_hash>/{4 files})           │
│     1b. GGUF metadata: tokenizer.chat_template (read directly)  │
│     1c. GGUF metadata: tokenizer.chat_template_n (multi-tmpl)   │
│                                                                 │
│   if any source yields a non-empty Jinja string:                │
│     → parse Jinja for variable references (capability map)      │
│     → DetectionResult(source="embedded", confidence=HIGH, ...)  │
│   else: fall through to Layer 2                                 │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: Architecture-based heuristic                           │
│                                                                 │
│   read GGUF general.architecture field                          │
│                                                                 │
│   map (10 archs → 8 templates):                                 │
│     llama      → llama-3                                        │
│     qwen2      → chatml                                         │
│     qwen3      → qwen3-thinking (default sub-template)          │
│     gemma2     → gemma3                                         │
│     gemma3     → gemma3                                         │
│     command-r  → command-r                                      │
│     deepseek2  → deepseek                                       │
│     deepseek3  → deepseek (with R1 reasoning family)            │
│     mistral    → mistral-v0-1 (lowest common denom)             │
│     mixtral    → mistral-v0-1                                   │
│                                                                 │
│   → DetectionResult(source="arch", confidence=MED, ...)         │
│   → ALWAYS resolves (architecture is always present in GGUF)    │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: ChatML fallback WITH MANDATORY UI WARNING              │
│                                                                 │
│   (only reached if Layer 2 also fails — GGUF malformed)         │
│                                                                 │
│   → DetectionResult(source="fallback", confidence=LOW, ...)     │
│   → emit user-visible WARNING via log_template_validation()     │
│   → Debug panel shows "Template not identified — quality may    │
│      degrade. Select a template manually."                      │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 4: Manual override (always available, not just fallback)  │
│                                                                 │
│   if settings.chat_template != "Auto":                          │
│     DetectionResult is OVERWRITTEN — user's manual pick wins    │
│     but the auto-detected result is preserved in                │
│     DetectionResult.detected_auto (shown in Debug panel)        │
│                                                                 │
│   combo box label becomes:                                      │
│     "Manual override (auto-detected: Qwen3-Thinking)"           │
│   when the override differs from auto-detected:                 │
│     WARNING banner: "Manual override != auto-detected. Verify." │
└─────────────────────────────────────────────────────────────────┘
```

### 3.3 DetectionResult data class

```python
# app/utils/ai_clients/template_detector.py (NEW file in iter-16)
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class DetectionSource(Enum):
    BACKEND = "backend"          # /props API
    EMBEDDED = "embedded"        # GGUF metadata / HF cache
    ARCH = "arch"                # architecture heuristic
    FALLBACK = "fallback"        # ChatML with warning
    MANUAL = "manual"            # user override
    CLOUD = "cloud"              # cloud provider (heuristic table)

class Confidence(Enum):
    HIGH = "high"
    MED = "med"
    LOW = "low"

@dataclass
class CapabilityMap:
    """Which Jinja variables the template references. Drives UI auto-hide."""
    enable_thinking: bool = False       # Family B (Qwen3, Skyfall-/think)
    reasoning_budget: bool = False      # Family A (gpt-oss, Phi-4)
    tools: bool = False                 # tool-calling templates
    date_string: bool = False           # Llama 3 date_string var
    system_prompt: bool = False         # explicit system_prompt var
    add_generation_prompt: bool = True  # standard — almost always True
    custom: dict = field(default_factory=dict)  # unknown vars surfaced

@dataclass
class DetectionResult:
    resolved_template_name: Optional[str]   # None = "use backend default"
    source: DetectionSource
    confidence: Confidence
    jinja_source: Optional[str]             # raw Jinja text, for Debug panel
    capability_map: CapabilityMap
    stop_tokens: list[str]                  # resolved eos/special tokens
    stop_token_source: str                  # "generation_config" | "gguf" | "manual" | "default"
    arch: Optional[str]                     # general.architecture from GGUF
    detected_auto: Optional["DetectionResult"] = None  # preserved when MANUAL overrides
    warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
```

### 3.4 Capability map — replacing the iter-14 hardcoded set

Today iter-14 has:

```python
# app/gui/interface_signals.py — iter-14 stopgap
_ENABLE_THINKING_TEMPLATES = {"Qwen3-Thinking", "Qwen3-Non-Thinking", "Auto"}
```

This breaks for any new Family B model (Skyfall-/think, Magistral, future Qwen3.5, future community finetunes). The replacement is a **dynamic capability map** computed by parsing the resolved Jinja template once per model load:

```python
def compute_capability_map(jinja_source: str) -> CapabilityMap:
    """
    Parse Jinja source for variable references.
    Uses a conservative regex — no Jinja evaluation, just tokenization.
    """
    import re
    caps = CapabilityMap()
    # match {{ variable }} and {% if variable %} patterns
    var_pattern = re.compile(r'\{\{?\s*([a-zA-Z_][a-zA-Z0-9_]*)')
    if_pattern = re.compile(r'\{%[^%]*?\bif\s+([a-zA-Z_][a-zA-Z0-9_]*)')
    found = set()
    found.update(m.group(1) for m in var_pattern.finditer(jinja_source))
    found.update(m.group(1) for m in if_pattern.finditer(jinja_source))

    caps.enable_thinking = "enable_thinking" in found
    caps.reasoning_budget = "reasoning_budget" in found
    caps.tools = "tools" in found
    caps.date_string = "date_string" in found
    caps.system_prompt = "system_prompt" in found
    caps.add_generation_prompt = "add_generation_prompt" in found
    # unknown variables surfaced for debugging
    known = {"enable_thinking", "reasoning_budget", "tools", "date_string",
             "system_prompt", "add_generation_prompt", "messages",
             "loop", "index", "is", "false", "true", "none", "now"}
    caps.custom = {v: True for v in found if v.lower() not in known}
    return caps
```

The iter-14 visibility logic then becomes:

```python
# app/gui/interface_signals.py — iter-19 replacement
def update_capability_aware_visibility(self, detection: DetectionResult):
    caps = detection.capability_map
    # Family B (enable_thinking) — replaces _ENABLE_THINKING_TEMPLATES
    self.ui.checkBox_enable_thinking.setVisible(caps.enable_thinking)
    # Family A (reasoning_budget) — NEW
    self.ui.checkBox_reasoning_mode.setVisible(caps.reasoning_budget)
    # date_string (Llama 3) — automatic, no UI control needed
    # tools — future, hidden for now
    # system_prompt — future, hidden for now
```

When `detection.source == DetectionSource.MANUAL` and the user has selected a specific named template from the combo (not "Auto"), the capability map is computed from the **llama.cpp built-in template's known Jinja** (a static lookup table shipped with SoW — see §5.2). When the user picks "Auto", the capability map comes from the live GGUF/HF cache parse.

### 3.5 Stop-token resolution chain

iter-7 closed KI#6 by removing hardcoded `<|im_end|>` from cloud providers and from LocalProvider's defaults. But the user's `lineEdit_stop_strings` (KI#7) is still orphaned — the setting is saved, no consumer. iter-18 closes KI#7 by introducing a resolution chain:

```
┌─────────────────────────────────────────────────────────────────┐
│ STOP-TOKEN RESOLUTION (iter-18, replaces KI#7 orphan)           │
│                                                                 │
│  priority:                                                      │
│    1. manual override (settings.stop_strings non-empty)         │
│       source = "manual"                                         │
│    2. generation_config.json eos_token (HF cache)               │
│       source = "generation_config"                              │
│    3. GGUF metadata tokenizer.ggml.eos_token_id                 │
│       source = "gguf"                                           │
│    4. template-implied defaults (chatml = <|im_end|>, etc.)     │
│       source = "default"                                        │
│                                                                 │
│  result fed into:                                               │
│    - local_server_manager --stop <tokens> CLI flag              │
│    - LocalProvider generate_stream stop=[tokens]                │
│    - Debug panel display                                        │
│                                                                 │
│  user-visible:                                                  │
│    Debug tab shows: "Active stop tokens: ['<|im_end|>']         │
│                     Source: generation_config.json"             │
│    lineEdit_stop_strings tooltip shows the resolved defaults    │
│    as placeholder text — user knows what they're overriding     │
└─────────────────────────────────────────────────────────────────┘
```

For cloud providers: stop tokens are NOT sent (iter-7 fix — cloud APIs handle EOS internally). The Debug panel still shows what *would* be sent if it were a local model, for diagnostic transparency.

---

## 4. GGUF Metadata Reading — technical investigation

### 4.1 Three viable approaches

| Approach | Library / API | Pros | Cons | Recommended |
|---|---|---|---|---|
| **A. Python `gguf` library** | `pip install gguf` (official, maintained by ggml-org) | Pure-Python read, no subprocess, fast (~50ms per file), exposes all metadata fields including `tokenizer.chat_template`, `general.architecture`, `tokenizer.ggml.eos_token_id` | Adds a dependency (~50KB wheel). Requires Python 3.8+. | ✅ YES |
| **B. llama-server `/props` endpoint** | HTTP GET to running llama-server | No new dependency. Already running for local LLM. Returns resolved template (after llama-server's own Layer 1 logic). | Requires server to be running — does not work for "scan model before launch" use case. Returns resolved Jinja, not raw GGUF fields. | ⚠️ Optional, used as Layer 0 |
| **C. Manual binary parsing** | Custom Python parser | Zero dependencies | Fragile — GGUF format evolves (v1 → v2 → v3 with big-endian variants). Re-implements what `gguf` library already does. High maintenance burden. | ❌ NO |

**Decision:** Use approach A (Python `gguf` library) as primary, approach B (`/props`) as Layer 0 bonus when server is already running. Approach C is explicitly rejected.

### 4.2 `gguf` library — proof-of-concept read

The `gguf` library exposes a `GGUFReader` class:

```python
# iter-16 proof-of-concept — actual implementation lives in
# app/utils/ai_clients/template_detector.py
import gguf

def read_gguf_metadata(model_path: str) -> dict:
    """Read all relevant metadata fields from a GGUF file."""
    reader = gguf.GGUFReader(model_path)
    fields = reader.fields
    result = {
        "chat_template": None,
        "architecture": None,
        "eos_token_id": None,
        "bos_token_id": None,
        "tokenizer_model": None,
        "chat_template_n": {},  # multi-template models
    }
    # tokenizer.chat_template (string)
    if "tokenizer.chat_template" in fields:
        f = fields["tokenizer.chat_template"]
        result["chat_template"] = bytes(f.parts[-1]).decode("utf-8", errors="replace")
    # general.architecture (string)
    if "general.architecture" in fields:
        f = fields["general.architecture"]
        result["architecture"] = bytes(f.parts[-1]).decode("utf-8", errors="replace")
    # tokenizer.ggml.eos_token_id (int or array)
    if "tokenizer.ggml.eos_token_id" in fields:
        f = fields["tokenizer.ggml.eos_token_id"]
        # could be scalar or array depending on model
        result["eos_token_id"] = list(f.parts[-1]) if len(f.parts[-1]) > 1 else int(f.parts[-1][0])
    # tokenizer.ggml.bos_token_id (int)
    if "tokenizer.ggml.bos_token_id" in fields:
        f = fields["tokenizer.ggml.bos_token_id"]
        result["bos_token_id"] = int(f.parts[-1][0])
    # tokenizer.model (string — BPE / Word / etc.)
    if "tokenizer.ggml.model" in fields:
        f = fields["tokenizer.ggml.model"]
        result["tokenizer_model"] = bytes(f.parts[-1]).decode("utf-8", errors="replace")
    # multi-template: tokenizer.chat_template.<name> (Qwen3, Mistral 2024+)
    for key in fields:
        if key.startswith("tokenizer.chat_template."):
            template_name = key[len("tokenizer.chat_template."):]
            f = fields[key]
            result["chat_template_n"][template_name] = bytes(f.parts[-1]).decode("utf-8", errors="replace")
    return result
```

**Performance:** ~50ms for a 4B model, ~200ms for a 70B model (mostly I/O — only the metadata block is read, not the weights). Acceptable for T1/T2/T4 trigger points; not appropriate per-request.

**Caching:** The result is memoized keyed by `(model_path, mtime, size)`. Cache lives in `app/data/template_detection_cache.json` (gitignored — runtime data). Invalidated automatically when the GGUF file changes.

### 4.3 GGUF fields actually used

| GGUF field | Type | Used by | Notes |
|---|---|---|---|
| `tokenizer.chat_template` | string | Layer 1 | Primary embedded template source. Present in ~95% of modern GGUFs. |
| `tokenizer.chat_template.<name>` | string (multiple) | Layer 1 | Multi-template models (Qwen3, Mistral 2024+). Each is a separate field. |
| `general.architecture` | string | Layer 2 | Always present. Maps to template family. |
| `tokenizer.ggml.eos_token_id` | int or array | Stop-token resolution | May be a single int or a list (e.g., Llama-3.1 has 2 eos tokens). |
| `tokenizer.ggml.bos_token_id` | int | Stop-token resolution (bos not actually sent as stop, but logged) | |
| `tokenizer.ggml.model` | string | Mistral version disambiguation (§19) | "llama" vs "gpt2" BPE variant. |
| `general.name` | string | Debug panel display | Human-readable model name. |
| `general.source.huggingface.repository` | string | §8.5 cache key | When present, allows HF cache lookup without user input. |

---

## 5. HF Source-of-Truth Cache (§8.5 implementation)

### 5.1 Why a cache is needed

Reading GGUF metadata gives us `tokenizer.chat_template` — but only what the GGUF author baked in. For community finetunes, this is sometimes stale (author copied the base model's template, finetune uses different tokens). For Qwen3 multi-template models, the GGUF may only carry the default sub-template. The §8.5 HF cache provides the **authoritative source** — the model author's own `tokenizer_config.json` + `chat_template.jinja` + `generation_config.json` + `special_tokens_map.json`.

### 5.2 Cache structure

```
assets/template_cache/<repo_hash>/
├── tokenizer_config.json     # chat_template field + eos/bos/pad tokens
├── chat_template.jinja       # standalone Jinja file (Qwen3, Gemma 3, Skyfall)
├── generation_config.json    # eos_token_id, bos_token_id, pad_token_id
├── special_tokens_map.json   # fullwidth-pipe variants for DeepSeek family
└── _cache_meta.json          # commit_hash, fetched_at, ttl_expires_at
```

`<repo_hash>` is `sha256(huggingface_repo_id)` — example: `sha256("Qwen/Qwen3-8B") = "a1b2c3..."`. This isolates cache entries by repo, not by local filename (one user may have multiple GGUFs from the same repo — quants, versions — they all share the cache entry).

### 5.3 Cache lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│ CACHE LIFECYCLE (per model load — T1/T2 trigger)                │
│                                                                 │
│  1. Determine repo_id:                                          │
│     a. GGUF metadata general.source.huggingface.repository      │
│        (when present — most official quants)                    │
│     b. User-configured "HF repo override" field in Debug tab    │
│        (when GGUF lacks the field — community quants)           │
│     c. SKIP cache — fall back to GGUF-only (Layer 1b)           │
│                                                                 │
│  2. Compute repo_hash = sha256(repo_id)                         │
│                                                                 │
│  3. Check cache:                                                │
│     if assets/template_cache/<repo_hash>/_cache_meta.json:      │
│       meta = json.load(...)                                     │
│       if meta.ttl_expires_at > now:                             │
│         → USE CACHE (skip network entirely)                     │
│       else:                                                     │
│         → CHECK HF API for new commit_hash                      │
│         if meta.commit_hash == hf_commit_hash:                  │
│           → refresh ttl_expires_at, USE CACHE                   │
│         else:                                                   │
│           → REFETCH (commit_hash changed)                       │
│     else:                                                       │
│       → FETCH FRESH                                             │
│                                                                 │
│  4. Fetch (when needed):                                        │
│     for each filename in [tokenizer_config.json,                │
│                           chat_template.jinja,                  │
│                           generation_config.json,               │
│                           special_tokens_map.json]:             │
│       GET https://huggingface.co/{repo_id}/resolve/main/{file}  │
│       (404 is OK — not all repos ship all 4 files)              │
│       save to cache dir                                         │
│     GET https://huggingface.co/api/models/{repo_id}             │
│       → extract commit_hash, save to _cache_meta.json           │
│       ttl_expires_at = now + 24h                                │
│                                                                 │
│  5. Offline handling:                                           │
│     if HF API unreachable:                                      │
│       if cache exists:                                          │
│         → USE CACHE + log INFO "offline — using stale cache"    │
│       else:                                                     │
│         → SKIP HF cache, rely on GGUF metadata only             │
└─────────────────────────────────────────────────────────────────┘
```

**TTL:** 24 hours default. Configurable via `settings.json::main_settings.template_cache_ttl_hours` (default 24, 0 disables cache).

**`commit_hash` verification:** HF exposes the latest commit hash via `GET https://huggingface.co/api/models/{repo_id}` (returns JSON with `sha` field). Cache is refreshed only when this hash changes — protects against silent model author updates.

### 5.4 Cache invalidation triggers

- TTL expiry (automatic, lazy on next access)
- User clicks "Refresh detection" in Debug tab (T4 trigger, bypasses cache)
- GGUF file mtime change (T2 trigger from new download)
- Manual cache clear: `rm -rf assets/template_cache/` (documented in AGENT_NAVIGATION.md)

### 5.5 Cache size estimate

Each cache entry is ~50KB (4 JSON files, mostly the Jinja template). For a typical user with 5 local models, total cache footprint is ~250KB. Acceptable.

### 5.6 Network failure modes

| Failure | Behavior | User-visible |
|---|---|---|
| HF API unreachable on first fetch (no cache) | Skip HF cache, rely on GGUF metadata | INFO log, no warning |
| HF API unreachable on TTL refresh (cache exists) | Use stale cache indefinitely | INFO log "offline — using stale cache" |
| HF API returns 404 for one of the 4 files | Use partial cache (e.g., tokenizer_config.json only) | DEBUG log |
| HF repo deleted (410 Gone) | Keep cache, log WARNING | WARNING in Debug panel |
| Disk full (cannot write cache) | Operate without cache for this session | ERROR log |

---

## 6. Cloud Provider Path (KI#19)

### 6.1 The cloud detection problem

Cloud providers (OpenAI, Anthropic, DeepSeek, etc.) do not expose their model's chat template — the API is the template. SoW cannot read a Jinja string for `gpt-4o` or `claude-sonnet-5`. The capability map for cloud models must come from a **heuristic table** maintained by SoW.

### 6.2 Heuristic table

```python
# app/utils/ai_clients/cloud_capability_table.py (NEW file in iter-24+ — see §11.0)
# Maintained manually — based on provider docs as of 2026-07-30.
#
# ⚠️ iter-24-doc-cleanup annotation: entries marked "SPECULATIVE" below were drafted
# at iter-15 (2026-07-30) based on provider API patterns, NOT verified against live
# API. Before shipping iter-21 (cloud reasoning plumbing), the implementing agent
# MUST verify each entry against the provider's current API docs and remove or
# correct speculative ones. Common pitfalls:
#   - DeepSeek has no public "v4-pro" model (only deepseek-chat / deepseek-reasoner
#     per 2026-07-30 API docs). The reasoning_family: "B" entry is speculative.
#   - Claude Haiku-5 is not publicly released as of 2026-07-30. The entry is a
#     placeholder based on the Claude 5 family naming pattern.
#   - Grok-4.3 reasoning_family: "A" is based on Grok's o-series-style API;
#     verify the actual reasoning_effort / reasoning_mode parameter name.
#   - Floating aliases (mistral-small-latest, gemini-flash-latest) resolve to
#     different model snapshots over time — the capability may rotate with the
#     alias. Prefer explicit model versions where stable.

CLOUD_CAPABILITIES = {
    # OpenAI
    "gpt-4o": {"reasoning_family": None, "supports_tools": True, "supports_vision": True},
    "gpt-4o-mini": {"reasoning_family": None, "supports_tools": True, "supports_vision": True},
    "o1": {"reasoning_family": "A", "supports_tools": True, "supports_vision": True},
    "o1-mini": {"reasoning_family": "A", "supports_tools": True, "supports_vision": False},
    "o3": {"reasoning_family": "A", "supports_tools": True, "supports_vision": True},
    "o3-mini": {"reasoning_family": "A", "supports_tools": True, "supports_vision": False},
    "o4-mini": {"reasoning_family": "A", "supports_tools": True, "supports_vision": True},

    # Anthropic
    "claude-sonnet-5": {"reasoning_family": "A", "supports_tools": True, "supports_vision": True},
    "claude-opus-5": {"reasoning_family": "A", "supports_tools": True, "supports_vision": True},
    "claude-haiku-5": {"reasoning_family": None, "supports_tools": True, "supports_vision": True},  # SPECULATIVE — not publicly released as of 2026-07-30

    # DeepSeek
    "deepseek-v4-flash": {"reasoning_family": None, "supports_tools": False, "supports_vision": False},
    "deepseek-v4-pro": {"reasoning_family": "B", "supports_tools": False, "supports_vision": False},  # SPECULATIVE — DeepSeek API has deepseek-chat / deepseek-reasoner, no public "v4-pro" as of 2026-07-30
    "deepseek-r1": {"reasoning_family": "C", "supports_tools": False, "supports_vision": False},

    # Qwen
    "qwen-plus": {"reasoning_family": None, "supports_tools": True, "supports_vision": False},
    "qwen3-flash": {"reasoning_family": "B", "supports_tools": True, "supports_vision": False},
    "qwen3-pro": {"reasoning_family": "B", "supports_tools": True, "supports_vision": False},

    # Gemini
    "gemini-3.5-flash": {"reasoning_family": None, "supports_tools": True, "supports_vision": True},
    "gemini-3.5-pro": {"reasoning_family": None, "supports_tools": True, "supports_vision": True},

    # Mistral
    "mistral-small-latest": {"reasoning_family": None, "supports_tools": True, "supports_vision": False},  # floating alias — capability may rotate
    "magistral-medium-latest": {"reasoning_family": "C", "supports_tools": False, "supports_vision": False},

    # Grok
    "grok-4.3": {"reasoning_family": "A", "supports_tools": True, "supports_vision": True},  # verify reasoning parameter name against xAI API docs before shipping

    # Z.AI (ZhipuAI)
    "glm-5": {"reasoning_family": None, "supports_tools": True, "supports_vision": False},
    "glm-5-plus": {"reasoning_family": None, "supports_tools": True, "supports_vision": False},
}
```

The table is keyed by exact model name. For floating aliases (`mistral-small-latest`), the table resolves the alias's current target — manual maintenance required when providers change aliases. SoW logs a WARNING when a model name is not in the table; user can add custom entries via `settings.json::main_settings.cloud_capability_overrides`.

### 6.3 Cloud reasoning plumbing (KI#19 fix)

Today's behavior:
- `reasoning_mode` setting: consumed ONLY by `local_server_manager.py` (Family A `--reasoning-budget 0`). Cloud providers IGNORE it. DeepSeek uses fragile `"pro" in model.lower()` heuristic.
- `enable_thinking` setting (iter-14): consumed ONLY by `local_server_manager.py` (Family B `--chat-template-kwargs`). Cloud providers IGNORE it.

iter-21 fix:

```python
# app/utils/ai_clients/providers/openai_provider.py (extend in iter-21)
class OpenAIProvider(BaseAIProvider):
    async def generate_stream(self, messages, **kwargs):
        # ... existing setup ...
        # NEW: apply reasoning plumbing based on capability table
        caps = get_cloud_capabilities(self.model)
        if caps.reasoning_family == "A":
            # o-series: reasoning_effort parameter
            if "reasoning_mode" in kwargs:
                payload["reasoning_effort"] = "high" if kwargs["reasoning_mode"] else "low"
        elif caps.reasoning_family == "B":
            # Qwen3 via OpenAI-compat: enable_thinking parameter
            if "enable_thinking" in kwargs:
                payload["enable_thinking"] = kwargs["enable_thinking"]
        # Family C (DeepSeek-R1, Magistral) — no toggle, model always reasons,
        # strip_think_blocks() cleans history (iter-10) + post-gen filter (future)
```

Same pattern applied to: `deepseek_provider.py`, `anthropic_provider.py`, `qwen_provider.py`, `gemini_provider.py`. Five provider files modified in iter-21.

### 6.4 Family C post-generation reasoning strip

iter-10 added `strip_think_blocks()` for history replay (KI#9). But for cloud Family C models (DeepSeek-R1 API, Magistral), the model still emits `<think>...</think>` in its response — SoW currently displays this raw. A post-generation filter (similar to `strip_think_blocks()` but applied to the streaming response) is needed. This is **iter-22** (post-iter-21) — out of scope for this plan but documented as the natural follow-up.

---

## 7. UI Diagnostics Panel (KI#17)

### 7.1 Layout

New "Diagnostics" tab in the LLM settings card. Replaces the iter-16 "Debug Mode" checkbox (which moves to the bottom of the new tab). Layout:

```
┌─ Diagnostics ───────────────────────────────────────────────────┐
│                                                                 │
│  ┌─ Detection ─────────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  Model:      Qwen3-8B-Instruct                           │   │
│  │  GGUF path:  D:/models/Qwen3-8B-Q5_K_M.gguf              │   │
│  │  HF repo:    Qwen/Qwen3-8B  [refresh]                    │   │
│  │                                                          │   │
│  │  Detected template:  qwen3-thinking                      │   │
│  │  Source:             embedded (GGUF tokenizer.chat_*)    │   │
│  │  Confidence:         HIGH                                │   │
│  │  Manual override:    Auto (no override)                  │   │
│  │                                                          │   │
│  │  Architecture:       qwen3                               │   │
│  │  Tokenizer model:    gpt2 (BPE)                          │   │
│  │  EOS token ID:       151645                              │   │
│  │  EOS token text:     <|im_end|>                          │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ Capability Map ────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  [✓] enable_thinking       (Family B — Qwen3 toggle)     │   │
│  │  [✓] reasoning_budget      (Family A — not used here)    │   │
│  │  [✓] date_string           (auto-computed per chat)      │   │
│  │  [ ] tools                 (not supported)               │   │
│  │  [ ] system_prompt         (not used)                    │   │
│  │  [✓] add_generation_prompt (standard)                    │   │
│  │                                                          │   │
│  │  Custom vars: thinking, content                          │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ Active Stop Tokens ────────────────────────────────────┐   │
│  │                                                          │   │
│  │  Tokens:  ['<|im_end|>']                                 │   │
│  │  Source:  generation_config.json (HF cache)              │   │
│  │                                                          │   │
│  │  Manual override field:                                  │   │
│  │  [_____________________________________________]          │   │
│  │  (comma-separated; empty = use auto-detected)            │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ Template Preview (read-only) ──────────────────────────┐   │
│  │                                                          │   │
│  │  ┌────────────────────────────────────────────────┐     │   │
│  │  │  {%- for message in messages -%}              │     │   │
│  │  │  {%- if message.role == 'user' -%}            │     │   │
│  │  │  <|im_start|>user                             │     │   │
│  │  │  {{ message.content }}<|im_end|>              │     │   │
│  │  │  {%- elif message.role == 'assistant' -%}     │     │   │
│  │  │  ...                                          │     │   │
│  │  └────────────────────────────────────────────────┘     │   │
│  │                                                          │   │
│  │  [Copy Jinja]  [Save as override]                       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ Sanitization Log (iter-13 helper output) ──────────────┐   │
│  │                                                          │   │
│  │  [2026-07-30 14:23:01] Stripped 3 tokens from character │   │
│  │  card 'Alice': <|im_start|>, <|im_end|>, [/INST]        │   │
│  │  [2026-07-30 14:23:01] Stripped 1 token from lorebook:  │   │
│  │  <｜begin▁of▁sentence｜>                                 │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ Validation ────────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  [✓] All special tokens in template are in vocab        │   │
│  │  [✓] EOS token present in vocab                         │   │
│  │  [✓] No conflicting stop tokens                         │   │
│  │  [!] Template references 'date_string' but app does not │   │
│  │      populate it (Llama 3 only — auto-fix in iter-17)   │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [✓] Debug Mode (verbose logging)                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Lazy rendering

The Diagnostics tab is **lazy** — it does not populate until the user opens it. Rationale: GGUF parsing on app startup would slow first-launch for users who never use the Diagnostics tab. The tab shows a "Click to load" button on first open, then runs the pipeline (with cache).

### 7.3 Live updates

The tab subscribes to settings changes via Qt signals:
- `chat_template` changed → re-run Layer 4 (manual override) → refresh "Manual override" line
- `stop_strings` changed → re-run stop-token resolution → refresh "Active Stop Tokens" block
- `local_llm` changed → re-run full pipeline → refresh "Detection" block
- `reasoning_mode` / `enable_thinking` changed → refresh "Capability Map" checkboxes (no re-detection needed)

### 7.4 Free-form Jinja override (KI#7 fix direction B)

Below the "Template Preview (read-only)" block, an "Advanced" expander reveals:

```
┌─ Free-form Jinja Override ─────────────────────────────────────┐
│                                                                │
│  ⚠️  WARNING: Free-form Jinja is rendered by the backend.       │
│      Sandbox-escape attacks possible if template is untrusted. │
│      Only use templates from sources you trust.                │
│                                                                │
│  [paste Jinja template here...]                                │
│  ...                                                           │
│                                                                │
│  [Apply as override]  [Reset to detected]                      │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

When the user pastes a custom Jinja template and clicks "Apply as override", SoW writes it to a new file `app/data/custom_template.jinja` (gitignored) and passes `--chat-template-file <path>` to llama-server. The capability map is recomputed from the pasted Jinja — UI controls auto-show/hide accordingly. iter-14's hardcoded `_ENABLE_THINKING_TEMPLATES` becomes fully obsolete.

The free-form Jinja override is the **last-resort fallback** the user requested. The combo box remains for the common case ("I know I want Llama-3, just pick it"), the free-form text area handles the exceptional case ("community finetune with broken template, I have the correct Jinja from the author's HF repo").

---

## 8. Template-Variable Pre-Population (KI#13 partial + §9)

### 8.1 Variables SoW should populate

| Variable | Source | Population | iter-15 plan |
|---|---|---|---|
| `messages` | PromptEngine `final_history` | Always — already populated by `/v1/chat/completions` contract | unchanged |
| `add_generation_prompt` | Constant `True` | Always — passed by llama-server automatically | unchanged |
| `tools` | (future — tool calling) | None today | deferred |
| `enable_thinking` | `settings.enable_thinking` (iter-14) | Family B models only, via `--chat-template-kwargs` | iter-14 done; iter-19 makes it capability-driven |
| `reasoning_budget` | `settings.reasoning_mode` (boolean) | Family A models only, via `--reasoning-budget` | iter-14 done; iter-19 makes it capability-driven |
| `date_string` | `chat.created_at` | Per chat session, computed once | **NEW iter-17** |
| `system_prompt` | (future — explicit system_prompt var) | None today | deferred |

### 8.2 `date_string` computation (iter-9 contradiction #6 resolution)

```python
# app/utils/ai_clients/local_server_manager.py (extend in iter-17)
from datetime import datetime

def _compute_date_string(chat_created_at: float) -> str:
    """Per §7.2 + iter-9 contradiction #6: fixed per chat session."""
    dt = datetime.fromtimestamp(chat_created_at)
    return dt.strftime("%Y-%m-%d")  # Llama 3 expected format

# In _build_command_list() or equivalent:
if detection.capability_map.date_string:
    chat_created_at = self._get_current_chat_created_at()  # from chat metadata
    kwargs_payload["date_string"] = _compute_date_string(chat_created_at)
```

`chat.created_at` is already stored in SoW at `interface_signals.py:3357, 11863`. No schema change needed. The value is **immutable per chat** — derived once at chat creation, reused for every turn of that chat. This satisfies the iter-9 resolution: "fix per chat session, not per app session, not per request."

### 8.3 KV-cache impact (KI#13 partial mitigation)

iter-3 audit noted that SoW's high-volatility system blocks (Soul Memory, lorebook activation, state tracking) make KV-cache prefix reuse mostly useless. The `date_string` variable, when *not* populated, causes additional cache invalidation: llama-server sees a different prompt every turn (because Llama 3's template injects today's date).

By fixing `date_string` per chat session, we eliminate one source of per-turn prefix volatility. The other sources (Soul Memory updates, lorebook activation) are core SoW features — accepted trade-off, documented in `AGENT_NAVIGATION.md` §6.

This is a **partial** KI#13 fix — the deeper KV-cache restructure (moving high-volatility blocks to the end of the prompt) remains deferred per iter-3 audit recommendation.

---

## 9. Tokenizer Vocab Validation (KI#12)

### 9.1 When to validate

Only when the HF cache is available (which includes `tokenizer_config.json` — the `added_tokens_decoder` field lists every special token the tokenizer recognizes). Without the cache, validation is skipped (GGUF metadata alone does not include the full vocab map).

### 9.2 Validation algorithm

```python
def validate_template_against_vocab(
    jinja_source: str,
    tokenizer_config: dict,
) -> list[str]:
    """
    Returns list of validation errors. Empty list = OK.
    """
    errors = []
    # 1. Extract special token strings from Jinja (regex)
    import re
    # Match <|token|>, [TOKEN], <token> patterns
    token_pattern = re.compile(r'<\|[^>]+\|>|\[[A-Z_]+\]|<[a-z_]+>')
    referenced_tokens = set(token_pattern.findall(jinja_source))
    # 2. Get vocab tokens from tokenizer_config.added_tokens_decoder
    vocab_tokens = set()
    for token_info in tokenizer_config.get("added_tokens_decoder", {}).values():
        vocab_tokens.add(token_info["content"])
    # 3. Check each referenced token is in vocab
    for tok in referenced_tokens:
        if tok not in vocab_tokens:
            errors.append(f"Template references '{tok}' but tokenizer vocab does not contain it")
    return errors
```

### 9.3 User-visible result

Validation runs after Layer 1 (embedded template read). Errors populate `DetectionResult.validation_errors` and surface in the Debug panel "Validation" block:

```
[!] Template references '<|custom_eot|>' but tokenizer vocab does not contain it
    This is common with community finetunes that ship a stale template.
    Recommended: select a manual override from the combo box, or paste the
    author's correct Jinja in the Free-form Override area.
```

This is exactly the "author-error vocab validation" use case from strategy §13, addressing KI#12.

### 9.4 Byte-level DeepSeek fullwidth-pipe handling

Per strategy §21, DeepSeek tokens use fullwidth pipe `｜` (U+FF5C) instead of ASCII `|`. The validation must use byte-level comparison, not Unicode string comparison. The `sanitize_special_tokens()` helper (iter-13) already handles this for content sanitization; the validation logic in iter-20 reuses the same byte-level comparison.

---

## 10. Integration with Existing Iterations

### 10.1 What stays unchanged

- **iter-10 `strip_think_blocks()`** — Family C history stripping. Continues to run, unchanged. Detection result informs *when* it runs (only when capability map says Family C).
- **iter-11 `enforce_role_alternation()`** — Anthropic alternation. Independent of template detection. Unchanged.
- **iter-13 `sanitize_special_tokens()`** — Structural-token sanitization. Continues to run. The 26-entry token list is **static** — the detection result does not change it. Future iteration could make the list dynamic based on detected template's special tokens, but that is out of scope.
- **iter-14 `enable_thinking` wiring** — The `--chat-template-kwargs` mechanism. Unchanged. Only the **visibility logic** changes (iter-19): the hardcoded `_ENABLE_THINKING_TEMPLATES` set is replaced by `detection.capability_map.enable_thinking`.
- **iter-16 logging redesign** — `log_template_validation()`, `log_runtime_context_delta()`, etc. Unchanged. The new detection result feeds into `log_template_validation()` as a richer input.

### 10.2 What gets replaced

- **iter-14 `_ENABLE_THINKING_TEMPLATES` hardcoded set** (`interface_signals.py` ~55 lines) → **REMOVED** in iter-19. Replaced by `detection.capability_map.enable_thinking`. The visibility logic becomes a one-liner.
- **`comboBox_chat_template` semantics** — today: primary control. iter-15: labeled "Manual override (auto-detected: ...)". When set to "Auto", pipeline runs fully automatic. When set to a specific name, it overrides the auto-detected result (with warning if different).
- **`lineEdit_stop_strings` semantics** — today: orphan (KI#7). iter-15: labeled "Stop token override (auto-detected: ...)". When empty, auto-detected tokens are used. When non-empty, overrides (with warning if different from auto-detected).

### 10.3 Backward compatibility

- `settings.json` schema: only additions, no removals. New keys: `template_cache_ttl_hours`, `cloud_capability_overrides`, `custom_template_path`. Existing keys (`chat_template`, `stop_strings`, `enable_thinking`, `reasoning_mode`) unchanged in name and meaning.
- Pre-iter-15 configs load without migration. Default behavior: `chat_template: "Auto"` triggers full pipeline (was: pass-through to llama-server); `stop_strings: "<|im_end|>"` is now consumed as override (was: orphan).
- The `_ENABLE_THINKING_TEMPLATES` removal in iter-19 is safe — the visibility logic now keys off the live capability map, which is computed from the actual template. A user who had `chat_template: "Qwen3-Thinking"` saved will see the same `enable_thinking` checkbox visibility as before, because the Qwen3-Thinking template's Jinja contains `enable_thinking` variable.

---

## 11. Implementation Roadmap

### 11.0 Numbering collision note (iter-24-doc-cleanup addendum)

> ⚠️ **iter-16..iter-21 in §11 below = VIRTUAL sub-iterations of the iter-15 plan, NOT real shipped iterations.** The iter-15 plan was authored 2026-07-30 when iter-15 was the latest research iteration. Subsequently, real shipped iterations used the iter-16..iter-21 numbers for **completely different work** (logging redesign, f-string fix, mlock/flash_attn delta, audit cleanup). When implementing this plan, use iter-24+ numbering per the mapping table below.

**Mapping table — plan sub-iteration → real iteration number to use:**

| Plan §11 sub-iteration | Plan's "iter" label | Real iter number to use when implementing | Notes |
|---|---|---|---|
| 1 | iter-16 (GGUF reader + HF cache) | iter-24 (or next available) | Foundation layer. No KI closed. |
| 2 | iter-17 (pipeline integration) | iter-25 | `date_string` per-chat (KI#13 partial). |
| 3 | iter-18 (stop-token chain) | iter-26 | **Tiers 2–4 only** — tier 1 (settings.json `stop_strings` → LocalProvider API `stop`) already closed iter-22. |
| 4 | iter-19 (capability-aware UI) | iter-27 | Replaces iter-14 `_ENABLE_THINKING_TEMPLATES` hardcoded set. |
| 5 | iter-20 (vocab validation + UI diagnostics) | iter-28 | Closes KI#12 + KI#17. |
| 6 | iter-21 (cloud reasoning plumbing) | iter-29 | Closes KI#19. Verify §6.2 speculative entries before shipping. |
| optional | iter-22 (Family C post-gen strip) | iter-30 (optional) | Listed for completeness; not in plan scope. Note: real iter-22 = stop_strings wiring (KI#7 tier 1 closed). |

**Real iter-16..iter-23 reference (do NOT confuse with plan sub-iterations):**

| Real iter | What it actually was | Closed KIs |
|---|---|---|
| iter-16 (minimal + plan-review + impl + smoke-test) | Logging redesign plan + implementation + user validation | KI#22, KI#20 partial, KI#21 partial |
| iter-17 | Logging polish (7-step) | KI#24–KI#30 |
| iter-18 | f-string SyntaxError fix | KI#31 |
| iter-19 (log-analysis + impl) | Production log audit + final logging fixes | KI#32, KI#33 |
| iter-20-delta | mlock/flash_attn RUNTIME CONTEXT DELTA + LocalProvider timeout + SESSION CONTEXT resilience | KI#34, KI#35 |
| iter-21-audit-cleanup | Stale doc + orphan asset removal (commit message aspirational; iter-23 closed the gap) | (no KI closed in iter-21 itself; KI#36 raised) |
| iter-22 | stop_strings wiring into LocalProvider (KI#7 tier 1) | KI#7 (partial — tier 1 only) |
| iter-23 | `git rm` 13 orphaned paths iter-21 claimed but did not delete | KI#36 |

---

Six sub-iterations. Each respects the 3–5 file soft limit. Each is independently shippable (no broken intermediate states). Order is by dependency — earlier iterations are prerequisites for later ones.

### iter-16: GGUF metadata reader + HF cache (foundation)

**Goal:** infrastructure layer — read GGUF metadata, fetch/cache HF source files. No UI changes, no behavior changes. Detection result is computed but not yet consumed.

**Files (4):**
1. `app/utils/ai_clients/template_detector.py` (NEW, ~400 lines) — `read_gguf_metadata()`, `compute_capability_map()`, `detect_template()` pipeline (Layers 0–3 only — Layer 4 manual override is existing logic).
2. `app/utils/ai_clients/hf_template_cache.py` (NEW, ~250 lines) — §8.5 cache logic: fetch, store, TTL, commit_hash verification, offline fallback.
3. `requirements.txt` — add `gguf>=0.10.0`.
4. `app/configuration/settings.json` — add `main_settings.template_cache_ttl_hours: 24`, `main_settings.cloud_capability_overrides: {}`.

**Smoke test:** `python -c "from app.utils.ai_clients.template_detector import detect_template; print(detect_template('test.gguf'))"` for 5 representative GGUFs (Qwen3, Llama-3, Mistral-v7-Tekken, Gemma3, DeepSeek-R1). Verify detection source, capability map, stop tokens.

**KI progress:** no KI closed. Foundation for iter-17 through iter-21.

### iter-17: Pipeline integration into local_server_manager

**Goal:** wire detection result into `local_server_manager.py`. Pass `--chat-template-kwargs` for `date_string` (when supported). Compute `date_string` from `chat.created_at`. Pass auto-detected template name when user has "Auto" selected (currently we pass nothing — relies on llama-server's internal Layer 1, which is correct but loses the capability map).

**Files (4):**
1. `app/utils/ai_clients/local_server_manager.py` — extend `_build_command_list()` to accept `DetectionResult`, pass `--chat-template <detected_name>` when user has "Auto" (instead of nothing), pass `--chat-template-kwargs` with `date_string` when capability map says supported.
2. `app/utils/ai_clients/template_detector.py` (extend) — add `detect_template_for_chat()` that takes `chat_created_at` parameter.
3. `app/gui/interface_signals.py` — when chat is created/loaded, trigger detection (T3 trigger point). Pass result to `LocalServerManager`.
4. `app/utils/prompt_engine.py` — minor: expose `chat_created_at` from chat metadata (already stored, just needs accessor).

**Smoke test:** load Qwen3-8B, create new chat, verify `--chat-template qwen3-thinking --chat-template-kwargs '{"enable_thinking": false, "date_string": "2026-07-30"}'` is passed to llama-server. Verify Llama-3 model gets `date_string` kwarg but not `enable_thinking`.

**KI progress:** KI#13 partial fix (date_string per-chat-session). KI#20 partial (already iter-16-minimal closed most of it — this finishes by passing capability-aware kwargs).

### iter-18: Stop-token resolution chain (KI#7 — tier 1 closed iter-22, tiers 2–4 pending)

> ⚠️ **iter-24-doc-cleanup annotation.** KI#7's tier 1 (settings.json `stop_strings` → LocalProvider API `stop` parameter via `parse_stop_strings()` helper in `local_provider.py`) was **closed in iter-22** (real iteration). This plan sub-iteration now covers **tiers 2–4 only**:
> - Tier 2: `generation_config.json` `eos_token` from HF cache
> - Tier 3: GGUF metadata `tokenizer.ggml.eos_token_id`
> - Tier 4: template-implied defaults (`chatml = <|im_end|>`, etc.)
>
> The architecture deviation noted in iter-22 worklog — LocalProvider API `stop` parameter implemented, llama-server `--stop` CLI flag skipped as redundant in API mode — affects this sub-iteration's file list: item 1 (`local_server_manager.py` `--stop` flag) is **no longer required**. Items 2–4 may also need adjustment since `local_provider.py` and `interface_signals.py` already have the iter-22 wiring in place.

**Goal:** implement tiers 2–4 of the stop-token resolution chain. Tier 1 (manual override from `settings.stop_strings`) already wired in iter-22. Tiers 2–4 require the §8.5 HF cache (sub-iteration 1) to fetch `generation_config.json`. When all 4 tiers are in place, the Debug panel can show "Active stop tokens: ['<|im_end|>'] Source: generation_config.json" or "Source: GGUF metadata" or "Source: manual override".

**Files (3 — reduced from 4 after iter-22):**
1. `app/utils/ai_clients/local_provider.py` — extend `__init__` to accept a `stop_tokens_resolved: list[str]` parameter (in addition to the iter-22 `stop_strings: str` parameter). When `kwargs["stop"]` is not provided AND `self.stop_list` (from iter-22 tier 1) is empty, fall back to `self.stop_tokens_resolved` (from tiers 2–4). 4-tier precedence: caller kwarg > manual override (tier 1) > generation_config (tier 2) > GGUF (tier 3) > template-implied default (tier 4) > no stop field.
2. `app/gui/interface_signals.py` — update `lineEdit_stop_strings` save handler to mark setting as "override" (tooltip: "Empty = use auto-detected stop tokens from generation_config.json or GGUF metadata").
3. `app/gui/sowInterface.py` — update `lineEdit_stop_strings` placeholder text to show auto-detected tokens (refreshed when detection pipeline runs).

**Smoke test:** verify LocalProvider sends `stop=['<|im_end|>']` when auto-detected from `generation_config.json`. Verify GGUF-only fallback (no HF cache) reads `tokenizer.ggml.eos_token_id` and resolves to the correct token text via the cached tokenizer vocab. Verify user override (`stop_strings="User:,</s>"`) overrides auto-detected (iter-22 tier 1 contract preserved). Verify cloud providers still send no stop (iter-7 fix preserved).

**KI progress:** KI#7 FULLY CLOSED (tier 1 closed iter-22; tiers 2–4 closed in this sub-iteration). KI#12 partial (vocab validation still pending sub-iteration 5).

### iter-19: Capability-aware UI (replaces iter-14 hardcoded set)

**Goal:** replace `_ENABLE_THINKING_TEMPLATES` with `detection.capability_map`. Add `checkBox_reasoning_mode` visibility logic for Family A models (today it's always visible — incorrect for non-Family-A models). Generalize the auto-hide/show pattern.

**Files (3):**
1. `app/gui/interface_signals.py` — replace `_ENABLE_THINKING_TEMPLATES` block (55 lines) with `update_capability_aware_visibility(detection)` method (~20 lines). Subscribe to `detection_changed` signal.
2. `app/gui/sowInterface.py` — combo box label changes dynamically: "Manual override (auto-detected: ...)" when override differs from auto.
3. `app/translations/ru.yaml` + `en.yaml` — new i18n keys for "Manual override (auto-detected: %s)" and "auto-detected differs from manual override" warning.

**Smoke test:** load Qwen3 → `enable_thinking` checkbox visible, `reasoning_mode` checkbox hidden (Qwen3 is Family B not A). Load gpt-oss model → both checkboxes hidden (gpt-oss uses `--reasoning-budget` not `--chat-template-kwargs`; iter-14 made `reasoning_mode` always visible — iter-19 fixes this). Load Llama-3 model → both hidden.

**KI progress:** no KI closed, but unblocks the iter-14 stopgap removal. QI: this is the "clean and qualitative" cleanup the user requested.

### iter-20: Tokenizer vocab validation + UI diagnostics panel

**Goal:** implement KI#12 (vocab validation) and KI#17 (UI diagnostics panel). Both ship together because they share the same UI surface.

**Files (5):**
1. `app/utils/ai_clients/template_detector.py` (extend) — `validate_template_against_vocab()` function (algorithm in §9.2).
2. `app/gui/sowInterface.py` — new "Diagnostics" tab in LLM settings card (layout in §7.1). Lazy-loaded.
3. `app/gui/interface_signals.py` — wire Diagnostics tab to `detection_changed` signal. Implement live updates.
4. `app/gui/diagnostics_panel.py` (NEW, ~300 lines) — `DiagnosticsPanel(QWidget)` class. Renders the layout in §7.1. Subscribes to detection changes.
5. `app/translations/ru.yaml` + `en.yaml` — i18n keys for Diagnostics tab labels.

**Smoke test:** load Qwen3 → Diagnostics tab shows detected template, capability map, stop tokens, template preview. Load community finetune with broken template → validation errors appear in red. Test free-form Jinja override (paste Qwen3 Jinja, click Apply, verify capability map recomputes).

**KI progress:** KI#12 CLOSED (vocab validation). KI#17 CLOSED (UI diagnostics). KI#7 fully closed (Free-form Override area in Diagnostics tab completes the override control).

### iter-21: Cloud provider reasoning plumbing (KI#19 closed)

**Goal:** extend capability table to cloud providers. Wire `reasoning_mode` and `enable_thinking` into cloud provider API calls based on heuristic table.

**Files (5):**
1. `app/utils/ai_clients/cloud_capability_table.py` (NEW, ~150 lines) — `CLOUD_CAPABILITIES` dict (§6.2) + `get_cloud_capabilities(model)` function.
2. `app/utils/ai_clients/providers/openai_provider.py` — apply reasoning plumbing based on capability table.
3. `app/utils/ai_clients/providers/deepseek_provider.py` — replace `"pro" in model.lower()` heuristic with capability table lookup.
4. `app/utils/ai_clients/providers/anthropic_provider.py` — apply reasoning_effort parameter for Claude o-series.
5. `app/utils/ai_clients/providers/qwen_provider.py` — apply `enable_thinking` parameter for Qwen3 via DashScope API.

**Smoke test:** for each cloud provider, verify reasoning controls actually affect API call. (DeepSeek: `reasoning_mode=False` → no reasoning. OpenAI o3: `reasoning_mode=False` → `reasoning_effort=low`. Claude Sonnet 5: similar. Qwen3: `enable_thinking=False` → parameter sent.)

**KI progress:** KI#19 CLOSED. All 7 remaining strategy-level KIs closed.

### Optional iter-22: Family C post-generation reasoning strip (cloud)

**Goal:** for cloud Family C models (DeepSeek-R1 API, Magistral), strip `<think>...</think>` from streaming response. iter-10 already strips from history; this extends to live display.

**Files (2):**
1. `app/utils/ai_clients/providers/deepseek_provider.py` — apply `strip_think_blocks()` to streaming chunks before yielding.
2. `app/utils/ai_clients/providers/mistral_provider.py` — same for Magistral.

**Out of scope for iter-15 plan** — listed for completeness.

---

## 12. Risk Analysis and Open Questions

### 12.1 Risks

| Risk | Severity | Mitigation |
|---|---|---|
| `gguf` Python library not maintained | LOW | Official ggml-org repo, last release 2026-06. If abandoned, fallback to `/props` API only (Layer 0) — lose Layer 1b. |
| HF API rate limits | LOW | 24h TTL means at most 1 fetch per model per day. Well within HF's unauthenticated rate limit (60 req/min). |
| HF API goes down | LOW | Offline fallback designed in §5.6. Cache persists indefinitely when offline. |
| GGUF parsing crashes on malformed file | MED | All `read_gguf_metadata()` calls wrapped in try/except. On crash, log WARNING, fall through to Layer 2 with `arch=None` (Layer 2 fails too, Layer 3 ChatML fallback fires). |
| Detection pipeline slow on first load | LOW | 50–200ms per GGUF. Cached after first run. Lazy Diagnostics tab means UI never blocks. |
| Cloud capability table stale (provider adds new model) | MED | WARNING logged when model not in table. User can add override via settings.json. Table updated quarterly. |
| Free-form Jinja override security (SSTI) | MED | Backend (llama-server) renders, not SoW. Sandbox-escape risk lives in llama-server, not in SoW. SoW only stores + passes the Jinja string. Strategy §6 (sandboxed Jinja) stays deferred — SoW never renders Jinja client-side. |
| `date_string` per-chat breaks existing chats | LOW | Existing chats have `created_at` already stored. Migration: compute `date_string` on first access after iter-17, cache in chat metadata. No data loss. |

### 12.2 Open questions for user

1. **`general.source.huggingface.repository` field availability.** Not all GGUFs include this. Should SoW prompt the user to enter the HF repo manually when missing, or silently skip HF cache and rely on GGUF-only? **Recommendation:** silent skip with INFO log; user can manually enter repo in Diagnostics tab "Refresh" button.

2. **Cloud capability table maintenance.** Should this be a static Python dict (manual updates per SoW release) or a YAML file shipped separately (users can update without code change)? **Recommendation:** Python dict in iter-21 for simplicity; promote to YAML in a later iteration if maintenance burden grows.

3. **Diagnostics tab default visibility.** Should it be visible by default, or hidden behind an "Advanced" toggle? **Recommendation:** visible by default — transparency helps users understand why their model misbehaves. The tab is lazy-loaded so no perf cost until opened.

4. **Free-form Jinja override persistence.** Should the pasted Jinja be saved to `app/data/custom_template.jinja` (per-app, single override) or stored per-model (different override for Qwen3 vs Llama-3)? **Recommendation:** per-app single override in iter-20; promote to per-model if users request it.

---

## 13. Verification Matrix

For each KI, the test case that proves it closed:

| KI | Test case | Expected result | Sub-iter |
|---|---|---|---|
| KI#7 (tier 1) | User enters `stop_strings="User:"`, sends to LocalProvider | LocalProvider API call includes `stop=["User:"]` | ✅ CLOSED iter-22 (real) |
| KI#7 (tiers 2–4) | Load Qwen3 model with HF cache available, send to LocalProvider with empty `stop_strings` | LocalProvider API call includes `stop=["<|im_end|>"]` auto-detected from `generation_config.json` (tier 2); GGUF fallback (tier 3) works when HF cache unavailable; ChatML fallback (tier 4) works when GGUF lacks `eos_token_id` | sub-iter 3 (real iter-26) |
| KI#12 | Load community finetune with broken template (`<|custom_eot|>` not in vocab) | Diagnostics panel shows validation error; combo box highlights manual override | sub-iter 5 (real iter-28) |
| KI#13 (partial) | Load Llama-3 model, create chat, send 3 messages | `date_string` is identical across all 3 turns (per-chat-session, not per-request) | sub-iter 2 (real iter-25) |
| KI#17 | Open Diagnostics tab | All 6 blocks populate (Detection, Capability Map, Stop Tokens, Template Preview, Sanitization Log, Validation) | sub-iter 5 (real iter-28) |
| KI#19 | Set `reasoning_mode=False`, send to OpenAI o3 | API payload includes `reasoning_effort=low`; same for DeepSeek-reasoner → no reasoning emitted | sub-iter 6 (real iter-29) |
| KI#20 (full close) | Open Diagnostics tab, change `chat_template` combo | "Manual override (auto-detected: ...)" label updates; runtime context delta logged | sub-iter 4 (real iter-27) |
| KI#21 (full close) | All print() statements in `app/` | grep returns 0 matches outside `__main__` blocks | ✅ CLOSED iter-16-minimal + iter-5b (verified in iter-19-log-analysis) |

---

## 14. References

- `docs/CHAT_TEMPLATE_STRATEGY_AUDIT.md` §2 (KI#6–KI#17 inventory), §7 (active KI summary — ⚠️ snapshot iter-9, see §8.7 catch-up addendum for current KI status), §8.5 (HF cache design), §8.6 (iter-9 contradictions resolved), §8.7 (iter-24 catch-up — 9 of 12 strategy-level KIs closed).
- `docs/chat-template-strategy.md` §3 (4-layer detection pipeline), §6 (sandboxed Jinja — deferred), §7 (KV-cache prefix stability), §8.5 (HF source-of-truth cache), §11.3 (reasoning-tag scope exclusion), §12 (UI/UX requirements — 9 items including #9 capability-aware UI), §13 (vocab validation), §17 (reasoning mode handling — 3 families), §20 (llama.cpp runtime flags), §21 (DeepSeek byte-level tokens).
- `STATUS.md` — canonical KI registry. iter-22 done state (KI#7 tier 1 closed), iter-23 done state (KI#36 closed), 6 active KIs.
- `AGENT_NAVIGATION.md` §6 (17 known pitfalls — detection pipeline extends these).
- iter-14 worklog block — `_ENABLE_THINKING_TEMPLATES` hardcoded set, capability-aware UI auto-hide pattern. iter-15 plan generalizes this pattern.
- iter-22 worklog block — `parse_stop_strings()` helper + 3-tier stop resolution (tier 1 of this plan's 4-tier chain).

---

## 15. Summary — what the user gets

After sub-iterations 1–6 ship (using real iter-24..iter-29 numbering per §11.0):

1. **User loads a local model.** SoW reads the GGUF, fetches the HF cache (or uses stale/offline fallback), parses the embedded Jinja, computes the capability map. The combo box label updates: "Manual override (auto-detected: Qwen3-Thinking)". The `enable_thinking` checkbox shows because the template references that variable. The `reasoning_mode` checkbox hides because the template does not reference `reasoning_budget`. The Diagnostics tab populates with the resolved template, stop tokens, capability map, validation status.

2. **User sends a message.** SoW passes `--chat-template qwen3-thinking --chat-template-kwargs '{"enable_thinking": false, "date_string": "2026-07-30"}' --stop <|im_end|>` to llama-server. The stop token came from `generation_config.json` (HF cache). The `date_string` came from `chat.created_at`. The kwargs came from the capability map. No hardcoded anything.

3. **User switches to a different model.** Pipeline re-runs (T2 trigger). Combo box label updates. Checkboxes auto-show/hide. Stop tokens re-resolve. Diagnostics tab refreshes.

4. **User encounters a broken community finetune.** Diagnostics tab shows validation error: "Template references `<|custom_eot|>` but tokenizer vocab does not contain it." Combo box shows warning banner. User pastes the correct Jinja from the author's HF repo into the Free-form Override area. SoW writes it to `app/data/custom_template.jinja`, passes `--chat-template-file` to llama-server. Capability map recomputes from the pasted Jinja. Working.

5. **User uses a cloud provider.** Cloud capability table looks up the model. `reasoning_mode` and `enable_thinking` checkboxes map to the correct API parameter for that provider. DeepSeek-pro stops using the fragile `"pro" in model.lower()` heuristic — uses the table instead. OpenAI o3 gets `reasoning_effort=low/high`. Claude gets the right parameter. All driven by one maintained table.

6. **User picks "Auto" in the combo box.** Pipeline runs end-to-end. Combo box label shows just "Auto (detected: Qwen3-Thinking)". The manual controls are available but not required. This is the "maximally automated" state the user requested. The combo box and stop-strings field become fallback controls for the exceptional cases where auto-detection is wrong or the user wants explicit control.

7. **User opens Diagnostics tab.** Sees everything: detection source, confidence, capability map, stop tokens with source, Jinja preview (read-only), sanitization log (iter-13 helper output), validation status. Can copy the Jinja for sharing, can paste a corrected Jinja for override, can refresh detection, can clear the HF cache. No more "I have no idea what template is being used" — full transparency.

The 6 remaining strategy-level KIs (#7 partial — tiers 2–4 only, #12, #13 partial, #17, #19, #20 partial, #21 partial) all close as a coherent system, not as disconnected patches. **KI#7 tier 1 already closed iter-22** — manual override from `settings.stop_strings` is wired into LocalProvider. The iter-14 stopgap (`_ENABLE_THINKING_TEMPLATES` hardcoded set) is removed. The architecture is ready for new models without code changes — when Llama 5 / Qwen 4 / Mistral Nemo 3 ship, they already carry `chat_template` in their metadata; SoW reads it, computes the capability map, surfaces the right controls. The only ongoing maintenance is the cloud capability table (sub-iteration 6, real iter-29), and that's a documentation problem, not a code problem.
