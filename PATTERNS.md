# PATTERNS.md — Soul of Waifu

> **Purpose**: A living registry of recurring patterns, anti-patterns, and known
> issues (KIs) — solved AND open. Created in **iter-91** to break the "going in
> circles" dynamic the user reported: iterations 66–90 kept fixing template
> *detection* issues but the actual model *behavior* problems persisted.
>
> **How to use**:
> 1. Before starting a new iteration, scan §1 (Anti-Patterns) to avoid stepping
>    on the same rake twice.
> 2. Before adding a new AI provider / model template, scan §3 (Decision Tree).
> 3. When investigating a bug, scan §4 (Open KIs) — the bug may already be
>    tracked.
> 4. When closing a KI, move it from §4 to §5 and add a one-line lesson learned
>    to §2.
>
> **Maintenance rule**: append-only within an iteration. Edit existing entries
> only to correct factual errors or add cross-references. Never delete —
> historical context prevents regression.
>
> **Cross-refs**: STATUS.md has full per-KI root-cause + fix tables;
> worklog.md has per-iteration work logs; AGENT_NAVIGATION.md has repo structure.
>
> **Alias note (iter-92)**: External LLM analyses proposed creating
> `docs/LLM_FAILURE_PATTERNS.md`. That file is **NOT** created — this file
> (`PATTERNS.md`, root) already serves that purpose (created iter-91).
> §8 (Consolidated LLM Failure Pattern Categories) + §9 (Resolved
> Contradictions) added in iter-92 consolidate the external analyses into
> this single registry.

---

## §1. Anti-Patterns (the "rakes" we keep stepping on)

These are recurring failure modes observed across iterations 22–90. Each
anti-pattern has a **symptom**, **root cause**, and **prevention rule**.

### AP-1. Detection without consumption

**Symptom**: The detection pipeline computes rich metadata
(`capability_map`, `eos_drift`, `stop_tokens`, `validation_errors`) that
nobody reads. Bugs recur because the data needed to prevent them was *already
computed* but never wired into the generation path.

