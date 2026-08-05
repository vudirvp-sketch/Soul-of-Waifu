# План: полное удаление fairseq из Soul of Waifu (пересмотр iter-111)

**Дата**: 2026-08-06 (полный пересмотр: отказ от stub/monkey-patch, форк rvc-python)
**Масштаб**: Deep (форк 3rd-party пакета + новый модуль + правки в text_to_speech.py + requirements.txt)
**Путь**: A-clean — форк rvc-python с заменой fairseq→HF HuBERT внутри форка

**Принцип**: никаких stub'ов `sys.modules`, никаких monkey-patch'ей поверх rvc-python, никаких остатков fairseq. Удалить с корнем.

**История ревизий**:
- iter-107: первичный план (8 разделов, путь A — monkey-patch).
- iter-107-audit: GAP-A/GAP-B найдены, добавлены stub + dual-target monkey-patch.
- iter-110-audit: 8 фактических ошибок исправлено.
- **iter-111**: полный пересмотр. Заказчик отказывается от stub'ов и monkey-patch'ей («не хочу костылей»). Новый подход: **форк rvc-python**, замена fairseq→HF HuBERT **внутри форка**. fairseq удаляется полностью — из requirements.txt, из кода, из sys.modules. Никаких runtime-костылей.

---

## 1. Контекст — что проверено

### 1.1. Где fairseq реально используется

**В SoW-коде** — единственное место: `app/utils/text_to_speech.py:30-35` (safe_globals-костыль для `torch.load`):
```python
import torch.serialization
try:
    from fairseq.data.dictionary import Dictionary
    torch.serialization.add_safe_globals([Dictionary])
except ImportError:
    pass
```
Это мёртвый код после удаления fairseq — просто удалить.

**В rvc-python@9a67ac7** — ровно 2 файла с fairseq-импортами:

| Файл | Импорт | Использование |
|------|--------|---------------|
| `modules/vc/utils.py:2` | `from fairseq import checkpoint_utils` | Загрузка `hubert_base.pt` через `checkpoint_utils.load_model_ensemble_and_task` |
| `lib/jit/get_hubert.py:4,5` | `from fairseq.checkpoint_utils import load_model_ensemble_and_task` + `from fairseq.utils import index_put` | ONNX/JIT-экспорт HuBERT |

**rvc-python НЕ перечисляет fairseq в своих зависимостях** (ни в `pyproject.toml`, ни в `requirements.txt`). fairseq — неявная зависимость, которая в SoW-окружение попадает только через `requirements.txt:58`.

### 1.2. Импорт-цепочка (GAP-A)

```
text_to_speech.py:28  from rvc_python.infer import RVCInference
  → rvc_python/__init__.py:1  import rvc_python.infer
    → infer.py:5  (импорт modules)
      → modules/vc/modules.py:19  from .utils import *
        → modules/vc/utils.py:2  from fairseq import checkpoint_utils   ← ModuleNotFoundError, если fairseq нет
```

Старый план решал это через stub `sys.modules['fairseq']`. **Новый план** решает это через **форк rvc-python**, где строка `from fairseq import checkpoint_utils` **заменяется** на HF-загрузчик. fairseq исчезает из цепочки полностью.

### 1.3. Двойная цель (GAP-B)

`modules/vc/modules.py:19` делает `from .utils import *`, что реэкспортирует `load_hubert` в namespace `modules.vc.modules`. `vc_single()` (строка 168) вызывает `load_hubert(...)` как bare name → Python разрешает из globals `modules.vc.modules`.

**Старый план** решал это через dual-target monkey-patch (патчить обе ссылки). **Новый план** решает это **внутри форка**: `utils.py` переписывается полностью, `modules.py` продолжает делать `from .utils import *`, и получает обновлённую `load_hubert` автоматически. Никакого GAP-B — это штатная работа Python import system.

### 1.4. Контракт модели HuBERT

Из `rvc_python/modules/vc/pipeline.py:221-223`:
```python
logits = model.extract_features(**inputs)
feats = model.final_proj(logits[0]) if version == "v1" else logits[0]
```

Где `inputs = {"source": feats, "padding_mask": padding_mask, "output_layer": 9 if version == "v1" else 12}`.

