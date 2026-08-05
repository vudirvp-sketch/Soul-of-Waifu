# Security Policy

> What counts as a security issue and how to report vulnerabilities in Soul of Waifu.

## Supported Versions

Only the latest version (v2.4.0 and later). Older versions are not patched.

## What Counts as a Security Issue

### Critical (private disclosure)

1. **API token leak via git.** If filled `app/configuration/api.json` (with real `*_API_TOKEN` values) is found in the repository — critical leak.
2. **Vulnerability in `web_server.py`** (FastAPI on `http://<pc-ip>:8000`): no authorization, remote code execution, character data leak.
3. **Vulnerability in `discord_manager.py`**: command injection, `DISCORD_BOT_TOKEN` leak.
4. **Read/write outside `.soul/`** in `soul_memory.py` or `character_cards.py` — path traversal.
5. **Arbitrary code execution** via character card import (PNG/JSON with embedded scripts).

### Not a security issue (open a regular GitHub Issue)

- App crashes on invalid input — regular bug.
- TTS/STT not working on a specific Windows config — bug.
- Version incompatibility in `requirements.txt` — bug.
- UI crash after long session — bug.

## What to Do if You Accidentally Committed a Token

**Do NOT create a public Issue!** The token is already compromised.

### Steps (execute immediately):

1. **Revoke the token** at the provider's site (OpenAI, Anthropic, OpenRouter, Discord, etc.). This is the MAIN action — even if git history is rewritten, the token may already be in GitHub cache/forks/mirrors.

2. **Rewrite git history** (if commit is already in public repo):
   ```bash
   # Install BFG Repo-Cleaner (faster than git filter-repo for single-file cleanup)
   # https://rtyley.github.io/bfg-repo-cleaner/
   
   # 1. Clone mirror
   git clone --mirror https://github.com/<you>/Soul-of-Waifu.git
   
   # 2. Replace token in history
   bfg --replace-text passwords.txt Soul-of-Waifu.git
   # (passwords.txt contains the token string)
   
   # 3. Force push
   cd Soul-of-Waifu.git
   git reflog expire --expire=now --all
   git gc --prune=now --aggressive
   git push --force
   
   # 4. All forks — ask owners to delete and re-create from clean upstream
   ```

3. **Locally** — restore empty values in `app/configuration/api.json`:
   ```bash
   # Verify all tokens are empty
   git diff app/configuration/api.json
   # Expected: all *_API_TOKEN = ""
   ```

4. **Report** (without disclosing the token itself) to Discord `woonderdad` (privately) or developer email — so other forks can be notified.

## Where Sensitive Data Lives Locally

| Path | Contents | In .gitignore? |
|------|----------|---------------|
| `app/configuration/api.json` | 9 AI tokens + ElevenLabs + Discord + CUSTOM_ENDPOINT_URL (12 keys) | No — stored in repo with **empty** values. Verify before commit. |
| `.soul/` | Soul Memory data — psychology, relationships, diaries, topics. **PRIVATE.** | Yes |
| `app/voices/` | User RVC voice models | Yes |
| `assets/local_llm/` | Downloaded GGUF models | Yes |
| `assets/rvc_models/` | RVC models | Yes |
| `logs/sow_*.log` | App logs (may contain dialog fragments) | Yes |
| `app/configuration/characters.json` | Character cards (may contain private prompts) | No — in repo with examples. User cards — DO NOT commit. |
| `app/configuration/settings.json` | UI settings, file paths | No — in repo with defaults. Local user settings — intentionally. |

## Pre-Commit Check

Before every `git commit`:

```bash
# 1. Verify api.json is empty
git diff app/configuration/api.json
# All *_API_TOKEN / *_BOT_TOKEN = "" ?

# 2. Verify no .soul/
git status | grep -E "\.soul|app/data/[^.]|app/voices/[^.]|logs/[^.]"
# Must be empty

# 3. Verify characters.json — no user cards
git diff app/configuration/characters.json
# Only default/example cards?
```

## Reporting a Vulnerability

If you found a security issue from the "Critical" list:

1. **Do NOT open a public GitHub Issue.**
2. Message Discord user `woonderdad` (privately) — https://discord.com/invite/6vFtQGVfxM
3. In the message include:
   - Brief description of the problem.
   - File(s) where the issue is.
   - Steps to reproduce (if applicable).
   - Possible impact (what an attacker could do).

**Response:** within 72 hours. If confirmed — fix in next iteration + credit in `STATUS.md` (if desired).

## Security Principles

- **100% local and private.** All AI requests go to local Llama.cpp or directly to chosen cloud provider with user's API key. No developer proxy servers.
- **Logs — local.** Not sent anywhere automatically.
- **Soul Memory — local files** in `.soul/`. Never leave user's machine.
- **Web server** (`http://<pc-ip>:8000`) — only in home Wi-Fi network. **No authentication** — do NOT run on public network.

## Known Risks

1. **Web server without auth.** `app/utils/web_server.py` listens on `0.0.0.0:8000` without password. Anyone on the same network can send messages as the character. **Mitigation:** run only at home, behind NAT/firewall. Do not open port 8000 on router.

2. **MCP servers in Soul Companion.** `app/utils/ai_clients/mcp_client.py` connects external MCP servers. Any connected MCP server can execute arbitrary tools. **Mitigation:** connect only trusted MCP servers.

3. **Character cards from untrusted sources.** PNG/JSON cards may contain prompts causing undesirable AI behavior. **Mitigation:** import only from trusted authors. Review `character.json` before importing.

---

**Contact:** Discord `woonderdad` · https://discord.com/invite/6vFtQGVfxM
