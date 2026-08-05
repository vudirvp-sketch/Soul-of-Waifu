# Soul of Waifu — STATUS

## Maintenance rules

1. **Current iteration header** — one `## Iteration N` section at the top, max ~60 lines. Root-cause chains, log evidence, acceptance criteria belong in worklog.md or git history, NOT here.
2. **History table** — one row per past iteration (iter, date, KI(s), 1-line summary). No prose blocks for old iterations.
3. **Active KIs** — only truly open/deferred items. CLOSED KIs go to the Closed KIs table (1-line summary).
4. **No historical appendices** — FAQ, hypothesis tables, "what iter-N adds" sections belong in worklog.md or git history. STATUS.md is a status snapshot, not an archive.
5. **Closed KIs** — one-line summary + closed-in-iter reference. No multi-paragraph descriptions.
6. **Trim on every iteration** — before adding a new header, archive the previous one to the history table. If the history table exceeds 30 rows, trim to the most recent 30.

---

## Iteration 113-doc: KI#86 — numpy/faiss dependency-trap в rvc-python (тот же pattern, что fairseq)

**Date**: 2026-08-06
**Scale**: Normal. Doc-only — no code changes. 3 files: `STATUS.md`, `worklog.md`, `docs/fairseq_removal_plan.md`.

**Task**: Заказчик проверил iter-112 план через сторонний отчёт (Politrees/contentvec + модификация pipeline.py). Перепроверен каждый пункт отчёта против реального кода: 5 утверждений подтверждены, 5 опровергнуты/уточнены. Главное открытие: **7-я ошибка iter-112 плана** (KI#85 ловил 6, эта пропущена) — `pyproject.toml` rvc-python пинит `numpy<=1.23.5` и `faiss-cpu==1.7.3`, что воспроизводит тот же dependency-trap pattern, что `fairseq==0.12.2`. SoW пинит `numpy==1.26.4` → resolver conflict.

**Что сделано**:
1. Открыт KI#86 (BLOCKING) — отдельно от KI#85, т.к. это другой класс ошибок (upstream pin lock-in vs implementation correctness).
2. В `docs/fairseq_removal_plan.md` добавлен §1.8 (52 строки) с таблицей upstream-пинов daswer123@cff3ffb vs JarodMica@782467a vs SoW, объяснением почему `numpy<=1.23.5` критичен, контрактом `faiss-cpu` (единственное использование `read_index` в `pipeline.py:313`), решением (`numpy>=1.21,<3` + `faiss-cpu>=1.7,<2`), verification script.
3. §3 stages: iter-113 шаги расширены — добавлен relaxation numpy/faiss + verification script.
4. §5 риски: добавлены 2 строки про numpy 2.x compat и faiss-cpu 1.8.x compat.
5. §8 итог: добавлена разблокировка KI#86.
6. §9 audit checklist: 14→18 пунктов (4 новых про numpy/faiss verification).
7. История ревизий (header) обновлена iter-113-doc entry.

**Проверено через прямое клонирование**: daswer123@cff3ffb и JarodMica@782467a — оба пинят `numpy<=1.23.5` + `faiss-cpu==1.7.3` одинаково. JarodMica bumped только `omegaconf` (2.0.6→2.3.0, May 2025).

### Stop point

| Field | Value |
|-------|-------|
| Done | KI#86 открыт. `docs/fairseq_removal_plan.md` обновлён: §1.8 (новый, 52 строки), §3 (iter-113 шаги расширены), §5 (+2 риска), §8 (разблокировка KI#86), §9 (14→18 пунктов), header (история ревизий +1). Проверены все утверждения стороннего отчёта: Politrees/RVC_resources и lengyue233/content-vec-best — config.json байт-в-байт идентичны (та же модель, 378 МБ). Подтверждено: отчёт — это переоткрытие iter-112 плана с меньшей точностью. |
| Not done | Реализация (iter-114: форк rvc-python + правки) — pending решения заказчика. |
| Next step | Заказчик одобряет пересмотренный план → iter-114: форкнуть `daswer123/rvc-python@cff3ffb`, реализовать §2.3-2.5 + удалить fairseq из pyproject.toml + расслабить numpy/faiss пины (§1.8) + запустить verification script. |
| Active KIs | KI#83 (open), KI#85 (open — 6 ошибок, ждёт A/B-test iter-116), KI#86 (open — 7-я ошибка, ждёт verification script iter-114). |

---

## Iteration history

| Iter | Date | KI(s) | Summary |
|------|------|-------|---------|
| 113-doc | 2026-08-06 | KI#86 | 7th error in iter-112 plan found via 3rd-party report cross-check: rvc-python pyproject pins `numpy<=1.23.5` + `faiss-cpu==1.7.3` — same dependency-trap as fairseq. Plan §1.8 + §3/§5/§8/§9 updated. Verified daswer123@cff3ffb + JarodMica@782467a both pin numpy/faiss identically (JarodMica only bumped omegaconf). |
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

---

## Active KIs

| KI# | Severity | Description | Status |
|-----|----------|-------------|--------|
| KI#83 | BLOCKING | fairseq→HF ContentVec replacement. Plan полностью пересмотрен iter-111, верифицирован и исправлен iter-112 (KI#85) + iter-113-doc (KI#86). Реализация pending iter-114+ (форк daswer123/rvc-python@cff3ffb). | **OPEN** |
| KI#85 | BLOCKING | 6 ошибок в iter-111 плане: (1) неверная HF-модель `facebook/hubert-base-ls960` вместо ContentVec; (2) plain HubertModel ломает v1; (3) attention_mask bool vs Long; (4) daswer123 pyproject.toml пинит fairseq; (5) JarodMica — активный форк; (6) пропущены ultimate-rvc/zerorvc. Все 6 исправлены в плане iter-112. Закроется после A/B-теста iter-116. | **OPEN** |
| KI#86 | BLOCKING | 7-я ошибка iter-112 плана (найдена iter-113-doc через сторонний отчёт): `pyproject.toml` rvc-python пинит `numpy<=1.23.5` и `faiss-cpu==1.7.3` — тот же dependency-trap pattern, что `fairseq==0.12.2`. SoW пинит `numpy==1.26.4` → resolver conflict или тихая установка несовместимой версии. Проверено: daswer123@cff3ffb и JarodMica@782467a пинят одинаково (JarodMica bumped только omegaconf). Решение: в форке relax `numpy<=1.23.5` → `numpy>=1.21,<3`, `faiss-cpu==1.7.3` → `faiss-cpu>=1.7,<2` + verification script в чистом venv. Закроется после verification script iter-114. | **OPEN** |

---

## Closed KIs

| KI# | Closed | Summary |
|-----|--------|---------|
| KI#84 | iter-109 | KI#80 placeholder-strip broke Mistral-family templates (HTTP 400 `roles must alternate`). Added `CapabilityMap.requires_role_alternation`; gating in `_strip_role_alternation_placeholders()` skips strip when True. |
| KI#73 | iter-110 | Multi-template GGUF selection — fork redirected to fairseq removal; out of scope. |
| KI#71 | iter-110 | Reasoning extraction false-positive detection — fork redirected; out of scope. |
| KI#70 | iter-110 | Stop_tokens atomic check on hot path — fork redirected; out of scope. |
| KI#65 | iter-110 | qasync task race: `start_new_dialog_main` vs `_launch_server_then_update_visibility` — fork redirected; out of scope. |
