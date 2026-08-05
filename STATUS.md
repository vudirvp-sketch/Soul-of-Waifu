# Soul of Waifu — STATUS

## Maintenance rules

1. **Current iteration header** — one `## Iteration N` section at the top, max ~60 lines. Root-cause chains, log evidence, acceptance criteria belong in worklog.md or git history, NOT here.
2. **History table** — one row per past iteration (iter, date, KI(s), 1-line summary). No prose blocks for old iterations.
3. **Active KIs** — only truly open/deferred items. CLOSED KIs go to the Closed KIs table (1-line summary).
4. **No historical appendices** — FAQ, hypothesis tables, "what iter-N adds" sections belong in worklog.md or git history. STATUS.md is a status snapshot, not an archive.
5. **Closed KIs** — one-line summary + closed-in-iter reference. No multi-paragraph descriptions.
6. **Trim on every iteration** — before adding a new header, archive the previous one to the history table. If the history table exceeds 30 rows, trim to the most recent 30.

---

## Iteration 109: fix — KI#80 breaks Mistral-family chat templates (KI#84)

**Date**: 2026-08-04
**Scale**: Normal. Edits in 3 files (`template_detector.py`, `ai_factory.py`, `local_provider.py`) + 1 new smoke test. No new deps. No schema changes.

**Task**: KI#80 (`_strip_role_alternation_placeholders()` in `local_provider.py`, iter-101) strips `[conversation continued]` placeholder messages before sending to llama-server. This was correct for Llama-3-8B (model echoed the placeholder text). But for Mistral-family models (e.g. `MN-Violet-Lotus-12B`, Tekken tokenizer, embedded Jinja = `mistral-v0-1`), the template's Jinja contains `raise_exception("After the optional system message, conversation roles must alternate user/assistant/...")` — stripping the placeholder makes the prompt `system → assistant → user` (instead of `system → user(placeholder) → assistant → user`) → HTTP 400 from llama-server before generation starts.

**Fix** (3 layers):
1. `template_detector.py` — add `requires_role_alternation: bool` to `CapabilityMap`; populate via Jinja-source inspection (`"roles must alternate"` substring) in `compute_capability_map()` AND via template-name fallback (`"mistral"` substring) in `_capability_map_from_template_name()`.
2. `ai_factory.py` — forward `requires_role_alternation` from `detection_result.capability_map` to `LocalProvider.__init__()`.
3. `local_provider.py` — `_strip_role_alternation_placeholders()` accepts `requires_role_alternation` kwarg; when True → NO-OP (returns messages unchanged). All 3 call sites pass `self._requires_role_alternation`.

**Result**: smoke test 18 PASS / 0 FAIL. KI#80 behavior preserved for non-Mistral models (Llama-3 echo fix still works). KI#84 CLOSED.

### Stop point

| Field | Value |
|-------|-------|
| Done | `template_detector.py`: `CapabilityMap.requires_role_alternation` field + `compute_capability_map()` Jinja-source detection + `_capability_map_from_template_name()` Mistral-name fallback. `ai_factory.py`: forwards `requires_role_alternation` to LocalProvider. `local_provider.py`: `__init__` accepts kwarg (`self._requires_role_alternation`); `_strip_role_alternation_placeholders()` accepts `requires_role_alternation` kwarg → NO-OP when True; all 3 generation methods updated. `scripts/iter109_smoke_test.py`: 18 PASS / 0 FAIL across 8 groups. Housekeeping: STATUS.md — KI#82 deleted from Closed KIs (>2 iterations closed, §3 rule); worklog.md one-in-one-out (deleted iter-101 entry). |
| Not done | iter-110 fairseq removal from requirements.txt (still pending A/B at iter-109-fairseq-AB — unrelated to this fix). User A/B test with `MN-Violet-Lotus-12B` to confirm HTTP 400 is gone. |
| Next step | User runs `MN-Violet-Lotus-12B` and verifies chat works. If new template-related issues appear, open KI#85. Otherwise iter-110 fairseq removal. |
| Active KIs | KI#65 (open) · KI#70 (deferred) · KI#71 (deferred) · KI#73 (deferred) · KI#83 (open — implementation done iter-108, A/B pending iter-109-AB-branch, fairseq removal pending iter-110) |