**Root cause**: Detection (iter-51 → iter-89) and generation (iter-80 v2 KI#60)
were developed as separate pipelines. `ai_factory.py` extracted only
`stop_tokens` from `DetectionResult`, ignoring `capability_map` and `eos_drift`.

**Observed in**: iter-66 → iter-89 (template detector refinements had no
effect on actual model behavior). First broken by iter-90 (KI#74), which
wired `enable_thinking` + `eos_drift` into `_build_extra_body()`.

**Prevention rule**: Every new field added to `DetectionResult` MUST have a
consumer in the generation path (`ai_factory.py`, `local_provider.py`, or
`local_server_manager.py`) within the SAME iteration. Detection without
consumption is dead code.

---

### AP-2. Partial gating (fix one layer, miss its sibling)

**Symptom**: A parameter is correctly gated on capability, but a sibling
parameter that controls the same behavior is left ungated. The fix appears to
work in smoke tests but fails in production because the ungated sibling
re-enables the broken behavior.

**Root cause**: The reasoning pipeline has THREE layers that each need
gating:
1. **Server flag**: `--reasoning on/off` (in `local_server_manager.py`)
2. **Per-request budget**: `reasoning_budget_tokens` (in `local_provider.py:_build_extra_body()`)
3. **Per-request message**: `reasoning_budget_message` (opt-in, same site as #2)

iter-90 (KI#74) gated layer #2 on `enable_thinking` + `eos_drift`, but left
layer #1 ungated. Result: `--reasoning on` is still sent to llama-server for
models that can't think (Llama-3) or can't stop (Qwen3.5-abliterated), causing
the server to enter reasoning-parse mode regardless of the per-request budget
skip.

**Observed in**: iter-90 verification log (`sow_2026-08-01_17-32-17.log`):
- Qwen3.5-abliterated: 1000 reasoning chunks, 0 text chunks, empty response
  (server enabled thinking, no budget cap, model thought forever)
- Llama-3: subtle tokenization artifacts (server enabled thinking for a
  non-thinking model + KI#72 pre-tokenizer missing compounds the issue)

**Prevention rule**: When gating a parameter on capability, audit ALL layers
that control the same behavior. Document each layer's gating status in the
KI's "Compatibility" field. A gating fix that leaves any sibling ungated is
incomplete — open a follow-up KI in the same iteration.

---

### AP-3. Order-of-operations (detection runs after the decision that needs it)

**Symptom**: The detection pipeline runs AFTER the code that needs its data.
The decision falls back to defaults, and the detection result is only used for
logging/diagnostics — not for the actual behavior it was meant to control.

**Root cause**: In `local_server_manager.py:start_server_async()`:
- Line 340: `reasoning_mode = ...` (read from settings)
- Line 375–428: `--reasoning on/off` decision (NO detection data!)
- Line 485–494: `detection = detect_template(model_path)` (runs too late)

The `--reasoning on/off` flag is decided BEFORE `detect_template()` runs, so
even if we wanted to gate it on `enable_thinking` / `eos_drift`, the data
isn't available at the decision point.

**Observed in**: every iteration that tried to make `--reasoning on/off`
model-aware but couldn't because of the ordering. Currently blocking KI#75
(the natural successor to KI#74).

**Prevention rule**: When adding a consumer for `DetectionResult`, trace the
call order in `start_server_async()`. If the consumer runs before
`detect_template()`, either (a) move the consumer after detection, or (b)
move detection earlier and deduplicate. Never assume detection data is
available — verify the call order.

---

### AP-4. Warning without action

**Symptom**: A defect is detected and logged as a WARNING, but no behavioral
change follows. The user sees the warning in logs but the app continues with
the broken behavior. The warning becomes noise, not signal.

**Root cause**: iter-89 (KI#69) added `eos_drift` detection as a WARNING only
— `stop_tokens` were left unchanged (template_implied), and `reasoning_mode`
was left unchanged. The warning was deferred to "iter-90 KI#70" for the
actual behavioral fix. iter-90 (KI#74) closed part of the gap (gated
`reasoning_budget_tokens`), but `--reasoning on/off` and `stop_tokens` are
still untouched.

**Observed in**: KI#69 (eos_drift warning), KI#72 (pre-tokenizer warning),
KI#71 (reasoning false-positive detection — not yet implemented).

**Prevention rule**: A WARNING without a corresponding behavioral mitigation
is a half-fix. When adding a WARNING, open a KI for the behavioral fix in the
SAME iteration and defer it explicitly with a target iteration. Never leave a
WARNING as the final state — it's a TODO, not a resolution.

---

### AP-5. Assumption without verification ("reasoning_mode=True means the model can think")

**Symptom**: The app assumes that if the user enabled `reasoning_mode`, the
loaded model supports thinking. Non-thinking models (Llama-3, Mistral, plain
Gemma) receive thinking-related parameters that have no meaning, causing
undefined server behavior.

**Root cause**: `reasoning_mode` is a USER setting (checkbox in LLM Settings).
`enable_thinking` is a MODEL capability (computed from the Jinja template).
The two were conflated — `reasoning_mode=True` was treated as "this model can
think", which is false for ~40% of the models in the user's library.

**Observed in**: iter-80 v2 (KI#60) — `reasoning_budget_tokens` injected
whenever `reasoning_mode=True`, regardless of model capability. Fixed in
iter-90 (KI#74) for the per-request budget. NOT yet fixed for the server flag
(KI#75).

**Prevention rule**: Never conflate user settings with model capabilities.
User settings express INTENT ("I want reasoning"); model capabilities express
SUPPORT ("this model can reason"). The generation path must AND-gate them:
`actual_behavior = user_intent AND model_supports_it`. When either is False,
the behavior is suppressed — and the user is notified via INFO log so they
understand why their setting was overridden.

---

### AP-6. Tokenization vs reasoning (confusing two different bugs)

**Symptom**: The user reports "garbage in the response" and the team
investigates reasoning pipeline issues. The actual root cause is tokenization
degradation from a missing pre-tokenizer in the GGUF file — completely
unrelated to reasoning.

**Root cause**: llama.cpp logs `missing pre-tokenizer type, using: 'default'`
+ `GENERATION QUALITY WILL BE DEGRADED` when a GGUF file lacks the
`tokenizer.ggml.pre-tokenizer_type` metadata. This causes subtle tokenization
bugs: broken apostrophes (`Vivy'` instead of `Vivy's`), mis-split special
characters, degraded generation quality. The symptom looks like "garbage in
the response" but the reasoning pipeline is innocent.

**Observed in**: `llama_server_2026-08-01_17-32-17.log:9-15` (Llama-3 GGUF
shows this warning). KI#72 (pre-tokenizer detection) is still open.

**Prevention rule**: When investigating "garbage output", FIRST check the
llama-server log for `missing pre-tokenizer` / `GENERATION QUALITY WILL BE
DEGRADED` warnings. If present, the bug is in the GGUF file (re-quantize from
the original HF source) — NOT in the reasoning pipeline. Only investigate
reasoning if the pre-tokenizer warning is absent.

---

### AP-7. Model broken vs app broken (abliterated + drifted eos)

**Symptom**: The app applies all the correct mitigations, but the model still
produces garbage. The team keeps iterating on app-side fixes that can't
possibly help because the model itself is fundamentally broken.

**Root cause**: Some models in the user's library are broken at the model
level:
- **Qwen3.5-9B-abliterated**: abliteration (removal of refusal mechanism) +
  eos_token_id drift (248046 vs canonical 151645). The model can't stop
  properly AND has altered reasoning behavior.
- **Gemma-4-HauhauCS-Aggressive**: eos_token_id drift (1 vs canonical for
  qwen3-thinking). The model works because Gemma's native eos=1 happens to
  match, but the SoW detection pipeline flags it as drift.

For Qwen3.5-abliterated, no app-side fix can produce good output — the model
itself is the problem. The app can only:
- (a) Disable reasoning at the server level (KI#75 — proposed) so the model
  doesn't consume all tokens on thinking
- (b) Recommend the user switch to a non-abliterated Qwen3.5 variant

**Observed in**: every iteration since iter-87 where Qwen3.5-abliterated
produced garbage. The team kept tuning reasoning parameters hoping to fix a
model-level defect.

**Prevention rule**: When a model produces garbage DESPITE correct app-side
mitigations (verified via logs showing all gates firing correctly), classify
the bug as "model broken" — not "app broken". Document the model as known-
broken in §6 (Known-Broken Models) and recommend alternatives. Do NOT keep
iterating on app-side fixes for a model-level defect.

---

### AP-8. Smoke test green ≠ production green

**Symptom**: A smoke test passes (35 PASS, 0 FAIL) but the production behavior
is broken. The team ships the iteration, the user reports a regression, and
the next iteration starts from scratch.

**Root cause**: Smoke tests verify CODE correctness (function X returns Y for
input Z) but not SYSTEM correctness (model M produces visible output when
server S is started with flags F). The KI#74 smoke test verified that
`_build_extra_body()` correctly skips `reasoning_budget_tokens` when
`enable_thinking=False`, but it did NOT verify that the model actually
produces visible text when the budget is skipped.

**Observed in**: iter-90 — 35 smoke tests PASS, but Qwen3.5-abliterated
produces 0 visible text chunks in production because `--reasoning on` is still
sent to the server.

**Prevention rule**: Every KI that touches the reasoning pipeline MUST have
at least one "end-to-end" smoke test that simulates the full path: detection
→ server flag decision → per-request parameter injection → simulated stream
with reasoning + text chunks → assert visible text chunks > 0. Code-level
unit tests are necessary but NOT sufficient for reasoning-pipeline changes.

---

## §2. Lessons learned (one-liners, append-only)

- **iter-22**: Stop tokens are a 4-tier precedence, not a single value.
  Caller kwarg > user stop_strings > auto-detected > no stop. Never collapse
  the tiers.
- **iter-29.1**: `enable_thinking` via `--chat-template-kwargs` is deprecated
  by llama.cpp build 4629+. Use `--reasoning on/off` instead.
- **iter-38**: `--chat-template` flag triggers a peg-native parser bug in
  llama.cpp b9550. Only pass it when GGUF-embedded template is absent.
- **iter-44**: H6 (`--reasoning off` causes prompt_eval collapse) was a red
  herring. H7 (`--chat-template` flag is the real trigger) was confirmed.
  Always verify hypotheses with controlled experiments, not just log
  correlation.
- **iter-59**: Consume `reasoning_content` silently — do NOT yield it. Yielding
  reasoning causes history leakage (markers persist in saved history) and
  display leakage (typewriter shows thinking text).
- **iter-60**: `reasoning_budget_tokens` is the canonical field name (PR
  #22740). `thinking_budget_tokens` is a back-compat alias — never send both.
- **iter-64**: `--reasoning on` is needed EXPLICITLY when `reasoning_mode=True`
  because `--reasoning auto` (the default) doesn't split `<think>` blocks
  beyond the first one for ChatML-family templates.
- **iter-66**: `qwen3-thinking` Jinja pattern must be checked BEFORE `chatml`
  — Qwen3 Jinja contains ChatML markers as its base format.
- **iter-67**: llama.cpp b10214 changed log format from `main: model loaded`
  to `srv  llama_server: model loaded`. Progress parsers must match BOTH.
- **iter-68**: Unique-family Jinja patterns (`gemma3`, `mistral-v0-1`,
  `command-r`, `alpaca`) must be checked BEFORE `qwen3-thinking` — finetune
  authors add `<think>` markers to non-Qwen3 models.
- **iter-69**: `eos_token_id` drift is real for abliterated/uncensored models.
  Detect it, warn about it, and (per KI#74) gate reasoning budget on it.
- **iter-74**: iter-77 KI#58 claimed to fix reasoning markers but the commit
  only touched docs. Always verify code changes via `git diff`, not just
  commit messages.
- **iter-90**: Gating `reasoning_budget_tokens` without gating `--reasoning
  on/off` is a half-fix (AP-2). Qwen3.5-abliterated went from "garbage visible
  text" to "no visible text" — the symptom changed but didn't resolve.
- **iter-102**: `finish_reason` is hardcoded to `"stop"` at
  `interface_signals.py:14089+14366`. Never trust the sow log's
  `finish_reason=stop` — verify `completion_tokens == max_tokens` instead
  (if equal, the model hit the limit and was truncated). The actual API
  `finish_reason` from llama-server is dropped on the floor.
- **iter-102**: `tokens_out` in the sow log is `len(full_response)//4` — a
  chars-based estimate, NOT real token count. Always cross-check with the
  `[usage]` line which carries the real `completion_tokens` from
  llama-server. The two values diverge by ~15% for roleplay text.
- **iter-102**: When the model hits `max_tokens` every time, the symptom is
  NOT "model broken" — it's "max_tokens too low". Llama-3-8B roleplay
  responses are typically 1000-1500 tokens. Setting `max_tokens=875`
  truncates mid-sentence and the model never gets to emit `<|eot_id|>`.
  Always check `completion == max_tokens` before investigating deeper bugs.
- **iter-102**: External 2026 reference — Alex Ewerlof "Sampling args in
  llama-server" (Jul 1, 2026): DRY `multiplier=0.8 + allowed_length=2`
  matches the Coding/JSON profile, NOT creative writing. For roleplay,
  use `dry_multiplier=0.5` and `top_p=0.80-0.95`. The user's `top_p=0.7`
  is below the recommended creative-writing range.

---

## §3. Decision tree — adding a new model / AI provider

Use this checklist when adding a new GGUF model to the user's library OR a new
cloud provider. Each step references the KI that established the rule.

### Adding a new local GGUF model

1. **Place the file** in `assets/local_llm/`. Verify `.gitignore` covers it
   (§4 of AGENTS.md — never `git add` model files).
2. **Launch SoW** and open the Diagnostics Panel. Check:
   - **Template Source** (Block 7): should show `EMBEDDED` with `HIGH`
     confidence. If `FALLBACK` or `NONE`, the GGUF lacks an embedded Jinja
     template — `--chat-template` flag will be passed (KI#44 risk).
   - **EOS drift** (Block 5 / log WARNING): if the GGUF `eos_token_id` does
     not match the canonical eos for the resolved family, the model is
     "drifted" (KI#69). Reasoning budget will be skipped (KI#74) and
     `--reasoning on` may be overridden (KI#75, when implemented).
   - **Pre-tokenizer** (llama-server log): if `missing pre-tokenizer type`
     appears, the GGUF is malformed — re-quantize from the original HF source
     (KI#72, AP-6).
   - **Vocab validation** (Block 7 "Validate vocab" button): if errors
     appear, stop tokens may not be atomic in the vocab (KI#12, KI#70
     deferred).
3. **Test with `reasoning_mode=True`**: send a simple message. Check the log:
   - `stream_chunks=N text_chunks=M reasoning_chunks=K`
   - If `M=0` and `K>0`: model entered thinking and never exited. Either
     disable `reasoning_mode` for this model, or wait for KI#75 (server-level
     gating).
   - If `M>0` but text is garbage: check AP-6 (tokenization) and AP-7 (model
     broken). If the model is abliterated + drifted, it may be fundamentally
     broken.
4. **Test with `reasoning_mode=False`**: send the same message. If the
   response is good, the model doesn't support thinking — leave
   `reasoning_mode` off for this model.
5. **Document findings** in §6 (Known Models) below.

### Adding a new cloud AI provider

1. **Read** `app/utils/ai_clients/providers/<existing>_provider.py` as a
   template (recommend `openai_provider.py` — most complete).
2. **Implement** `generate_stream()`, `generate()`, `generate_summary()`.
   Each MUST:
   - Consume `reasoning_content` silently (KI#59) — `getattr(delta,
     "reasoning_content", None)` + count for diagnostics, do NOT yield.
   - Yield ONLY `delta.content` (the visible text).
   - Emit `REASONING_EXHAUSTED` warning when `text_chunks == 0 and
     reasoning_chunks > 0` (KI#58).
   - Log `[usage]` and `[stream]` lines matching the LocalProvider format
     (KI#62).
3. **Add the provider** to `AIFactory.get_provider()` in `ai_factory.py`.
4. **Add UI combobox item** in `sowInterface.py` — append to the END of the
   `comboBox_conversation_method` items list (NEVER change existing order —
   settings.json stores the index, not the name; reordering breaks user
   configs).
5. **Update i18n** — add the provider name to BOTH `ru.yaml` AND `en.yaml`.
6. **Update AGENT_NAVIGATION.md §3** with the new provider's file path and
   key methods.
7. **Write a smoke test** — `scripts/iter<N>_smoke_test.py` with at least 5
   tests covering: provider instantiation, message format, reasoning
   consumption, REASONING_EXHAUSTED warning, diagnostic logging.

---

## §4. Open KIs (active defects)

These KIs are tracked in STATUS.md but not yet fixed. Listed here for
visibility — scan before starting a new iteration to avoid duplicating effort.

| KI# | Title | Status | Suspected fix site | Blocked by |
|-----|-------|--------|--------------------|------------|
| KI#65 | qasync task race — `start_new_dialog_main` vs `_launch_server_then_update_visibility` | OPEN (non-blocking) | `interface_signals.py` (16k LOC — high risk) | Nothing — deferred until user reports it as blocking |
| KI#70 | stop_tokens atomic check on hot path | DEFERRED | `template_detector.py` + `local_provider.py` | Requires `validate_stop_tokens_against_vocab()` helper |
| KI#71 | reasoning false-positive detection — warn when `enable_thinking=False` and `reasoning_chunks > 0` | DEFERRED | `local_provider.py:generate_stream()` hot path | Nothing — scope risk |
| KI#72 | pre-tokenizer missing detection — parse `missing pre-tokenizer type` warning | **CLOSED (iter-93)** — detection + DiagnosticsPanel Block 10 (TOKENIZER INTEGRITY) + re-quantization recommendation implemented. **iter-97 (KI#79) SUPERSEDES** the "true cure = re-quantize" verdict: auto-apply `--override-kv tokenizer.ggml.pre=str:<value>` at server launch when the GGUF field is missing. KI#72 detection logic retained for out-of-map models (Mistral, older Qwen2) — will simply not fire for in-map models because the warning is eliminated at the source. | `local_server_manager.py:_check_pretokenizer_warning()` + `diagnostics_panel.py` Block 10 (retained) + `local_server_manager.py:start_server_async()` KI#79 override (iter-97) | N/A — CLOSED. Detection retained; true fix in KI#79. |
| KI#73 | multi-template GGUF selection — when `multi_tmpl > 0`, select thinking/non-thinking variant | DEFERRED | `template_detector.py:detect_template()` | Design decision needed (which variant to prefer) |
| **KI#75** | **`--reasoning on/off` server flag not gated on capability + eos drift** | **CLOSED (iter-93)** — gated on `enable_thinking` ONLY (NOT `eos_drift` per contradiction #4). `detect_template()` moved before the flag decision (AP-3 fixed); duplicate calls deduplicated (3→1). | `local_server_manager.py:start_server_async()` | N/A — CLOSED. |
| **KI#77** | **Qwen3.5 EOS drift false positive — `reasoning_budget_tokens` skipped for all eos-drifted models, causing REASONING_EXHAUSTED** | **CLOSED (iter-95)** — (1) `_CANONICAL_EOS_BY_TEMPLATE` updated with Qwen3.5 EOS tokens (248044, 248046) so drift detector no longer fires for Qwen3.5; (2) `eos_drift` gate removed from `_build_extra_body()` — budget is now injected for ALL thinking-capable models regardless of eos_drift. | `template_detector.py` + `local_provider.py` | N/A — CLOSED. |
| **KI#79** | **Llama-3 pre-tokenizer TRUE fix — auto-apply `--override-kv tokenizer.ggml.pre=str:<value>` when GGUF field is missing (supersedes KI#72's "re-quantize" verdict)** | **OPEN — awaiting Windows verification**. Code complete in iter-97: `template_detector.py` reads `tokenizer.ggml.pre` field (added to `GGUFMetadata` + `DetectionResult`); `local_server_manager.py` auto-applies `--override-kv tokenizer.ggml.pre=str:<value>` in `start_server_async()` when 5 conditions are met (detection OK + pre field missing + BPE `tokenizer_model` + arch+family match in `_ARCH_PRETOKENIZER_MAP` + user `custom_args` doesn't already have `--override-kv`). 5 map entries: Llama-3→`llama3`, Qwen3/Qwen3.5→`qwen3`, DeepSeek V2/V3→`deepseek-llm`, DeepSeek R1→`deepseek-llm`, gpt-oss→`gpt-2`. Inline smoke test 16 PASS. | `template_detector.py:GGUFMetadata.pre_tokenizer` + `DetectionResult.pre_tokenizer` + `read_gguf_metadata()` field read + `local_server_manager.py:_ARCH_PRETOKENIZER_MAP` + `start_server_async()` override block | N/A — code complete; awaiting user Windows verification (4-model matrix: Llama-3 KEY + Qwen3.5 + Gemma-4-HauhauCS + MN-Violet-Lotus). |
| **KI#81** | **Llama-3-8B generation — KI#80 fixed garbage, but `max_tokens=875` truncates response before `<\|eot_id\|>` emitted. Model hits limit every time** | **ANALYZED (iter-102)** — root cause identified. Verified: chat template correct (GGUF-embedded Llama-3, HIGH confidence); stop words correct (`<\|eot_id\|>`, token 128009); reasoning not interfering (`--reasoning off` forced, budget skipped, `reasoning_chunks=0`). User needs to test with `max_tokens=1500+`. 3 code bugs found (deferred): (1) `finish_reason` hardcoded `"stop"` at `interface_signals.py:14089+14366`; (2) `tokens_out = len(full_response)//4` misleading at `prompt_engine.py:1106`; (3) 41s streaming overhead (`asyncio.sleep(0.016)` × 875 chunks + typewriter). | `interface_signals.py:14089+14366` (finish_reason) + `prompt_engine.py:1106` (tokens_out) | Awaiting user test with `max_tokens=1500`. |

### KI#75 detail (identified in iter-91, NOT yet fixed)

**Symptom** (from `sow_2026-08-01_17-32-17.log`):
- **Qwen3.5-9B-abliterated**: `--reasoning on` sent to llama-server (line
  115). KI#74 correctly skipped `reasoning_budget_tokens`, but the server
  still entered reasoning-parse mode. Result: `stream_chunks=1003
  text_chunks=0 reasoning_chunks=1000` — model thought for the full
  `max_tokens=1000` and produced ZERO visible text. Response preview:
  `(empty)`.
- **Llama-3-8B**: `--reasoning on` sent to llama-server (line 41) for a
  non-thinking model (`enable_thinking=False`). KI#74 correctly skipped
  `reasoning_budget_tokens`. Result: stream closed cleanly (no 38s hang —
  KI#74 helped here), BUT llama-server log shows `missing pre-tokenizer`
  (KI#72) and the response preview shows broken apostrophe (`Vivy'` instead
  of `Vivy's`). The "garbage" the user sees for Llama-3 is KI#72 (tokenization),
  NOT reasoning.
- **Gemma-4-HauhauCS**: `--reasoning on` sent, KI#74 skipped budget. Model
  self-regulated thinking (438 reasoning + 159 text chunks). Works OK.
- **MN-Violet-Lotus-12B**: not tested in this verification log.

**Root cause**: `local_server_manager.py:375-428` decides `--reasoning on/off`
based ONLY on `settings.json::main_settings.reasoning_mode` — does NOT consult
`detection_result.capability_map.enable_thinking` or
`detection_result.eos_drift`. The detection pipeline runs at line 485-494,
AFTER the reasoning flag decision at line 375-428 (AP-3: order-of-operations).

**Proposed fix** (for iter-92):
1. Move `detection = detect_template(model_path)` to BEFORE the `--reasoning
   on/off` decision (before line 375).
2. Deduplicate — remove the later `detect_template()` calls at lines 466 and
   487 (they re-run the same detection; the cache makes this cheap, but the
   code duplication is confusing).
3. Gate `--reasoning on/off` on the same conditions as KI#74:
   - `enable_thinking=False` → `--reasoning off` (model can't think anyway)
   - `eos_drift=True` → `--reasoning off` (model can't stop; thinking would
     consume all tokens — see Qwen3.5-abliterated above)
   - Otherwise → respect user's `reasoning_mode` setting (current behavior)
4. Log INFO when overriding the user's setting: `[KI#75] --reasoning off
   FORCED for this model: <reason>. User reasoning_mode=True is overridden
   because <explanation>.`
5. Smoke test: simulate the 4 model archetypes (thinking+no-drift,
   thinking+drift, non-thinking+no-drift, non-thinking+drift) and verify the
   correct `--reasoning` flag is passed.

**Expected outcomes**:
- Qwen3.5-abliterated: `--reasoning off` → model produces visible text
  directly (no `<think>` blocks). Quality may still be poor (abliterated +
  drifted), but at least the user sees SOMETHING.
- Llama-3: `--reasoning off` → server doesn't enter reasoning-parse mode.
  Tokenization artifacts (KI#72) may persist but reasoning-related artifacts
  will be gone.
- Gemma-4-HauhauCS: `--reasoning off` → loses reasoning capability. Response
  quality may decrease (was good with reasoning). **Trade-off**: this model
  works WITH reasoning, but KI#75 would disable it. **Mitigation**: KI#75
  should ONLY force `--reasoning off` when `enable_thinking=False` OR
  (`eos_drift=True` AND the model has produced 0 text chunks in a prior
  request). The second condition is harder to implement — may need a
  per-model "reasoning success" flag persisted across requests.
- MN-Violet-Lotus: `--reasoning off` → no change in behavior (model doesn't
  support thinking anyway).

**Risk**: disabling reasoning for Gemma-4-HauhauCS would be a regression
(it works fine with reasoning). Need a more nuanced gating than KI#74's
binary rule. **Recommendation**: KI#75 should gate `--reasoning on/off` on
`enable_thinking` ONLY (not `eos_drift`). For eos-drifted-but-thinking-capable
models, keep `--reasoning on` and rely on the model's self-regulation. If
the model can't self-regulate (Qwen3.5-abliterated), classify it as
"model broken" (AP-7) and recommend switching models.

---

## §5. Closed KIs (historical reference)

Full per-KI root-cause + fix tables are in `STATUS.md` → "Closed KIs" section
(near the end of the file). This section is a quick-reference index.

| KI# | Closed in | One-line summary |
|-----|-----------|------------------|
| KI#6 | iter-22 | Stop tokens 4-tier precedence established |
| KI#7 | iter-22 + iter-67 | Stop strings parsing + free-form Jinja override |
| KI#8 | iter-13 + iter-62 | `sanitize_special_tokens()` + Diagnostics Panel Block 6 |
| KI#9 | iter-22 | (see STATUS.md) |
| KI#12 | iter-61 | Vocab validation in `template_detector.py` |
| KI#13 | iter-76 | `checkBox_enable_thinking` dead widget cleanup |
| KI#17 | (see STATUS.md) | |
| KI#19 | iter-25 | Cloud reasoning wiring (DeepSeek-R1, etc.) |
| KI#39 | (accepted limitation) | Stale `date_string` on new chat without server restart |
| KI#40–43 | (see STATUS.md) | |
| KI#44 | iter-38 | `--chat-template` flag conditional on GGUF-embedded template presence |
| KI#45–48 | iter-33 | iter-32 destructive rewrite reverted (3 files restored) |
| KI#49 | (see STATUS.md) | Call sites updated |
| KI#50 | iter-42 | (see STATUS.md) |
| KI#51 | iter-50 | `checkBox_enable_thinking` visibility on model/provider change |
| KI#52 | iter-52 | Template detector `arch=llama` misclassification fixed |
| KI#53 | iter-53 | `prompt_engine.py` PROMPT STRUCTURE log reflects auto-detected stops |
| KI#54 | iter-54 | `log_template_validation()` Jinja-inferred fallback |
| KI#55 | iter-69 | Async template detection in Diagnostics Panel |
| KI#56 | iter-70 | DiagnosticsPanel crash on startup — init order fix |
| KI#57 | iter-76 | `reasoning_content` field consumed (was silently dropped) |
| KI#58 | iter-77 | Reasoning markers fixed (`<think>`/`</think>` canonical) |
| KI#59 | iter-78 | Consume `reasoning_content` silently (do NOT yield) |
| KI#60 | iter-80 v2 + iter-80.1 | Per-request `reasoning_budget_tokens` sub-cap |
| KI#61 | iter-86 | Settings persistence atomicity (`_atomic_save` + `.bak`) |
| KI#62 | iter-86 | Logging gap for `reasoning_budget_tokens` / `reasoning_budget_message` |
| KI#63 | iter-86 | `installer.bat` missing llama-server.exe update step |
| KI#64 | iter-87 | `--reasoning on` flag added when `reasoning_mode=True` (was defaulting to `auto`) |
| KI#66 | iter-88 | Jinja inference distinguishes Qwen3-thinking from ChatML |
| KI#67 | iter-88 | `_parse_ui_progress` matches llama.cpp b10214 log format |
| KI#68 | iter-89 | Unique-family Jinja patterns before `qwen3-thinking` |
| KI#69 | iter-89 | `eos_token_id` drift detection (WARNING only — behavioral fix in KI#74) |
| KI#72 | iter-93 | Pre-tokenizer warning detection (`_check_pretokenizer_warning`) + DiagnosticsPanel Block 10 (TOKENIZER INTEGRITY) + re-quantization recommendation. **iter-97 (KI#79) supersedes** the "re-quantize" verdict — runtime CLI flag `--override-kv` eliminates the warning at the source for in-map families. KI#72 detection logic retained for out-of-map models. |
| KI#74 | iter-90 + iter-95 | `reasoning_budget_tokens` gated on `enable_thinking` ONLY (iter-95 KI#77 removed `eos_drift` gate — was false positive for Qwen3.5) |
| KI#75 | iter-93 | `--reasoning on/off` server flag gated on `enable_thinking` ONLY (NOT `eos_drift`); `detect_template()` moved before flag decision (AP-3 fixed); duplicate calls deduplicated (3→1) |
| KI#77 | iter-95 | Qwen3.5 EOS drift false positive fixed — `_CANONICAL_EOS_BY_TEMPLATE` updated with 248044/248046; `eos_drift` gate removed from budget injection |
| KI#79 | iter-97 (pending Windows verification) | Llama-3 pre-tokenizer TRUE fix — auto-apply `--override-kv tokenizer.ggml.pre=str:<value>` when GGUF field is missing. Supersedes KI#72's "re-quantize" verdict. 5 map entries (Llama-3/Qwen3/Qwen3.5/DeepSeek/gpt-oss). 5 conditions gate the override (detection OK + pre field missing + BPE tokenizer_model + arch+family match + user custom_args doesn't already have `--override-kv`). Inline smoke test 16 PASS. |
| KI#80 | iter-101 | Content-match placeholder stripping in local_provider.py — `_strip_role_alternation_placeholders()` strips `[conversation continued]` messages + merges consecutive same-role. Applied in all 3 generation methods. |

---

## §6. Known models (behavioral reference)

Empirical observations from verification logs. Updated each iteration when
new logs are analyzed. **If a model is listed here as "broken", do NOT keep
iterating on app-side fixes for it — see AP-7.**

| Model | arch | eos | enable_thinking | eos_drift | Behavior with iter-95 (KI#77 + KI#75 + KI#72) | Recommendation |
|-------|------|-----|-----------------|-----------|------|----------------|
| Meta-Llama-3-8B.Q4_K_M | llama | [128001] | False | False | **iter-97 VERIFIED**: KI#79 pre-tokenizer override applied (`--override-kv tokenizer.ggml.pre=str:llama3`), no warning in llama_server log. KI#75 forces `--reasoning off`. **iter-100 NEW SYMPTOM**: Generation collapse — model produces repetitive `brakkbrakkbrakk;brkk;brk;brk;...` garbage (588 text tokens, 875 total, 0 reasoning, `finish_reason=abort`). **iter-101 KI#80 CLOSED**: `_strip_role_alternation_placeholders()` now strips `[conversation continued]` placeholders in local_provider.py (content-match only, not `_block_type`). Previous log showed coherent output with placeholder echo, so the model is NOT fundamentally broken. | **Re-test with KI#80 fix applied.** If model produces coherent text → placeholder was the sole trigger for both echo and collapse. If still garbage → KI#81 (generation collapse) — investigate sampling params, tokenization, model-level. |
| MN-Violet-Lotus-12B.i1-Q4_K_M | llama | [2] | False | False | KI#75 forces `--reasoning off` (was `--reasoning on`). Response quality UNCHANGED (model doesn't support thinking anyway). **iter-94: NOT TESTED — verification gap (not a code defect).** Same archetype as Llama-3 (enable_thinking=False, eos_drift=False) — KI#75 code path verified by Llama-3. | No action needed — KI#75 is a no-op for capability. User should re-test MN-Violet-Lotus separately to close the last verification gap. |
| Qwen3.5-9B-abliterated.Q5_K_M | qwen35 | [248046] | True | **True** (iter-95: canonical table now includes 248044/248046 — drift detector no longer fires for Qwen3.5) | **iter-94 VERIFIED (2 runs)**: KI#75 does NOT apply (`enable_thinking=True` → user's `reasoning_mode` respected, `--reasoning on` still sent). 0 visible text CONFIRMED at both `max_tokens=1000` (1000 reasoning, 0 text, empty response) AND `max_tokens=1538` (1538 reasoning, 0 text, empty response). **AP-7 confirmed at 2 token envelopes — model is definitively broken.** **iter-95 KI#77**: `reasoning_budget_tokens` is now injected (eos_drift gate removed) — budget will cap reasoning at 50% of max_tokens, but the model may still produce garbage or empty text if the abliteration broke the thinking→text transition. | **Switch to non-abliterated Qwen3.5.** The app cannot fix this model — KI#75 deliberately does NOT gate on `eos_drift` (would regress Gemma-4-HauhauCS per contradiction #4). KI#77 budget injection may help but AP-7 classification remains. |
| **Qwen3.5-9B-Q4_K_M** (official, non-abliterated) | qwen35 | [248046] | True | **False** (iter-95: canonical table now includes 248044/248046) | **iter-95 NEW ENTRY** — user tested official Qwen3.5-9B-Q4_K_M and confirmed it works on the FIRST request (261 text + 1244 reasoning, `finish_reason=stop`) but REASONING_EXHAUSTED on the SECOND request (875 reasoning + 0 text, empty response). Root cause: KI#74 EOS drift false positive (248046 ≠ 151645) skipped `reasoning_budget_tokens`, allowing model to spend all max_tokens on thinking. **iter-95 KI#77 FIX**: canonical table updated + eos_drift gate removed → `reasoning_budget_tokens` will now be injected for Qwen3.5 (budget ≈ 50% of max_tokens). User should re-test to verify the model self-regulates with the budget. | **Re-test with iter-95 code.** The budget should force the model to switch from thinking to text after the reasoning cap is exhausted. If the model still produces 0 text with the budget, the issue is at the model level (AP-7). |
| Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q4_K_M | gemma4 | [1] | True | **True** | **iter-94 VERIFIED — KEY REGRESSION TEST PASSED**: KI#75 does NOT apply (`enable_thinking=True` → `--reasoning on` still sent). Response quality UNCHANGED — iter-91 baseline: 159 text + 438 reasoning → iter-94: 282 text + 618 reasoning (session-to-session variation, NOT regression; quality preview good: `*A faint, high-pitched *thwack* echoes in the sterile confines of the maintenance room...`). KI#75's deliberate choice to NOT gate on `eos_drift` preserves Gemma-4-HauhauCS reasoning capability. Contradiction #4 resolution empirically re-validated. **iter-95 KI#77**: `reasoning_budget_tokens` is now injected for this model too (eos_drift gate removed). Budget should cap reasoning at ~50% of max_tokens — model already self-regulates, so the budget is a safety net, not a constraint. | No action needed — KI#75 + KI#77 protect this model. Budget injection is a safety net for self-regulating models. |

---

## §7. Change log

| Date | Iteration | Change |
|------|-----------|--------|
| 2026-08-02 | iter-102 | **Research iteration (no code changes).** Investigated KI#81 root cause per user request to verify chat template / stop words / reasoning mode + consult external 2026 sources. Verified all 3 are CORRECT: chat template is GGUF-embedded Llama-3 (HIGH confidence, KI#44 fix holds), stop words are `['<\|eot_id\|>']` (token 128009, source=gguf+template_implied), reasoning not interfering (`--reasoning off` forced KI#75, `reasoning_budget_tokens` skipped KI#74, `reasoning_chunks=0`). KI#80 fix verified working in log (no more `brakkbrakk` garbage, preview shows coherent text). **Root cause for "still broken"**: `completion=875 == max_tokens=875` — model hits limit every time, response truncated mid-word. User's `max_tokens=875` setting too low for Llama-3-8B roleplay (typical 1000-1500 tokens). 3 code bugs found (deferred): (1) `finish_reason` hardcoded `"stop"` at `interface_signals.py:14089+14366` — never reads actual API value; (2) `tokens_out = len(full_response)//4` misleading estimate at `prompt_engine.py:1106` — real completion=875 reported as 1001; (3) 41s streaming overhead (`asyncio.sleep(0.016)` × 875 chunks = 14s + typewriter/UI = 27s, vs llama-server generation = 9.5s). External sources consulted: Alex Ewerlof "Sampling args in llama-server" (Jul 1, 2026) — DRY `multiplier=0.8 + allowed_length=2` matches Coding/JSON profile, NOT creative; GitHub Issue #8856 (closed Sep 2024) — finish_reason bug fixed in PR #8894 but local code doesn't use the value. KI#81 status: OPEN → ANALYZED. §2 Lessons learned: 4 new entries. §4 Open KIs: KI#81 updated to ANALYZED with full details. |
| 2026-08-02 | iter-101 | **KI#80 CLOSED**: Implemented `_strip_role_alternation_placeholders()` in local_provider.py — content-match only (not `_block_type`), strips `[conversation continued]` placeholder messages, merges consecutive same-role messages. Applied in all 3 generation methods (`generate_stream`, `generate_summary`, `generate`). 8 functional tests passed. This is the actual code fix that iter-99 claimed but never committed (AP-10 ghost commit). §5 Closed KIs: KI#80 added. §6 Llama-3: updated with KI#80 fix status. |
| 2026-08-02 | iter-100 | **Deep analysis iteration (no code changes).** Investigated Llama-3-8B garbage output from user-supplied logs (`sow_2026-08-01_21-23-49.log` + `llama_server_2026-08-01_21-23-49.log`). Three critical findings: (1) **KI#80 fix was NEVER implemented in code** — `_strip_role_alternation_placeholders()` doesn't exist in `local_provider.py`; iter-99 commit only added docs + smoke test. Same failure mode as iter-77 (KI#58). Documented as AP-10 (Ghost commit). (2) **`_block_type` metadata is stripped BEFORE reaching local_provider.py** — `prompt_engine.py:log_prompt_structure()` (line 1079-1080) strips `_block_type` from messages before they reach the provider. KI#80 fix must use content match only, not `_block_type`. (3) **NEW symptom: generation collapse** — Llama-3-8B produces repetitive `brakkbrakk;brkk;brk;...` garbage (588 text tokens, 875 total, `finish_reason=abort`). Previous log showed coherent output with placeholder echo. Root cause unresolved — opened KI#81. Added §10 (full analysis), AP-10 (ghost commit anti-pattern), updated §6 Llama-3 entry. |
| 2026-08-01 | iter-95 | **KI#77 CLOSED**: Qwen3.5 EOS drift false positive fixed. Root cause: `_CANONICAL_EOS_BY_TEMPLATE` only listed Qwen3's eos_token_id=151645, but Qwen3.5 uses a larger 248320-vocab tokenizer where `<|im_end|>` is at token 248044 (GGUF reports 248046). The drift detector fired a false positive (248046 ≠ 151645) → KI#74 skipped `reasoning_budget_tokens` → model exhausted all max_tokens on reasoning → REASONING_EXHAUSTED (0 text, empty response). Fix: (1) `_CANONICAL_EOS_BY_TEMPLATE` updated with 248044 + 248046 for `qwen3-thinking` and `qwen3-non-thinking`; (2) `eos_drift` gate removed from `_build_extra_body()` — budget is now injected for ALL thinking-capable models regardless of eos_drift. This is a safety net: even for models with genuine EOS drift, an empty response (0 text) is strictly worse than potentially degraded text from a forced budget switch. 3 code files + 3 doc files. §4 Open KIs: KI#77 added. §5 Closed KIs: KI#74 updated, KI#77 added. §6 Known models: Qwen3.5-9B-Q4_K_M (official) added as new entry; Qwen3.5-abliterated + Gemma-4-HauhauCS updated with iter-95 KI#77 notes. §7 Change log: iter-95 entry. |
| 2026-08-01 | iter-94 | Verification iteration (no code changes). Verified iter-93 KI#75 + KI#72 implementation against user-supplied Windows logs (`sow_2026-08-01_18-38-04.log` + `llama_server_2026-08-01_18-38-04.log`). **3/4 models tested (MN-Violet-Lotus NOT tested — verification gap, not code defect).** Results: (1) Llama-3 — KI#75 + KI#72 fired correctly, generation aborted by user at 802 tokens (broken apostrophe NOT visible in 200-char preview — KI#72 detection is the app-side contract; true cure = re-quantize GGUF); (2) Qwen3.5-abliterated — AP-7 confirmed at 2 token envelopes (max_tokens=1000 + 1538, both 0 text chunks, empty response), reinforced recommendation to switch to non-abliterated Qwen3.5; (3) **Gemma-4-HauhauCS — KEY REGRESSION TEST PASSED** — 282 text + 618 reasoning chunks (iter-91 baseline 159/438 — session-to-session variation, NOT regression), `--reasoning on` preserved, quality good. **KI#76 NOT OPENED** — no regression detected. Contradiction #4 resolution (gate on `enable_thinking` ONLY, NOT `eos_drift`) empirically re-validated. 3 docs updated (STATUS.md + worklog.md + PATTERNS.md). |
| 2026-08-01 | iter-93 | Code iteration. KI#75 CLOSED: `--reasoning on/off` server flag gated on `capability_map.enable_thinking` ONLY (NOT `eos_drift` per contradiction #4). `detect_template()` moved before the flag decision (AP-3 fixed); duplicate calls deduplicated (3→1). INFO override log when user's `reasoning_mode=True` is overridden for non-thinking models. KI#72 CLOSED: pre-tokenizer warning detection (`_check_pretokenizer_warning()` parses llama-server log for `missing pre-tokenizer type` + `GENERATION QUALITY WILL BE DEGRADED`), surfaced to DiagnosticsPanel Block 10 (TOKENIZER INTEGRITY) with re-quantization recommendation. 5 code files + 1 test file (`iter93_smoke_test.py`, 37 PASS) + 3 doc files. §4 Open KIs: KI#72 + KI#75 marked CLOSED. §5 Closed KI index: KI#72 + KI#75 added. §6 Known models: updated to reflect iter-93 behavior (KI#75 forces `--reasoning off` for Llama-3 + MN-Violet-Lotus; Qwen3.5-abliterated + Gemma-4-HauhauCS unaffected — `enable_thinking=True`). |
| 2026-08-01 | iter-92 | Analysis-only iteration. Verified external consolidated LLM failure-pattern text (from other LLMs/agents) against code + iter-91 logs. All 5 issue categories confirmed accurate. Added §8 (Consolidated LLM Failure Pattern Categories — cross-ref table) + §9 (Resolved Contradictions — 4 entries with code/log evidence). Elevated KI#72 from DEFERRED to ELEVATED (proof of corruption confirmed). Refined KI#75 proposed fix: gate `--reasoning on/off` on `enable_thinking` ONLY (NOT `eos_drift`) — confirmed by contradiction #4 resolution (Gemma-4-HauhauCS works WITH reasoning despite eos_drift=True). Confirmed `docs/LLM_FAILURE_PATTERNS.md` proposed by external analyses is already covered by this file — no new file created. |
| 2026-08-01 | iter-91 | File created. Documented 8 anti-patterns (AP-1..AP-8), 13 lessons learned, decision tree for new models/providers, 6 open KIs (including newly identified KI#75), closed KI index, 4 known models, change log. |

---

## §8. Consolidated LLM Failure Pattern Categories (iter-92)

Cross-reference table mapping the 5 failure categories from the external
consolidated analysis (other LLMs/agents) to the existing AP/KI entries in
this registry. All 5 categories verified accurate against code + iter-91 logs.

| # | Category (external text) | Symptom | Confirmed root cause | Maps to | Status |
|---|--------------------------|---------|----------------------|---------|--------|
| 1 | Thinking Exit Failure (Reasoning Loop) | Model generates 1000 reasoning chunks, 0 text chunks (`REASONING_EXHAUSTED`). Affected: Qwen3.5-abliterated. | `--reasoning on` forces server into reasoning-parse mode; model never emits `</think>` transition. KI#74 skipped per-request budget but server flag ungated (AP-2). | KI#75 (server flag gating) + AP-2 + AP-7 (model broken) | OPEN — fix in iter-93 (code). Note: external text's `thinking_can_exit` property idea is useful but redundant — `enable_thinking=False` already covers non-thinking models; for thinking-capable-but-can't-exit models, AP-7 classification applies. |
| 2 | EOS Drift (Template/Model Integrity) | GGUF `eos_token_id` differs from canonical (e.g. 248046 vs 151645 for Qwen3). Stop mechanism mismatched. | Abliteration/uncensoring overrides eos. SoW detects via `_check_eos_drift()` (iter-89). | KI#69 (detection) + KI#74 (gating consumer) | Detection CLOSED (iter-89). Behavioral gating CLOSED for per-request budget (iter-90 KI#74). Server-flag gating NOT done — see contradiction #4 resolution: do NOT gate `--reasoning` on eos_drift (would regress Gemma-4-HauhauCS). |
| 3 | Tokenizer Integrity (Missing Pre-Tokenizer) | `missing pre-tokenizer type, using: 'default'` + `GENERATION QUALITY WILL BE DEGRADED`. Affected: Llama-3-8B-Q4_K_M. | GGUF file lacks `tokenizer.ggml.pre-tokenizer_type` metadata. Fallback to generic pre-tokenizer → broken merge rules → corrupt tokens (broken apostrophes). | KI#72 + AP-6 | **ELEVATED in iter-92** (proof confirmed). App fix = detection + surfacing (iter-93). True cure = re-quantize GGUF from HF source (user action). |
| 4 | Reasoning Budget Injection | `reasoning_budget_tokens=600` forcefully added to every request when `reasoning_mode=True`. | `_build_extra_body()` had no capability check. | KI#74 | **CLOSED (iter-90)**. External text's "Fixed" label is accurate. |
| 5 | Control Token Misclassification (Gemma4-specific) | `control-looking token ... was not control-type` + `outdated gemma4 chat template, applying compatibility workarounds`. | llama.cpp-side issue: Gemma4 GGUF Jinja is outdated, llama.cpp applies compatibility workarounds. Non-control tokens may emit as literal text. | iter-89 observation (llama.cpp-side, not SoW code) | **NOT a SoW bug** — llama.cpp handles this internally. SoW only logs the workaround message. No action needed in SoW. Documented for awareness. |

### §8.1 Verification of external text's "Proposed Root Cause Resolution" table

The external consolidated text proposed 4 actions. Status:

| Action (external text) | Status in SoW | Notes |
|------------------------|---------------|-------|
| Server startup: conditionally add `--reasoning on` only when `enable_thinking == True` AND `eos_drift == False` | **PARTIALLY ADOPTED** — iter-91 refined to `enable_thinking` ONLY (NOT `eos_drift`). See contradiction #4. | External text was written before iter-91's refinement. The `eos_drift == False` condition would regress Gemma-4-HauhauCS. |
| `_build_extra_body`: keep current logic | **ALREADY DONE** (KI#74, iter-90) | External text confirms iter-90 fix is correct. |
| Pattern documentation: create `docs/LLM_FAILURE_PATTERNS.md` | **REDIRECTED** — already exists as `PATTERNS.md` (root, iter-91). | No new file created. §8 + §9 added to consolidate external analysis. |
| Priority reshuffle: elevate KI#72 | **DONE in iter-92** | See §4 Open KIs table — KI#72 status changed from DEFERRED to ELEVATED. |

---

## §9. Resolved Contradictions (iter-92)

The external consolidated text included a "Contradictory / Disputable Points"
table with 4 unresolved uncertainties. Each is resolved below with code/log
evidence. **These resolutions are authoritative** — future iterations should
not re-litigate them without new evidence.

### Contradiction #1: Does `--reasoning on` cause garbage on non-thinking models?

| | View A | View B |
|---|---|---|
| Claim | Yes — server may inject special tokens or alter stop logic, leading to intermittent trailing garbage (observed on Llama-3). | No — llama.cpp ignores the flag for models that do not support reasoning; the garbage stems only from tokenizer/pre-tokenizer issues. |

**Resolution: View B is correct for the garbage symptom.**

**Evidence**:
1. **iter-91 log** (`sow_2026-08-01_17-32-17.log:30-102`): Llama-3 with `--reasoning on`:
   - Stream chunks: 296 stream, 293 text, **0 reasoning** — reasoning pipeline is clean (no `<think>` blocks emitted by Llama-3).
   - `finish_reason=stop`, 8.13s, tok/s=38.6 — stream closed cleanly.
   - Response preview: `*Vivy' silence is unnerving...` — broken apostrophe (`Vivy'` instead of `Vivy's`).
2. **llama-server log** (`llama_server_2026-08-01_17-32-17.log:9-15`): `missing pre-tokenizer type, using: 'default'` + `GENERATION QUALITY WILL BE DEGRADED` — this is KI#72, a tokenizer integrity issue, NOT a reasoning issue.
3. **Code** (`local_server_manager.py:384-388`, iter-38 H7 comment): "`--reasoning off` is harmless for non-thinking models (Llama-3 doesn't support thinking anyway)". The inverse is also true: `--reasoning on` is harmless for non-thinking models — llama.cpp's reasoning-parse mode is a no-op when the model doesn't emit `<think>` blocks.
4. **PATTERNS.md §2 iter-44 lesson**: "H6 (`--reasoning off` causes prompt_eval collapse) was a red herring. H7 (`--chat-template` flag is the real trigger) was confirmed. Always verify hypotheses with controlled experiments, not just log correlation." — Same principle applies here: don't blame `--reasoning on` without isolating it from KI#72.

**Nuance**: `--reasoning on` for non-thinking models IS a latent architectural issue (KI#75) — it's semantically incorrect and causes unnecessary server-side reasoning-parse overhead. But it does NOT cause output garbage. KI#75 (gate on `enable_thinking`) is the clean fix, but it won't fix the Llama-3 garbage — only KI#72 (pre-tokenizer) or re-quantizing the GGUF will.

**Action**: Implement KI#75 (gate `--reasoning on/off` on `enable_thinking`) in iter-93 for cleanliness. Separately, implement KI#72 (detect + surface pre-tokenizer warning) in iter-93. Do NOT expect KI#75 to fix Llama-3's broken apostrophes — that requires KI#72 detection + user re-quantization.

---

### Contradiction #2: Is EOS drift the sole cause of Qwen's empty output?

| | View A | View B |
|---|---|---|
| Claim | Yes — the mismatched stop token prevents the model from terminating the thinking phase, resulting in 0 text tokens. | No — even with correct EOS, the model might still exhaust its reasoning budget if it never decides to answer; it's a model-specific behaviour, not a token mismatch. |

**Resolution: View B is more correct. EOS drift is a contributing factor, not the sole cause.**

**Evidence**:
1. **iter-91 log** (`sow_2026-08-01_17-32-17.log:103-179`): Qwen3.5-abliterated with `--reasoning on` + KI#74 (no budget cap):
   - Result: 1003 stream, **0 text**, 1000 reasoning chunks.
   - `REASONING_EXHAUSTED: model produced 1000 reasoning chunks but 0 text chunks (max_tokens=1000)`.
   - Mechanism: llama-server parses `<think>` blocks as `reasoning_content`. The model never emits a clean `</think>` transition (or emits it but eos at 248046 doesn't match canonical 151645, so the server's stop logic doesn't fire). All 1000 tokens go to `reasoning_content`; 0 to `delta.content`.
2. **Model characteristics**: Qwen3.5-9B-abliterated is **both** abliterated (altered refusal/reasoning behavior) **and** eos-drifted (248046 vs 151645). The abliteration itself may have broken the thinking→text transition — independent of eos drift. If the model never "decides" to stop thinking, fixing eos alone wouldn't help.
3. **iter-91 stage summary**: "even with KI#75 forcing `--reasoning off`, the model may still produce garbage because it's fundamentally broken. The app can only mitigate (force `--reasoning off` so the model at least produces SOME visible text instead of 0)."
4. **PATTERNS.md AP-7**: "When a model produces garbage DESPITE correct app-side mitigations, classify the bug as 'model broken' — not 'app broken'." Qwen3.5-abliterated fits AP-7.

**Empirical test (deferred to iter-93 verification)**: run Qwen3.5-abliterated with `--reasoning off` (after KI#75 fix). Three outcomes:
- (a) Produces visible text → reasoning was the sole blocker → View A was wrong, View B was right (eos drift alone wasn't the cause; reasoning mode was).
- (b) Produces 0 text or garbage → model is broken (AP-7) → both views partially wrong; the defect is at the model level.
- (c) Produces visible text but with garbage → eos drift contributes (stop logic still broken) but isn't the sole cause.

**Action**: Implement KI#75 (force `--reasoning off` for `enable_thinking=False` models — Qwen3.5-abliterated has `enable_thinking=True` so this WON'T apply; the model will STILL get `--reasoning on`). For Qwen3.5-abliterated specifically, the app cannot fix it — recommend switching to non-abliterated Qwen3.5. Document as AP-7 (model broken).

---

### Contradiction #3: Should KI#72 (missing pre-tokenizer) be treated as critical now?

| | View A | View B |
|---|---|---|
| Claim | Yes — the explicit "GENERATION QUALITY WILL BE DEGRADED" warning is a strong signal, and it can silently corrupt output. | No — the fallback tokenizer might be acceptable for most use cases; defer until explicit corruption is proven. |

**Resolution: View A is correct. KI#72 is ELEVATED from DEFERRED to scheduled for iter-93.**

**Evidence**:
1. **Explicit corruption confirmed**: iter-91 log shows Llama-3 response with broken apostrophe (`Vivy'` instead of `Vivy's`) — `sow_2026-08-01_17-32-17.log` response preview. This is direct proof of tokenization degradation, not a hypothetical risk.
2. **llama.cpp's own assessment**: the warning text literally says `GENERATION QUALITY WILL BE DEGRADED` — this is llama.cpp's explicit judgement, not SoW's interpretation. When the upstream tool says quality will degrade, believe it.
3. **PATTERNS.md AP-6** (iter-91): "When investigating 'garbage output', FIRST check the llama-server log for `missing pre-tokenizer` / `GENERATION QUALITY WILL BE DEGRADED` warnings. If present, the bug is in the GGUF file — NOT in the reasoning pipeline." — This anti-pattern was documented precisely because the team kept blaming reasoning for what was actually a tokenizer issue.
4. **External text's A/B test** (Llama-3 with/without correct tokenizer): good in principle but unnecessary — the broken apostrophe is sufficient proof. Re-quantizing the GGUF from the original HF source (with proper `tokenizer.ggml.pre-tokenizer_type` metadata) would eliminate the warning.

**Important nuance — app fix vs true cure**:
- **App-level fix (KI#72, iter-93)**: parse the `missing pre-tokenizer type` warning in `local_server_manager.py:_parse_ui_progress()`, surface it to the Diagnostics Panel, and recommend re-quantization. This is DETECTION + WARNING, not a cure.
- **True cure (user action)**: re-quantize the Llama-3 GGUF from the original HF source, or download a properly-quantized version. The app cannot fix a malformed GGUF.

**Action**: KI#72 status changed from DEFERRED to ELEVATED in §4 Open KIs. Implement detection + Diagnostics Panel surfacing in iter-93. Document the re-quantization recommendation in the Diagnostics Panel message.

---

### Contradiction #4: Can we trust `eos_drift` detection to disable reasoning globally?

| | View A | View B |
|---|---|---|
| Claim | Yes — any model with EOS drift is unsafe to run in reasoning mode because the stop mechanism is broken. | No — EOS drift could be a detector false positive; disabling reasoning might unnecessarily degrade performance for models that actually can think but have a non-standard EOS. |

**Resolution: View B is correct. `eos_drift` alone is NOT sufficient to disable reasoning. Gate on `enable_thinking` ONLY.**

**Evidence**:
1. **Direct empirical refutation of View A**: iter-91 log (`sow_2026-08-01_17-32-17.log:180-251`) shows **Gemma-4-HauhauCS** with `eos_drift=True` (eos=[1], canonical for qwen3-thinking is 151645) AND `enable_thinking=True`, running WITH `--reasoning on`:
   - Stream chunks: 600 stream, **159 text**, 438 reasoning — **mixed reasoning + text, working OK**.
   - Response preview: `*Vivy remains perfectly still for a fraction of a second, processing the simple auditory input. Her sapphire eyes widen marginally...` — good quality.
   - This directly disproves View A's claim that "any model with EOS drift is unsafe to run in reasoning mode".
2. **iter-91 KI#75 proposed fix** (already in §4): "gate on `enable_thinking` ONLY (NOT `eos_drift` — Gemma-4-HauhauCS proves eos_drift models can self-regulate)". This was the correct call.
3. **Detector conservatism**: `_check_eos_drift()` (`template_detector.py:689-720`) only flags when NONE of the GGUF eos IDs match ANY canonical eos for the resolved family. False positives are possible but rare (e.g. a model with a legitimate non-standard eos that happens to not be in our canonical table). Disabling reasoning globally on a false positive would regress working models.
4. **PATTERNS.md §6 Known Models table**: explicitly notes for Gemma-4-HauhauCS: "**Do NOT apply KI#75 `eos_drift` gating here** — would disable working reasoning. KI#75 should gate on `enable_thinking` only."

**Why eos_drift doesn't universally break reasoning**: eos drift means the model's stop TOKEN is mismatched, but the `<think>`/`</think>` MARKERS are string-based, not token-based. If the model emits `</think>` as a string, llama-server's reasoning-parse mode can still split reasoning from text correctly — the eos drift only affects when generation STOPS, not how reasoning is PARSED. Gemma-4-HauhauCS emits `</think>` correctly (string-wise) and self-regulates; Qwen3.5-abliterated does not (abliteration may have broken the marker emission).

**Action**: KI#75 proposed fix is REFINED and CONFIRMED — gate `--reasoning on/off` on `enable_thinking` ONLY:
- `enable_thinking=False` → `--reasoning off` (Llama-3, Mistral, MN-Violet-Lotus, plain Gemma)
- `enable_thinking=True` → respect user's `reasoning_mode` (Qwen3, Gemma-4-HauhauCS, Skyfall)
- For eos_drift + thinking-capable models that can't self-regulate (Qwen3.5-abliterated) → classify as AP-7 (model broken); recommend switching models. Do NOT add `eos_drift` to the gating condition.

**Future improvement (not blocking, defer to post-iter-93)**: add a per-model override mechanism in the Diagnostics Panel (checkbox: "Force `--reasoning off` for this model") so the user can manually disable reasoning for specific eos_drift models that don't self-regulate, without globally gating all eos_drift models. This is a UI enhancement, not a global gate change.

---

## §10. iter-100 deep analysis: Llama-3 full-chain investigation (2026-08-02)

### 10.1 Critical finding: KI#80 fix was NEVER implemented in code

The iter-99 commit (`740c455`, 2026-08-01 21:23:22) claimed to implement
`_strip_role_alternation_placeholders()` in `local_provider.py`, but the
**actual code change was never committed**. The commit only contains:

- `STATUS.md` — documentation of the fix
- `worklog.md` — documentation of the fix
- `scripts/iter99_smoke_test.py` — test that imports the non-existent function

**Proof**: `git diff 91b0bd7 740c455 -- app/utils/ai_clients/providers/local_provider.py`
produces zero output. The function `_strip_role_alternation_placeholders` and
the constant `_PLACEHOLDER_CONTENT` do not exist in `local_provider.py`.

Running the smoke test confirms: `ImportError: cannot import name
'_strip_role_alternation_placeholders'`. This is the same failure mode as
iter-77 (KI#58): STATUS.md + worklog.md claimed a fix, but the actual code
was never modified.

**Lesson (AP-10)**: ALWAYS verify that the code change is in the commit
before updating STATUS.md/worklog.md. The iter-99 commit message says "strip
role-alternation placeholders" but the diff shows 0 lines changed in the
target file. This is the second time this exact failure mode has occurred
(iter-77 KI#58 was the first).

### 10.2 Critical finding: `_block_type` metadata is stripped BEFORE reaching local_provider.py

`prompt_engine.py:log_prompt_structure()` (line 1079-1080) strips `_block_type`
metadata from messages:

```python
for msg in messages:
    msg.pop('_block_type', None)
```

This method is called at `prompt_engine.py:1525` BEFORE the messages are
passed to the provider. By the time `local_provider.py:generate_stream()`
receives the messages, `_block_type` is already gone.

**Impact on KI#80**: The original KI#80 plan was to filter by `_block_type ==
"placeholder"` AND content match. But since `_block_type` is stripped before
the messages reach local_provider.py, the filter can ONLY use content match.
The smoke test's G1.1 test case (which includes `_block_type`) would never
encounter that field in production.

**Correct fix approach**: The placeholder stripping must happen in
`local_provider.py` using content match ONLY (`msg["content"] ==
"[conversation continued]"`). The `_block_type` field is unreliable at the
provider level because it's already stripped.

### 10.3 New symptom: Llama-3-8B produces GARBAGE output, not just placeholder echo

The user's previous log (`sow_2026-08-01_20-54-33.log`) showed Llama-3-8B
echoing the placeholder but then producing coherent text:
`[conversation continued]   "Good evening. It is indeed a pleasure to meet you."`

The NEW log (`sow_2026-08-01_21-23-49.log`) shows a COMPLETELY DIFFERENT
and much worse symptom:
```
[conversation continued]brakkbrakkbrakk;brkk;brk;brk;bk;brk;bbrrkk;bbrk;br;
bk;br;k;bk;bbr;kr;k;k;kbk;rk;bkr;k;rkbkr;k;brrbkrk;k;rkbrrkk;brkbrk;br;
kbrbkk  [conversation continued]br
```

This is **generation collapse** — the model produces repetitive "br"/"k"
subword tokens in a degenerate loop. Key metrics:

- **Prompt**: 690 tokens (4 blocks: system + placeholder-user + assistant-history + user-message)
- **Output**: 875 tokens generated (max_tokens=875), 588 tokens of text, 0 reasoning
- **finish_reason**: `abort` (user stopped after 20s)
- **tok/s**: 111.26 (normal speed — model is generating fast, just wrong)
- **Stop**: `<|eot_id|>` never produced — model hit max_tokens limit

### 10.4 Root cause analysis: two separate issues

**Issue A — Placeholder echo (KI#80, known)**: The `[conversation continued]`
placeholder is sent as a user message. Llama-3-8B echoes it. This is the
original KI#80 bug.

**Issue B — Generation collapse (NEW, KI#81)**: The model produces repetitive
garbage instead of coherent text. This is a NEW symptom not seen in the
previous log. Possible causes:

1. **Placeholder confusion** — The model sees `[conversation continued]` as a
   user message and tries to continue from it, but the continuation is
   degenerate. However, the previous log showed coherent output with the
   same placeholder, so the placeholder alone is not sufficient to cause
   generation collapse.

2. **Tokenization issue** — The pre-tokenizer override (`--override-kv
   tokenizer.ggml.pre=str:llama3`) was applied in this session (KI#79
   VERIFIED). The llama_server log shows NO `missing pre-tokenizer` warning.
   So the tokenization SHOULD be correct. But the garbage output suggests
   something is wrong at the token level.

3. **Sampling parameters** — The XTC sampler (xtc_probability=0.3,
   xtc_threshold=0.1) randomly excludes the top token 30% of the time. This
   could contribute to degenerate output when combined with the dry sampler
   (dry_multiplier=0.8, dry_base=1.75, dry_allowed_length=2). The dry sampler
   is supposed to prevent repetition, but the garbage output shows it's not
   effective against this specific pattern.

4. **Model-specific issue** — The Q4_K_M quantization of Llama-3-8B might be
   broken or the model might be in a degenerate state. However, the previous
   log showed coherent output, so the model itself is not fundamentally broken.

5. **Session state** — The user switched from Qwen3.5-9B to Llama-3-8B
   (`RUNTIME CONTEXT DELTA`). The server was restarted. The first message
   was sent. The model generated garbage. This is a fresh session with no
   prior state.

### 10.5 Hypothesis: the placeholder + Llama-3 template interaction is the trigger

The Llama-3 chat template renders the messages as:
```
<|begin_of_text|><|start_header_id|>system<|end_header_id|>
{story preamble}<|eot_id|><|start_header_id|>user<|end_header_id|>
[conversation continued]<|eot_id|><|start_header_id|>assistant<|end_header_id|>
{assistant history}<|eot_id|><|start_header_id|>user<|end_header_id|>
hello!<|eot_id|><|start_header_id|>assistant<|end_header_id|>
```

The model sees a user turn saying `[conversation continued]` — this is
semantically confusing. The model may interpret it as a prompt to continue
a previous conversation, and the "continuation" is degenerate.

**Why the previous log showed coherent output**: The previous session may have
had a different prompt structure (different system prompt, different assistant
history, different placeholder position). The specific combination of the
placeholder + the system prompt + the assistant history in the new log may
trigger the degenerate behavior.

**Key test**: If the placeholder is stripped (KI#80 fix actually implemented),
does the model generate coherent output? If yes → placeholder is the sole
trigger. If no → there's a deeper issue (sampling parameters, tokenization,
or model-level).

### 10.6 Action items for next iteration

1. ~~**Actually implement KI#80**~~ — **DONE iter-101**. `_strip_role_alternation_placeholders()` added to `local_provider.py` using content match ONLY. Applied in all 3 generation methods. 8 functional tests passed.

2. **Open KI#81** — Generation collapse on Llama-3-8B. The model produces
   repetitive "br"/"k" garbage. Root cause unknown. Awaiting user test with
   KI#80 fix applied to determine if the placeholder is the sole trigger.

3. ~~**Update PATTERNS.md §6 Known Models**~~ — **DONE iter-101**. Llama-3-8B entry updated with KI#80 fix status.

4. **Consider prompt_engine.py fix** — Instead of stripping placeholders in
   local_provider.py, could we NOT insert them for the local provider? The
   placeholders are inserted for Anthropic API role alternation (KI#15), but
   the local provider doesn't need them. This would be a cleaner fix but
   requires passing provider information to `build_prompt_blocks()`.

### 10.7 Anti-pattern: AP-10 — Ghost commit (code claimed but not in diff)

**Symptom**: STATUS.md/worklog.md/smoke test document a fix that was never
actually committed to the target source file. The commit message references
the fix, but `git diff` shows 0 lines changed in the target file.

**Root cause**: The agent writes the STATUS.md/worklog.md/smoke test in the
same commit as the code change, but the code change is either forgotten or
applied to a different file. The documentation is written from the plan, not
from the actual diff.

**Observed in**: iter-77 (KI#58 — reasoning markers fix claimed but
local_provider.py never modified) and iter-99 (KI#80 — placeholder stripping
claimed but local_provider.py never modified).

**Prevention rule**: Before committing, ALWAYS run `git diff` on the target
source file and verify the change is present. Never trust "I wrote the code"
— verify the diff.
