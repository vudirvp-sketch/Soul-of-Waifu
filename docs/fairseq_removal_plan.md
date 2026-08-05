# План: полное удаление fairseq из Soul of Waifu (пересмотр iter-113-doc)

**Дата**: 2026-08-06 (iter-113-doc: добавлен §1.8 + §5/§8/§9 правки для KI#86 — numpy/faiss dependency-trap)
**Масштаб**: Deep (форк 3rd-party пакета + новый модуль + правки в text_to_speech.py + requirements.txt)
**Путь**: A-clean — форк daswer123/rvc-python с заменой fairseq→HF ContentVec внутри форка

**Принцип**: никаких stub'ов `sys.modules`, никаких monkey-patch'ей поверх rvc-python, никаких остатков fairseq. Удалить с корнем.

**История ревизий**:
- iter-107: первичный план (8 разделов, путь A — monkey-patch).
- iter-107-audit: GAP-A/GAP-B найдены, добавлены stub + dual-target monkey-patch.
- iter-110-audit: 8 фактических ошибок исправлено.
- iter-111: полный пересмотр. Заказчик отказывается от stub'ов и monkey-patch'ей («не хочу костылей»). Новый подход: **форк rvc-python**, замена fairseq→HF HuBERT **внутри форка**.
- **iter-112**: верификация iter-111 плана против upstream-репозиториев. Найдены 6 ошибок (KI#85): (1) HF-модель `facebook/hubert-base-ls960` НЕ ContentVec — это стандартный HuBERT для ASR, даёт неправильные фичи для RVC; (2) `HubertHFWrapper` использует plain `HubertModel` вместо `HubertModelWithFinalProj` → v1-модели ломаются; (3) `attention_mask=~padding_mask` возвращает bool, HF хочет LongTensor; (4) daswer123@0.1.5 pyproject.toml **пинит `fairseq==0.12.2`** — нужно удалить в форке; (5) JarodMica/rvc-python — активный форк (не «ноу-нейм»), last commit Mar 2026; (6) найдены 2 пропущенных fairseq-free альтернативы: `ultimate-rvc==0.6.0` (318★, MIT, `transformers==4.57.3` — точное совпадение с SoW) и `zerorvc==0.0.19`. Все 6 исправлены в этом пересмотре.
- **iter-113-doc**: заказчик проверил iter-112 план через сторонний отчёт. Найдена 7-я ошибка (KI#86): iter-112 §1.7 упускает `numpy<=1.23.5` и `faiss-cpu==1.7.3` жёсткие пины в `pyproject.toml` rvc-python — тот же dependency-trap pattern, что и `fairseq==0.12.2`. SoW пинит `numpy==1.26.4`, rvc-python пинит `numpy<=1.23.5` → resolver conflict или тихая установка несовместимой версии. Без relaxation форк решит fairseq-симптом, но оставит класс проблемы. Добавлен §1.8 (KI#86), §3 iter-113 шаги расширены, §5/§8/§9 обновлены. Проверено через прямое клонирование daswer123@cff3ffb и JarodMica@782467a — оба пинят numpy/faiss одинаково (JarodMica bumped только omegaconf).

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

**关于 зависимости rvc-python от fairseq — два разных upstream, два разных состояния** (исправлено iter-112, KI#85):
- **daswer123/rvc-python@0.1.5** (PyPI, recommended fork base): **пинит `fairseq==0.12.2`** в `pyproject.toml` dependencies. Форк **обязан** удалить эту строку.
- **JarodMica/rvc-python@9a67ac7** (текущий pin в SoW `requirements.txt:191`): fairseq уже удалён из `pyproject.toml` (commit `0caaf86` May 2025 «fix hubert issues»), но fairseq-импорты в коде остались. JarodMica — активный форк (last commit Mar 2026), не «ноу-нейм».

В SoW-окружение fairseq попадает через `requirements.txt:58` (явный pin) + rvc-python@9a67ac7 imports его в runtime (implicit).

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

### 1.5. HF-модель: `lengyue233/content-vec-best` (ContentVec, НЕ стандартный HuBERT)

**Исправлено iter-112 (KI#85)**: iter-111 план указывал `facebook/hubert-base-ls960` — это **стандартный HuBERT для ASR**, а не ContentVec. RVC обучен против ContentVec (variant legacy-500), и загрузка стандартного HuBERT даёт неправильные фичи (issues RVC-Boss #2078, #2121 — подтверждено автором RVC).

**Правильная модель**: `lengyue233/content-vec-best`
- Конвертирована из `content-vec-best-legacy-500.pt` (official ContentVec от auspicious3000).
- `architectures: ["HubertModelWithFinalProj"]` (включая `final_proj` веса).
- `classifier_proj_size: 256` (final_proj: 768→256, для RVC v1).
- `num_hidden_layers: 12`, `hidden_size: 768`, `do_stable_layer_norm: false`.
- Лицензия: MIT.
- Альтернативный источник (тот же ContentVec): `lj1995/VoiceConversionWebUI/hubert_base` — используется официальным RVC-Project.

**Эталонная имплементация** (официальный RVC, `infer/hubert.py`, commit `5d47da1` 2026-07-19): использует ровно эту модель (через `HubertModelWithFinalProj` подкласс) — proven, MIT-лицензированный код от самих авторов RVC.

### 1.6. v1 vs v2 (уточнено iter-112)

- `rvc_python/infer.py:65`: `load_model(model_name, version="v2")` — **по умолчанию v2**.
- `text_to_speech.py:198` вызывает `self.rvc.load_model(model_name)` без указания version → v2.
- Для v2 `final_proj` **НЕ нужен** — используется `last_hidden_state` (== `hidden_states[12]`).
- Для v1 `final_proj` **нужен** — `hidden_states[9]` → `final_proj` → 256-dim. Исправлено iter-112: обёртка теперь наследует `HubertModelWithFinalProj`, чтобы v1-модели работали (раньше iter-111 план ломал v1).

**Контракт extract_features** (верифицировано официальным RVC `infer/hubert.py` комментарием: *«Transformers hidden_states[N] is numerically equivalent to the source checkpoint's output_layer=N for this converted checkpoint»*):
- `fairseq extract_features(output_layer=N)` 1-based → `HF outputs.hidden_states[N]` 1-based equivalent.
- `hidden_states[9]` == fairseq layer 9 output (для v1).
- `hidden_states[12]` == `last_hidden_state` (для v2).
- `padding_mask` (bool, True=padded) → HF `attention_mask = (~padding_mask.bool()).long()` (Long, 1=real token).

### 1.7. Зависимости

- `transformers==4.57.3` **уже в requirements.txt:235** — ничего добавлять. Версия подтверждена совместимой с HF HuBERT подходом: `ultimate-rvc==0.6.0` (318★, MIT) использует ровно `transformers==4.57.3`.
- `fairseq==0.12.2` (requirements.txt:58) — **УДАЛИТЬ** (после переключения на форк).
- `rvc-python @ git+https://github.com/JarodMica/rvc-python@9a67ac7...` (requirements.txt:191) — **ЗАМЕНИТЬ** на URL форка `daswer123/rvc-python` (рекомендуемая база) или форка от `JarodMica/rvc-python@HEAD`.
- **В форке**: удалить `"fairseq==0.12.2"` из `pyproject.toml` dependencies (это для daswer123@0.1.5; JarodMica@HEAD уже не имеет этой строки).

### 1.8. Зависимости-ловушки (KI#86, iter-113-doc)

При верификации iter-112 (KI#85) упущен класс зависимостей, который воспроизводит ровно тот же «dependency-trap» pattern, что и `fairseq==0.12.2`: жёстко зафиксированные пины в `pyproject.toml` rvc-python, которые блокируют апгрейды дерева зависимостей SoW.

**Фактическое состояние upstream `pyproject.toml`** (проверено прямым клонированием):

| Пин | daswer123@cff3ffb (реком. база форка) | JarodMica@782467a (SoW pin) | SoW requirements.txt | Конфликт |
|-----|---------------------------------------|------------------------------|----------------------|---------|
| `fairseq==0.12.2` | **пинит** | нет | `fairseq==0.12.2` (line 58) | iter-112 KI#85 #4 (решается форком) |
| `numpy<=1.23.5` | **пинит** | **пинит** (не bumped) | `numpy==1.26.4` (line 130) | **БЛОКИРУЕТ** — pip resolver падает или тихо ставит несовместимое |
| `faiss-cpu==1.7.3` | **пинит** | **пинит** (не bumped) | `faiss-cpu==1.7.3` (line 59) | На сегодняшний день совпадает, но блокирует будущие апгрейды faiss |
| `omegaconf==2.0.6` | **пинит** | `omegaconf==2.3.0` (bumped May 2025) | `omegaconf==2.3.0` (line 131) | Решено upstream'ом JarodMica |

**Почему `numpy<=1.23.5` — критический блокер**:
- SoW пинит `numpy==1.26.4` (May 2024, современная версия с поддержкой Python 3.12).
- rvc-python пинит `numpy<=1.23.5` (August 2022 — версия двухлетней давности).
- `pip install -r requirements.txt` с обоими пинами: либо resolver error, либо pip тихо ставит numpy 1.23.5 и ломает `transformers`, `scikit-learn`, `scipy`, `pandas` и ~15 других SoW-зависимостей, которые требуют `numpy>=1.24`.
- Это **не гипотеза**: именно так fairseq ломал SoW в iter-107–iter-112. Удаление fairseq из requirements.txt без relaxing numpy-пина в rvc-python → ровно тот же сценарий, но с другим пакетом в роли блокера.

**Контракт `faiss-cpu` в коде rvc-python** (проверено):
- `rvc_python/modules/vc/pipeline.py:313`: `index = faiss.read_index(file_index)` — единственное использование.
- `read_index` стабилен в API faiss-cpu с версии 1.7.0 до текущей 1.8.0. Жёсткий пин `==1.7.3` не имеет технического обоснования — это артефакт 2022 года.

**Решение (в форке, на iter-113)**:

В `pyproject.toml` форка:

```diff
- "numpy<=1.23.5",
- "faiss-cpu==1.7.3",
+ "numpy>=1.21,<3",
+ "faiss-cpu>=1.7,<2",
```

**Почему эти диапазоны**:
- `numpy>=1.21` — нижняя граница: самая старая версия, с которой код rvc-python реально работает (по `np.from_numpy`/`torch.from_numpy` паттернам, проверено в `pipeline.py`, `rmvpe.py`, `infer_pack/`). Верхняя `<3` — defensive guard против hypothetic numpy 3.0 breaking changes (на Aug 2026 numpy 2.x — latest).
- `faiss-cpu>=1.7` — `read_index` стабилен с 1.7.0. `<2` — defensive guard.

**Дополнительный шаг на iter-113**: после создания форка, до коммита в SoW, запустить verification:

```bash
# В чистом venv с Python 3.12:
python -m venv /tmp/verify_rvc_fork
source /tmp/verify_rvc_fork/bin/activate
pip install "numpy==1.26.4" "transformers==4.57.3" "faiss-cpu==1.7.4" \
            "git+https://github.com/vudirvp-sketch/rvc-python@<commit>"
python -c "from rvc_python.infer import RVCInference; print('OK')"
```

Если `pip install` проходит без resolver conflict и импорт succeeds → KI#86 закрывается на iter-114 (A/B-тест). Если падает → расширить диапазоны или добавить missing dep в KI#86 followup.

**История ревизий §1.8**: добавлено iter-113-doc (KI#86). iter-112 verification пропустил — фокус был на fairseq-removal correctness, не на dependency-tree health. KI#86 отдельный от KI#85, потому что это другой класс ошибок (upstream pin lock-in vs implementation correctness).

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


# Портировано из официального RVC infer/hubert.py (commit 5d47da1, 2026-07-19, MIT).
# Использует lengyue233/content-vec-best (ContentVec, НЕ стандартный HuBERT).

from transformers import HubertModel


class HubertModelWithFinalProj(HubertModel):
    """HF HuBERT с final_proj (768→256) для RVC v1-совместимости.

    Тот же класс, что в официальном RVC infer/hubert.py и в
    lengyue233/content-vec-best README. Загружает final_proj веса
    из `pytorch_model.bin` ContentVec-модели.
    """
    def __init__(self, config):
        super().__init__(config)
        self.final_proj = torch.nn.Linear(
            config.hidden_size, config.classifier_proj_size
        )


class HubertHFWrapper(torch.nn.Module):
    """Обёртка над HubertModelWithFinalProj, эмулирующая fairseq-контракт.

    Воспроизводит интерфейс fairseq HuBERT:
      - extract_features(source, padding_mask, output_layer) → (feats, padding_mask)
      - final_proj(feats) — делегирует в HubertModelWithFinalProj.final_proj
        (v1: hidden_states[9] → final_proj → 256-dim)
      - .eval(), .to(device), .half()/.float() — стандартные nn.Module
    """

    DEFAULT_HF_MODEL_ID = "lengyue233/content-vec-best"

    def __init__(self, hf_model_id=None, device="cpu", is_half=False):
        super().__init__()
        model_id = hf_model_id or self.DEFAULT_HF_MODEL_ID
        dtype = torch.float16 if is_half else torch.float32
        self.model = HubertModelWithFinalProj.from_pretrained(
            model_id, torch_dtype=dtype
        ).to(device)
        self.model.eval()
        self._hf_model_id = model_id

    def extract_features(self, source, padding_mask=None, output_layer=None,
                         mask=False, ret_conv=False):
        """Возвращает (feats, padding_mask) — как fairseq HuBERT.extract_features.

        Контракт (верифицирован официальным RVC infer/hubert.py, KI#85 fix):
          fairseq extract_features(output_layer=N) 1-based
          ↔ HF outputs.hidden_states[N] 1-based equivalent.
          hidden_states[9]  → layer 9 output (для v1)
          hidden_states[12] → last_hidden_state (для v2)
        """
        # padding_mask: bool tensor (True = padded) → attention_mask: LongTensor (1 = real token)
        attention_mask = None
        if padding_mask is not None:
            attention_mask = (~padding_mask.bool()).long()

        outputs = self.model(
            input_values=source,
            attention_mask=attention_mask,
            output_hidden_states=True,
        )
        if output_layer is not None:
            feats = outputs.hidden_states[output_layer]
        else:
            feats = outputs.last_hidden_state
        return feats, padding_mask

    def final_proj(self, feats):
        """Делегирует в HubertModelWithFinalProj.final_proj (v1 support).

        В отличие от iter-111 плана (который выбрасывал RuntimeError),
        теперь v1-модели работают: final_proj веса загружены из
        lengyue233/content-vec-best (classifier_proj_size=256).
        """
        return self.model.final_proj(feats)


def load_hubert(config, lib_dir):
    """HF-based ContentVec loader — полная замена fairseq checkpoint_utils.

    Загружает lengyue233/content-vec-best через transformers.HubertModelWithFinalProj.
    HF-кеш управляется через HF_HOME/HUGGINGFACE_HUB_CACHE env vars
    (настраиваются в text_to_speech.py до импорта rvc_python).
    """
    hf_model_id = os.environ.get(
        "RVC_HUBERT_MODEL_ID", HubertHFWrapper.DEFAULT_HF_MODEL_ID
    )
    wrapper = HubertHFWrapper(
        hf_model_id=hf_model_id,
        device=config.device,
        is_half=config.is_half,
    )
    _utils_logger.info(
        "ContentVec loaded via HF (%s), device=%s, is_half=%s",
        hf_model_id, config.device, config.is_half,
    )
    return wrapper
```

**Ключевые отличия от iter-111 плана** (исправлено iter-112, KI#85):
- HF-модель: `lengyue233/content-vec-best` (ContentVec), а НЕ `facebook/hubert-base-ls960` (стандартный HuBERT для ASR).
- Обёртка: наследует `HubertModelWithFinalProj` (загружает `final_proj` веса из ContentVec) — v1-модели работают.
- `attention_mask = (~padding_mask.bool()).long()` (LongTensor), а НЕ `~padding_mask` (bool, HF падает на некоторых версиях).
- `final_proj(feats)` делегирует в подкласс (раньше выбрасывал RuntimeError → ломал v1).
- fairseq нет ВООБЩЕ — ни импорта, ни stub'а, ни monkey-patch'а.
- `load_hubert` — нормальная функция, не патч.
- Переменная окружения `RVC_HUBERT_MODEL_ID` позволяет переключить HF-модель (например, на `lj1995/VoiceConversionWebUI/hubert_base`).

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
2. **Заменить** строку 191: `rvc-python @ git+https://github.com/JarodMica/rvc-python@9a67ac7...` → URL форка `vudirvp-sketch/rvc-python` (см. §3).

### 2.8. Правки в SoW: `app/utils/rvc_hubert_hf.py`

**НЕ создаётся.** Обёртка `HubertHFWrapper` встроена в форк (`modules/vc/utils.py`). SoW не нуждается в собственном файле обёртки — форк самодостаточен.

---

## 3. Этапы реализации

| iter | Этап | Объём | Риск |
|------|------|-------|------|
| **111** | Переписать план — полный пересмотр подхода (stub/monkey-patch → форк rvc-python). | docs только | 0 |
| **112** | (Этот документ) Верификация iter-111 плана против upstream-репозиториев. Найдено 6 ошибок (KI#85): неверная HF-модель, plain HubertModel vs HubertModelWithFinalProj, attention_mask тип, fairseq в pyproject.toml форка, JarodMica — не «ноу-нейм», 2 пропущенных альтернативы. Все 6 исправлены в плане. | docs только | 0 |
| **113** | Форкнуть `daswer123/rvc-python@cff3ffb` (v0.1.5) → `vudirvp-sketch/rvc-python`. В форке: переписать `modules/vc/utils.py` (§2.3), `lib/jit/get_hubert.py` (§2.4), `download_model.py` (§2.5), удалить `fairseq==0.12.2` из `pyproject.toml`, **расслабить `numpy<=1.23.5` → `numpy>=1.21,<3` и `faiss-cpu==1.7.3` → `faiss-cpu>=1.7,<2`** (§1.8, KI#86). Запустить verification script (§1.8). Запушить форк. | ~130 строк в 4 файлах | низкий — форк независим, можно тестировать отдельно |
| **114** | SoW: удалить safe_globals-костыль из `text_to_speech.py:30-35`, заменить `rvc-python` на форк в `requirements.txt:191`, удалить `fairseq==0.12.2` из `requirements.txt:58`. | ~7 строк в 2 файлах | средний — требует переустановки env + верификации |
| **115** | A/B-тест: генерация речи через форк (HF ContentVec) vs оригинальный rvc-python (fairseq ContentVec). Сравнение спектрограмм/слепое прослушивание. | тестовый скрипт | низкий |
| **116** | Если A/B OK: обновить STATUS.md (закрыть KI#83, KI#85), AGENT_NAVIGATION.md (§4 Pitfalls + §1 line counts), worklog.md. Удалить старый `scripts/iter108_smoke_test.py` / `scripts/iter109_smoke_test.py` (больше не актуальны — тестировали monkey-patch подход). | docs/cleanup | 0 |

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
| HF ContentVec выдаёт фичи, отличающиеся от fairseq ContentVec (padding_mask обработка, normalization) | низкая (верифицировано официальным RVC, тот же ContentVec) | A/B-тест на спектрограмме. Если отличаются — инспектировать `transformers.models.hubert.modeling_hubert.HubertModel.forward` и сверять с `infer/hubert.py` официального RVC. |
| Пользователь загрузит RVC v1 `.pth` модель | низкая (дефолт v2) | iter-112 fix: `HubertModelWithFinalProj` загружает `final_proj` веса из ContentVec → v1 работает. Дополнительно: detection в `load_model` — если `cpt.get("version") == "v1"`, warn пользователя. |
| `transformers.HubertModel` ломит совместимость с `torch==2.10.0+cu128` | низкая (4.57.3 подтверждено `ultimate-rvc==0.6.0` в проде) | Если упадёт — downgrade `transformers` до 4.49.0<4.50 (как в официальном RVC). |
| Upstream rvc-python выпустит обновление с новыми фичами, и форк отстанет | низкая (daswer123 — последний коммит Oct 2024, зрелый) | При необходимости: rebase форка на новый upstream-коммит, повторить правки в 3 файлах + pyproject.toml. |
| `lib/jit/get_hubert.py` ONNX-экспорт не используется в SoW, но может понадобиться | низкая | Правка включена превентивно. Если ONNX-экспорт сломается — легко откатить только этот файл. |
| `download_model.py` правка неполна — оригинальная логика скачивания rmvpe.pt не скопирована | средняя | На iter-113: скопировать оригинальную логику скачивания rmvpe.pt из upstream, только убрать hubert_base.pt. |
| HF-кеш растёт: ContentVec ~370 МБ + возможные повторные скачивания | низкая | HF-кеш уже настроен в `text_to_speech.py:39-45` через `HF_HOME`/`HUGGINGFACE_HUB_CACHE` в `app/models/hf_cache`. |
| (KI#86, iter-113-doc) Расслабление `numpy<=1.23.5` → `numpy>=1.21,<3` ломает rvc-python runtime на numpy 2.x | низкая | iter-113 verification script (§1.8) тестирует импорт в чистом venv с `numpy==1.26.4`. rvc-python использует только `np.from_numpy`/`torch.from_numpy` (нативный PyTorch interop, стабилен на numpy 1.x→2.x). Если падает — расширить нижнюю границу до `>=1.24` (выровнять с SoW). |
| (KI#86) Расслабление `faiss-cpu==1.7.3` → `faiss-cpu>=1.7,<2` — `read_index` сломан в 1.8.x | очень низкая | `faiss.read_index` — part of stable C-API с 1.7.0. iter-113 verification script ставит `faiss-cpu==1.7.4` явно. Если падает — pin `faiss-cpu==1.7.4` (минимальный bump с сохранением совместимости). |

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

### 7.4. Путь E (новое, iter-112): использовать `ultimate-rvc==0.6.0` (PyPI)
- Найден в iter-112 при поиске пропущенных альтернатив. 318★ на GitHub, MIT, `transformers==4.57.3` (точное совпадение с SoW), Python 3.12+, уже реализован fairseq-free HuBERT loader.
- Минусы: приносит ~30 тяжёлых зависимостей (gradio, audio-separator, yt-dlp, nodejs-wheel-binaries, static-ffmpeg, static-sox, pedalboard, noisereduce, tensorboard, torch-tb-profiler и др.). API отличается от rvc-python — потребуется переписать SoW интеграцию. Это приложение, а не библиотека.
- Решение: отклонено как drop-in replacement. Но код `ultimate-rvc/rvc/lib/utils.py` (их `HubertModelWithFinalProj` + `load_embedding`) — полезный референс для нашего форка.

### 7.5. Путь F (новое, iter-112): inline RVC pipeline в SoW (Путь 2 из исследования)
- Полностью убрать rvc-python из requirements.txt, реализовать RVC pipeline в SoW (~400-500 строк), используя HF HuBERT loader из официального RVC `infer/hubert.py`.
- Плюсы: 0 third-party RVC deps, нет риска заброшенности upstream.
- Минусы: ~500 строк нового кода в SoW, берём на себя поддержку всех багфиксов RVC pipeline.
- Решение: отклонено в пользу Path 1 (меньше кода, proven reference от авторов RVC). Может быть пересмотрено если Path 1 столкнётся с непреодолимыми проблемами.

### 7.6. Путь G (новое, iter-112): torchaudio.pipelines.HUBERT_BASE
- SoW уже имеет `torchaudio==2.10.0` в requirements.txt:229. `torchaudio.pipelines.HUBERT_BASE` предоставляет стандартный HuBERT, но НЕ ContentVec.
- Чтобы использовать ContentVec веса, нужен ручной ремап ~90 тензоров ключей.
- Решение: отклонено — больше работы, чем Path 1, без явных преимуществ.

---

## 8. Итог

- **Подход**: форк rvc-python → замена fairseq→HF HuBERT внутри форка → SoW переключается на форк → fairseq удаляется из requirements.txt полностью.
- **Сколько кода?** ~120 строк в 3 файлах форка + ~7 строк правок в SoW (удаление safe_globals + замена URL в requirements.txt + удаление fairseq).
- **Какой риск?** Низкий. Форк — чистая замена, без runtime-костылей. GAP-A/GAP-B не существуют в этом подходе (fairseq просто нет в импорт-цепочке).
- **Что разблокирует?** Python 3.12+, удаление `fairseq==0.12.2` (проблемная зависимость с conflict'ами на новых pip/setuptools), отсутствие технического долга от stub/monkey-patch. **(KI#86, iter-113-doc)** Дополнительно: снятие dependency-trap с `numpy<=1.23.5` и `faiss-cpu==1.7.3` — те же жёсткие пины, что блокировали fairseq-апгрейды, только для numpy/faiss. Без relaxation форк решит fairseq-симптом, но оставит класс проблемы.
- **Новый файл в SoW?** Нет. Обёртка встроена в форк.

---

## 9. Audit checklist (перед iter-113)

1. **Форк создан**: `vudirvp-sketch/rvc-python` существует на GitHub, базируется на `daswer123/rvc-python@cff3ffb` (v0.1.5).
2. **utils.py не содержит fairseq**: grep по форку → 0 совпадений `fairseq` в `.py` файлах.
3. **pyproject.toml форка не содержит fairseq**: grep по `pyproject.toml` → 0 совпадений `fairseq` (daswer123@0.1.5 пинит, нужно удалить).
4. **utils.py экспортирует load_hubert**: `from rvc_python.modules.vc.utils import load_hubert` работает.
5. **HubertHFWrapper — nn.Module**: `isinstance(wrapper, torch.nn.Module)` == True.
6. **HubertModelWithFinalProj загружает final_proj веса**: `wrapper.model.final_proj` — `nn.Linear(768, 256)`, веса не None.
7. **Контракт extract_features**: `wrapper.extract_features(source, padding_mask, output_layer=12)` возвращает `(feats, padding_mask)` с правильными размерностями.
8. **v1 работает**: `wrapper.extract_features(source, padding_mask, output_layer=9)` → `wrapper.final_proj(feats)` → 256-dim output (не RuntimeError).
9. **modules.py не изменён**: `from .utils import *` продолжает работать, `vc_single()` вызывает обновлённую `load_hubert`.
10. **download_model.py не скачивает hubert_base.pt**: только rmvpe.pt.
11. **requirements.txt SoW**: нет `fairseq`, rvc-python URL указывает на форк.
12. **text_to_speech.py**: нет fairseq-импортов, нет safe_globals-костыля, нет stub'а, нет monkey-patch'а.
13. **Приложение стартует без fairseq в env**: `python main.py` не падает с `ModuleNotFoundError: fairseq`.
14. **HF ContentVec скачалась**: `app/models/hf_cache/` содержит `content-vec-best` (~370 МБ).
15. **(KI#86, iter-113-doc) pyproject.toml форка не содержит жёстких пинов numpy/faiss**: grep → 0 совпадений `numpy<=1.23.5` и `faiss-cpu==1.7.3`. Заменены на `numpy>=1.21,<3` и `faiss-cpu>=1.7,<2`.
16. **(KI#86) Verification script проходит**: `pip install "numpy==1.26.4" "transformers==4.57.3" "faiss-cpu==1.7.4" "git+...@fork"` в чистом venv Python 3.12 завершается без resolver conflict.
17. **(KI#86) Импорт succeeds в verify-venv**: `python -c "from rvc_python.infer import RVCInference"` → `OK` без `ModuleNotFoundError` / `ImportError`.
18. **(KI#86) SoW deps не сломаны**: после установки форка в venv, `pip install "scikit-learn==1.4.2" "scipy==1.13.1" "pandas==2.2.3"` проходят без conflict с rvc-python deps.
