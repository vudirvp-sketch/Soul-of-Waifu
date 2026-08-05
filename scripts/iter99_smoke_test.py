#!/usr/bin/env python3
"""iter-99 smoke test — KI#80 (role-alternation placeholder leak).

Tests the ``_strip_role_alternation_placeholders`` helper in
``local_provider.py`` that removes synthetic ``[conversation continued]``
placeholder messages before the payload is sent to llama-server.

Background (user-supplied log evidence from sow_2026-08-01_20-54-33.log):
  - prompt_engine.py inserts placeholders at lines 1410, 1412, 1451, 1454
    to satisfy Anthropic API's strict role-alternation contract (KI#15).
  - These placeholders are inserted UNIVERSALLY for all providers.
  - Llama-3-8B echoes the placeholder text verbatim at the start of its
    response: ``[conversation continued]   "Good evening..."``.
  - llama-server's chat template does NOT require strict alternation, so
    the placeholders are unnecessary for the local provider.

Test groups:
  G1: Placeholder detection — verifies the helper removes messages with
      ``_block_type == "placeholder"`` AND messages with content matching
      ``[conversation continued]`` (defense-in-depth for code paths that
      don't set the _block_type field).
  G2: Consecutive same-role merging — after stripping placeholders,
      consecutive same-role messages (e.g. two ``user`` messages) are
      merged with ``\n\n`` separator (matches prompt_engine.py convention).
  G3: No-mutation contract — the input list is NOT mutated.
  G4: Edge cases — empty list, single message, no placeholders, all
      placeholders, system messages preserved.
  G5: Real-world scenario — replicates the exact message structure from
      the user's log (system + placeholder + assistant_history + user_message)
      and verifies the placeholder is removed.

Run: python scripts/iter99_smoke_test.py
"""

import sys
import os
import logging

# Suppress log noise during tests
logging.basicConfig(level=logging.CRITICAL)

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


# Import the helper under test.
# Mock openai + httpx first — they're not installed in the test environment,
# but local_provider.py imports them at module level. We only need the
# _strip_role_alternation_placeholders helper, which is a pure function
# with no external dependencies.
import types
import sys

# Stubs for modules imported by local_provider.py
for mod_name in ("openai", "httpx"):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)
# openai.AsyncOpenAI is referenced at class-definition time
sys.modules["openai"].AsyncOpenAI = type("AsyncOpenAI", (), {})
# httpx.Timeout is called at module-load time (line 11)
sys.modules["httpx"].Timeout = lambda **kw: None

from app.utils.ai_clients.providers.local_provider import (
    _strip_role_alternation_placeholders,
    _PLACEHOLDER_CONTENT,
)

# ── G1: Placeholder detection ──────────────────────────────────────

print("\n=== G1: Placeholder detection ===")

# G1.1: Remove placeholder by _block_type
msgs = [
    {"role": "system", "content": "preamble", "_block_type": "story_preamble"},
    {"role": "user", "content": _PLACEHOLDER_CONTENT, "_block_type": "placeholder"},
    {"role": "assistant", "content": "history", "_block_type": "assistant_history"},
    {"role": "user", "content": "hello", "_block_type": "user_message"},
]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G1.1: placeholder with _block_type=placeholder is removed",
    len(result) == 3 and all(m.get("_block_type") != "placeholder" for m in result),
    f"result={result}",
)

# G1.2: Remove placeholder by content match (no _block_type field)
msgs = [
    {"role": "system", "content": "preamble"},
    {"role": "user", "content": "[conversation continued]"},
    {"role": "assistant", "content": "history"},
    {"role": "user", "content": "hello"},
]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G1.2: placeholder detected by content match (no _block_type)",
    len(result) == 3 and not any(m["content"] == _PLACEHOLDER_CONTENT for m in result),
    f"result={result}",
)

# G1.3: Remove assistant-side placeholder (end of history)
# After removal, two consecutive user messages are merged.
msgs = [
    {"role": "system", "content": "preamble"},
    {"role": "user", "content": "question"},
    {"role": "assistant", "content": "[conversation continued]", "_block_type": "placeholder"},
    {"role": "user", "content": "hello"},
]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G1.3: assistant-side placeholder removed (two user msgs merged → 1)",
    len(result) == 2
    and result[0]["role"] == "system"
    and result[1]["role"] == "user"
    and result[1]["content"] == "question\n\nhello",
    f"result={result}",
)

# G1.4: Remove multiple placeholders
msgs = [
    {"role": "user", "content": "[conversation continued]", "_block_type": "placeholder"},
    {"role": "assistant", "content": "history"},
    {"role": "assistant", "content": "[conversation continued]", "_block_type": "placeholder"},
    {"role": "user", "content": "hello"},
]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G1.4: multiple placeholders removed (2 → 0)",
    len(result) == 2 and not any(m["content"] == _PLACEHOLDER_CONTENT for m in result),
    f"result={result}",
)

# ── G2: Consecutive same-role merging ──────────────────────────────

print("\n=== G2: Consecutive same-role merging ===")

# G2.1: Two user messages merged after placeholder removal
msgs = [
    {"role": "system", "content": "preamble"},
    {"role": "user", "content": "first user msg"},
    {"role": "assistant", "content": "[conversation continued]", "_block_type": "placeholder"},
    {"role": "user", "content": "hello"},
]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G2.1: two user messages merged with \\n\\n after placeholder removal",
    len(result) == 2
    and result[1]["role"] == "user"
    and result[1]["content"] == "first user msg\n\nhello",
    f"result={result}",
)

