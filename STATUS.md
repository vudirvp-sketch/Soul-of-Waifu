# Soul of Waifu — STATUS

## Maintenance rules

1. **Current iteration header** — one `## Iteration N` section at the top, max ~60 lines. Root-cause chains, log evidence, acceptance criteria belong in worklog.md or git history, NOT here.
2. **History table** — one row per past iteration (iter, date, KI(s), 1-line summary). No prose blocks for old iterations.
3. **Active KIs** — only truly open/deferred items. CLOSED KIs go to the Closed KIs table (1-line summary).
4. **No historical appendices** — FAQ, hypothesis tables, "what iter-N adds" sections belong in worklog.md or git history. STATUS.md is a status snapshot, not an archive.
5. **Closed KIs** — one-line summary + closed-in-iter reference. No multi-paragraph descriptions.
6. **Trim on every iteration** — before adding a new header, archive the previous one to the history table. If the history table exceeds 30 rows, trim to the most recent 30.

---

## Iteration 112: верификация iter-111 плана — 6 критических ошибок найдено и исправлено

**Date**: 2026-08-06
**Scale**: Normal. Doc-only — no code changes. 3 files: `STATUS.md`, `worklog.md`, `docs/fairseq_removal_plan.md`.

**Task**: Заказчик попросил перепроверить всё исследование iter-111, убедиться что решение «ультимативное со всех сторон». Клонированы и проверены upstream-репозитории: daswer123/rvc-python (PyPI upstream), JarodMica/rvc-python (текущий SoW pin), RVC-Project/Retrieval-based-Voice-Conversion-WebUI (official), JackismyShephard/ultimate-rvc (пропущенная альтернатива). Проверены 3 HF-модели, 6 PyPI-пакетов rvc, контракт extract_features.

**Найдено 6 ошибок в iter-111 плане** (KI#85 открыт):
1. **HF-модель**: iter-111 указывал `facebook/hubert-base-ls960` (стандартный HuBERT для ASR). RVC обучен против ContentVec — стандартный HuBERT даёт неправильные фичи. Исправлено: `lengyue233/content-vec-best` (ContentVec в HF формате).
2. **HubertHFWrapper**: iter-111 использовал plain `HubertModel` → `final_proj` выбрасывал RuntimeError → ломал v1-модели. Исправлено: наследует `HubertModelWithFinalProj` (3-строчный подкласс из официального RVC `infer/hubert.py`), загружает `final_proj` веса из ContentVec.
3. **attention_mask**: iter-111 передавал `~padding_mask` (bool tensor) в HF. Исправлено: `(~padding_mask.bool()).long()` (LongTensor, 1=real token) — каноничный паттерн из официального RVC.
4. **pyproject.toml форка**: iter-111 утверждал «rvc-python НЕ перечисляет fairseq в зависимостях». Это верно для JarodMica@9a67ac7 (SoW pin), но НЕверно для daswer123@0.1.5 (рекомендованная база форка) — там `fairseq==0.12.2` явно пинит. Добавлен шаг: удалить `"fairseq==0.12.2"` из `pyproject.toml` в форке.
5. **JarodMica characterization**: iter-111 исследование называло JarodMica/rvc-python «ноу-нейм форк (12★)». Реальность: активный форк, last commit Mar 2026, автор вносил правки (May 2025 «fix hubert issues», Mar 2026 «Update library to change where sources are downloaded from»). Не «ноу-нейм».
6. **Пропущенные альтернативы**: найдено 2 fairseq-free пакета на PyPI: `ultimate-rvc==0.6.0` (318★, MIT, `transformers==4.57.3` — точное совпадение с SoW, Python 3.12+) и `zerorvc==0.0.19`. Ultimate-rvc отклонён как drop-in replacement (приносит ~30 тяжёлых deps, другой API), но его `HubertModelWithFinalProj` + `load_embedding` код использован как референс.

### Stop point

| Field | Value |
|-------|-------|
| Done | Верификация завершена. 6 ошибок найдено и исправлено в `docs/fairseq_removal_plan.md`: §1.1 (правильное описание зависимостей daswer123 vs JarodMica), §1.5 (ContentVec вместо стандартного HuBERT), §1.6 (v1+v2 контракт через HubertModelWithFinalProj), §1.7 (pyproject.toml шаг добавлен), §2.3 (полная переработка HubertHFWrapper), §3 (этапы пересчитаны: iter-112 verification, iter-113 fork, iter-114 SoW, iter-115 A/B, iter-116 cleanup), §5 (риски обновлены), §7 (добавлены Путь E ultimate-rvc, Путь F inline, Путь G torchaudio), §9 (audit checklist 10→14 пунктов). KI#85 открыт в STATUS.md. |
| Not done | Реализация (iter-113: форк + правки) — pending решения заказчика. |
| Next step | Заказчик одобряет пересмотренный план → iter-113: форкнуть `daswer123/rvc-python@cff3ffb`, реализовать §2.3-2.5 + удалить fairseq из pyproject.toml. |
| Active KIs | KI#83 (open), KI#85 (open — 6 ошибок iter-111 плана исправлены iter-112; будет закрыт после A/B-теста iter-115). |

---

## Iteration history

| Iter | Date | KI(s) | Summary |
|------|------|-------|---------|
| 112 | 2026-08-06 | KI#85 | Verification of iter-111 plan against upstream: 6 errors found & fixed (wrong HF model facebook/hubert-base-ls960 → lengyue233/content-vec-best; plain HubertModel → HubertModelWithFinalProj; attention_mask type; pyproject.toml fairseq dep; JarodMica characterization; missed ultimate-rvc/zerorvc alternatives). |
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
| KI#83 | BLOCKING | fairseq→HF ContentVec replacement. Plan полностью пересмотрен iter-111, верифицирован и исправлен iter-112 (KI#85). Реализация pending iter-113+ (форк daswer123/rvc-python@cff3ffb). | **OPEN** |
| KI#85 | BLOCKING | 6 ошибок в iter-111 плане: (1) неверная HF-модель `facebook/hubert-base-ls960` вместо ContentVec; (2) plain HubertModel ломает v1; (3) attention_mask bool vs Long; (4) daswer123 pyproject.toml пинит fairseq; (5) JarodMica — активный форк; (6) пропущены ultimate-rvc/zerorvc. Все 6 исправлены в плане iter-112. Закроется после A/B-теста iter-115. | **OPEN** |

---

## Closed KIs

| KI# | Closed | Summary |
|-----|--------|---------|
| KI#84 | iter-109 | KI#80 placeholder-strip broke Mistral-family templates (HTTP 400 `roles must alternate`). Added `CapabilityMap.requires_role_alternation`; gating in `_strip_role_alternation_placeholders()` skips strip when True. |
| KI#73 | iter-110 | Multi-template GGUF selection — fork redirected to fairseq removal; out of scope. |
| KI#71 | iter-110 | Reasoning extraction false-positive detection — fork redirected; out of scope. |
| KI#70 | iter-110 | Stop_tokens atomic check on hot path — fork redirected; out of scope. |
| KI#65 | iter-110 | qasync task race: `start_new_dialog_main` vs `_launch_server_then_update_visibility` — fork redirected; out of scope. |