---

## Iteration 108: implement — fairseq→HF HuBERT monkey-patch (KI#83)

**Date**: 2026-08-03
**Scale**: Normal. 1 new file (~240 lines) + edits in `text_to_speech.py` (stub + dual-target monkey-patch + temp assert + removed safe_states hack) + 1 new smoke test.

**Task**: Implement KI#83 per `docs/fairseq_removal_plan.md` §2.2 — exactly 4 sub-blocks in the order specified: §2.2.1 stub `sys.modules['fairseq']`, §2.2.2 rvc_python import after stub, §2.2.3 dual-target monkey-patch (`utils.load_hubert` + `modules.load_hubert`), §2.2.4 temp assert. Delete safe_states hack per §2.3. **fairseq NOT removed from requirements.txt** (fallback path; removal is iter-110).

**Implementation**:
1. New `app/utils/rvc_hubert_hf.py` — `HubertHFWrapper(nn.Module)` wraps `transformers.HubertModel`, reproduces fairseq contract: `extract_features(source, padding_mask, output_layer=9|12) → (feats, padding_mask)`, lazy `final_proj()` loader for RVC v1. Resolves inner model device via `next(self.model.parameters()).device` (works with both real HubertModel AND bare nn.Module stand-ins).
2. `text_to_speech.py` top-of-module (lines 24-116): `_install_fairseq_stub()` injects `sys.modules['fairseq']` + `sys.modules['fairseq.checkpoint_utils']` if real fairseq absent; then `from rvc_python.infer import RVCInference`; then dual-target patch `_rvc_utils.load_hubert = _rvc_modules.load_hubert = _hf_load_hubert`; then 2 temp asserts (`modules` + `utils`) — DELETE before iter-109. Old `torch.serialization.add_safe_globals([Dictionary])` hack removed.
3. `scripts/iter108_smoke_test.py` — 22 tests across 6 groups: G1 GAP-A stub, G2 GAP-B dual-target, G3 stub no-op when real fairseq present, G4 HubertHFWrapper contract (2-tuple return, `logits[0]` indexing, `output_layer=9|12`, `padding_mask=None`, `final_proj` raises for v1), G5 temp assert present + safe_states removed, G6 end-to-end `vc_single()` bare-name resolution.

**Result**: 22 PASS / 0 FAIL. All 7 invariants from §9 audit checklist verified.

**Env note**: smoke test runs in Python 3.12 venv with mock rvc_python (mirrors @9a67ac7 structure including `from .utils import *` rebind) + fake transformers.HubertModel. Real rvc-python install fails on Python 3.12 (old numpy build dep). Real-package integration test happens at iter-109 A/B on user's Windows env.

### Stop point

| Field | Value |
|-------|-------|
| Done | `app/utils/rvc_hubert_hf.py` (new, 240 lines). `text_to_speech.py`: stub `_install_fairseq_stub()` (§2.2.1) + `from rvc_python.infer import RVCInference` after stub (§2.2.2) + dual-target monkey-patch `_rvc_utils.load_hubert = _rvc_modules.load_hubert = _hf_load_hubert` (§2.2.3) + 2 temp asserts (§2.2.4). Old safe_states hack (lines 27-32) removed (§2.3). `scripts/iter108_smoke_test.py`: 22 PASS / 0 FAIL across 6 groups. Housekeeping: STATUS.md history table trimmed 44→30 rows; worklog.md one-in-one-out (deleted iter-100 entry). |
| Not done | iter-109 A/B-test (real rvc-python + real HuBERT weights on Windows env). iter-110: remove `fairseq` from `requirements.txt:55` + delete temp assert §2.2.4 (preconditions: A/B passes — see §2.5). iter-111 optional: monkey-patch `download_rvc_models` to skip `hubert_base.pt`. |
| Next step | iter-109: write A/B script (same `.pth` + same WAV, run fairseq path via temporary patch revert, run HF path, compare mel-spectrogram RMS <1%, blind listening). Confirm `_hf_load_hubert` log line `HuBERT loaded via HF` appears in HF-side log. Delete temp assert §2.2.4 before A/B run. |
| Active KIs | KI#65 (open) · KI#70 (deferred) · KI#71 (deferred) · KI#73 (deferred) · KI#83 (open — implementation done iter-108, A/B pending iter-109, fairseq removal pending iter-110) |