# G2.2: Two assistant messages merged
# After removing the leading user placeholder, two consecutive assistant
# messages are merged into one.
msgs = [
    {"role": "user", "content": "[conversation continued]", "_block_type": "placeholder"},
    {"role": "assistant", "content": "first assistant msg"},
    {"role": "assistant", "content": "second assistant msg"},
    {"role": "user", "content": "hello"},
]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G2.2: two assistant messages merged with \\n\\n (2 → 1)",
    len(result) == 2
    and result[0]["role"] == "assistant"
    and result[0]["content"] == "first assistant msg\n\nsecond assistant msg"
    and result[1]["role"] == "user",
    f"result={result}",
)

# G2.3: System messages are NOT merged (left untouched)
msgs = [
    {"role": "system", "content": "first system"},
    {"role": "system", "content": "second system"},
    {"role": "user", "content": "hello"},
]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G2.3: consecutive system messages NOT merged (handled by prompt_engine)",
    len(result) == 3 and result[0]["content"] == "first system" and result[1]["content"] == "second system",
    f"result={result}",
)

# ── G3: No-mutation contract ───────────────────────────────────────

print("\n=== G3: No-mutation contract ===")

# G3.1: Input list is not mutated
msgs = [
    {"role": "system", "content": "preamble"},
    {"role": "user", "content": "[conversation continued]", "_block_type": "placeholder"},
    {"role": "assistant", "content": "history"},
    {"role": "user", "content": "hello"},
]
original_len = len(msgs)
original_contents = [m["content"] for m in msgs]
_ = _strip_role_alternation_placeholders(msgs)
check(
    "G3.1: input list length unchanged after call",
    len(msgs) == original_len,
    f"input len={len(msgs)}, expected={original_len}",
)
check(
    "G3.2: input message contents unchanged after call",
    [m["content"] for m in msgs] == original_contents,
    f"input contents={[m['content'] for m in msgs]}",
)

# G3.3: Returned list is a new list (not the same object)
msgs = [{"role": "user", "content": "hello"}]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G3.3: returned list is a new object (not the input)",
    result is not msgs,
    "returned the same list object",
)

# ── G4: Edge cases ─────────────────────────────────────────────────

print("\n=== G4: Edge cases ===")

# G4.1: Empty list
result = _strip_role_alternation_placeholders([])
check("G4.1: empty list returns empty list", result == [], f"result={result}")

# G4.2: Single message (no placeholder)
msgs = [{"role": "user", "content": "hello"}]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G4.2: single non-placeholder message preserved",
    len(result) == 1 and result[0]["content"] == "hello",
    f"result={result}",
)

# G4.3: All placeholders → empty list
msgs = [
    {"role": "user", "content": "[conversation continued]", "_block_type": "placeholder"},
    {"role": "assistant", "content": "[conversation continued]", "_block_type": "placeholder"},
]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G4.3: all-placeholder list returns empty list",
    result == [],
    f"result={result}",
)

# G4.4: No placeholders → unchanged (but new list)
msgs = [
    {"role": "system", "content": "preamble"},
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": "hi there"},
]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G4.4: no-placeholder list preserved (same content, new list)",
    len(result) == 3 and result is not msgs,
    f"result={result}",
)

# G4.5: Content that contains but doesn't equal placeholder is preserved
msgs = [
    {"role": "user", "content": "Let's have [conversation continued] in the middle"},
]
result = _strip_role_alternation_placeholders(msgs)
check(
    "G4.5: content containing (not equal to) placeholder is preserved",
    len(result) == 1 and result[0]["content"] == msgs[0]["content"],
    f"result={result}",
)

# ── G5: Real-world scenario from user's log ────────────────────────

print("\n=== G5: Real-world scenario (user's log) ===")

# This is the EXACT message structure from sow_2026-08-01_20-54-33.log
# lines 59-64 (PROMPT STRUCTURE):
#   [1] system     story_preamble       2007 chars
#   [2] user       placeholder            24 chars  ← THE BUG SOURCE
#   [3] assistant  assistant_history     946 chars
#   [4] user       user_message            5 chars  ("hello")
msgs = [
    {"role": "system", "content": "This is a neverending story between User...", "_block_type": "story_preamble"},
    {"role": "user", "content": "[conversation continued]", "_block_type": "placeholder"},
    {"role": "assistant", "content": "*The maintenance room is quiet, save for...", "_block_type": "assistant_history"},
    {"role": "user", "content": "hello", "_block_type": "user_message"},
]
result = _strip_role_alternation_placeholders(msgs)

# Expected: 3 messages (system, assistant, user) — placeholder removed
check(
    "G5.1: real-world scenario — placeholder removed (4 → 3 messages)",
    len(result) == 3,
    f"len={len(result)}, result={result}",
)

# Verify the structure: system → assistant → user (no role alternation issue)
roles = [m["role"] for m in result]
check(
    "G5.2: structure is system → assistant → user (clean, no placeholder)",
    roles == ["system", "assistant", "user"],
    f"roles={roles}",
)

# Verify no placeholder content remains
check(
    "G5.3: no [conversation continued] content in result",
    not any(_PLACEHOLDER_CONTENT in m.get("content", "") for m in result),
    f"contents={[m['content'][:30] for m in result]}",
)

# Verify the user_message is preserved
check(
    "G5.4: user_message 'hello' preserved at the end",
    result[-1]["content"] == "hello" and result[-1].get("_block_type") == "user_message",
    f"last msg={result[-1]}",
)

# Verify the assistant_history is preserved
check(
    "G5.5: assistant_history preserved",
    result[1]["content"].startswith("*The maintenance room") and result[1].get("_block_type") == "assistant_history",
    f"assistant msg={result[1]}",
)

# ── Summary ────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print(f"iter-99 smoke test: {PASS} PASS, {FAIL} FAIL")
print(f"{'='*60}")

sys.exit(1 if FAIL > 0 else 0)
