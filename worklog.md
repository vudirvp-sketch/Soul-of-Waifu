# Soul of Waifu — Worklog

---

Task ID: iter-114-fork-rvc-python-hf-contentvec
Agent: Super Z (main)
Task: Реализовать §2.3-2.5 плана в форке `daswer123/rvc-python@cff3ffb` + relax numpy/faiss пинов (§1.8) + verification script.

Work Log:
- Клонирован `daswer123/rvc-python@cff3ffb` (v0.1.5) → `/home/z/my-project/rvc-python-fork`.
- Переписан `modules/vc/utils.py` (§2.3): `HubertModelWithFinalProj` (наследует `transformers.HubertModel`, `final_proj = nn.Linear(hidden_size, classifier_proj_size)` для v1), `HubertHFWrapper(nn.Module)` с контрактом `extract_features(source, padding_mask, output_layer) → (feats, padding_mask)`, `final_proj(feats)` делегирует в подкласс, `load_hubert(config, lib_dir)` через HF `from_pretrained`. 0 fairseq импортов.
- Переписан `lib/jit/get_hubert.py` (§2.4): `get_hubert_model(model_path, device)` через `HubertHFWrapper`. Внутренние `_extract_features`/`_hubert_extract_features`/`_infer` для JIT. Ветка v1 `final_proj` сохранена в `_infer` (план §2.4 упускал — добавлено для safety).
- Обновлён `download_model.py` (§2.5): skip `hubert_base.pt`, keep `rmvpe.pt`+`rmvpe.onnx`. `print()` → `logging.getLogger("rvc_python.download_model")` (rule §2). Сигнатура `download_rvc_models(this_dir)` сохранена.
- `pyproject.toml`: удалён `fairseq==0.12.2`, relaxed `numpy<=1.23.5`→`>=1.21,<3` (KI#86), `faiss-cpu==1.7.3`→`>=1.7,<2` (KI#86), `omegaconf==2.0.6`→`>=2.0,<3` (KI#87 — gap §1.8), добавлен `transformers>=4.40` (KI#88 — gap §1.7).
- Verification script (§1.8, адаптированный `faiss-cpu==1.7.4`→`1.8.0` т.к. 1.7.x не существует для py3.12). **10/10 PASSED**: pip dry-run без conflict + pip install без conflict + `from rvc_python.infer import RVCInference` → `OK` + 7 структурных проверок (fairseq НЕ в sys.modules, HubertHFWrapper is nn.Module, HubertModelWithFinalProj inherits HubertModel, сигнатуры сохранены, 0 активных fairseq imports).
- §9 audit: 11/18 PASSED, 4 pending iter-116 (A/B-test), 3 pending iter-115 (SoW-side).
- Housekeeping: STATUS.md history 31→30 (удалена iter-84, oldest). worklog.md one-in-one-out — удалена iter-106 (oldest).

Stage Summary:
- Files changed (fork): `rvc_python/modules/vc/utils.py`, `rvc_python/lib/jit/get_hubert.py`, `rvc_python/download_model.py`, `pyproject.toml`. Files changed (SoW docs): `docs/fairseq_removal_plan.md`, `STATUS.md`, `worklog.md`. KI#86/87/88 CLOSED. KI#83/85 unchanged. GitHub push pending (user action). iter-115 (SoW-side: requirements.txt + text_to_speech.py) — pending решения заказчика.

---

Task ID: iter-113-doc-ki86-numpy-faiss-dependency-trap
Agent: Super Z (main)
Task: Заказчик проверил iter-112 план через сторонний отчёт. Перепроверить каждое утверждение отчёта против реального кода, открыть KI#86 если найдены новые ошибки, обновить план.

Work Log:
- Перепроверен каждый пункт стороннего отчёта: 5 утверждений подтверждены (fairseq только в utils.py + get_hubert.py, lengyue233/content-vec-best существует, Politrees/RVC_resources содержит contentvec 378 МБ, API conversion `extract_features` → `hidden_states[N]`), 5 опровергнуты (утверждение «12 строк» — реально 4 места в 2 файлах; утверждение «нужно модифицировать pipeline.py» — wrapper эмулирует контракт, pipeline не трогается; утверждение «нужно проверить final_proj» — уже проверено iter-112 §1.5; утверждение про JarodMica «мёртвый импорт» — это не обёртка, а делегирование load_hubert→get_hubert_model).
- Найдена 7-я ошибка iter-112 плана (KI#86): `pyproject.toml` rvc-python пинит `numpy<=1.23.5` + `faiss-cpu==1.7.3` — тот же dependency-trap pattern, что `fairseq==0.12.2`. SoW пинит `numpy==1.26.4` → resolver conflict или тихая установка несовместимой версии. iter-112 §1.7 упустил, фокус был на fairseq correctness, не на dependency-tree health.
- Проверено через прямое клонирование: daswer123@cff3ffb и JarodMica@782467a — оба пинят `numpy<=1.23.5` + `faiss-cpu==1.7.3` одинаково. JarodMica bumped только omegaconf (2.0.6→2.3.0, May 2025). Подтверждено: JarodMica не решает проблему.
- Проверено через HF API: Politrees/RVC_resources/embedders/transformers/contentvec/config.json байт-в-байт идентичен lengyue233/content-vec-best/config.json (та же модель, 378 МБ).
- Обновлён `docs/fairseq_removal_plan.md`: добавлен §1.8 (52 строки, таблица upstream-пинов + объяснение + решение + verification script), §3 iter-113 шаги расширены (relax numpy/faiss + verification), §5 +2 риска (numpy 2.x compat, faiss-cpu 1.8.x compat), §8 разблокировка KI#86, §9 checklist 14→18 пунктов, header история ревизий +1 entry.
- KI#86 открыт в STATUS.md. Housekeeping: worklog.md one-in-one-out — удалена iter-105 запись (самая старая); STATUS.md history table 31→30 строк (удалена iter-83).

Stage Summary:
- Doc-only. Files changed: `docs/fairseq_removal_plan.md`, `STATUS.md`, `worklog.md`. KI#86 OPEN, KI#83/85 unchanged. iter-114 (форк + реализация §2.3-2.5 + relax numpy/faiss + verification) — pending решения заказчика.

---

Task ID: iter-112-verification-6-errors-fixed
Agent: Super Z (main)
Task: Перепроверить iter-111 исследование полностью. Клонировать upstream-репозитории, верифицировать каждое утверждение, убедиться что решение «ультимативное со всех сторон».

Work Log:
- Клонированы 4 репозитория: daswer123/rvc-python@0.1.5 (PyPI upstream, MIT, last Oct 2024, pyproject pinит `fairseq==0.12.2`), JarodMica/rvc-python@9a67ac7 (SoW pin) + @HEAD (last Mar 2026, активный форк, fairseq REMOVED из pyproject но остался в коде), RVC-Project/Retrieval-based-Voice-Conversion-WebUI@81eed5e (official, last Aug 2026, ZERO fairseq refs, migration commit `5d47da1` 2026-07-19 «Import RVC 20260716»), JackismyShephard/ultimate-rvc@e6519bc (318★, MIT, last Apr 2026, `transformers==4.57.3` совпадает с SoW, fairseq-free).
- Сравнены 3 HF-модели через их config.json: (1) `facebook/hubert-base-ls960` — plain HubertModel, NO classifier_proj_size, NO final_proj (ASR model, НЕ ContentVec). (2) `lengyue233/content-vec-best` — HubertModelWithFinalProj, classifier_proj_size=256, INCLUDES final_proj веса (ContentVec). (3) `lj1995/VoiceConversionWebUI/hubert_base` — то же ContentVec, используется официальным RVC. iter-111 план указывал (1) — ОШИБКА, исправлено на (2).
- Проверен контракт extract_features: официальный RVC `infer/hubert.py` явно комментирует «Transformers hidden_states[N] is numerically equivalent to the source checkpoint's output_layer=N». v1 → hidden_states[9] + final_proj. v2 → last_hidden_state (== hidden_states[12]). iter-111 план этот контракт описал правильно.
- Найдено 2 пропущенных PyPI-пакета: `ultimate-rvc==0.6.0` (318★, MIT, fairseq-free, `transformers==4.57.3` совпадает с SoW, но приносит 30+ тяжёлых deps — gradio, audio-separator, yt-dlp, etc.); `zerorvc==0.0.19` (no fairseq, no transformers — отдельное решение). Оба отклонены как drop-in replacement, но ultimate-rvc код использован как референс.
- Все 4 ранее проверенных PyPI-пакета (daswer123, R3gm, Thatneos, rvc-infer) — всё ещё на fairseq, версии не вышли.
- Применено 6 правок к `docs/fairseq_removal_plan.md`: §1.1 (daswer123 pyproject pinит fairseq, JarodMica — активный форк), §1.5 (ContentVec вместо стандартного HuBERT), §1.6 (v1+v2 контракт через HubertModelWithFinalProj), §1.7 (pyproject.toml шаг добавлен), §2.3 (полная переработка HubertHFWrapper — HubertModelWithFinalProj + правильный attention_mask), §3 (этапы пересчитаны iter-112→iter-116), §5 (риски обновлены), §7 (Путь E ultimate-rvc, Путь F inline, Путь G torchaudio), §9 (audit checklist 10→14 пунктов).
- KI#85 открыт в STATUS.md. Housekeeping: worklog.md one-in-one-out — удалена iter-104 запись (самая старая).

Stage Summary:
- Doc-only. Files changed: `docs/fairseq_removal_plan.md`, `STATUS.md`, `worklog.md`. No code changes. iter-113 (форк daswer123 + реализация §2.3-2.5 + pyproject fix) — pending решения заказчика.

---

Task ID: iter-111-plan-revision-fork-approach
Agent: Super Z (main)
Task: Полный пересмотр плана удаления fairseq. Заказчик отказывается от stub/monkey-patch подхода — требует чистого удаления «с корнем».

Work Log:
- Проанализировал все fairseq-референсы в SoW (3 production: text_to_speech.py:30-35 safe_globals, requirements.txt:58, rvc-python@9a67ac7 utils.py:2).
- Проанализировал rvc-python@9a67ac7 исходники: 2 файла с fairseq-импортами (modules/vc/utils.py, lib/jit/get_hubert.py), fairseq НЕ в dependencies rvc-python.
- Переписал `docs/fairseq_removal_plan.md` полностью: подход изменён с stub+monkey-patch на **форк rvc-python**. В форке: utils.py (HF HuBERT вместо fairseq checkpoint_utils), get_hubert.py (HF вместо fairseq), download_model.py (пропуск hubert_base.pt). В SoW: удаление safe_globals + замена rvc-python URL + удаление fairseq.
- Обновил STATUS.md: iter-111 header, KI#83 описание обновлено, history +1/-2 (trim to 30 rows).

Stage Summary:
- Doc-only. Files changed: `docs/fairseq_removal_plan.md`, `STATUS.md`, `worklog.md`. No code changes. Plan ready for iter-112 (верификация → форк rvc-python + implement HF HuBERT).

---

Task ID: iter-110-fork-reset-cleanup-and-plan-audit
Agent: Super Z (main)
Task: User redirected fork to fairseq removal + dep audit. Clean up all old open KIs. Audit `docs/fairseq_removal_plan.md` for factual accuracy.

Work Log:
- Closed 4 old KIs as out-of-scope (fork redirect): KI#65 (qasync task race), KI#70 (stop_tokens atomic check), KI#71 (reasoning extraction false-positive), KI#73 (multi-template GGUF selection). KI#83 stays OPEN — fork's main task.
- Audited `docs/fairseq_removal_plan.md` against current repo state — found 8 factual errors: fairseq version 0.12.3→0.12.2 (line 58 not 55); transformers/rvc-python line refs 235/191 not 212/173; `text_to_speech.py` line refs 28/30-35/39-45/198 not 25/27-32/37-42/195; `installer.bat:93 --no-deps` claim is FALSE (installer.bat does NOT install rvc-python at all — line 93 is `python -m pip check`; rvc-python comes only from `requirements.txt:191`). All 8 fixed in plan doc.
- Verified iter-108/109 main-line implementation is NOT in this fork: `text_to_speech.py:30-35` still has safe_states hack; no `app/utils/rvc_hubert_hf.py`; no `_install_fairseq_stub()`; no dual-target monkey-patch. KI#83 implementation must be re-executed from scratch (iter-112+).
- Housekeeping: STATUS.md — 3 stale iter-107/108/109 prose sections collapsed into history rows; history table trimmed 31→30 (deleted iter-79 + iter-80, added iter-110); Closed KIs gained KI#65/70/71/73 (KI#84 retained, <2 iter old). worklog.md one-in-one-out — deleted iter-102.

Stage Summary:
- KI#65/70/71/73 CLOSED. KI#83 stays OPEN. Files changed: `STATUS.md`, `worklog.md`, `docs/fairseq_removal_plan.md`. Doc-only iteration. Next: iter-111 nav file refresh (`AGENT_NAVIGATION.md §1` stale line counts), iter-112 execute plan §2.

---

Task ID: iter-109-ki84-mistral-role-alternation-fix
Agent: Super Z (main)
Task: Fix KI#84 — KI#80 placeholder-strip broke Mistral-family chat templates (HTTP 400 `roles must alternate`). User log: `MN-Violet-Lotus-12B` (Tekken, embedded Jinja = mistral-v0-1).

Work Log:
- Root cause (logs `sow_2026-08-04`): prompt_engine produces `system → user(placeholder) → assistant(history) → user(input)` (valid alternation), but KI#80 in `local_provider.py` strips the placeholder → `system → assistant → user` → Mistral Jinja `raise_exception("After the optional system message, conversation roles must alternate...")` → HTTP 400 before generation.
- Fix layer 1 — `template_detector.py`: added `CapabilityMap.requires_role_alternation: bool = False`; `compute_capability_map()` sets True when Jinja source contains `"roles must alternate"` substring (canonical for Mistral raise guard); `_capability_map_from_template_name()` sets True when normalized name contains `"mistral"` OR `"mixtral"` (mixtral != mistral substring-wise — both checked explicitly).
- Fix layer 2 — `ai_factory.py`: extracts `requires_role_alternation` from `detection_result.capability_map` via defensive `getattr` (works on CapabilityMap instances missing the field — pre-iter-109 callers); forwards to `LocalProvider(__init__, requires_role_alternation=...)`. Default False preserves iter-108 behavior.
- Fix layer 3 — `local_provider.py`: `__init__` accepts kwarg, stores `self._requires_role_alternation = bool(...)`; `_strip_role_alternation_placeholders()` accepts `requires_role_alternation` keyword-only arg → early `return messages` (NO-OP) when True; all 3 generation methods (`generate_stream`, `generate_summary`, `generate`) updated to pass `requires_role_alternation=self._requires_role_alternation`.
- `scripts/iter109_smoke_test.py`: 79 PASS / 0 FAIL across 9 groups. Functional tests verify: (a) `compute_capability_map(Mistral Jinja sample) → True`; (b) `compute_capability_map(Llama-3 Jinja sample) → False`; (c) name fallback covers `mistral-v0-1`/`mistral-v3-tekken`/`mistral-v7-tekken`/`mixtral`; (d) `LocalProvider(requires_role_alternation=True)` → strip is NO-OP, placeholder preserved, alternation `system → user → assistant → user` intact; (e) `LocalProvider()` default → KI#80 strip active (back-compat with iter-101 for non-Mistral models like Llama-3-8B echo fix).
- Regression check: iter-80 + iter-80.1 smoke tests still pass all functional assertions; only brittle line-count upper bound (734→1000 since iter-82) fails — pre-existing, not caused by this iter. iter-108 smoke test requires `torch` (unavailable in Linux env) — pre-existing.
- Housekeeping: STATUS.md — KI#82 deleted from Closed KIs (>2 iterations closed per §3 rule, closed iter-105); KI#84 added + closed in same iter (root-cause-clear, fix verified by smoke test); history table row added. worklog.md one-in-one-out — deleted iter-101 entry (oldest, the very KI#80 implementation being patched here).

Stage Summary:
- KI#84 CLOSED. Files changed: `app/utils/ai_clients/template_detector.py` (CapabilityMap + compute_capability_map + _capability_map_from_template_name), `app/utils/ai_clients/ai_factory.py` (forwarding), `app/utils/ai_clients/providers/local_provider.py` (kwarg + gate + 3 call sites), `scripts/iter109_smoke_test.py` (new, 79 tests), STATUS.md, worklog.md. KI#80 behavior preserved for non-Mistral models. User A/B pending: run `MN-Violet-Lotus-12B` and verify HTTP 400 is gone.

---

Task ID: iter-108-fairseq-hf-hubert-implementation
Agent: Super Z (main)
Task: Implement KI#83 per `docs/fairseq_removal_plan.md` §2.2 — stub + dual-target monkey-patch + temp assert + safe_states removal.

Work Log:
- New `app/utils/rvc_hubert_hf.py` (240 lines): `HubertHFWrapper(nn.Module)` wraps `transformers.HubertModel`, reproduces fairseq contract `extract_features(source, padding_mask, output_layer=9|12) → (feats, padding_mask)`. Lazy `final_proj()` loader for RVC v1. Resolves inner device via `next(self.model.parameters()).device` (works with real HubertModel AND bare nn.Module stand-ins).
- `text_to_speech.py:24-116`: `_install_fairseq_stub()` (GAP-A) → `from rvc_python.infer import RVCInference` after stub → dual-target monkey-patch `_rvc_utils.load_hubert = _rvc_modules.load_hubert = _hf_load_hubert` (GAP-B) → 2 temp asserts (DELETE before iter-109). Old `torch.serialization.add_safe_globals([Dictionary])` hack (lines 27-32) removed per §2.3.
- `scripts/iter108_smoke_test.py`: 22 tests across 6 groups (G1 GAP-A stub, G2 GAP-B dual-target, G3 stub no-op, G4 HubertHFWrapper contract, G5 temp assert present + safe_states removed, G6 end-to-end vc_single() bare-name resolution). 22 PASS / 0 FAIL. Uses mock rvc_python (mirrors @9a67ac7) + fake transformers.HubertModel because real rvc-python install fails on Python 3.12 (old numpy build dep).
- Housekeeping: STATUS.md history table trimmed 44→30 rows; worklog.md one-in-one-out (deleted iter-100 entry below).

Stage Summary:
- KI#83 stays OPEN — implementation done, A/B-test (iter-109) + fairseq removal from requirements.txt (iter-110) pending. Files changed: `app/utils/rvc_hubert_hf.py` (new), `app/utils/text_to_speech.py`, `scripts/iter108_smoke_test.py` (new), STATUS.md, worklog.md.

---

Task ID: iter-107-audit-plan-update
Agent: Super Z (main)
Task: Update `docs/fairseq_removal_plan.md` with GAP-A/GAP-B fixes from KI#83 audit.

Work Log:
- Rewrote §2.2 into 4 sub-blocks: §2.2.1 stub `sys.modules['fairseq']` (no-op if real fairseq already imported), §2.2.2 rvc_python import after stub, §2.2.3 dual-target monkey-patch (`_rvc_utils.load_hubert` + `_rvc_modules.load_hubert`), §2.2.4 temp assert for iter-108 first run.
- Added §1.7 (GAP-A: import-time `from fairseq import checkpoint_utils` at `rvc_python/modules/vc/utils.py:3`) and §1.8 (GAP-B: `modules.py:19 from utils import *` rebinds `load_hubert` into `modules.vc.modules` namespace; `vc_single()` at `modules.py:168` calls bare `load_hubert` → resolves from `modules` not `utils`).
- Updated §3 stages table (iter-108 now includes stub + dual-target + assert; iter-110 hard preconditions noted). §5 risks gained GAP-A/B rows. §6 notes `lib/jit/get_hubert.py` ONNX-export-only untouched. New §9 audit checklist (7 items for iter-108 implementer).
- Minor fixes: §3 ref `AGENT_NAVIGATION.md §3`→`§4` (Pitfalls); §4 A/B memory note ~1.5 GB cache → ~370 MB weights (`pytorch_model.bin` only).
- Housekeeping: deleted iter-99 entry per §6 one-in-one-out (10-entry cap). KI#83 stays OPEN — plan-stage fixed, implementation pending iter-108.

Stage Summary:
- Doc-only. Files changed: `docs/fairseq_removal_plan.md` (revised), STATUS.md (KI#83 row + iter-107-audit history row + stop point updated; iter-77 history row trimmed to keep 30-row cap), worklog.md (this entry). No code changes. Plan ready for iter-108 — no blockers.

---

Task ID: iter-107-fairseq-plan-audit
Agent: Super Z (main)
Task: User asked to verify `docs/fairseq_removal_plan.md` — confirm fairseq is really not used elsewhere and the plan is complete.

Work Log:
- Verified SoW repo: only fairseq usage is `text_to_speech.py:27-32` safe_globals hack. Full repo grep finds 0 other code refs (only docs/STATUS/worklog mentions).
- Fetched rvc-python@9a67ac7 source, mapped all fairseq refs: `modules/vc/utils.py:3` (top-level import), `modules/vc/utils.py:21` (`load_hubert` body), `lib/jit/get_hubert.py:4,10` (ONNX-export-only, not in __init__ chain).
- Confirmed plan correctness: HF model arch match, v2 default, contract at `pipeline.py:215-223`, `download_rvc_models` at `download_model.py:16`, rvc-python's own requirements.txt does NOT list fairseq (only SoW:55 does).
- Found GAP-A (BLOCKING): `utils.py:3` top-level `from fairseq import checkpoint_utils` runs at import time via chain `__init__.py`→`infer.py:5`→`modules.py:19 from utils import *`→`utils.py:3`. Removing fairseq from requirements.txt will cause ModuleNotFoundError at SoW startup. Plan's monkey-patch of `load_hubert` does NOT neutralize this. Fix: inject stub `sys.modules['fairseq']` BEFORE `from rvc_python.infer import RVCInference`.
- Found GAP-B (BLOCKING): plan patches `rvc_utils.load_hubert`, but `modules.py:19` does `from utils import *` which rebinds `load_hubert` into `modules.vc.modules` namespace. `vc_single()` at `modules.py:168` calls bare `load_hubert(...)` — resolves from `modules.vc.modules` globals, NOT `modules.vc.utils`. Patch silently no-ops. Fix: patch BOTH `utils.load_hubert` AND `modules.load_hubert`.
- Minor: plan §3 "update AGENT_NAVIGATION.md §3" — §3 is LLM-providers table, structurally wrong place. Use §4 (Pitfalls) or docs/ARCHITECTURE.md TTS section. Plan §4 A/B memory note (~1.5 GB HF cache) imprecise — HuBERT base ~370 MB weights only.
- KI#83 OPENED (BLOCKING) in STATUS.md. Did NOT modify `docs/fairseq_removal_plan.md` — user decides whether to update plan doc or address gaps inline at iter-108.
- Housekeeping: deleted iter-98 entry from worklog per §6 one-in-one-out (10-entry cap). Full iter-98 record in git history.

Stage Summary:
- Doc-only audit. Files changed: STATUS.md (KI#83 added to Active KIs + iter-107 section updated with audit findings + history row updated), worklog.md (this entry). No code changes.
- iter-110 CANNOT proceed without stub-module + dual-target patch. iter-108/109 are unaffected (fairseq still installed, fallback path works).

---

Task ID: iter-107-fairseq-removal-plan
Agent: Super Z (main)
Task: User wants to remove `fairseq` dep. Plan how to replace HuBERT loader with HF transformers version.

Work Log:
- Verified `facebook/hubert-base-ls960` (HF, 889k dl) is architecturally identical to `hubert_base.pt`: 12 layers, hidden=768, `do_stable_layer_norm=false` = fairseq `layer_norm_first=False`.
- Identified single fairseq runtime entry point: `rvc_python/modules/vc/utils.py:load_hubert`. The other one (`lib/jit/get_hubert.py`) is ONNX-export-only.
- Contract: `model.extract_features(source, padding_mask, output_layer=9|12)` → `(feats, padding_mask)`. `final_proj` only needed for v1; rvc-python defaults to v2 (`infer.py:65`), so HF model (no `final_proj`) suffices.
- `transformers==4.57.3` already in requirements.txt:212. Only removal target: `fairseq==0.12.3` (line 55).
- New `docs/fairseq_removal_plan.md` — 8-section plan (context, architecture, stages, A/B-test criteria, risks, alternatives).
- Stages: iter-108 (impl + monkey-patch with fairseq fallback) → iter-109 (A/B) → iter-110 (remove fairseq if pass).

Stage Summary:
- Doc-only iteration. Files changed: `docs/fairseq_removal_plan.md` (new), STATUS.md, worklog.md. No code changes.
- Housekeeping: deleted iter-97 entry from worklog per §6 one-in-one-out (10-entry cap). Full iter-97 record in git history @ 744af9b.

