# Soul of Waifu — STATUS

## Maintenance rules

1. **Current iteration header** — one `## Iteration N` section at the top, max ~60 lines. Root-cause chains, log evidence, acceptance criteria belong in worklog.md or git history, NOT here.
2. **History table** — one row per past iteration (iter, date, KI(s), 1-line summary). No prose blocks for old iterations.
3. **Active KIs** — only truly open/deferred items. CLOSED KIs go to the Closed KIs table (1-line summary).
4. **No historical appendices** — FAQ, hypothesis tables, "what iter-N adds" sections belong in worklog.md or git history. STATUS.md is a status snapshot, not an archive.
5. **Closed KIs** — one-line summary + closed-in-iter reference. No multi-paragraph descriptions.
6. **Trim on every iteration** — before adding a new header, archive the previous one to the history table. If the history table exceeds 30 rows, trim to the most recent 30.

---

## Iteration 114: KI#86/87/88 CLOSED — форк rvc-python реализован, verification PASSED

**Date**: 2026-08-06
**Scale**: Deep. Fork-implementation: 4 файла в форке + 3 doc-файла в SoW. ~150 строк кода в форке.

**Task**: Реализовать §2.3-2.5 плана `docs/fairseq_removal_plan.md` в форке `daswer123/rvc-python@cff3ffb` + relax numpy/faiss пинов (§1.8) + verification script.