---

## Iteration 107: plan — remove fairseq via HF HuBERT (`facebook/hubert-base-ls960`)

**Date**: 2026-08-02
**Scale**: Normal (planning). Doc-only. No code changes.

**Task**: User wants to remove `fairseq` dep. Asked: does a transformers version of the HuBERT model used in SoW exist? Plan needed. Audit: verify plan completeness + that fairseq is really not used elsewhere.

**Findings**:
1. `facebook/hubert-base-ls960` (HF, 889k downloads) — architecturally identical to `hubert_base.pt`: 12 layers, hidden=768, group-norm conv, `do_stable_layer_norm=false` (=fairseq `layer_norm_first=False`).
2. SoW repo: only fairseq usage = `text_to_speech.py:27-32` safe_globals hack. ✓ Verified by full repo grep.
3. rvc-python@9a67ac7 fairseq usage map (verified from upstream source):
   - `modules/vc/utils.py:3` — top-level `from fairseq import checkpoint_utils` (executed at import time, NOT just runtime).
   - `modules/vc/utils.py:21` — `load_hubert()` body uses `checkpoint_utils.load_model_ensemble_and_task`. Runtime entry point.
   - `lib/jit/get_hubert.py:4,10` — two fairseq imports; file is ONNX-export-only, NOT in `__init__.py` chain. ✓
4. rvc-python's own `requirements.txt` does NOT list fairseq — only SoW `requirements.txt:55` puts it in env. Installer uses `--no-deps` (line 93).
5. `load_model` defaults to v2 (`infer.py:65`); v2 path (`pipeline.py:223`) does NOT use `final_proj`. HF model sufficient.
6. `transformers==4.57.3` already in `requirements.txt:212` — no new deps. `fairseq==0.12.3` (line 55) is the only removal target.

**Plan** (full in `docs/fairseq_removal_plan.md`):
- iter-108: create `app/utils/rvc_hubert_hf.py` + monkey-patch `rvc_python.modules.vc.utils.load_hubert` in `text_to_speech.py`. Keep fairseq as fallback.
- iter-109: A/B-test (spectrogram RMS <1% + blind listening).
- iter-110: if A/B passes — remove `fairseq` from `requirements.txt`, delete safe_globals hack.
- iter-111 (optional): monkey-patch `download_rvc_models` to skip `hubert_base.pt` download (~370 MB saved).

**Audit (iter-107 follow-up) — KI#83 OPEN**:
Plan had 2 critical gaps. Fixed in plan doc (`docs/fairseq_removal_plan.md`, iter-107-audit rev):
- **GAP-A** (§1.7, §2.2.1): `rvc_python/modules/vc/utils.py:3` has top-level `from fairseq import checkpoint_utils`. Triggered at SoW startup via `__init__.py`→`infer.py`→`modules.py:19 from utils import *`→`utils.py:3`. Monkey-patching `load_hubert` does NOT neutralize this. Removing fairseq from requirements.txt will cause `ModuleNotFoundError: fairseq` at app launch. Fix in plan: inject stub `fairseq` module into `sys.modules` BEFORE `from rvc_python.infer import RVCInference`.
- **GAP-B** (§1.8, §2.2.3): Plan patches `rvc_python.modules.vc.utils.load_hubert`, but `modules/vc/modules.py:19` does `from rvc_python.modules.vc.utils import *` — binds `load_hubert` into `modules.vc.modules` namespace. `vc_single()` at `modules.py:168` calls bare `load_hubert(...)`, resolving from `modules.vc.modules` globals — NOT `modules.vc.utils`. Patch silently no-ops. Fix in plan: patch BOTH `utils.load_hubert` AND `modules.load_hubert`. Temp assert §2.2.4 catches regression on first run.
- Minor fixes: §3 ref → §4 (Pitfalls); §4 A/B memory note 1.5 GB → ~370 MB weights; added §9 audit checklist (7 items).

