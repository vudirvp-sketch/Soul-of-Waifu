**Архитектура определения шаблонов**
*Detection Layers · описание пайплайна выбора chat-template*

> Текст сверен с актуальным кодом `app/utils/ai_clients/template_detector.py` (iter‑105) и `app/utils/ai_clients/local_server_manager.py`. Номера строк актуальны на iter‑105. iter‑106: добавлен §5 (reasoning pipeline), исправлена ошибка в §4 про `eos_drift` gate (устарел в iter‑95 KI#77).

---

### 1. Уровни детекции (Detection Layers)

**Layer 0 — пользовательский Jinja-override** *(iter‑67)*
- Если в `settings.json → main_settings.custom_jinja_override` задан непустой Jinja‑текст — `local_server_manager.start_server_async()` (код вокруг `local_server_manager.py:556-591`) записывает его в `app/data/custom_template.jinja` и передаёт `llama-server` флаг `--chat-template-file <path>`.
- Этот путь имеет приоритет **над** значением из combo‑box и над авто‑детекцией.
- Пайплайн детекции всё равно запускается (безусловно, в самом верху `start_server_async()`, `local_server_manager.py:469`) — он нужен для формирования `capability_map`, который определяет `--chat-template-kwargs`. Но флаг `--chat-template` при этом не добавляется.

---

**Layer 1 — главный путь** *(~95% современных GGUF)*
- Пользователь кладёт новый `.gguf` в `assets/local_llm/`, `chat_template = "Auto"`.
- При старте сервера `local_server_manager.start_server_async()` вызывает `detect_template(model_path)` с параметрами по умолчанию (`validate_vocab=False`).
- `detect_template()` через `read_gguf_metadata()` (функция ~`template_detector.py:166-315`) читает метаданные GGUF — `tokenizer.chat_template`, `tokenizer.chat_template.<name>`, `general.architecture`, `tokenizer.ggml.eos_token_id`, `tokenizer.ggml.pre`, `general.source.repo_url`/`general.url`.
- Если в GGUF есть `tokenizer.chat_template` (95% случаев): `jinja_source = meta.chat_template`, `source = EMBEDDED`, `confidence = HIGH`.
- Флаг `--chat-template` в команду **не добавляется** — `llama-server` сам применяет embedded Jinja нативно. Решение KI#44 (iter‑38): флаг `--chat-template` намеренно не передаётся ни при `EMBEDDED`, ни при `ARCH` (см. ниже), потому что в `llama-server` b9550+ парсер встроенных шаблонов содержит баг, ломающий `prompt_eval` (4-токенный коллапс).

---

**Layer 1a — HF cache** *(не fallback, а авторитетный источник)*
- Кэш HF (`HFTemplateCache.fetch()`) запрашивается **безусловно**, если в GGUF есть `general.source.repo_url` (или `general.url`) и URL содержит `huggingface.co` — независимо от того, найден ли уже `chat_template` в самом GGUF (`template_detector.py:985-1017`).
- Если HF‑кэш вернул `chat_template` — он **предпочитается** над GGUF‑embedded (комментарий в коде `template_detector.py:1025`: «Prefer HF cache (authoritative source) over GGUF embedded»). Причина: `tokenizer_config.json` на HF может быть свежее, чем embedded‑поле в квантизированном GGUF — авторы квантов не всегда его обновляют.
- Дополнительно из HF забирается `generation_config.eos_token_id` + `special_tokens_map.eos_token` — это влияет на stop‑tokens (см. §3).
- Работает после первого скачивания — далее из кэша, TTL по умолчанию 24ч, настраивается через `main_settings.template_cache_ttl_hours`.

---

**Layer 1b — мультитемплейтные модели** *(iter‑52)*
- Если GGUF содержит `tokenizer.chat_template.<name>` (Qwen3, Mistral 2024+) — берётся **первый** именованный шаблон в порядке вставки (`template_detector.py:1112-1116`):
  ```python
  first_name = next(iter(meta.chat_template_n))
  jinja_source = meta.chat_template_n[first_name]
  resolved_name = first_name
  ```
- ⚠️ **Ограничение**: `resolved_name` здесь — это GGUF‑имя (например `"default"` или `"tool_use"`), а **не** имя встроенного шаблона `llama.cpp`. Поэтому последующий lookup `_TEMPLATE_IMPLIED_STOPS[resolved_name]` для таких имён обычно промахивается, и stop‑tokens берутся из GGUF `eos_token_id` (как ID, без текстового представления). Это компенсируется либо HF `generation_config.eos_token`, либо Layer 2/3 при ручном выборе.
- ⚠️ **Открытая недоработка** (KI#73, DEFERRED): когда `multi_tmpl > 1`, выбор первого шаблона не зависит от `reasoning_mode` — thinking/non‑thinking вариант не выбирается явно.

---

**Layer 1c — auto‑fallthrough при vocab validation** *(iter‑76, KI#57)*
- Срабатывает, **только** если пользователь кликает «Validate vocab» в Diagnostics Panel (`diagnostics_panel.py:_on_validate_vocab_clicked` → `_ValidateVocabWorker` → `detect_template(model_path, validate_vocab=True)`, ленивая загрузка словаря ~1–2с).
- Если `validate_template_against_vocab()` находит неатомарные special tokens в embedded Jinja (например, `<|im_end|>` разбит на `<|im` + `_end|>` в словаре) — и при этом `source == EMBEDDED` — пайплайн автоматически откатывается к архитектурной эвристике (Layer 2):
  ```python
  # template_detector.py:1269-1282
  result.resolved_template_name = arch_name              # например "qwen3-thinking"
  result.source             = DetectionSource.ARCH       # был EMBEDDED
  result.confidence         = Confidence.MED             # был HIGH
  result.jinja_source       = None                       # arch heuristic не даёт Jinja
  result.capability_map     = _capability_map_from_template_name(arch_name)  # ← пересчитывается
  if arch_name in _TEMPLATE_IMPLIED_STOPS:
      result.stop_tokens       = _TEMPLATE_IMPLIED_STOPS[arch_name]   # ← пересчитывается
      result.stop_token_source = "template_implied"
  result.warnings.append(
      f"Auto-fallthrough to Layer 2: embedded template had "
      f"{len(result.validation_errors)} vocab validation error(s), "
      f"arch heuristic '{arch_name}' used instead."
  )
  ```
- Дополнительная строка лога (logger.warning, `template_detector.py:1264`): `"Auto-fallthrough: embedded template has validation errors, falling back to architecture heuristic. embedded=%s -> arch=%s (arch=%s)"`.
- ⚠️ `validate_vocab=False` по умолчанию (`template_detector.py:919`) — в обычном server‑startup flow этот путь **не срабатывает**. Это чисто диагностический механизм, включаемый только ручным кликом «Validate vocab».

---

**Layer 2 — fallback по архитектурной эвристике**
Если не найдены ни HF, ни GGUF `chat_template`, ни `chat_template_n`, используется `_ARCH_TEMPLATE_MAP` (`template_detector.py:399-432`):

| Параметр | Значение |
|----------|----------|
| Всего записей | **22** (17 базовых + 5 добавлено в iter‑56: `gpt‑oss`, `exaone`, `granite`, `olmo`, `stablelm`) |
| Confidence HIGH | `qwen3`, `gpt‑oss`, `exaone`, `granite`, `olmo` |
| Confidence MED | `llama`, `gemma4`, `gemma2`, `gemma`, `command‑r`, `deepseek2`, `deepseek`, `qwen2`, `qwen`, `phi3`, `qwen2moe`, `internlm2` |
| Confidence LOW | `mistral`, `mixtral`, `phi2`, `minicpm`, `stablelm` |
| Примеры | `qwen3 → qwen3-thinking`, `llama → llama-3`, `mistral → mistral-v0-1`, `gpt-oss → gpt-oss`, `gemma4 → gemma3` |

Сопоставление — по подстроке (`arch_lower`); порядок важен, более специфичные записи идут первыми (например, `qwen3` → `qwen3-thinking` идёт перед `qwen2` → `chatml`, `deepseek2` перед `deepseek`).

⚠️ Даже при `source = ARCH` флаг `--chat-template` в команду **не добавляется** — тот же KI#44. Логика: если детектор нашёл шаблон через архитектурную эвристику, `llama-server` сделает то же самое своим внутренним `common_chat_try_specialized_template()`, а флаг только включит баги парсера. Флаг добавляется **только** при `source ∈ {FALLBACK, NONE}` — то есть когда детектор сам сдался и предложил ChatML.

---

**Layer 3 — последний рубеж: ChatML** *(WARNING)*
- Срабатывает, если архитектура не опознана или вообще отсутствует в GGUF.
- `resolved_name = "chatml"`, `source = FALLBACK`, `confidence = LOW` — с записью WARNING в лог.
- Актуальные строки (`template_detector.py:1138` — архитектура есть, но не в карте; `:1148` — архитектуры нет вовсе):
  - `"Architecture %s not in heuristic map — falling back to ChatML. Template may be incorrect; select manually if quality degrades."`
  - `"No architecture field in GGUF — falling back to ChatML. Template may be incorrect; select manually if quality degrades."`
- ⚠️ Если генерация ведёт себя странно — сначала стоит проверить именно эти строки лога.

---

### 2. Jinja‑inference: resolved_name и stop‑tokens

Работает поверх Layer 1/1a: `_JINJA_TEMPLATE_PATTERNS`, `template_detector.py:611-712`. Функция `_infer_template_from_jinja()` (`:715-736`).

**Назначение**
Когда есть Jinja‑строка (из GGUF или HF), она сканируется на telltale‑маркеры. Проблема: `arch=llama` в GGUF встречается у Llama‑3, Llama‑2, Mistral и Vicuna, а у них разные eos‑токены (`<|eot_id|>` vs `</s>`). Без Jinja‑inference все они получили бы один и тот же `llama-3` и неверный stop‑token `</s>` для Mistral.

**Что делает**
- Обновляет `resolved_name` (например `llama-3 → mistral-v0-1`, если в Jinja найдены `[INST]/[/INST]`).
- Это влияет на `_TEMPLATE_IMPLIED_STOPS` → правильные stop‑токены.
- iter‑96 (KI#78) добавил **guard**: для «однозначных» архитектур (`_UNAMBIGUOUS_ARCH_PREFIXES`, всё кроме `llama`) cross‑family Jinja‑override **срезается** — иначе Gemma4‑HauhauCS finetune с маркерами `enable_thinking` ошибочно резолвился в `qwen3-thinking` и получал stop‑token `<|im_end|>`, которого нет в словаре Gemma как атомарного.

**Чего не делает**
- Не меняет `detection.source` — остаётся `EMBEDDED`.
- Не передаёт флаг `--chat-template` (он и так не передаётся при `EMBEDDED`).

Итог: на пользовательский контракт («какой шаблон применит `llama-server`») это не влияет — влияет только на stop‑токены и на отображаемое имя в Diagnostics Panel.

**Список паттернов — 10, не 9** (порядок критичен, см. KI#68/iter‑89)
```
# Unique-family markers (HIGH, проверяются первыми):
(r"<\|start_header_id\|>|<\|end_header_id\|>|<\|eot_id\|>",  "llama-3",      HIGH)   // Llama-3 — уникальные маркеры
(r"<\|channel\|>|<\|message\|>|<\|return\|>",                 "gpt-oss",      HIGH)   // iter-56, multi-channel reasoning
(r"<start_of_turn>|<end_of_turn>",                            "gemma3",       HIGH)   // iter-89 KI#68, moved BEFORE qwen3-thinking
(r"\[INST\]|\[/INST\]",                                       "mistral-v0-1", HIGH)   // iter-89 KI#68, moved BEFORE qwen3-thinking
(r"<\|START_OF_TURN_TOKEN\|>|<\|END_OF_TURN_TOKEN\|>",        "command-r",    HIGH)   // iter-89 KI#68, moved BEFORE qwen3-thinking
(r"\n### Instruction:|\n### Response:",                       "alpaca",       HIGH)   // iter-59, iter-89 KI#68
# Semi-unique thinking markers (HIGH, после unique-family):
(r"enable_thinking|<think>|</think>",                         "qwen3-thinking", HIGH) // iter-88 KI#66, iter-89 KI#68 reordered
# Generic markers (HIGH, last resort):
(r"<\|im_start\|>|<\|im_end\|>",                              "chatml",       HIGH)   // Qwen2/Yi/internlm2/minicpm + exaone/granite/olmo
# Lower-confidence (MED):
(r"<\|end\|>",                                                "phi-3",        MED)
(r"<\|end_of_text\|>",                                        "deepseek",     MED)
```

**Порядок критичен**: уникальные семейства (llama-3, gpt-oss, gemma3, mistral-v0-1, command-r, alpaca) → qwen3-thinking → ChatML → phi-3 → deepseek. Финетюны (особенно HauhauCS/abliteration) часто добавляют `enable_thinking`/`<think>`/`</think>` в шаблоны не‑Qwen3 моделей — если qwen3-thinking проверять раньше unique‑family, все они ошибочно резолвятся в `qwen3-thinking` и получают stop‑token `<|im_end|>`, который BPE‑токенизатор Gemma/Mistral/Llama‑2 разбивает на 5–7 сабвордов (молчаливая деградация качества).

`exaone`/`granite`/`olmo`/`stablelm`/`smolmodels` намеренно **не добавлены** в `_JINJA_TEMPLATE_PATTERNS` — все они используют стандартные ChatML‑маркеры (`<|im_start|>`/`<|im_end|>`), так что существующий ChatML‑паттерн корректно их детектит и даёт правильные stop‑tokens.

---

### 3. Stop‑tokens: приоритет разрешения (3 уровня)

`detect_template()` резолвит stop‑tokens по цепочке приоритетов (`template_detector.py:1166-1182`, комментарий: «Priority: HF generation_config > GGUF eos_token_id > template-implied»):

| Tier | Источник | `stop_token_source` | Что попадает в `stop_tokens` |
|------|----------|---------------------|------------------------------|
| 1 (высший) | HF `generation_config.eos_token_id` + `special_tokens_map.eos_token` | `"generation_config"` | Текст EOS из HF (например `"<|im_end|>"`) |
| 2 | GGUF `tokenizer.ggml.eos_token_id` | `"gguf"` или `"gguf+template_implied"` | `stop_token_ids` = ID из GGUF; `stop_tokens` (текст) = `_TEMPLATE_IMPLIED_STOPS[resolved_name]` как fallback |
| 3 (низший) | `_TEMPLATE_IMPLIED_STOPS[resolved_name]` | `"template_implied"` | Только текстовые stop‑токены (например `["<|eot_id|>", "<|start_header_id|>"]` для llama-3) |

iter‑104 (KI#82) добавил `<|start_header_id|>` как **вторичный** stop‑token в `_TEMPLATE_IMPLIED_STOPS["llama-3"]` — теперь список `["<|eot_id|>", "<|start_header_id|>"]`. Это defensive‑catch для role‑bleed: если base/non‑Instruct Llama‑3 (например `Meta-Llama-3-8B.Q4_K_M`) пытается продолжить диалог и эмитит новый `<|start_header_id|>`, генерация останавливается на role‑boundary вместо того, чтобы писать диалог за обоих собеседников. Тот же приём использует SillyTavern для Llama‑3.

Полный список `_TEMPLATE_IMPLIED_STOPS` — 17 записей (`template_detector.py:515-545`), включая `qwen3-thinking`, `qwen3-non-thinking`, `qwen`, `mistral-v0-1`, `mistral-v3-tekken`, `deepseek`, `gemma3`, `gemma`, `command-r`, `phi-3`, `gpt-oss`, `exaone`, `granite`, `olmo`, `alpaca` (iter‑59), `chatml`, `llama-3`.

---

### 4. Сопутствующие подсистемы (критично для воспроизведения)

**iter‑97 (KI#79) — auto‑override `tokenizer.ggml.pre`**
- В `_ARCH_PRETOKENIZER_MAP` (`local_server_manager.py:78-85`) лежит 5 записей: `llama+llama-3→llama3`, `qwen3+qwen3→qwen3`, `deepseek2+deepseek→deepseek-llm`, `deepseek3+deepseek→deepseek-llm`, `gpt-oss+gpt-oss→gpt-2`.
- Если GGUF не содержит `tokenizer.ggml.pre` (поле появилось в llama.cpp PR #6920, 2024‑04‑24) и архитектура опознана как BPE — `start_server_async()` автоматически добавляет `--override-kv tokenizer.ggml.pre=str:<value>`.
- Без этого `llama-server` пишет `missing pre-tokenizer type` + `GENERATION QUALITY WILL BE DEGRADED` — ломаются апострофы, распределение токенов уезжает от тренировочного. Это частая проблема старых квантов (QuantFactory/Meta-Llama-3-8B, апрель 2024).

**iter‑89 (KI#69) — EOS drift detection**
- `_CANONICAL_EOS_BY_TEMPLATE` (`template_detector.py:775-811`) хранит канонические `eos_token_id` для каждой семьи. Для Qwen3 — три значения (`151645`, `248044`, `248046`) — последние два добавлены iter‑95 (KI#77), чтобы Qwen3.5 с расширенным вокабуляром не давал ложное срабатывание.
- Если GGUF `eos_token_id` НЕ содержит ни одного канонического ID — логируется WARNING + `result.eos_drift = True`. Stop‑tokens при этом **не меняются** (остаются template_implied), warning лишь сигнализирует, что они могут быть неэффективны.
- `result.eos_drift` логируется как WARNING, но **больше не используется для gating reasoning_budget_tokens** (iter‑95 KI#77 — gate был убран, потому что оказался false positive для Qwen3.5: canonical eos изменился на 248044/248046 в более крупном вокабуляторе, и детектор ложно срабатывал). Раньше (iter‑90 KI#74) при дрейфе `reasoning_budget_tokens` skip'ался, но это приводило к REASONING_EXHAUSTED (0 text, empty response) — строго хуже гипотетического garbage‑риска. Сейчас budget инжектится для ВСЕХ thinking-capable моделей независимо от `eos_drift`. Подробности — см. §5.
- Семьи с нестабильным/недокументированным eos (gpt-oss, command-r, phi-3, deepseek, alpaca) намеренно **пропущены** — лучше нет warning, чем ложный.

**iter‑93 (KI#75) — гейт `--reasoning on/off` на capability_map** (слой 1 из 3 — см. §5)
- В самом верху `start_server_async()` (`local_server_manager.py:469`) детектор отрабатывает **до** решения про `--reasoning`. Если `capability_map.enable_thinking == False` — `--reasoning off` форсируется независимо от пользовательской настройки (лог KI#75: «model template does not support thinking»). Покрывает Llama‑3/Mistral/Gemma/Vicuna.
- Это критичный order‑of‑operations фикс (AP‑3 из PATTERNS.md): детекция обязана идти раньше решения про reasoning flag. Раньше detect_template() вызывался в двух местах ПОСЛЕ решения про флаг — теперь один раз выше, результат переиспользуется.
- Только один из трёх слоёв gating reasoning — полный разбор в §5.

---

### 5. Reasoning pipeline: эволюция и текущая архитектура (iter‑76 → iter‑105)

Пайплайн рассуждений завязан на детекцию шаблонов через два поля `DetectionResult`:
- `capability_map.enable_thinking` — извлекается из Jinja (присутствие переменной `enable_thinking` или маркеров `<think>`/`</think>`), говорит, **умеет ли модель думать**.
- `eos_drift` — вычисляется в `_check_eos_drift()` (см. §4), говорит, **совпадает ли GGUF eos с каноническим**.

Архитектура: **3 слоя gating**, каждый со своим KI‑циклом:

| # | Слой | Где живёт | Что контролирует | Главный KI |
|---|------|-----------|------------------|------------|
| 1 | Server flag | `local_server_manager.py:496-548` | `--reasoning on/off` — серверный parse `<think>` блоков | KI#75 (iter‑93) |
| 2 | Per-request budget | `local_provider.py:_build_extra_body()` (~`:486-510`) | `reasoning_budget_tokens` — sub-cap на thinking токены | KI#60 (iter‑80) + KI#74 (iter‑90) + KI#77 (iter‑95) |
| 3 | Per-request message | тот же сайт, opt-in | `reasoning_budget_message` — force switch на ответ при budget exhaustion | iter‑80.1 (opt-in) |

**Хронология KI** (кратко — полный разбор в PATTERNS.md §5 + STATUS.md Closed KIs):

| KI | iter | Суть | Статус |
|----|------|------|--------|
| KI#57 | 76 | `reasoning_content` extraction (до этого silently dropped) | CLOSED |
| KI#58 | 77 | Канонические маркеры `<think>\n` / `\n</think>\n` (были literal `"thinking\n"`) — iter‑77 был ghost commit (AP‑10), реально пофикшено позже | CLOSED |
| KI#59 | 78 | **CONSUME, NOT YIELD** — `reasoning_content` считаем для диагностики, но НЕ отдаём в поток (иначе history/display leakage) | CLOSED |
| KI#60 | 80 v2 | Per-request `reasoning_budget_tokens` sub-cap (`reasoning_mode=True` → инжектится) | CLOSED |
| KI#62 | 86 | DEBUG-логирование `reasoning_budget_tokens` / `reasoning_budget_message` в extra_body | CLOSED |
| KI#64 | 87 | `--reasoning on` ЯВНО при `reasoning_mode=True` (auto не парсит `<think>` после первого блока для ChatML-family) | CLOSED |
| KI#74 | 90 + 95 | Gate `reasoning_budget_tokens` на `enable_thinking` (skip, если модель не умеет думать). `eos_drift` gate **убран** в iter‑95 | CLOSED |
| KI#75 | 93 | Gate `--reasoning on/off` на `enable_thinking` ONLY. `detect_template()` перенесён ВЫШЕ решения про флаг (AP‑3 fixed) | CLOSED |
| KI#77 | 95 | Qwen3.5 EOS false positive — `_CANONICAL_EOS_BY_TEMPLATE` дополнен 248044/248046; `eos_drift` gate removed | CLOSED |
| KI#80 | 101 | `_strip_role_alternation_placeholders()` в `local_provider.py` — strip `[conversation continued]` перед отправкой (Llama‑3 echo fix). iter‑99 был ghost commit (AP‑10) | CLOSED |
| KI#82 | 105 | Base model runaway generation — CLOSED как model limitation. `<|start_header_id|>` stop token retained как defensive measure для Instruct | CLOSED |

**Contradiction #4 (PATTERNS.md §9)** — критичное архитектурное решение:

`eos_drift` НЕ используется для gating reasoning. Только `enable_thinking`.

Доказательство: Gemma‑4‑HauhauCS (`eos_drift=True`, `enable_thinking=True`) работает WITH reasoning — 282 text + 618 reasoning chunks, хорошее качество. `<think>`/`</think>` — это **string-based markers**, а не token-based. eos drift влияет на STOP generation, не на PARSE reasoning. Глобальный gate на `eos_drift` регрессил бы эту модель.

Для `eos_drift=True` + thinking-capable моделей, которые НЕ self-regulate (Qwen3.5-abliterated) — это AP‑7 (model broken), app не лечит, рекомендация: switch to non-abliterated.

**Reasoning_content handling (KI#57 → KI#59)** — критичный паттерн consume-not-yield:

`LocalProvider.generate_stream()` (~`:773`):
```python
reasoning = getattr(delta, "reasoning_content", None)
if reasoning:
    reasoning_chunks += 1
    continue  # consume but don't yield
```

Yield thinking НЕЛЬЗЯ — это даёт: (a) сохранение в history как literal текст, (b) typewriter показывает thinking, (c) TTS озвучивает thinking. `reasoning_chunks` используется только для диагностики: `REASONING_EXHAUSTED` warning если `text_chunks == 0 and reasoning_chunks > 0`.

**Known model behavior** (полная таблица — PATTERNS.md §6):

| Модель | enable_thinking | eos_drift | Поведение с iter‑105 |
|--------|-----------------|-----------|----------------------|
| Meta-Llama-3-8B (base) | False | False | `--reasoning off` FORCED (KI#75). Base model генерирует raw prose без структурных токенов — stop-words не ловят. KI#82 CLOSED как model limitation |
| Qwen3.5-9B-abliterated | True | True (canonical расширена iter‑95) | 0 text + 1000 reasoning, REASONING_EXHAUSTED. AP‑7 — abliteration сломала thinking→text. App не лечит, рекомендация: switch to non-abliterated |
| Gemma-4-E4B-HauhauCS | True | True | Работает WITH reasoning (282 text + 618 reasoning, good quality). KI#75 намеренно НЕ gate'ит на eos_drift |
| Qwen3.5-9B-Q4 (official) | True | False (после iter‑95 fix) | Работает. KI#77 budget injection = safety net, модель self-regulates |

**Ключевые anti-patterns** (полный список — PATTERNS.md §1):
- **AP‑2 Partial gating**: fix одного слоя без sibling. KI#74 (iter‑90) закрыл per-request budget, но оставил server flag ungated → Qwen3.5-abliterated всё равно 0 text. Закрыто KI#75 (iter‑93).
- **AP‑3 Order-of-operations**: detection跑 ПОСЛЕ решения про `--reasoning`. KI#75 перенёс `detect_template()` ВЫШЕ флага (см. §4 этой статьи).
- **AP‑5 Assumption without verification**: `reasoning_mode=True` ≠ "модель умеет думать". `reasoning_mode` — user INTENT, `enable_thinking` — model SUPPORT. Должно быть AND-gate.
- **AP‑7 Model broken vs app broken**: если ВСЕ mitigation'ы применены (verified via logs), а модель всё равно garbage → модель сломана. Не итерировать app-side фиксы для model-level дефекта (Qwen3.5-abliterated).
- **AP‑10 Ghost commit**: STATUS/worklog описывают фикс, которого нет в `git diff`. iter‑77 (KI#58) и iter‑99 (KI#80). Всегда проверять `git diff <target_file>` перед commit.

**Ключевые уроки из PATTERNS.md §2** (без повторов — только то, что влияет на детекцию):
- iter‑29.1: `enable_thinking` via `--chat-template-kwargs` deprecated в llama.cpp build 4629+. Использовать `--reasoning on/off`.
- iter‑38: `--chat-template` flag triggerит peg-native parser bug в llama.cpp b9550. Только при отсутствии GGUF‑embedded template.
- iter‑59: `reasoning_content` consume silently — НЕ yield'ить.
- iter‑60: `reasoning_budget_tokens` — canonical field name (PR #22740). `thinking_budget_tokens` — back-compat alias, никогда не слать оба.
- iter‑64: `--reasoning on` нужен ЯВНО при `reasoning_mode=True` (auto не парсит `<think>` после первого блока для ChatML-family).
- iter‑66: `qwen3-thinking` Jinja pattern должен проверяться BEFORE `chatml` — Qwen3 Jinja содержит ChatML маркеры как base format.
- iter‑68: unique-family Jinja patterns (`gemma3`, `mistral-v0-1`, `command-r`, `alpaca`) должны проверяться BEFORE `qwen3-thinking` — finetune авторы добавляют `<think>` в не-Qwen3 модели.

---

### 6. Когда реально нужно смотреть в логи

- `"Architecture <X> not in heuristic map — falling back to ChatML. Template may be incorrect"` — WARNING из `template_detector.py:1138`.
- `"No architecture field in GGUF — falling back to ChatML"` — WARNING из `:1148`.
- `"Auto-fallthrough: embedded template has validation errors, falling back to architecture heuristic"` — появляется только после ручного «Validate vocab» в Diagnostics Panel и означает, что embedded Jinja сломана (неатомарные special tokens), поэтому используется arch‑эвристика (Layer 1c).
- `"EOS drift: GGUF eos_token_id=... does not contain canonical ... eos (...)"` — WARNING: GGUF eos не совпадает с каноническим. Больше НЕ влияет на reasoning budget (см. §4/§5), но сигнализирует, что stop-words могут быть неэффективны.
- `"missing pre-tokenizer type"` + `"GENERATION QUALITY WILL BE DEGRADED"` (лог `llama-server`) — GGUF без `tokenizer.ggml.pre`, нужно либо обновить квант, либо убедиться что сработал auto‑override KI#79.
- `"[KI#75] --reasoning off FORCED for this model"` — INFO, не ошибка: модель не поддерживает thinking, флаг принудительно off.
- `"[KI#74] reasoning_budget_tokens SKIPPED for this model"` — INFO: `enable_thinking=False`, per-request budget не инжектится (слой 2). Не путать с KI#75 (слой 1).
- `"Chat Template '<name>' SKIPPED — GGUF-embedded template present"` — INFO, не ошибка: флаг `--chat-template` намеренно не передаётся (KI#44), `llama-server` применит embedded Jinja нативно.
- `"Template name overridden by Jinja inference: arch=<X> -> <Y> (arch) -> <Z> (jinja, conf=...)"` — INFO: Jinja‑inference подменяет arch‑эвристику для disambiguation Llama‑3/Mistral/Llama‑2.
- `"[KI#78] Jinja inference '<X>' SKIPPED for arch=<Y>: unambiguous arch resolved to '<Z>' (same family)"` — INFO: cross‑family override срезан guard'ом, потому что архитектура однозначная.
- `REASONING_EXHAUSTED: model produced N reasoning chunks but 0 text chunks` — WARNING: модель зациклилась в thinking и не выдала видимого ответа. Либо `reasoning_mode` выключить, либо (для abliterated) — модель сломана (AP‑7).
- Если качество генерации резко упало (модель «сходит с ума», не останавливается, ломает JSON) — это уже не про детекцию шаблона, а про повреждённый GGUF (пример: `Meta-Llama-3-8B.Q4_K_M`, на который `llama.cpp` ругается `missing pre-tokenizer type` — проблема квантизации, не детектора шаблонов). Базовые модели (не Instruct) могут генерировать сырую прозу без структурных токенов — stop‑words их не поймают, нужен Instruct‑finetune (KI#82, iter‑105 CLOSED как model limitation).