Контракт:
1. `model.extract_features(source, padding_mask, output_layer=9|12)` → `(feats, padding_mask_out)`
2. `model.final_proj(feats)` — **только для RVC v1**
3. `model.eval()`, `model.to(device)`, `model.half()`/`.float()` — стандартные `nn.Module` методы

### 1.5. HF-модель: `facebook/hubert-base-ls960`

- 889,944 скачиваний на HuggingFace Hub.
- Архитектурно идентичен `hubert_base.pt`:
  - `num_hidden_layers: 12`, `hidden_size: 768`
  - `do_stable_layer_norm: false` → соответствует fairseq `layer_norm_first=False`
- Веса сконвертированы из того же fairseq-чекпойнта официальным скриптом.
- **НЕ включает `final_proj`** (pretraining-only head, в HF-модели отсутствует).

### 1.6. v1 vs v2

- `rvc_python/infer.py:65`: `load_model(model_name, version="v2")` — **по умолчанию v2**.
- `text_to_speech.py:198` вызывает `self.rvc.load_model(model_name)` без указания version → v2.
- Для v2 `final_proj` **НЕ нужен** (`pipeline.py:223`: `feats = logits[0]`).

**Вывод**: HF-модели без `final_proj` достаточно для всех сценариев SoW.

### 1.7. Зависимости

- `transformers==4.57.3` **уже в requirements.txt:235** — ничего добавлять.
- `fairseq==0.12.2` (requirements.txt:58) — **УДАЛИТЬ** (после переключения на форк).
- `rvc-python @ git+https://github.com/JarodMica/rvc-python@9a67ac7...` (requirements.txt:191) — **ЗАМЕНИТЬ** на URL форка.

---

## 2. Архитектура решения

### 2.1. Стратегия: форк rvc-python с заменой fairseq

Вместо monkey-patch'ить rvc-python поверх — **форкаем** его, и вносим изменения **внутрь форка**. SoW переключается на форк в `requirements.txt`.

**Что меняется в форке** (3 файла):

| Файл форка | Изменение | Объём |
|------------|-----------|-------|
| `modules/vc/utils.py` | Полная замена: удалить `from fairseq import checkpoint_utils`, переписать `load_hubert()` на `transformers.HubertModel` | ~40 строк вместо 30 |
| `lib/jit/get_hubert.py` | Замена: удалить fairseq-импорты, переписать на HF `HubertModel` + кастомный `extract_features` | ~80 строк вместо 200 |
| `download_model.py` | Пропуск скачивания `hubert_base.pt` (HF скачает сама через `from_pretrained`) | ~5 строк |

**Что НЕ меняется в форке**:
- `modules/vc/modules.py` — `from .utils import *` продолжает работать, получает обновлённую `load_hubert` автоматически (GAP-B решён штатным путём).
- `modules/vc/pipeline.py` — контракт `extract_features` + `final_proj` сохранён.
- `infer.py` — без изменений.
- `__init__.py` — без изменений.

### 2.2. Новый файл в SoW: `app/utils/rvc_hubert_hf.py`

Обёртка `HubertHFWrapper(torch.nn.Module)` над `transformers.HubertModel`, эмулирующая fairseq-контракт.

Этот файл нужен, потому что `load_hubert()` в форке будет импортировать его. Но вместо создания зависимости форка от SoW-кода, мы **встроим обёртку прямо в форк** — сделаем `utils.py` самодостаточным.

**Альтернатива A (рекомендуется)**: встроить HF-обёртку прямо в `modules/vc/utils.py` форка. Тогда форк не зависит от SoW, и любой проект может его использовать.

**Альтернатива B**: отдельный файл `hubert_hf.py` в форке. Чище, но лишний файл.

Выбираем **А** — минимизация изменений, один файл правим (`utils.py`), и он самодостаточен.

### 2.3. Переписанный `modules/vc/utils.py` (форк)

