# Soul of Waifu — STATUS

## Maintenance rules

1. **Current iteration header** — one `## Iteration N` section at the top, max ~60 lines. Root-cause chains, log evidence, acceptance criteria belong in worklog.md or git history, NOT here.
2. **History table** — one row per past iteration (iter, date, KI(s), 1-line summary). No prose blocks for old iterations.
3. **Active KIs** — only truly open/deferred items. CLOSED KIs go to the Closed KIs table (1-line summary).
4. **No historical appendices** — FAQ, hypothesis tables, "what iter-N adds" sections belong in worklog.md or git history. STATUS.md is a status snapshot, not an archive.
5. **Closed KIs** — one-line summary + closed-in-iter reference. No multi-paragraph descriptions.
6. **Trim on every iteration** — before adding a new header, archive the previous one to the history table. If the history table exceeds 30 rows, trim to the most recent 30.

---

## Iteration 111: полный пересмотр плана удаления fairseq

**Date**: 2026-08-06
**Scale**: Normal. Doc-only — no code changes. 3 files: `STATUS.md`, `worklog.md`, `docs/fairseq_removal_plan.md`.

**Task**: Заказчик отказывается от stub/monkey-patch подхода (iter-107→110). Требование: «не хочу костылей и остатков fairseq — с корнем убрать». Полный пересмотр `docs/fairseq_removal_plan.md`: вместо stub `sys.modules['fairseq']` + dual-target monkey-patch → **форк rvc-python** с заменой fairseq→HF HuBERT внутри форка.

**Изменение подхода**:
- Старый план (Путь D): stub `sys.modules` + monkey-patch `load_hubert` в двух namespace + отдельный файл `rvc_hubert_hf.py` + GAP-A/B runtime-костыли.
- Новый план (Путь A-clean): форк `JarodMica/rvc-python` → переписать `modules/vc/utils.py` (заменить `from fairseq import checkpoint_utils` на `transformers.HubertModel`) + `lib/jit/get_hubert.py` + `download_model.py` → SoW переключается на форк → `fairseq==0.12.2` удаляется из `requirements.txt` → safe_globals-костыль удаляется из `text_to_speech.py`. Никаких runtime-костылей.

### Stop point

| Field | Value |
|-------|-------|
| Done | `docs/fairseq_removal_plan.md` полностью переписан (9 разделов, ~300 строк). Подход: форк rvc-python + HF HuBERT. Нет stub'ов, нет monkey-patch'ей, нет GAP-A/B. Этапы: iter-112 (форк + правки), iter-113 (SoW: requirements.txt + text_to_speech.py), iter-114 (A/B-тест), iter-115 (cleanup docs). |
| Not done | KI#83 implementation (создание форка + правки кода). AGENT_NAVIGATION.md §1 line counts stale (5 entries). |
| Next step | iter-112: форкнуть `JarodMica/rvc-python` → `vudirvp-sketch/rvc-python`, переписать 3 файла, запушить. iter-113: SoW переключение на форк + удаление fairseq. |
| Active KIs | KI#83 (open — подход изменён на форк rvc-python; план переписан iter-111, реализация pending iter-112+) |

---

## Iteration history

| Iter | Date | KI(s) | Summary |
|------|------|-------|---------|
| 111 | 2026-08-06 | KI#83 | Plan fully revised: stub/monkey-patch → fork rvc-python + HF HuBERT (clean removal, no runtime crutches). |
| 110 | 2026-08-06 | KI#65/70/71/73→CLOSED | Fork reset: 4 old KIs closed (out of scope). `fairseq_removal_plan.md` audited — 8 factual errors fixed. Doc-only. |
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

---

## Active KIs

| KI# | Severity | Description | Status |
|-----|----------|-------------|--------|
| KI#83 | BLOCKING | fairseq→HF HuBERT replacement. Plan полностью пересмотрен iter-111: подход изменён с stub/monkey-patch на **форк rvc-python** (чистое удаление fairseq без runtime-костылей). Реализация pending iter-112+. | **OPEN** |

---

## Closed KIs

| KI# | Closed | Summary |
|-----|--------|---------|
| KI#84 | iter-109 | KI#80 placeholder-strip broke Mistral-family templates (HTTP 400 `roles must alternate`). Added `CapabilityMap.requires_role_alternation`; gating in `_strip_role_alternation_placeholders()` skips strip when True. |
| KI#73 | iter-110 | Multi-template GGUF selection — fork redirected to fairseq removal; out of scope. |
| KI#71 | iter-110 | Reasoning extraction false-positive detection — fork redirected; out of scope. |
| KI#70 | iter-110 | Stop_tokens atomic check on hot path — fork redirected; out of scope. |
| KI#65 | iter-110 | qasync task race: `start_new_dialog_main` vs `_launch_server_then_update_visibility` — fork redirected; out of scope. |
