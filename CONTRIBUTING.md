# Contributing to Soul of Waifu

> Quick guide. For details — `AGENT_NAVIGATION.md` (map) and `AGENTS.md` (standards).

## Before Starting

1. Read `AGENT_NAVIGATION.md` — repo map + 16 known pitfalls.
2. Read `STATUS.md` — current state, known issues, FAQ.
3. Read `SECURITY.md` — what to do on token / private data leak.
4. Read `AGENTS.md` — code standards and working prompt.

## Development Setup (Windows)

```bat
:: 1. Fork + clone
git clone https://github.com/<your-fork>/Soul-of-Waifu.git
cd Soul-of-Waifu

:: 2. Download release ZIP from Releases (for bundled Miniconda in app/data/)
::    OR run installer.bat (NOT as admin!)
::    This creates app/data/envs/sow/ virtual environment

:: 3. Activate environment
call app\data\Scripts\activate.bat sow

:: 4. Run
python main.py
```

**Linux/macOS:** not officially supported. Can `pip install PyQt6 qasync` for UI development, but TTS/STT/Companion won't start.

## Workflow

1. Create branch: `git checkout -b <type>-<short-desc>` (e.g. `feat-cohere-provider`, `fix-tts-crash`, `docs-architecture`).
2. Make targeted edits. No more than 3–5 files per PR (unless refactor).
3. Verify: `python -m compileall app/ main.py` — 0 errors.
4. Verify: `git status` — no `app/data/`, `app/cache/`, `app/voices/`, `logs/`.
5. Verify: `git diff app/configuration/api.json` — all tokens empty.
6. Start app, smoke-test (if changing UI/logic).
7. Update documentation:
   - `STATUS.md` — if new iteration / KI / FAQ.
   - `worklog.md` — add Task ID block.
   - `AGENT_NAVIGATION.md` — if structure changed.
8. Commit + push + PR.

## Commit Messages

```
<type>: <short description>

<optional: details>
<optional: KI#<N> closed/opened>
```

**Types:**
- `feat` — new feature (new AI provider, new TTS engine)
- `fix` — bugfix (KI#<N> if applicable)
- `docs` — documentation only
- `refactor` — refactoring without behavior change
- `chore` — dependencies, .gitignore, CI
- `i18n` — translations

## What NOT to Commit

- **`.soul/`** — Soul Memory runtime (character psychology, diaries — PRIVATE!)
- `app/data/` (Miniconda ~1.5GB, but keep `.gitkeep`)
- `app/cache/`, `app/voices/`, `app/ffmpeg/`, `app/font/` (content, but keep `.gitkeep`)
- `assets/local_llm/`, `assets/rvc_models/`, `assets/ambient/`, `assets/backgrounds/`, `assets/emotions/{images,live2d,vrm}/` (content, but keep `.gitkeep`)
- `logs/` (content, but keep `.gitkeep`)
- `api.json` with filled tokens (only empty values!)
- `characters.json` with user cards (only examples)
- `settings.local.json`, `*.local.json`, `.env*`

**Important:** `.gitkeep` files — NEVER delete. Pattern in `.gitignore`: `folder/* + !folder/.gitkeep`. See `SECURITY.md` if you committed tokens or `.soul/`.

## Code Rules (brief)

- Python 3.11+, type hints welcome in `app/utils/`.
- PyQt6 (NOT PyQt5).
- `qasync` for async in GUI thread (`@asyncSlot`).
- `logging.getLogger("<Module>")` instead of `print()`.
- Configs via `Configuration*` classes, not direct `open()`.
- Absolute imports (`from app.utils...`).
- Layers: `gui → utils → configuration`. Do not violate.

## Adding an AI Provider

1. Create `app/utils/ai_clients/providers/<name>_provider.py` (inheriting `BaseAIProvider`).
2. Add branch in `ai_factory.py::AIFactory.get_provider()`.
3. Add option in `interface_signals.py` conversation combo.
4. Add keys in `ru.yaml` + `en.yaml`.
5. Add field in `api.json` (empty value).
6. Smoke-test: select provider in UI → with empty token must show graceful error, not crash.

## Contact

- Discord: https://discord.com/invite/6vFtQGVfxM
- GitHub Issues: https://github.com/vudirvp-sketch/Soul-of-Waifu/issues
