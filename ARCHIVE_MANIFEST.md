# Soul of Waifu — agent-binding archive

Source: https://github.com/vudirvp-sketch/Soul-of-Waifu (cloned at 2026-08-05T17:54:13Z)
Purpose: backup of agent infrastructure / docs / patterns before creating a fresh fork of upstream (jofizcd/Soul-of-Waifu).

## Archived (this zip)

### Root docs & agent binding
- AGENTS.md
- AGENT_NAVIGATION.md
- STATUS.md
- SECURITY.md
- PATTERNS.md
- CONTRIBUTING.md
- worklog.md
- README.md
- README_RU.md
- .gitignore

### .github/
- FUNDING.yml

### docs/
- SIGNAL_MAP.md
- ARCHITECTURE.md
- template_detection_pipeline_corrected.md
- CHAT_TEMPLATE_AUTO_DETECTION_PLAN.md
- chat-template-strategy.md
- fairseq_removal_plan.md
- CHAT_TEMPLATE_STRATEGY_AUDIT.md

### scripts/ (iteration smoke tests only — update_llama_server.py stays in repo)
- iter108_smoke_test.py
- iter109_smoke_test.py
- iter31_smoke_test.py
- iter64_smoke_test.py
- iter65_smoke_test.py
- iter69_smoke_test.py
- iter70_smoke_test.py
- iter72_smoke_test.py
- iter73_smoke_test.py
- iter74_smoke_test.py
- iter75_smoke_test.py
- iter76_smoke_test.py
- iter77_smoke_test.py
- iter78_smoke_test.py
- iter79_smoke_test.py
- iter80_1_smoke_test.py
- iter80_smoke_test.py
- iter82_smoke_test.py
- iter83_smoke_test.py
- iter85_smoke_test.py
- iter88_smoke_test.py
- iter89_smoke_test.py
- iter90_smoke_test.py
- iter93_smoke_test.py
- iter99_smoke_test.py

## Kept in repo (NOT in this archive — these stay with the code)

- LICENSE (GPLv3 — legal)
- main.py
- requirements.txt
- installer.bat
- start.bat
- app/ (entire codebase — PyQt6 GUI, providers, utils, configuration templates)
- assets/ (with .gitkeep markers — empty runtime dirs)
- logs/.gitkeep
- scripts/update_llama_server.py (real working script, not iter-test)

## Restoring into a new fork

1. Create a fresh fork of https://github.com/jofizcd/Soul-of-Waifu
2. Clone your new fork locally.
3. Unzip this archive at the repo root — folder structure matches, files will land in their original locations.
4. Review .gitignore (already includes all .gitkeep + forbidden-pattern rules from the previous fork).
5. Review AGENTS.md / AGENT_NAVIGATION.md — they describe the *previous* fork's structure; adjust paths if upstream changed anything.
6. STATUS.md / worklog.md carry iteration history — keep them as reference, or reset for the new fork.