**Что сделано**:
1. Клонирован `daswer123/rvc-python@cff3ffb` (v0.1.5) → `/home/z/my-project/rvc-python-fork`.
2. Переписан `modules/vc/utils.py` (§2.3): `HubertModelWithFinalProj` (наследует `transformers.HubertModel`, добавляет `final_proj = nn.Linear(hidden_size, classifier_proj_size)` для RVC v1), `HubertHFWrapper(nn.Module)` с контрактом `extract_features(source, padding_mask, output_layer) → (feats, padding_mask)`, `final_proj(feats)` делегирует в подкласс, `load_hubert(config, lib_dir)` через HF `from_pretrained`. fairseq нет ВООБЩЕ.
3. Переписан `lib/jit/get_hubert.py` (§2.4): `get_hubert_model(model_path, device)` через `HubertHFWrapper`. Внутренние `_extract_features`, `_hubert_extract_features`, `_infer` функции для JIT-trace. Ветка v1 `final_proj` сохранена в `_infer` (план §2.4 упускал — добавлено для safety).
4. Обновлён `download_model.py` (§2.5): skip `hubert_base.pt` (HF скачает сама), keep `rmvpe.pt` + `rmvpe.onnx`. Переключён с `print()` на `logging.getLogger("rvc_python.download_model")` (rule §2). API-сигнатура `download_rvc_models(this_dir)` сохранена (callers в `infer.py:31` и `infer_old.py:30,77`).
5. `pyproject.toml`: удалён `fairseq==0.12.2`, расслаблены `numpy<=1.23.5`→`>=1.21,<3` (KI#86), `faiss-cpu==1.7.3`→`>=1.7,<2` (KI#86), `omegaconf==2.0.6`→`>=2.0,<3` (KI#87 — gap в §1.8 плана, SoW пинит `omegaconf==2.3.0`). Добавлен `transformers>=4.40` (KI#88 — gap в §1.7 плана, форк импортирует `transformers` напрямую, принцип §2.2 Alt A «форк самодостаточен»).
6. Verification script (§1.8, адаптированный): `faiss-cpu==1.7.4` → `faiss-cpu==1.8.0` (1.7.x НЕ существует для Python 3.12 — PyPI имеет только 1.8.0+; это ДОПОЛНИТЕЛЬНЫЙ аргумент за relaxation — оригинальный пин SoW `faiss-cpu==1.7.3` невыполним на py3.12).
7. **Результат verification: 10/10 PASSED** — pip dry-run без conflict + pip install без conflict + `from rvc_python.infer import RVCInference` → `OK` + 7 структурных проверок (fairseq НЕ в sys.modules, HubertHFWrapper is nn.Module, HubertModelWithFinalProj inherits HubertModel, сигнатуры сохранены, 0 активных fairseq imports).
8. §9 audit checklist: 11/18 PASSED, 4 PENDING iter-116 (A/B-test — требуют HF model download), 3 PENDING iter-115 (SoW-side changes).
9. `docs/fairseq_removal_plan.md` обновлён: header (revision history +1 iter-114), §1.7 (transformers как fork dep — KI#88), §1.8 (omegaconf row в таблице + diff + verification script адаптированный + 10-check результат), §3 (iter-113 row → "ВЫПОЛНЕНО iter-114"), §9 (audit checklist с iter-114 results).

**Дополнительно найдено и исправлено в iter-114**:
- **KI#87** (gap §1.8): `omegaconf==2.0.6` (daswer123) vs `omegaconf==2.3.0` (SoW) — тот же dependency-trap pattern. План §1.8 упомянул в таблице, но diff не включил. Исправлено: `omegaconf>=2.0,<3`.
- **KI#88** (gap §1.7): `transformers` отсутствует в `pyproject.toml` daswer123 — но форк теперь импортирует `from transformers import HubertModel` напрямую. План §1.7 говорил «ничего добавлять» (имея в виду SoW requirements.txt), но упустил что форку нужен `transformers` как dep. Исправлено: `transformers>=4.40`.
- **plan §1.8 verification script bug**: `faiss-cpu==1.7.4` НЕ существует для Python 3.12. Заменено на `faiss-cpu==1.8.0`.

**GitHub push pending**: форк локальный, user должен создать `vudirvp-sketch/rvc-python` на GitHub и запушить.

### Stop point

| Field | Value |
|-------|-------|
| Done | Форк `daswer123/rvc-python@cff3ffb` реализован локально (`/home/z/my-project/rvc-python-fork`). 4 файла изменены: `modules/vc/utils.py` (§2.3), `lib/jit/get_hubert.py` (§2.4), `download_model.py` (§2.5), `pyproject.toml` (§1.8 + KI#87/88). Verification script PASSED 10/10 (pip install без conflict + import succeeds + 8 structural checks). §9 audit: 11/18 passed, 4 pending iter-116 (A/B), 3 pending iter-115 (SoW-side). KI#86/87/88 CLOSED. `docs/fairseq_removal_plan.md` обновлён (header, §1.7, §1.8, §3, §9). |
| Not done | GitHub push форка (`vudirvp-sketch/rvc-python`) — user action. iter-115 (SoW-side: `requirements.txt:58` удалить fairseq, `requirements.txt:191` заменить URL, `text_to_speech.py:30-35` удалить safe_states) — pending решения заказчика. |
| Next step | User пушит форк на GitHub → iter-115: SoW-side changes (3 правки в 2 файлах + переустановка env + верификация запуска). Затем iter-116: A/B-test (генерация речи через форк vs оригинал, сравнение спектрограмм). |
| Active KIs | KI#83 (open — main task, ждёт iter-115+116), KI#85 (open — 6 ошибок плана, ждёт A/B-test iter-116). |

---

## Iteration history

| Iter | Date | KI(s) | Summary |
|------|------|-------|---------|
| 114 | 2026-08-06 | KI#86/87/88→CLOSED | Форк `daswer123/rvc-python@cff3ffb` реализован локально: §2.3 utils.py (HubertHFWrapper + HubertModelWithFinalProj), §2.4 get_hubert.py (v1 final_proj ветка сохранена), §2.5 download_model.py (skip hubert_base.pt). pyproject.toml: fairseq удалён, numpy/faiss/omegaconf relaxed, transformers добавлен. Verification 10/10 PASSED. KI#87 (omegaconf) + KI#88 (transformers) — 2 новых gap'а найдены и исправлены. GitHub push pending. |
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

---

## Active KIs

| KI# | Severity | Description | Status |
|-----|----------|-------------|--------|
| KI#83 | BLOCKING | fairseq→HF ContentVec replacement. План полностью пересмотрен iter-111, верифицирован iter-112 (KI#85) + iter-113-doc (KI#86). **Форк реализован iter-114** (verification 10/10 PASSED, KI#86/87/88 CLOSED). Pending: GitHub push форка → iter-115 (SoW-side: requirements.txt + text_to_speech.py) → iter-116 (A/B-test). | **OPEN** |
| KI#85 | BLOCKING | 6 ошибок в iter-111 плане (HF-модель, plain HubertModel, attention_mask тип, fairseq в pyproject, JarodMica, пропущенные альтернативы). Все 6 исправлены в плане iter-112. Дополнительно iter-114 нашёл KI#87 (omegaconf) + KI#88 (transformers) — оба исправлены. Закроется после A/B-test iter-116. | **OPEN** |

---

## Closed KIs

| KI# | Closed | Summary |
|-----|--------|---------|
| KI#88 | iter-114 | `transformers` отсутствует в `pyproject.toml` daswer123 — форк импортирует `from transformers import HubertModel` напрямую в `utils.py`. План §1.7 упустил (говорил «ничего добавлять» имея в виду SoW requirements.txt). Fix: добавлен `transformers>=4.40` в форк `pyproject.toml`. Verification script PASSED. |
| KI#87 | iter-114 | `omegaconf==2.0.6` (daswer123) vs `omegaconf==2.3.0` (SoW line 131) — тот же dependency-trap pattern, что KI#86. План §1.8 упомянул в таблице, но diff не включил. Fix: `omegaconf>=2.0,<3` в форк `pyproject.toml`. Verification script PASSED. |
| KI#86 | iter-114 | `numpy<=1.23.5` + `faiss-cpu==1.7.3` в `pyproject.toml` rvc-python — dependency-trap. Fix: `numpy>=1.21,<3` + `faiss-cpu>=1.7,<2`. Verification script PASSED (10/10 checks в чистом venv Python 3.12). Доп. находка: `faiss-cpu==1.7.4` НЕ существует для py3.12 — наш relaxed range `>=1.7,<2` resolves на 1.8.0+, оригинальный пин SoW `==1.7.3` невыполним на py3.12. |
| KI#84 | iter-109 | KI#80 placeholder-strip broke Mistral-family templates (HTTP 400 `roles must alternate`). Added `CapabilityMap.requires_role_alternation`; gating in `_strip_role_alternation_placeholders()` skips strip when True. |
| KI#73 | iter-110 | Multi-template GGUF selection — fork redirected to fairseq removal; out of scope. |
| KI#71 | iter-110 | Reasoning extraction false-positive detection — fork redirected; out of scope. |
| KI#70 | iter-110 | Stop_tokens atomic check on hot path — fork redirected; out of scope. |
| KI#65 | iter-110 | qasync task race: `start_new_dialog_main` vs `_launch_server_then_update_visibility` — fork redirected; out of scope. |