```python
import os
import logging

import torch

_utils_logger = logging.getLogger("rvc_python.modules.vc.utils")


def get_index_path_from_model(sid):
    return next(
        (
            f
            for f in [
                os.path.join(root, name)
                for root, _, files in os.walk(os.getenv("index_root"), topdown=False)
                for name in files
                if name.endswith(".index") and "trained" not in name
            ]
            if sid.split(".")[0] in f
        ),
        "",
    )


class HubertHFWrapper(torch.nn.Module):
    """HF HuBERT (facebook/hubert-base-ls960), эмулирующий fairseq-контракт.

    Воспроизводит интерфейс fairseq HuBERT:
      - extract_features(source, padding_mask, output_layer) → (feats, padding_mask)
      - final_proj(feats) — заглушка для v1-совместимости (выбрасывает RuntimeError)
      - .eval(), .to(device), .half()/.float() — стандартные nn.Module
    """

    DEFAULT_HF_MODEL_ID = "facebook/hubert-base-ls960"

    def __init__(self, hf_model_id=None, device="cpu", is_half=False):
        super().__init__()
        from transformers import HubertModel

        model_id = hf_model_id or self.DEFAULT_HF_MODEL_ID
        self.model = HubertModel.from_pretrained(model_id).to(device)
        if is_half:
            self.model = self.model.half()
        else:
            self.model = self.model.float()
        self.model.eval()
        self._hf_model_id = model_id

    def extract_features(self, source, padding_mask=None, output_layer=None,
                         mask=False, ret_conv=False):
        """Возвращает (feats, padding_mask) — как fairseq HuBERT.extract_features."""
        outputs = self.model(
            input_values=source,
            attention_mask=~padding_mask if padding_mask is not None else None,
            output_hidden_states=True,
        )
        if output_layer is not None:
            feats = outputs.hidden_states[output_layer]
        else:
            feats = outputs.last_hidden_state
        return feats, padding_mask

    def final_proj(self, feats):
        """Заглушка — HF HuBERT не включает final_proj (pretraining-only head).

        RVC v2 (дефолт в SoW) не вызывает этот метод.
        Если v1-модель попытается вызвать — понятный RuntimeError.
        """
        raise RuntimeError(
            "RVC v1 models require final_proj, which is not available in "
            f"the HF HuBERT model ({self._hf_model_id}). "
            "Use RVC v2 models, or extract final_proj weights from "
            "hubert_base.pt and place them alongside the model."
        )

    # Делегирование стандартных nn.Module методов (уже есть через наследование,
    # но .to() нужно перехватить, чтобы переводить и внутреннюю HF-модель)
    def to(self, *args, **kwargs):
        self.model = self.model.to(*args, **kwargs)
        return super().to(*args, **kwargs)


def load_hubert(config, lib_dir):
    """HF-based HuBERT loader — полная замена fairseq checkpoint_utils.

    Загружает facebook/hubert-base-ls960 через transformers.HubertModel.
    HF-кеш управляется через HF_HOME/HUGGINGFACE_HUB_CACHE env vars
    (настраиваются в text_to_speech.py до импорта rvc_python).
    """
    hf_model_id = os.environ.get("RVC_HUBERT_MODEL_ID", HubertHFWrapper.DEFAULT_HF_MODEL_ID)
    wrapper = HubertHFWrapper(
        hf_model_id=hf_model_id,
        device=config.device,
        is_half=config.is_half,
    )
    _utils_logger.info(
        "HuBERT loaded via HF (%s), device=%s, is_half=%s",
        hf_model_id, config.device, config.is_half,
    )
    return wrapper
```

**Ключевые отличия от старого плана**:
- fairseq нет ВООБЩ — ни импорта, ни stub'а, ни monkey-patch'а.
- `load_hubert` — нормальная функция, не патч.
- `HubertHFWrapper` — полноценный `nn.Module`, эмулирует контракт через `extract_features` + `final_proj` (заглушка).
- `final_proj` не загружает `final_proj.pt` — v2 дефолт, v1 выдаёт понятную ошибку.
- Переменная окружения `RVC_HUBERT_MODEL_ID` позволяет переключить HF-модель без правки кода.

### 2.4. Переписанный `lib/jit/get_hubert.py` (форк)

ONNX/JIT-экспорт HuBERT. Текущая версия использует fairseq для загрузки + кастомный `extract_features` с `index_put` из `fairseq.utils`.

