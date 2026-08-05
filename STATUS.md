# Soul of Waifu — STATUS

## Maintenance rules

1. **Current iteration header** — one `## Iteration N` section at the top, max ~60 lines. Root-cause chains, log evidence, acceptance criteria belong in worklog.md or git history, NOT here.
2. **History table** — one row per past iteration (iter, date, KI(s), 1-line summary). No prose blocks for old iterations.
3. **Active KIs** — only truly open/deferred items. CLOSED KIs go to the Closed KIs table (1-line summary).
4. **No historical appendices** — FAQ, hypothesis tables, "what iter-N adds" sections belong in worklog.md or git history. STATUS.md is a status snapshot, not an archive.
5. **Closed KIs** — one-line summary + closed-in-iter reference. No multi-paragraph descriptions.
6. **Trim on every iteration** — before adding a new header, archive the previous one to the history table. If the history table exceeds 30 rows, trim to the most recent 30.

---

## Iteration 110: fork reset — clean up open KIs + audit fairseq_removal_plan.md

**Date**: 2026-08-06
**Scale**: Normal. Doc-only — no code changes. 3 files: `STATUS.md`, `worklog.md`, `docs/fairseq_removal_plan.md`.

**Task**: User redirected this fork (`vudirvp-sketch/Soul-of-Waifu`) to be dedicated to executing `docs/fairseq_removal_plan.md` + possible dependency audit. Clean up all open KIs inherited from previous main-line work (KI#65/70/71/73) — they are out of scope for this fork. Audit `docs/fairseq_removal_plan.md` for factual accuracy against the current repo state.

**Audit findings (`docs/fairseq_removal_plan.md`)** — 8 factual errors, all corrected in this iteration:

| Plan claim | Actual repo state | Fix |
|------------|-------------------|-----|
| `fairseq==0.12.3` at `requirements.txt:55` | `fairseq==0.12.2` at line 58 | version + line |
| `transformers==4.57.3` at `requirements.txt:212` | line 235 | line |
| `rvc-python @ git+...` at `requirements.txt:173` | line 191 | line |
| `text_to_speech.py:25` rvc_python import | line 28 | line |
| `text_to_speech.py:27-32` safe_globals hack | lines 30-35 | line |
| `text_to_speech.py:37-42` HF_HOME setup | lines 39-45 | line |
| `text_to_speech.py:195` self.rvc.load_model | line 198 | line |
| `installer.bat:93` installs rvc-python `--no-deps` | **FALSE** — `installer.bat` does NOT install rvc-python at all (line 93 = `python -m pip check`); rvc-python comes only from `requirements.txt:191` | claim removed |

KIs closed (fork redirect — out of scope): KI#65, KI#70, KI#71, KI#73.

KI#83 stays OPEN — it is the fork's main task. iter-110 audit confirmed the implementation done in iter-108/109 (main-line) is NOT present in this fork (`text_to_speech.py:30-35` still has the safe_states hack; no `rvc_hubert_hf.py`; no `_install_fairseq_stub()`; no dual-target monkey-patch). Plan must be re-executed from scratch here.

### Stop point

| Field | Value |
|-------|-------|
| Done | `docs/fairseq_removal_plan.md`: 8 factual errors fixed (§1.1, §1.6, §1.7, §2.2.1, §2.2.2, §2.2.3, §2.5 line refs + fairseq version 0.12.3→0.12.2 + installer.bat false claim removed). iter-110 audit note added to revision history. `STATUS.md`: 4 old KIs closed (KI#65/70/71/73 — fork redirect, out of scope). Three stale iter-107/108/109 prose sections collapsed into history rows. History table trimmed 31→30 (deleted iter-79 + iter-80, added iter-110). `worklog.md`: one-in-one-out (deleted iter-102, added iter-110). |
| Not done | Navigation files audit — `AGENT_NAVIGATION.md §1` line counts stale (interface_signals.py 16259→17351, custom_widgets.py 8896→9567, sowInterface.py 6730→7153, sow_system_signals.py 4234→4596, soul_stage_page.py 3357→3977). Deferred to iter-111. KI#83 implementation (the actual fairseq removal) — pending iter-112+. |
| Next step | iter-111: refresh `AGENT_NAVIGATION.md §1` file line counts (5 stale entries) + sweep §4 Pitfalls for stale KI references. iter-112: execute `docs/fairseq_removal_plan.md §2` (stub + dual-target monkey-patch + temp assert + safe_states removal). Then iter-113 A/B, iter-114 fairseq removal from `requirements.txt:58`. |
| Active KIs | KI#83 (open — fork's main task; plan audited iter-110, implementation pending) |

---

## Iteration history

| Iter | Date | KI(s) | Summary |
|------|------|-------|---------|
| 110 | 2026-08-06 | KI#65/70/71/73→CLOSED | Fork reset: 4 old KIs closed (out of scope). `fairseq_removal_plan.md` audited — 8 factual errors fixed (line numbers + version + installer.bat false claim). Doc-only. |
| 109 | 2026-08-04 | KI#84→CLOSED | Fix: KI#80 placeholder-strip broke Mistral-family templates (HTTP 400 `roles must alternate`). Added `CapabilityMap.requires_role_alternation`; strip is NO-OP when True. Smoke 18 PASS. Main-line, not in this fork. |
| 108 | 2026-08-03 | KI#83 | Implement (main-line, NOT in this fork): new `app/utils/rvc_hubert_hf.py`; `text_to_speech.py` stub + dual-target monkey-patch + 2 temp asserts + removed safe_states hack. Smoke 22 PASS. |
| 107-audit | 2026-08-02 | KI#83 | Plan-doc update: §1.7 GAP-A (import-time dep) + §1.8 GAP-B (dual-target monkey-patch) + §2.2 rewritten (4 sub-blocks) + §9 audit checklist. |
| 107 | 2026-08-02 | KI#83 | Plan: remove `fairseq` via HF HuBERT (`facebook/hubert-base-ls960`); new `docs/fairseq_removal_plan.md`. Audit found 2 gaps. |
| 106 | 2026-08-02 | — | Doc update: added `docs/template_detection_pipeline_corrected.md` §5 reasoning pipeline section. |
| 105 | 2026-08-02 | KI#82→CLOSED | 3-model log analysis: `<\|start_header_id\|>` mitigation ineffective for base model. KI#82 CLOSED as model limitation. |
| 104 | 2026-08-02 | KI#82 | Verified stop words ✅ + chat template ✅ + KI#80 ✅. Added `<\|start_header_id\|>` to Llama-3 stop tokens. |
| 103 | 2026-08-02 | KI#81→CLOSED, KI#82 | Full-response DEBUG logging; KI#81 closed (max_tokens fixed); KI#82 opened. |
| 102 | 2026-08-02 | KI#81 | Research: root cause = max_tokens=875 truncation + 3 code bugs. |
| 101 | 2026-08-02 | KI#80 | Implement `_strip_role_alternation_placeholders()` in local_provider.py. |
| 100 | 2026-08-02 | KI#81 | Deep analysis: KI#80 never implemented (AP-10 ghost commit). |
| 99 | 2026-08-02 | KI#80 | Strip role-alternation placeholders — **CODE NOT ACTUALLY COMMITTED**. |
| 98 | 2026-08-01 | — | STATUS.md + worklog.md cleanup. |
| 97 | 2026-08-01 | KI#79 | Auto-apply `--override-kv tokenizer.ggml.pre` for BPE GGUFs missing the field. |
| 96 | 2026-08-01 | KI#78 | Unambiguous-arch guard prevents cross-family Jinja overrides. |
| 95 | 2026-08-01 | KI#77 | Qwen3.5 EOS drift false positive fixed; eos_drift gate removed. |
| 94 | 2026-08-01 | — | Verification of iter-93; 3/4 models tested; KI#76 not opened. |
| 93 | 2026-08-01 | KI#75, KI#72 | `--reasoning on/off` gated on `enable_thinking`; pre-tokenizer warning detection. |
| 92 | 2026-08-01 | KI#72↑, KI#75 | Verified external LLM failure-pattern text; resolved 4 contradictions. |
| 91 | 2026-08-01 | KI#75 | Deep analysis of Llama-3 + Qwen3.5 regressions; KI#75 identified. |
| 90 | 2026-08-01 | KI#74 | Gate `reasoning_budget_tokens` on `capability_map.enable_thinking` + eos_drift. |
| 89 | 2026-08-01 | KI#68, KI#69 | Unique-family markers; eos_token_id drift detection. |
| 88 | 2026-08-01 | KI#66, KI#67 | Jinja inference ChatML/Qwen3-thinking distinction; eternal CONNECTING fix. |
| 86 | 2026-08-01 | KI#61-63 | Settings persistence atomicity; logging gap; installer.bat llama-server version check. |
| 85 | 2026-08-01 | KI#59 | Cloud API provider fixes (cross-provider parity). |
| 84 | 2026-08-01 | — | Cleanup stale smoke tests from iter-78/80. |
| 83 | 2026-08-01 | — | DeepSeek provider parity. |
| 82 | 2026-08-01 | — | UI slider for `reasoning_budget_fraction`. |
| 80.1 | 2026-08-01 | — | `reasoning_budget_message` opt-in injection. |

---

## Active KIs

| KI# | Severity | Description | Status |
|-----|----------|-------------|--------|
| KI#83 | BLOCKING | fairseq→HF HuBERT replacement. Plan audited iter-110 (8 factual errors fixed in `docs/fairseq_removal_plan.md`). Implementation per §2 (stub `sys.modules['fairseq']` + dual-target monkey-patch `utils.load_hubert` + `modules.load_hubert` + temp assert + safe_states removal) PENDING — fork's main task. iter-108/109 main-line implementation NOT in this fork; must re-execute from scratch. | **OPEN** |

---

## Closed KIs

| KI# | Closed | Summary |
|-----|--------|---------|
| KI#84 | iter-109 | KI#80 placeholder-strip broke Mistral-family templates (HTTP 400 `roles must alternate`). Added `CapabilityMap.requires_role_alternation`; gating in `_strip_role_alternation_placeholders()` skips strip when True. |
| KI#73 | iter-110 | Multi-template GGUF selection — fork redirected to fairseq removal; out of scope. |
| KI#71 | iter-110 | Reasoning extraction false-positive detection — fork redirected; out of scope. |
| KI#70 | iter-110 | Stop_tokens atomic check on hot path — fork redirected; out of scope. |
| KI#65 | iter-110 | qasync task race: `start_new_dialog_main` vs `_launch_server_then_update_visibility` — fork redirected; out of scope. |