### Stop point

| Field | Value |
|-------|-------|
| Done | Audit + plan-update complete. `docs/fairseq_removal_plan.md` revised: §1.7 (GAP-A) + §1.8 (GAP-B) added; §2.2 rewritten into 4 sub-blocks (stub, import, dual-target monkey-patch, temp assert); §3 stages updated (iter-108 includes A+B fixes); §5 risks gains GAP-A/B rows; §6 notes `lib/jit/get_hubert.py` untouched; §9 audit checklist added. KI#83 stays OPEN (implementation pending iter-108). |
| Not done | Code implementation (iter-108). Plan is now ready for iter-108 — no blockers. |
| Next step | iter-108: implement per §2.2 (stub → import → dual-target monkey-patch → temp assert), then delete safe_globals per §2.3, all in one commit. Run iter-108 smoke test with assert §2.2.4 enabled. iter-109 A/B. iter-110 fairseq removal from requirements.txt (preconditions in §2.5). |
| Active KIs | KI#65 (open) · KI#70 (deferred) · KI#71 (deferred) · KI#73 (deferred) · KI#83 (open — plan-stage fixed, implementation pending iter-108) |

---

## Iteration history

| Iter | Date | KI(s) | Summary |
|------|------|-------|---------|
| 109 | 2026-08-04 | KI#84→CLOSED | Fix: KI#80 placeholder-strip broke Mistral-family templates (HTTP 400 Jinja `roles must alternate`). Added `CapabilityMap.requires_role_alternation` (Jinja-source + name fallback); `ai_factory` forwards it; `_strip_role_alternation_placeholders()` is NO-OP when True. Smoke 18 PASS. |
| 108 | 2026-08-03 | KI#83 | Implement: new `app/utils/rvc_hubert_hf.py` (HubertHFWrapper, 240 lines); `text_to_speech.py` stub `_install_fairseq_stub()` + dual-target monkey-patch (`utils` + `modules`) + 2 temp asserts + removed safe_states hack. Smoke test 22 PASS / 0 FAIL. fairseq NOT removed (iter-110). |
| 107-audit | 2026-08-02 | KI#83 | Plan-doc update: §1.7 GAP-A (import-time dep) + §1.8 GAP-B (dual-target monkey-patch) + §2.2 rewritten (4 sub-blocks: stub/import/patch/assert) + §9 audit checklist. Plan-stage fixed; implementation pending iter-108. |
| 107 | 2026-08-02 | KI#83 | Plan: remove `fairseq` via HF HuBERT (`facebook/hubert-base-ls960`); new `docs/fairseq_removal_plan.md`. Audit found 2 gaps (KI#83 OPEN): import-time fairseq dep + wrong monkey-patch target. |
| 106 | 2026-08-02 | — | Doc update: added `docs/template_detection_pipeline_corrected.md` with new §5 reasoning pipeline section; fixed §4 eos_drift gate error (iter-95 KI#77). |
| 105 | 2026-08-02 | KI#82→CLOSED | 3-model log analysis: `<\|start_header_id\|>` mitigation ineffective for base model. KI#82 CLOSED as model limitation. |
| 104 | 2026-08-02 | KI#82 | Verified stop words ✅ + chat template ✅ + KI#80 ✅ — all correct. Added `<\|start_header_id\|>` to Llama-3 stop tokens (mitigation #1). Confirmed root cause = base model + system prompt. |
| 103 | 2026-08-02 | KI#81→CLOSED, KI#82 | Full-response DEBUG logging; KI#81 closed (max_tokens fixed); KI#82 opened — base model runaway generation |
| 102 | 2026-08-02 | KI#81 | Research: root cause = max_tokens=875 truncation + 3 code bugs. Template/stop/reasoning verified correct. |
| 101 | 2026-08-02 | KI#80 | Implement `_strip_role_alternation_placeholders()` in local_provider.py |
| 100 | 2026-08-02 | KI#81 | Deep analysis: KI#80 never implemented (AP-10 ghost commit), new generation collapse symptom |
| 99 | 2026-08-02 | KI#80 | Strip role-alternation placeholders — **CODE NOT ACTUALLY COMMITTED** |
| 98 | 2026-08-01 | — | STATUS.md + worklog.md cleanup |
| 97 | 2026-08-01 | KI#79 | Auto-apply `--override-kv tokenizer.ggml.pre` for BPE GGUFs missing the field |
| 96 | 2026-08-01 | KI#78 | Unambiguous-arch guard prevents cross-family Jinja overrides |
| 95 | 2026-08-01 | KI#77 | Qwen3.5 EOS drift false positive fixed; eos_drift gate removed |
| 94 | 2026-08-01 | — | Verification of iter-93; 3/4 models tested; KI#76 not opened |
| 93 | 2026-08-01 | KI#75, KI#72 | `--reasoning on/off` gated on `enable_thinking`; pre-tokenizer warning detection |
| 92 | 2026-08-01 | KI#72↑, KI#75 | Verified external LLM failure-pattern text; resolved 4 contradictions |
| 91 | 2026-08-01 | KI#75 | Deep analysis of Llama-3 + Qwen3.5 regressions; KI#75 identified |
| 90 | 2026-08-01 | KI#74 | Gate `reasoning_budget_tokens` on `capability_map.enable_thinking` + eos_drift |
| 89 | 2026-08-01 | KI#68, KI#69 | Unique-family markers; eos_token_id drift detection |
| 88 | 2026-08-01 | KI#66, KI#67 | Jinja inference ChatML/Qwen3-thinking distinction; eternal CONNECTING fix |
| 86 | 2026-08-01 | KI#61-63 | Settings persistence atomicity; logging gap; installer.bat llama-server version check |
| 85 | 2026-08-01 | KI#59 | Cloud API provider fixes (cross-provider parity) |
| 84 | 2026-08-01 | — | Cleanup stale smoke tests from iter-78/80 |
| 83 | 2026-08-01 | — | DeepSeek provider parity |
| 82 | 2026-08-01 | — | UI slider for `reasoning_budget_fraction` |
| 80.1 | 2026-08-01 | — | `reasoning_budget_message` opt-in injection |
| 80 | 2026-08-01 | KI#60 | Per-request `reasoning_budget_tokens` sub-cap (Variant B) |
| 79 | 2026-08-01 | — | Diagnostics Panel in-place expand toggle |
---

## Active KIs

| KI# | Severity | Description | Status |
|-----|----------|-------------|--------|
| KI#65 | NON-BLOCKING | qasync task race: `start_new_dialog_main` vs `_launch_server_then_update_visibility`. | **OPEN** |
| KI#70 | DEFERRED | Stop_tokens atomic check on hot path — verify each stop_token string is present as atomic token in vocab. | **DEFERRED** |
| KI#71 | DEFERRED | Reasoning extraction false-positive detection — when `enable_thinking=False` and `reasoning_chunks > 0`, emit WARNING. | **DEFERRED** |
| KI#73 | DEFERRED | Multi-template GGUF selection — when `multi_tmpl > 0`, explicitly select thinking/non-thinking variant by `reasoning_mode`. | **DEFERRED** |
| KI#83 | BLOCKING | fairseq→HF HuBERT replacement. iter-108 IMPLEMENTED: stub `sys.modules['fairseq']` (GAP-A) + dual-target monkey-patch `utils.load_hubert` + `modules.load_hubert` (GAP-B) + temp assert + removed safe_states hack. Smoke test 22/22 PASS. PENDING: iter-109-AB A/B-test, iter-110 remove `fairseq` from `requirements.txt:55`. See `docs/fairseq_removal_plan.md` §1.7, §1.8, §2.2, §9. | **OPEN** |

---

## Closed KIs

| KI# | Closed | Summary |
|-----|--------|---------|
| KI#84 | iter-109 | KI#80 placeholder-strip broke Mistral-family templates (HTTP 400 `roles must alternate`). Added `CapabilityMap.requires_role_alternation`; gating in `_strip_role_alternation_placeholders()` skips strip when True. |