Заменяем:
1. Загрузка модели — через `HubertHFWrapper` (из `utils.py`).
2. `index_put` — реализация 1 строкой: `torch.index_put_(x, [mask], value)` (в PyTorch ≥2.0 это нативная операция, `fairseq.utils.index_put` — просто обёртка).
3. Кастомный `extract_features` — адаптируем для HF `HubertModel`.

```python
import torch
import logging
from rvc_python.modules.vc.utils import HubertHFWrapper

_jit_logger = logging.getLogger("rvc_python.lib.jit.get_hubert")


def _index_put(x, mask, value):
    """Замена fairseq.utils.index_put — нативный torch.index_put_."""
    return torch.index_put_(x, [mask], value)


def get_hubert_model(model_path, device="cpu"):
    """Загружает HuBERT для JIT/ONNX-экспорта через HF."""
    wrapper = HubertHFWrapper(device=device, is_half=False)

    # Кастомный extract_features для JIT-trace (аналог fairseq-версии,
    # но адаптированный под HF HubertModel)
    def _extract_features(self, source, padding_mask, output_layer, mask=False):
        outputs = self.model(
            input_values=source,
            attention_mask=~padding_mask if padding_mask is not None else None,
            output_hidden_states=True,
        )
        if output_layer is not None:
            feats = outputs.hidden_states[output_layer]
        else:
            feats = outputs.last_hidden_state
        return feats, padding_mask

    def _hubert_extract_features(source, padding_mask, output_layer, mask=False):
        feats, mask_out = wrapper.extract_features(
            source, padding_mask, output_layer=output_layer, mask=mask
        )
        return feats

    def _infer(source, padding_mask, output_layer):
        """Simplified inference function для JIT."""
        if isinstance(output_layer, torch.Tensor):
            output_layer = output_layer.item()
        logits = wrapper.extract_features(
            source=source, padding_mask=padding_mask, output_layer=output_layer
        )
        # v2 default: feats = logits[0]
        feats = logits[0]
        return feats

    # Monkey-patch для JIT-совместимости (внутренний, не связан с fairseq)
    wrapper.infer = _infer
    wrapper.extract_features_jit = _hubert_extract_features

    _jit_logger.info("HuBERT JIT model loaded via HF, device=%s", device)
    return wrapper
```

### 2.5. Обновлённый `download_model.py` (форк)

Пропускаем скачивание `hubert_base.pt` — HF `from_pretrained` скачает модель сама.

```python
import os
import logging

_dl_logger = logging.getLogger("rvc_python.download_model")


def download_rvc_models(lib_dir=None):
    """Скачивает RVC-модели. HuBERT больше не скачивается —
    используется HF facebook/hubert-base-ls960 (автоскачивание через transformers).

    Скачивает только rmvpe.pt (F0 model).
    """
    if lib_dir is None:
        lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")

    base_dir = os.path.join(lib_dir, "base_model")
    os.makedirs(base_dir, exist_ok=True)

    # Скачиваем только F0-модель (rmvpe.pt), HuBERT — через HF
    f0_path = os.path.join(base_dir, "rmvpe.pt")
    if not os.path.exists(f0_path):
        # (оригинальная логика скачивания rmvpe.pt сохраняется)
        ...  # TODO: скопировать оригинальную логику из JarodMica/rvc-python
    else:
        _dl_logger.info("F0 model already exists at %s, skipping download", f0_path)

    _dl_logger.info("HuBERT: will be loaded from HuggingFace (facebook/hubert-base-ls960)")
```

### 2.6. Правки в SoW: `app/utils/text_to_speech.py`

**Удалить** строки 30-35 (safe_globals-костыль):
```python
# УДАЛИТЬ:
import torch.serialization
try:
    from fairseq.data.dictionary import Dictionary
    torch.serialization.add_safe_globals([Dictionary])
except ImportError:
    pass
```

**Больше никаких правок в text_to_speech.py не требуется.** Строка 28 (`from rvc_python.infer import RVCInference`) остаётся как есть — теперь она импортирует форк, в котором fairseq нет.

### 2.7. Правки в SoW: `requirements.txt`

