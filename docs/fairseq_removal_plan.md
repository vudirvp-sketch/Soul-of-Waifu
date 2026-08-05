# План: удаление fairseq из Soul of Waifu (iter-107 → iter-107-audit → iter-110-audit)

**Дата**: 2026-08-02 (audit: 2026-08-02, re-audit: 2026-08-06)
**Масштаб**: Normal (1 новый файл ~180 строк + правки в `text_to_speech.py` + 1 строка в `requirements.txt`)
**Путь**: A — замена загрузчика HuBERT на HF-версию

**История ревизий**:
- iter-107: первичный план (8 разделов).
- iter-107-audit: добавлены GAP-A и GAP-B (KI#83, BLOCKING). Без этих фиксов iter-110 падает с `ModuleNotFoundError: fairseq` на старте приложения, а monkey-patch в iter-108/109 silently no-op. См. §1.7, §1.8, §2.2.
- iter-110-audit: сверка с актуальным состоянием репозитория `vudirvp-sketch/Soul-of-Waifu`. Найдено и исправлено 8 фактических ошибок: версия fairseq (0.12.3 → 0.12.2), 6 неверных номеров строк (`requirements.txt: 55/173/212 → 58/191/235`; `text_to_speech.py: 25/27-32/37-42/195 → 28/30-35/39-45/198`), удалён ложный assertion про `installer.bat:93 --no-deps` (installer.bat вообще не ставит rvc-python — он приходит только через `requirements.txt:191`).

---

## 1. Контекст — что проверено

### 1.1. Где fairseq реально используется

В коде SoW (`app/utils/text_to_speech.py:30-35`) — только safe_globals-костыль для `torch.load`:
```python
import torch.serialization
try:
    from fairseq.data.dictionary import Dictionary
    torch.serialization.add_safe_globals([Dictionary])
except ImportError:
    pass
```
Это не «использование fairseq как библиотеки», а «разрешение torch десериализовать HuBERT-чекпойнт». Реальный потребитель fairseq — `rvc-python@9a67ac7` (pinned в `requirements.txt:191`).

### 1.2. Точка входа fairseq внутри rvc-python

Единственное место, где fairseq дёргается в рантайме RVC:
```
rvc_python/modules/vc/utils.py:21  load_hubert(config, lib_dir)
    → from fairseq import checkpoint_utils
    → checkpoint_utils.load_model_ensemble_and_task([f"{lib_dir}/base_model/hubert_base.pt"])
    → returns hubert_model
```

Вторая точка (`rvc_python/lib/jit/get_hubert.py:get_hubert_model`) — используется только ONNX-экспортом, **не** в рантайме `RVCInference`. Патчить не обязательно.

### 1.3. Контракт модели HuBERT, который нужно воспроизвести

Из `rvc_python/modules/vc/pipeline.py:215-223`:
```python
inputs = {
    "source": feats,              # [1, T] float32, 16kHz аудио
    "padding_mask": padding_mask, # [1, T] bool, all False
    "output_layer": 9 if version == "v1" else 12,
}
logits = model.extract_features(**inputs)         # → tuple (feats, padding_mask)
feats = model.final_proj(logits[0]) if version == "v1" else logits[0]
```

Контракт:
1. `model.extract_features(source, padding_mask, output_layer=9|12)` → `(feats, padding_mask_out)`
2. `model.final_proj(feats)` — **только для RVC v1**
3. `model.eval()`, `model.to(device)`, `model.half()`/`.float()` — стандартные `nn.Module` методы

### 1.4. HF-модель: `facebook/hubert-base-ls960`

- 889,944 скачиваний на HuggingFace Hub.
- Архитектурно идентичен `hubert_base.pt` (сверены `config.json`):
  - `num_hidden_layers: 12`, `hidden_size: 768`
  - `do_stable_layer_norm: false` → соответствует fairseq `layer_norm_first=False`
  - `num_conv_pos_embeddings: 128`, `num_conv_pos_embedding_groups: 16`
  - `feat_extract_norm: group`, `conv_bias: false`
- Веса сконвертированы из того же fairseq-чекпойнта официальным скриптом `transformers/convert_hubert_original_pytorch_checkpoint_to_pytorch.py`.
- **НЕ включает `final_proj`** (это pretraining-only head, в HF-модели отсутствует).

### 1.5. v1 vs v2

- `rvc_python/infer.py:65`: `load_model(model_name, version="v2")` — **по умолчанию v2**.
- `text_to_speech.py:198` вызывает `self.rvc.load_model(model_name)` без указания version → v2.
- Для v2 `final_proj` НЕ нужен (`pipeline.py:223`: `feats = logits[0]`).
- v1 в SoW сейчас возможен только если пользователь положит v1 `.pth` в `assets/rvc_models/<name>/` и `load_model` обнаружит `version=v1` внутри чекпойнта — но это переопределяется аргументом `version="v2"` в `infer.py:65,107`. То есть фактически v1 путь в SoW не используется.

**Вывод**: HF-модели без `final_proj` достаточно для всех сценариев SoW.

### 1.6. Зависимости

- `transformers==4.57.3` **уже в requirements.txt:235** — ничего добавлять.
- `fairseq==0.12.2` (requirements.txt:58) — удалить (только после того, как stub `sys.modules['fairseq']` из §2.2 уже в коде, иначе падение на старте — см. §1.7).
- `rvc-python @ git+https://github.com/JarodMica/rvc-python@9a67ac7...` (requirements.txt:191) — оставить, monkey-patch поверх.
- **`installer.bat` НЕ устанавливает rvc-python** (проверено iter-110): в нём нет ни одной команды `pip install rvc-python`/`pip install rvc_python`, флаг `--no-deps` тоже не используется. rvc-python попадает в окружение исключительно через `requirements.txt:191` (стандартный `pip install -r requirements.txt`). Справочник rvc-python fairseq в собственных зависимостях не перечисляет — единственный источник fairseq в env = SoW `requirements.txt:58`.

### 1.7. GAP-A — import-time зависимость от fairseq (KI#83, BLOCKING)

В rvc-python@9a67ac7 fairseq импортируется не только внутри тела `load_hubert`, но и **на верхнем уровне модуля**:

```
rvc_python/modules/vc/utils.py:3   from fairseq import checkpoint_utils
```

Эта строка исполняется **в момент импорта** `rvc_python.modules.vc.utils`, который входит в цепочку, триггерящуюся при `from rvc_python.infer import RVCInference` (единственный rvc-python import во всём SoW — `text_to_speech.py:28`, проверено полным grep):

```
text_to_speech.py:28  from rvc_python.infer import RVCInference
  → rvc_python/__init__.py
    → infer.py:5  (импорт modules)
      → modules/vc/modules.py:19  from .utils import *
        → modules/vc/utils.py:3  from fairseq import checkpoint_utils   ← ModuleNotFoundError, если fairseq нет в env
```

Monkey-patch `load_hubert` (§2.2 ниже) **не** нейтрализует эту строку — она выполняется раньше любого прикладного кода SoW. Удаление `fairseq==0.12.2` из `requirements.txt` без stub'а → `ModuleNotFoundError: fairseq` на старте приложения.

**Фикс** (детали в §2.2.1): до строки `from rvc_python.infer import RVCInference` в `text_to_speech.py` inject'нуть в `sys.modules` stub-модуль `fairseq` + `fairseq.checkpoint_utils`. Stub устанавливается только если real fairseq ещё не в `sys.modules` (если уже импортирован кем-то раньше — пропускаем, не затеняем). Если fairseq установлен, но ещё не импортирован — stub встаёт первым и real fairseq не поднимается (это нормально: monkey-patch `load_hubert` заменяет единственного потребителя `checkpoint_utils.load_model_ensemble_and_task`, так что stub-реализация этой функции никогда не вызывается). Если fairseq удалён — stub удовлетворит `from fairseq import checkpoint_utils`.

### 1.8. GAP-B — двойная цель monkey-patch (KI#83, BLOCKING)

`rvc_python/modules/vc/modules.py:19` выполняет:

```python
from rvc_python.modules.vc.utils import *   # ← rebinds load_hubert into modules.vc.modules namespace
```

После этого `modules.vc.modules.load_hubert` и `modules.vc.utils.load_hubert` — **две разные ссылки** на один и тот же объект функции (на момент импорта). Патч `rvc_python.modules.vc.utils.load_hubert = _hf_load_hubert` меняет только первую; вторая (`modules.vc.modules.load_hubert`) продолжает указывать на оригинальную fairseq-реализацию.

`vc_single()` в `modules/vc/modules.py:168` вызывает `load_hubert(...)` как **bare name** → Python разрешает имя из globals `modules.vc.modules`, а не `modules.vc.utils`. То есть патч `utils.load_hubert` **silently no-op**: реальный вызов идёт через непатченную ссылку в `modules`.

Симптом на iter-108/109 без фикса: monkey-patch формально установлен, `RVCInference` ходит через оригинальный fairseq-загрузчик, A/B-тест сравнивает fairseq-vs-fairseq (а не fairseq-vs-HF), и проходит тривиально. На iter-110 после удаления fairseq приложение падает с ImportError уже после старта — но это другой сбой, не тот, что тестирует iter-109.

**Фикс** (детали в §2.2): патчить **обе** ссылки:
```python
_rvc_utils.load_hubert = _hf_load_hubert
_rvc_modules.load_hubert = _hf_load_hubert   # CRITICAL — именно эту вызывает vc_single()
```

---

## 2. Архитектура решения

### 2.1. Новый модуль `app/utils/rvc_hubert_hf.py`

Обёртка над `transformers.HubertModel`, эмулирующая fairseq-интерфейс:

```python
class HubertHFWrapper(torch.nn.Module):
    """HF HuBERT, эмулирующий fairseq-контракт для rvc-python."""
    
    def __init__(self, hf_model_id="facebook/hubert-base-ls960", device="cpu", is_half=False):
        super().__init__()
        from transformers import HubertModel
        self.model = HubertModel.from_pretrained(hf_model_id).to(device)
        if is_half:
            self.model = self.model.half()
        else:
            self.model = self.model.float()
        self.model.eval()
        # final_proj отсутствует в HF-модели. Заглушка для v1-совместимости.
        self._final_proj = None  # Lazy: загружается из final_proj.pt если есть
    
    def extract_features(self, source, padding_mask=None, output_layer=None,
                         mask=False, ret_conv=False):
        """Возвращает (feats, padding_mask) — как fairseq HuBERT.extract_features."""
        outputs = self.model(
            input_values=source,
            attention_mask=~padding_mask if padding_mask is not None else None,
            output_hidden_states=True,
        )
        # output_layer — int (9 для v1, 12 для v2)
        if output_layer is not None:
            feats = outputs.hidden_states[output_layer]
        else:
            feats = outputs.last_hidden_state
        return feats, padding_mask
    
    def final_proj(self, feats):
        if self._final_proj is None:
            raise RuntimeError(
                "RVC v1 models require final_proj weights. "
                "Place final_proj.pt (extracted from hubert_base.pt) in "
                "assets/rvc_models/base_model/final_proj.pt, or use v2 models."
            )
        return self._final_proj(feats)
    
    def _load_final_proj(self, path):
        """Загружает Linear weights из предварительно извлечённого final_proj.pt."""
        state = torch.load(path, map_location="cpu")
        self._final_proj = torch.nn.Linear(state["weight"].shape[1], state["weight"].shape[0])
        self._final_proj.load_state_dict(state)
        self._final_proj = self._final_proj.to(next(self.model.parameters()).device)
```

### 2.2. Monkey-patch `load_hubert` (двойная цель) + stub `sys.modules['fairseq']`

В `app/utils/text_to_speech.py` — три блока, идущие **строго в указанном порядке** в верхней части модуля (до любого другого кода, использующего `rvc_python`):

#### 2.2.1. Stub `fairseq` в `sys.modules` (GAP-A fix)

Должен идти **до** `from rvc_python.infer import RVCInference`. Если настоящий fairseq установлен — stub не мешает (импорт ниже по цепочке перезапишет атрибуты); если удалён — stub удовлетворит top-level `from fairseq import checkpoint_utils` в `rvc_python/modules/vc/utils.py:3`.

```python
import sys
import types

def _install_fairseq_stub() -> None:
    """Inject no-op fairseq stub into sys.modules if real fairseq is absent.

    rvc_python/modules/vc/utils.py:3 has top-level `from fairseq import checkpoint_utils`,
    which fires at import time (chain: rvc_python.infer → modules.vc.modules → modules.vc.utils).
    Without fairseq installed, this raises ModuleNotFoundError on app launch.
    The stub satisfies the import; the real loader is replaced by HubertHFWrapper
    via the monkey-patch below, so checkpoint_utils.load_model_ensemble_and_task
    is never actually called.
    """
    if 'fairseq' in sys.modules:
        return  # real fairseq already imported — don't shadow it
    fairseq_stub = types.ModuleType('fairseq')
    cp_stub = types.ModuleType('fairseq.checkpoint_utils')
    # Signature matches rvc_python/modules/vc/utils.py:21 call site. Never reached
    # in practice (load_hubert is patched), but defined defensively so any
    # unexpected call raises a clear error instead of AttributeError.
    def _load_model_ensemble_and_task(*args, **kwargs):
        raise RuntimeError(
            "fairseq stub called — HubertHFWrapper monkey-patch did not install correctly. "
            "Check that _rvc_modules.load_hubert (not just _rvc_utils.load_hubert) is patched."
        )
    cp_stub.load_model_ensemble_and_task = _load_model_ensemble_and_task
    fairseq_stub.checkpoint_utils = cp_stub
    sys.modules['fairseq'] = fairseq_stub
    sys.modules['fairseq.checkpoint_utils'] = cp_stub

_install_fairseq_stub()
```

#### 2.2.2. Импорт rvc_python (после stub'а)

```python
from rvc_python.infer import RVCInference  # ← после _install_fairseq_stub()
```

#### 2.2.3. Двойной monkey-patch `load_hubert` (GAP-B fix)

Вместо safe_globals-костыля строки 27-32. Патчит **обе** ссылки — в `utils` и в `modules` (см. §1.8 почему):

```python
import os
import logging

from app.utils.rvc_hubert_hf import HubertHFWrapper
import rvc_python.modules.vc.utils as _rvc_utils
import rvc_python.modules.vc.modules as _rvc_modules  # CRITICAL — vc_single() resolves here

logger = logging.getLogger("Text-To-Speech Module")

def _hf_load_hubert(config, lib_dir):
    """HF-based replacement for rvc_python's fairseq-based load_hubert.

    Patched into BOTH rvc_python.modules.vc.utils AND rvc_python.modules.vc.modules
    because modules.py:19 does `from utils import *` — see fairseq_removal_plan.md §1.8.
    """
    device = config.device
    is_half = config.is_half
    wrapper = HubertHFWrapper(
        hf_model_id="facebook/hubert-base-ls960",
        device=device,
        is_half=is_half,
    )
    fp_path = os.path.join("assets", "rvc_models", "base_model", "final_proj.pt")
    if os.path.exists(fp_path):
        wrapper._load_final_proj(fp_path)
    logger.info("HuBERT loaded via HF (facebook/hubert-base-ls960), device=%s, half=%s", device, is_half)
    return wrapper

# CRITICAL: patch BOTH namespaces. Order matters only if modules.py hasn't been
# imported yet — but text_to_speech.py:28 already triggered the chain, so both
# modules are loaded and both names exist by the time we reach this line.
_rvc_utils.load_hubert = _hf_load_hubert
_rvc_modules.load_hubert = _hf_load_hubert
```

#### 2.2.4. Sanity check (один раз при первом запуске iter-108)

После применения патча добавить временный assert в конце модуля (удалить перед iter-109):
```python
assert _rvc_modules.load_hubert is _hf_load_hubert, \
    "GAP-B fix failed: modules.vc.modules.load_hubert not patched"
assert _rvc_utils.load_hubert is _hf_load_hubert, \
    "GAP-B fix failed: modules.vc.utils.load_hubert not patched"
```

### 2.3. Удаление safe_globals-костыля

`text_to_speech.py:30-35` — удалить полностью (больше не нужно, `torch.load` для fairseq-чекпойнта не вызывается). Stub `sys.modules['fairseq']` из §2.2.1 заменяет эту защиту по всему модулю.

**Важно**: stub из §2.2.1 должен идти **до** удаления safe_globals-костыля в одной правке. Промежуточное состояние (удалён safe_globals, нет stub'а) упадёт на старте, если fairseq уже удалён. Порядок правок в iter-108: (1) добавить stub, (2) добавить monkey-patch, (3) удалить safe_globals — всё в одном коммите.

### 2.4. Пропуск скачивания `hubert_base.pt`

`rvc_python/download_model.py:16` скачивает `hubert_base.pt` (~370 МБ) с HuggingFace. Это больше не нужно. Опции:

- **(Рекомендуется)** Monkey-patch `rvc_python.download_model.download_rvc_models`, чтобы он пропускал `hubert_base.pt`:

  ```python
  import rvc_python.download_model as _rvc_dl

  _orig_download = _rvc_dl.download_rvc_models

  def _skip_hubert_download(lib_dir):
      # Скачиваем только rmvpe.pt, пропускаем hubert_base.pt
      # (HF-версия загрузится через transformers HubertModel.from_pretrained)
      ...

  _rvc_dl.download_rvc_models = _skip_hubert_download
  ```
  Или проще — проверить: что скачивает `download_rvc_models` и можно ли обойтись без патча (если скачивание идемпотентно и быстро).

- **(Альтернатива)** Оставить как есть — `hubert_base.pt` будет скачан, но не использован. Минус: +370 МБ на диске. Плюс: ноль кода.

Решение отложить на iter-108 (после проверки, что `download_rvc_models` действительно скачивает только HuBERT и нет других файлов).

### 2.5. `requirements.txt`

Удалить строку 58: `fairseq==0.12.2`.

**Жёсткое предусловие** (без него iter-110 падает на старте):
1. Stub `sys.modules['fairseq']` (§2.2.1) уже в коде и протестирован в iter-108.
2. Двойной monkey-patch (§2.2.3) в коде.
3. A/B-тест iter-109 прошёл.
4. safe_globals-костыль (§2.3) удалён — иначе при отсутствии fairseq `from fairseq.data.dictionary import Dictionary` тоже упадёт (он в `try/except ImportError`, так что формально не критично, но мёртвый код).

Сделать **только после A/B-теста** (шаг 4 ниже). До теста оставить — fallback.

---

## 3. Этапы реализации

| iter | Этап | Объём | Риск |
|------|------|-------|------|
| **107** | План + проверка архитектуры | docs только | 0 |
| **107-audit** | KI#83 OPEN: найдены GAP-A (import-time dep) и GAP-B (двойная цель monkey-patch). План обновлён (этот документ). | docs только | 0 |
| **108** | Создать `app/utils/rvc_hubert_hf.py` + stub `fairseq` (§2.2.1) + двойной monkey-patch (§2.2.3) + удалить safe_globals (§2.3). **fairseq НЕ удалять из requirements.txt** (fallback через try/except + реальный fairseq). Временный assert §2.2.4 на первый запуск. | ~200 строк | низкий — fallback есть, assert ловит GAP-B |
| **109** | A/B-тест: генерация речи с одним и тем же `.pth` через fairseq (временный откат патча) и через HF, сравнение спектрограмм/слепое прослушивание. **Предусловие**: assert §2.2.4 подтверждает, что A/B реально тестирует HF, а не fairseq-vs-fairseq. | тестовый скрипт | низкий |
| **110** | Если A/B OK: удалить `fairseq` из requirements.txt:58 (§2.5), обновить `AGENT_NAVIGATION.md §4` (Pitfalls) запиской про stub. Удалить временный assert §2.2.4. | ~10 строк | требует переустановки env |
| **111** | (Опционально) Monkey-patch `download_rvc_models` для пропуска `hubert_base.pt` (~30 строк) | ~30 строк | низкий |

**iter-110 БЕЗ фиксов A+B запускать нельзя** — приложение упадёт с `ModuleNotFoundError: fairseq` на старте (GAP-A) или продолжит ходить через fairseq (GAP-B, при установленных deps) — но в обоих случаях результат не тот, что обещает план.

---

## 4. A/B-тест (iter-109) — критерии приемки

1. **Спектрограмма**: для одного входного WAV и одного `.pth`-модели сравнить мел-спектрограммы выхода RVC через fairseq и через HF. Допуск: RMS различия < 1% по всему файлу.
2. **Слепое прослушивание**: 3 образца, 2 слушателя. Если оба не могут различить — pass.
3. **Перформанс**: время инференса на CPU/GPU. HF-версия ожидается равной или быстрее (нет overhead fairseq-checkpoint-loader).
4. **Память**: HF HuBERT base — ~370 МБ весов (`pytorch_model.bin`), ровно столько же, сколько fairseq-версия. Диск: HF-кеш ровно один файл весов (~370 МБ) + `config.json` (~2 КБ). Никаких «state_dict + оптимизатор» — модельное семейство `HubertModel` отдаёт только inference-веса, optimizer state не сохраняется. На GPU можно уменьшить до ~185 МБ через `torch_dtype=torch.float16`. Кеш лежит в `app/models/hf_cache` (уже настроен в `text_to_speech.py:39-45` через `HF_HOME`/`HUGGINGFACE_HUB_CACHE`).

Если A/B fails → откат к fairseq, документирование причины в STATUS.md как KI.

---

## 5. Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| **GAP-A**: top-level `from fairseq import checkpoint_utils` в `rvc_python/modules/vc/utils.py:3` падает при отсутствии fairseq | высокий (без фикса) | Stub `sys.modules['fairseq']` (§2.2.1) до `from rvc_python.infer import RVCInference`. Безопасно при установленном fairseq (no-op). |
| **GAP-B**: monkey-patch только `utils.load_hubert` silently no-op из-за `from utils import *` в `modules.py:19` | высокий (без фикса) | Патчить **обе** ссылки: `_rvc_utils.load_hubert` + `_rvc_modules.load_hubert` (§2.2.3). Временный assert §2.2.4 ловит регрессию на первом запуске iter-108. |
| HF HuBERT выдаёт фичи, отличающиеся от fairseq по subtle причинам (layer_norm позиции, padding_mask обработка) | средняя | A/B-тест на спектрограмме. Если отличаются — инспектировать `transformers.models.hubert.modeling_hubert.HubertModel.forward` и сравнивать с `get_hubert.py:extract_features`. |
| Пользователь загрузит RVC v1 `.pth` модель | низкая (дефолт v2) | Явная ошибка в `final_proj()` с инструкцией. Дополнительно: detection в `load_model` — если `cpt.get("version") == "v1"`, warn пользователя. |
| `transformers.HubertModel` ломит совместимость с `torch==2.10.0+cu128` | низкая (4.57.3 поддерживает) | Если упадёт — downgrade `transformers` до 4.40-4.50. |
| Stub `fairseq.checkpoint_utils` когда-нибудь понадобится с другой сигнатурой (если rvc-python обновит pinned-коммит) | низкая (коммит pinned в requirements.txt:191; rvc-python не переустанавливается через `installer.bat` — только через `requirements.txt`) | При обновлении pinned-коммита rvc-python — повторить аудит fairseq-usage map, как в iter-107. |
| `from rvc_python.modules.vc.utils import *` добавит новые имена в `modules` namespace в будущем rvc-python | низкая (pinned) | Тот же аудит. |

---

## 6. Что НЕ делаем в этом плане

- **Не** трогаем архитектуру RVC-пайплайна (`rvc_python/modules/vc/pipeline.py` остаётся как есть).
- **Не** трогаем `rvc_python/lib/jit/get_hubert.py` — ONNX-export-only, не входит в `__init__.py`→`infer.py` цепочку импорта (проверено в iter-107-audit). Если в будущем понадобится ONNX-экспорт из SoW — отдельная задача.
- **Не** форкаем `rvc-python` — monkey-patch на стороне SoW.
- **Не** меняем UX персонажей (поле `rvc_enabled`, `rvc_file`, `rvc_f0up_key` и т.д. — все сохраняются).
- **Не** меняем `assets/rvc_models/` структуру — все существующие `.pth`-модели продолжают работать.
- **Не** мигрируем на zero-shot VC (Путь B из контекста) — это отдельное стратегическое решение.
- **Не** добавляем stub для `fairseq.data.dictionary.Dictionary` — он использовался только в safe_globals-костыле (§2.3), который удаляется. Если выяснится, что rvc-python где-то ещё импортирует этот путь (не найдено в iter-107-audit) — добавим отдельный stub.

---

## 7. Альтернативы (отклонены)

### 7.1. Путь B: zero-shot VC (Seed-VC / OpenVoice)
- Объём: 1 файл ~300 строк + миграция UI + новая UX для reference-audio.
- Риск: высокий — все `.pth`-модели пользователей становятся бесполезны.
- Решение: отклонено. Если когда-нибудь понадобится — это отдельный проект, не патч.

### 7.2. Путь C: выключить RVC целиком
- Объём: ~10 строк.
- Риск: ломает UX — пользователи потеряют voice-cloning.
- Решение: отклонено. RVC — активная фича (5 TTS-движков имеют RVC-путь в `text_to_speech.py`).

### 7.3. Форк rvc-python с заменой fairseq
- Объём: fork + изменения в `lib/jit/get_hubert.py` и `modules/vc/utils.py`.
- Риск: средний — придется поддерживать fork.
- Решение: отклонено. Monkey-patch на стороне SoW проще и не требует fork-инфраструктуры.

---

## 8. Итог

- **Существует ли HF-версия HuBERT, используемого в SoW?** Да — `facebook/hubert-base-ls960`, архитектурно идентичен `hubert_base.pt`.
- **Сколько кода?** ~200 строк (1 новый файл `app/utils/rvc_hubert_hf.py` + правки в `text_to_speech.py`: stub `sys.modules` + двойной monkey-patch + удаление safe_globals-костыля + 1 строка в `requirements.txt` на iter-110).
- **Какой риск?** Низкий при условии что GAP-A и GAP-B фиксятся в iter-108 одновременно с monkey-patch. Без GAP-A iter-110 падает на старте; без GAP-B iter-108/109 тестирует не то, что кажется.
- **Что разблокирует?** Python 3.12+, удаление `fairseq==0.12.2` (проблемная зависимость с conflict'ами на новых pip/setuptools).

---

## 9. Audit checklist (iter-107-audit → iter-108)

Перед стартом iter-108 Implementer'у проверить (в порядке):

1. **GAP-A размещён правильно**: stub `_install_fairseq_stub()` идёт **до** `from rvc_python.infer import RVCInference` в `text_to_speech.py`. Если ниже — бесполезен.
2. **GAP-B dual-target**: патчатся `_rvc_utils.load_hubert` И `_rvc_modules.load_hubert`. Один без другого = silent no-op.
3. **Stub no-op при установленном fairseq**: если `sys.modules['fairseq']` уже есть (реальный fairseq), stub не перезаписывает. Проверить: при установленном fairseq приложение стартует и без stub'а, и со stub'ом — идентично.
4. **Assert §2.2.4 ловит регрессию**: временный assert на первый запуск iter-108 падает, если патч не встал. Удалить перед iter-109.
5. **safe_globals удалён в том же коммите**: промежуточное состояние (есть stub, нет safe_globals удаления) — допустимо, но менее чисто; обратное (удалён safe_globals, нет stub'а) — упадёт на iter-110.
6. **`lib/jit/get_hubert.py` не трогаем**: ONNX-export-only, не в импорт-цепочке. Если будущий код начнёт дёргать ONNX-экспорт — отдельная задача (см. §6).
7. **A/B-тест iter-109 реально сравнивает HF vs fairseq**: включить DEBUG-лог в `_hf_load_hubert` (см. §2.2.3 `logger.info(...)`) и убедиться, что в логе A/B-теста на HF-стороне есть «HuBERT loaded via HF», а на fairseq-стороне — нет.

Если хотя бы один пункт fails — iter-108 не закрывать, фиксить в том же коммите.
