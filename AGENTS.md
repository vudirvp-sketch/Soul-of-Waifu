# Soul of Waifu — AGENTS.md

> Agent work standards for this repository. Read by Cursor, Aider, Claude, GPT and others.
> **Entry sequence:** `AGENT_NAVIGATION.md` → `STATUS.md` → this file.

---

## 1. Master Working Prompt (use for new chats)

```
Work with the Soul of Waifu repository — Python/PyQt6 Windows-only desktop app
(v2.4.0, ~46k lines in app/). Stack: PyQt6 6.9 · qasync 0.27.1 · FastAPI 0.115 ·
Miniconda. Subsystems: 10 AI providers, 6 TTS engines, Soul Memory (long-term memory),
Soul Stage (RPG), Soul Companion (desktop overlay), FastAPI web server, Discord bot.
Layers: gui → utils → configuration (utils does NOT import from gui).

WHAT TO READ (gradient — match task scope):
- Trivial (typo, single config value, doc fix): STATUS.md only.
- Normal (bugfix, small feature): AGENT_NAVIGATION.md → STATUS.md → worklog.md.
- Deep (refactor, new module, security): all above + SECURITY.md + AGENTS.md §2+ + docs/ARCHITECTURE.md.

ITERATION RULES:
- Work iteratively: do only enough to avoid errors. Under-deliver rather than break —
  the rest goes into the next iteration.
- One Task ID per iteration: `iter-<N>-<short-desc>` (e.g. `iter-2-fix-tts-crash`).
- Soft file limit: 3–5 files per iteration. If task genuinely needs more (e.g. adding
  a provider touches 6 files) — proceed, just note scope in worklog. Stop only on scope creep.
- Found a bug → first document in STATUS.md as KI#<N> → then fix.

CODE STANDARDS (in app/ modules):
- Layers: gui → utils → configuration. Utils does NOT import from gui.
- Imports: absolute (`from app.utils...`), PyQt6 only (NOT PyQt5 — conflict).
- Async in GUI thread: `@asyncSlot` from qasync. NEVER `asyncio.run()` in GUI thread.
- Logging: `logging.getLogger("<Module>")`. Avoid `print()` for diagnostics
  (legit in main.py for user-facing output and in CLI scripts).
- Configs: use `Configuration*` classes for `settings.json` / `api.json` / `characters.json`.
  Direct `open()` OK for other files (translations yaml, card imports, etc.).
- Huge GUI files — grep first, do NOT open whole:
    interface_signals.py (15869), custom_widgets.py (8896), sowInterface.py (6743),
    soul_stage_page.py (3357), sow_system_signals.py (4234), sowSystem.py (716).
- Do NOT reorganize methods or extract new files unless task explicitly requires.
- i18n: add keys to BOTH `ru.yaml` AND `en.yaml` (else raw keys show in UI).
- UI combo order: NEVER change without migrating indexes in `settings.json`.
- Adding AI provider → see AGENT_NAVIGATION.md §3 (3 steps + api.json field).

GIT SAFETY (heavy files — installer.bat downloads GBs locally, repo must stay small):

NEVER commit any of these paths (all in .gitignore, but verify before EVERY commit):
- .soul/                              — Soul Memory runtime (PRIVATE character data!)
- app/data/*                          — Miniconda env (~1.5GB; torch_cuda.dll alone 867MB)
- app/cache/*                         — runtime caches
- app/voices/*                        — RVC voice models (user content)
- app/ffmpeg/*                        — ffmpeg binaries (101M+93M+20M+15M+13M)
- app/font/*                          — fonts (downloaded by installer)
- logs/*                              — except .gitkeep
- app/utils/ai_clients/backend/       — llama.cpp backends: cpu/cuda/vulkan/hip/sycl/
                                         + _backup/ _temp/ _update_cache/
                                         (539M+452M+56M+15M DLLs — CRITICAL!)
- app/utils/all-MiniLM-L6-v2/         — embedding model (~87MB safetensors)
- app/utils/emotions/detector/        — emotion detection model (~256MB pytorch_model.bin)
- app/utils/soul_companion/plugins/*  — user plugins
- assets/local_llm/*                  — user LLM models
- assets/rvc_models/*                 — user RVC models
- assets/ambient/*                    — user ambient audio (26M wav, 13M mp3)
- assets/backgrounds/*                — user chat backgrounds
- assets/emotions/{images,live2d,vrm}/* — user avatar assets (18M vrm)
- filled api.json                     — see SECURITY.md (rotate tokens if leaked)
- Defense-in-depth extensions (catch escapes): *.dll *.pyd *.lib *.pdb *.wasm *.exe
  *.pt *.pth *.bin *.gguf *.safetensors *.onnx *.ckpt

15 .gitkeep files — NEVER delete. .gitignore pattern is `folder/* + !folder/.gitkeep`,
NOT just `folder/` (breaks installer.bat).

PRE-COMMIT CHECKS (run ALL before staging):
1. python -m compileall app/ main.py           # → 0 errors (skip if PyQt6/qasync not installed)
2. git status --short                           # → file list should match expected scope (3-5 files)
3. git diff app/configuration/api.json          # → all *_API_TOKEN fields must be ""
4. git diff app/configuration/settings.json     # → only intentional changes (not local user settings)

PRE-COMMIT STAGING RULES (CRITICAL):
- Use `git add <specific file paths>` — NEVER `git add -A` or `git add .`
  (installer.bat downloads GBs locally; one careless `git add -A` pollutes repo forever).
- After staging, sanity-check sizes:
    git diff --cached --stat | sort -k3 -nr | head -10
  → no staged file should be >1MB unless explicitly intended (preview image, etc.).
- If staged file matches *.dll/.pyd/.pt/.bin/.safetensors/.onnx — STOP, unstage
  (`git reset HEAD <file>`), figure out why .gitignore didn't catch it.

LOCAL .git POLLUTION CHECK (one-time, then monthly):
If your local `.git/objects/` has files >50MB (check:
`find .git/objects -type f -size +50M -exec ls -lh {} \;`), these are unreferenced
loose objects from past failed `git add -A` with heavy files. Clean with:
    git gc --prune=now --aggressive
GitHub repo history is clean (verified iter-2: largest blob is 25MB preview.gif) —
these objects exist ONLY locally and are not pushed, but they bloat disk and slow git.

STOP AND CONFIRM (continue only after user OK):
- Touch `requirements.txt` (risk of Coqui TTS / RVC / transformers conflict).
- Change `api.json` structure (user key migration).
- Change `settings.json` schema (combo-index migration).
- Found security KI → stop current task, follow SECURITY.md, then resume.

OUTPUT (after completion):
1. Update docs (keep light — no stale sections, no long history):
   - STATUS.md — new iteration in header, KI updated, FAQ current.
     Closed KI — remove after 1–2 iterations.
   - worklog.md — new block (template in §3.3). Trim old entries to last 5–10.
   - AGENT_NAVIGATION.md — only if structure changed or new pitfalls found.
2. Package ONLY changed files into archive preserving folder structure.
3. Git-commands for repo update go IN CHAT (do NOT create .sh files in repo).
4. Mark stopping point with 4 fields:
   - Done (files, edits).
   - Not done (with reason).
   - Next step (concrete — where to continue in new chat).
   - Active KI (numbers + brief description).
```

---

## 2. Code Standards (Python / PyQt6)

### 2.1. Imports

```python
# Standard library
import os
import json
import logging

# Third-party
from PyQt6.QtWidgets import QWidget
from qasync import asyncSlot

# Local (absolute, not relative)
from app.configuration import configuration
from app.utils.ai_clients import ai_factory
```

**Rules:**
- Absolute imports (`from app.utils...`), not relative (`from ..utils...`).
- `logging` — first import candidate after stdlib.
- PyQt6 imports — separate group, before local.

### 2.2. Logging

```python
import logging
logger = logging.getLogger("ModuleName")

logger.info("Starting TTS engine: %s", engine_name)
logger.warning("Fallback to default voice: %s", reason)
logger.error("Failed to load character: %s", path, exc_info=True)
```

**NOT:** `print()`, `logging.basicConfig()` in modules (only in `main.py`).

### 2.3. Async in PyQt6

```python
from qasync import asyncSlot

@asyncSlot()
async def on_button_click(self):
    # Long async operation
    result = await self.ai_provider.generate_stream(messages)
    self.update_ui(result)
```

**NOT:** `asyncio.run()` in GUI thread, `threading.Thread()` without QThread for UI updates.

### 2.4. Config Access

```python
from app.configuration import configuration

# Correct:
settings = configuration.ConfigurationSettings()
api_key = configuration.ConfigurationAPI().get_token("OPEN_AI_API_TOKEN")
model = settings.get_main_setting("openai_model") or "gpt-4o-mini"

# Wrong:
with open("app/configuration/settings.json") as f:
    data = json.load(f)  # no validation, no fallback
```

### 2.5. AI Providers

All inherit from `BaseAIProvider` (`app/utils/ai_clients/base_provider.py`):

```python
class MyProvider(BaseAIProvider):
    async def generate_stream(self, messages, **kwargs):
        async for chunk in self._stream_response(messages):
            yield chunk

    async def generate_summary(self, messages, **kwargs):
        ...

    async def generate(self, messages, tools=None, **kwargs):
        return {"content": "...", "tool_calls": [...]}
```

**Registration** — in `ai_factory.py::AIFactory.get_provider()`:
```python
elif conversation_method == "My Provider":
    api_key = config_api.get_token("MY_API_TOKEN")
    return MyProvider(api_key=api_key, model=model)
```

**UI** — add string to combo (search `conversation_method` in `interface_signals.py`).

### 2.6. Naming

- Classes: `CamelCase` (`SowConfirmDialog`, `OpenAIProvider`).
- Functions/methods: `snake_case` (`generate_stream`, `save_configuration_edit`).
- Constants: `UPPER_SNAKE` (`DEFAULT_TEMPERATURE`, `MAX_TOKENS`).
- Files: `snake_case.py` (`soul_memory.py`, `ai_factory.py`).
- Private: `_leading_underscore` (`_check_embedder_available`).

---

## 3. Iteration Structure (workflow)

Each iteration = one logical work block.

### 3.1. Before starting

```bash
git pull
# Read:
# 1. AGENT_NAVIGATION.md
# 2. STATUS.md (especially Known Issues + Next iteration)
# 3. worklog.md (latest Task ID)
```

### 3.2. During work

- One Task ID per iteration: `iter-<N>-<short-desc>` (e.g. `iter-1-add-cohere-provider`).
- Do not touch more than 3–5 files per iteration (unless refactor task).
- After edits — `python -m compileall app/ main.py` (minimum check).
- If changing UI — verify app at least starts (`start.bat`).

### 3.3. After completion

Update 3 files (in priority order):

1. **`STATUS.md`:**
   - Header: new iteration.
   - "Current state": what was done.
   - "Roadmap": mark DONE / NEXT.
   - "Known Issues": new KI + closed ones.

2. **`worklog.md`:** add new block:
   ```markdown
   ---
   Task ID: iter-<N>-<desc>
   Agent: <claude/cursor/manual>
   Task: <what was requested>

   Work Log:
   - <step 1>
   - <step 2>
   - ...

   Stage Summary:
   - <key results>
   - <changed files>
   - Stopping point: <what remains / NEXT>
   ```

3. **`AGENT_NAVIGATION.md`:** only if folder structure changed, modules added/removed, or new pitfalls appeared.

### 3.4. Documentation hygiene

- Remove long history from `worklog.md` (keep only last 5–10 iterations, rest in git log).
- `STATUS.md` — only active KI. Closed KI — remove after 1–2 iterations.
- `AGENT_NAVIGATION.md` — no stale sections, no "change history".

---

## 4. Working with Large GUI Files

`interface_signals.py` (15869 lines) — special case.

**Before editing:**
```bash
# Find all occurrences of method/widget name
grep -n "method_name" app/gui/interface_signals.py
grep -n "widget_name" app/gui/interface_signals.py app/gui/custom_widgets.py app/gui/sowInterface.py
```

**Edits are surgical:**
- Do not "reorganize" methods in the file.
- Do not "extract" to a new file unless the task requires it.
- Comments — short, on point.

**If task is refactoring:**
- Separate iteration, only for this.
- Smoke-test mandatory: start app, verify all tabs work.
- Record in `worklog.md` file size before/after.

---

## 5. Security

### 5.1. API Tokens

- `api.json` stored in git with **empty** values. Intentional.
- During local dev — user fills tokens. **DO NOT commit filled file.**
- In code — only via `ConfigurationAPI().get_token(name)`.
- In logs — never output token values.
- If accidentally committed — `git rm --cached app/configuration/api.json`, rewrite history (`git rebase -i` or BFG), **ROTATE tokens**.

### 5.2. User Data

- **`.soul/` — CRITICAL PRIVACY.** Soul Memory runtime: `MEMORY.md`, `USER.md`, diaries, psychological profiles, relationships. All from character's first-person perspective. In `.gitignore`. If accidentally committed — see `SECURITY.md`.
- `characters.json` — character cards. If cards contain private prompts/scenarios — DO NOT commit.
- `app/voices/` — RVC voice models. In `.gitignore`.
- `logs/` — may contain dialog fragments. In `.gitignore`.
- `assets/local_llm/`, `assets/rvc_models/` — user models. In `.gitignore`.
- `assets/emotions/{images,live2d,vrm}/`, `assets/ambient/`, `assets/backgrounds/` — user content. In `.gitignore`.

### 5.3. Heavy Binaries (never commit — installer.bat downloads GBs locally)

These paths are NOT in repo, but `installer.bat` + `backend_updater.py` populate them at runtime. `.gitignore` covers them, but verify before EVERY commit (one careless `git add -A` pollutes repo):

- `app/data/` — Miniconda env (~1.5GB; `torch_cuda.dll` alone is 867MB, plus 644MB cublasLt, 491MB cudnn, etc.).
- `app/utils/ai_clients/backend/` — llama.cpp backends downloaded by `backend_updater.py`. Subdirs `cpu/`, `cuda/`, `vulkan/`, `hip/`, `sycl/`, `_backup/`, `_update_cache/`, `_temp/`. Heavy files: `ggml-cuda.dll` 539M, `cublasLt64_12.dll` 452M, `ggml-vulkan.dll` 56M, `llama-server-impl.dll` 15M×3, plus `llama-server.exe` per backend.
- `app/utils/all-MiniLM-L6-v2/` — embedding model loaded by `prompt_engine.py` via `SentenceTransformer('app/utils/all-MiniLM-L6-v2')`. Heavy: `model.safetensors` ~87MB.
- `app/utils/emotions/detector/` — emotion detection model. Heavy: `pytorch_model.bin` ~256MB.
- `app/ffmpeg/`, `app/font/`, `app/cache/` — downloaded binaries and runtime caches.
- Defense-in-depth extensions (catch any escape): `*.dll`, `*.pyd`, `*.lib`, `*.pdb`, `*.wasm`, `*.exe`, `*.pt`, `*.pth`, `*.bin`, `*.gguf`, `*.safetensors`, `*.onnx`, `*.ckpt`.

**If you accidentally `git add -A`'d heavy files:**
1. `git reset HEAD <file>` (unstage) — do NOT commit yet.
2. If already committed but not pushed: `git reset --soft HEAD~1` and re-stage selectively.
3. If already pushed: see SECURITY.md (treat as data leak), force-push rewritten history.
4. Run `git gc --prune=now` to clean local loose objects (318M+262M+68M typical).

### 5.4. Dependencies

- `requirements.txt` — conda-pinned, calibrated for Coqui TTS + RVC + PyTorch 2.10+cu128.
- Updating one version may break Coqui (known conflict with `transformers`).
- Before updating — test in separate branch, run smoke-test.

---

## 6. Git Commit Message Convention

```
iter <N>: <short description>

<optional: details — what added/changed/removed>
<optional: KI#<N> closed/opened, breaking changes, migration notes>
```

**Examples:**
```
iter 1: add agent infrastructure (AGENT_NAVIGATION, STATUS, AGENTS, .gitignore)

Baseline v2.4.0. Code unchanged. Added 6 new files for AI-agent workflow.
```

```
iter 2: fix KI#1 — graceful error when api_key empty in OpenAIProvider

- AIFactory.get_provider() now returns None + logs warning instead of raising.
- UI shows "Configure API key in Options" instead of crash dialog.
- KI#1 closed.
```

---

## 7. When NOT to Touch Code

If the task is only documentation, configs, or architecture discussion:
- Do not touch Python files.
- Do not run `installer.bat` / `start.bat` (unless asked).
- Do not create branches without an explicit task.

If the task is "prepare repo for agents" (like this iteration):
- Only markdown + `.gitignore` + optionally `docs/`.
- Do not touch code.

---

## 8. Quality Checklist Before Commit

- [ ] `python -m compileall app/ main.py` — 0 errors (skip if PyQt6/qasync not in env).
- [ ] `git status --short` — file count matches expected scope (3–5 files for normal task).
- [ ] NO heavy paths staged: `.soul/`, `app/data/`, `app/cache/`, `app/voices/`, `app/ffmpeg/`, `app/font/`, `logs/` (except .gitkeep), `app/utils/ai_clients/backend/`, `app/utils/all-MiniLM-L6-v2/`, `app/utils/emotions/detector/`, `app/utils/soul_companion/plugins/` (except .gitkeep), `assets/local_llm/`, `assets/rvc_models/`, `assets/ambient/`, `assets/backgrounds/`, `assets/emotions/{images,live2d,vrm}/` (except .gitkeep).
- [ ] NO heavy extensions staged: `*.dll *.pyd *.lib *.pdb *.wasm *.exe *.pt *.pth *.bin *.gguf *.safetensors *.onnx *.ckpt` (sanity-check: `git diff --cached --stat | sort -k3 -nr | head -10` — no file >1MB unless intended).
- [ ] `git diff app/configuration/api.json` — all tokens empty (`""`).
- [ ] `git diff app/configuration/settings.json` — only intentional changes (not local user settings).
- [ ] Used `git add <specific files>` — NOT `git add -A` / `git add .`.
- [ ] `.gitignore` — not broken (verify `folder/* + !folder/.gitkeep` patterns are present for 15 folders with `.gitkeep`).
- [ ] STATUS.md — updated (iteration, KI, FAQ).
- [ ] worklog.md — Task ID added.
- [ ] AGENT_NAVIGATION.md — current (if structure changed or new pitfalls).
- [ ] README.md / README_RU.md — not stale (if features/installation changed).

---

**Related documents:**
- `AGENT_NAVIGATION.md` — repo map + 16 pitfalls.
- `STATUS.md` — current state, roadmap, KI, FAQ.
- `SECURITY.md` — what counts as security issue, token leak procedures.
- `worklog.md` — iteration journal.
- `docs/ARCHITECTURE.md` — detailed module architecture.
- `CONTRIBUTING.md` — contribution rules.