1. **Удалить** строку 58: `fairseq==0.12.2`
2. **Заменить** строку 191: `rvc-python @ git+https://github.com/JarodMica/rvc-python@9a67ac7...` → URL форка (см. §3).

### 2.8. Правки в SoW: `app/utils/rvc_hubert_hf.py`

**НЕ создаётся.** Обёртка `HubertHFWrapper` встроена в форк (`modules/vc/utils.py`). SoW не нуждается в собственном файле обёртки — форк самодостаточен.

---

## 3. Этапы реализации

| iter | Этап | Объём | Риск |
|------|------|-------|------|
| **111** | (Этот документ) Переписать план — полный пересмотр подхода. | docs только | 0 |
| **112** | Форкнуть `JarodMica/rvc-python` → `vudirvp-sketch/rvc-python`. В форке: переписать `modules/vc/utils.py` (§2.3), `lib/jit/get_hubert.py` (§2.4), `download_model.py` (§2.5). Запушить форк. | ~120 строк в 3 файлах | низкий — форк независим, можно тестировать отдельно |
| **113** | SoW: удалить safe_globals-костыль из `text_to_speech.py:30-35`, заменить `rvc-python` на форк в `requirements.txt:191`, удалить `fairseq==0.12.2` из `requirements.txt:58`. | ~7 строк в 2 файлах | средний — требует переустановки env + верификации |
| **114** | A/B-тест: генерация речи через форк (HF HuBERT) vs оригинальный rvc-python (fairseq HuBERT). Сравнение спектрограмм/слепое прослушивание. | тестовый скрипт | низкий |
| **115** | Если A/B OK: обновить STATUS.md (закрыть KI#83), AGENT_NAVIGATION.md (§4 Pitfalls + §1 line counts), worklog.md. Удалить старый `scripts/iter108_smoke_test.py` / `scripts/iter109_smoke_test.py` (больше не актуальны — тестировали monkey-patch подход). | docs/cleanup | 0 |

Если A/B fails → откатить requirements.txt к оригинальному rvc-python + fairseq, документировать причину в STATUS.md как KI.

---

## 4. A/B-тест (iter-114) — критерии приёмки

1. **Спектрограмма**: для одного входного WAV и одного `.pth`-модели сравнить мел-спектрограммы выхода RVC через fairseq (оригинальный rvc-python) и через HF (форк). Допуск: RMS различия < 1% по всему файлу.
2. **Слепое прослушивание**: 3 образца, 2 слушателя. Если оба не могут различить — pass.
3. **Перформанс**: время инференса на CPU/GPU. HF-версия ожидается равной или быстрее.
4. **Память**: HF HuBERT base — ~370 МБ весов (`pytorch_model.bin`), столько же, сколько fairseq-версия. HF-кеш лежит в `app/models/hf_cache` (уже настроен в `text_to_speech.py:39-45` через `HF_HOME`/`HUGGINGFACE_HUB_CACHE`).

---

## 5. Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| HF HuBERT выдаёт фичи, отличающиеся от fairseq (layer_norm позиции, padding_mask обработка) | средняя | A/B-тест на спектрограмме. Если отличаются — инспектировать `transformers.models.hubert.modeling_hubert.HubertModel.forward` и сравнивать с `get_hubert.py:extract_features`. |
| Пользователь загрузит RVC v1 `.pth` модель | низкая (дефолт v2) | Явная `RuntimeError` в `final_proj()` с инструкцией. Дополнительно: detection в `load_model` — если `cpt.get("version") == "v1"`, warn пользователя. |
| `transformers.HubertModel` ломит совместимость с `torch==2.10.0+cu128` | низкая (4.57.3 поддерживает) | Если упадёт — downgrade `transformers` до 4.40-4.50. |
| Upstream rvc-python выпустит обновление с новыми фичами, и форк отстанет | низкая (pinned-коммит; rvc-python — зрелый, редко обновляется) | При необходимости: rebase форка на новый upstream-коммит, повторить правки в 3 файлах. |
| `lib/jit/get_hubert.py` ONNX-экспорт не используется в SoW, но может понадобиться | низкая | Правка включена превентивно. Если ONNX-экспорт сломается — легко откатить только этот файл. |
| `download_model.py` правка неполна — оригинальная логика скачивания rmvpe.pt не скопирована | средняя | На iter-112: скопировать оригинальную логику скачивания rmvpe.pt из upstream, только убрать hubert_base.pt. |

---

## 6. Что НЕ делаем в этом плане

- **Не** меняем архитектуру RVC-пайплайна (`modules/vc/pipeline.py` остаётся как есть).
- **Не** меняем UX персонажей (поле `rvc_enabled`, `rvc_file`, `rvc_f0up_key` — все сохраняются).
- **Не** меняем `assets/rvc_models/` структуру — все существующие `.pth`-модели продолжают работать.
- **Не** мигрируем на zero-shot VC (Seed-VC / OpenVoice) — это отдельное стратегическое решение.
- **Не** добавляем stub `sys.modules['fairseq']` — подход полностью заменён форком.
- **Не** добавляем monkey-patch поверх rvc-python — подход полностью заменён форком.
- **Не** создаём `app/utils/rvc_hubert_hf.py` в SoW — обёртка встроена в форк.

---

## 7. Альтернативы (отклонены)

### 7.1. Путь B: zero-shot VC (Seed-VC / OpenVoice)
- Объём: 1 файл ~300 строк + миграция UI + новая UX для reference-audio.
- Риск: высокий — все `.pth`-модели пользователей становятся бесполезны.
- Решение: отклонено. Если когда-нибудь понадобится — это отдельный проект.

### 7.2. Путь C: выключить RVC целиком
- Объём: ~10 строк.
- Риск: ломает UX — пользователи потеряют voice-cloning.
- Решение: отклонено.

### 7.3. Путь D (старый план): stub + monkey-patch без форка
- Объём: ~200 строк (stub + monkey-patch + отдельный файл `rvc_hubert_hf.py`).
- Риск: runtime-костыли, GAP-A/B, технический долг.
- Решение: **отклонено заказчиком** — «не хочу костылей и каких либо остатков fairseq».

---

## 8. Итог

- **Подход**: форк rvc-python → замена fairseq→HF HuBERT внутри форка → SoW переключается на форк → fairseq удаляется из requirements.txt полностью.
- **Сколько кода?** ~120 строк в 3 файлах форка + ~7 строк правок в SoW (удаление safe_globals + замена URL в requirements.txt + удаление fairseq).
- **Какой риск?** Низкий. Форк — чистая замена, без runtime-костылей. GAP-A/GAP-B не существуют в этом подходе (fairseq просто нет в импорт-цепочке).
- **Что разблокирует?** Python 3.12+, удаление `fairseq==0.12.2` (проблемная зависимость с conflict'ами на новых pip/setuptools), отсутствие технического долга от stub/monkey-patch.
- **Новый файл в SoW?** Нет. Обёртка встроена в форк.

---

## 9. Audit checklist (перед iter-112)

1. **Форк создан**: `vudirvp-sketch/rvc-python` существует на GitHub, базируется на `9a67ac7`.
2. **utils.py не содержит fairseq**: grep по форку → 0 совпадений `fairseq`.
3. **utils.py экспортирует load_hubert**: `from rvc_python.modules.vc.utils import load_hubert` работает.
4. **HubertHFWrapper — nn.Module**: `isinstance(wrapper, torch.nn.Module)` == True.
5. **Контракт extract_features**: `wrapper.extract_features(source, padding_mask, output_layer=12)` возвращает `(feats, padding_mask)` с правильными размерностями.
6. **modules.py не изменён**: `from .utils import *` продолжает работать, `vc_single()` вызывает обновлённую `load_hubert`.
7. **download_model.py не скачивает hubert_base.pt**: только rmvpe.pt.
8. **requirements.txt SoW**: нет `fairseq`, rvc-python URL указывает на форк.
9. **text_to_speech.py**: нет fairseq-импортов, нет safe_globals-костыля, нет stub'а, нет monkey-patch'а.
10. **Приложение стартует без fairseq в env**: `python main.py` не падает с `ModuleNotFoundError: fairseq`.

Если хотя бы один пункт fails → iter-112 не закрывать, фиксить в том же коммите.
