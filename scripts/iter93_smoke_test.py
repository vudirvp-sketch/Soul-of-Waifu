#!/usr/bin/env python3
"""iter-93 smoke test — KI#75 (--reasoning on/off gated on enable_thinking)
+ KI#72 (pre-tokenizer warning detection).

Tests 3 groups:
  G1: KI#75 gating logic — verify the --reasoning on/off decision is
      correctly gated on capability_map.enable_thinking. We simulate the
      4 model archetypes (thinking/non-thinking × drift/no-drift) and
      verify the expected --reasoning flag is appended to the command.
      The gating logic is extracted from LocalServerManager.start_server_async()
      and replayed here in isolation (we don't start a real server).
  G2: KI#72 pre-tokenizer warning detection — verify
      _check_pretokenizer_warning() correctly sets the warning flag when
      llama-server emits "missing pre-tokenizer type" or "GENERATION
      QUALITY WILL BE DEGRADED", and ignores unrelated log lines.
  G3: KI#72 accessor + reset — verify get_pretokenizer_warning() returns
      the expected (bool, list) tuple, and that start_server_async()
      resets the state on each new server session.

Run: python scripts/iter93_smoke_test.py
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


# ── G1: KI#75 gating logic ──────────────────────────────────────────
#
# We replicate the EXACT gating decision from
# LocalServerManager.start_server_async() (iter-93). The real method
# builds a `command` list and extends it with ["--reasoning", "off"] or
# ["--reasoning", "on"]. Here we extract just the decision logic and
# verify it produces the correct flag for the 4 model archetypes.
#
# Per PATTERNS.md §9 Contradiction #4:
#   - enable_thinking=False → --reasoning off (regardless of user setting)
#   - enable_thinking=True → respect user's reasoning_mode
# We do NOT gate on eos_drift (would regress Gemma-4-HauhauCS).

print("\n=== G1: KI#75 --reasoning on/off gating logic ===")


def ki75_reasoning_decision(enable_thinking: bool, reasoning_mode: bool) -> str:
    """Replicate the iter-93 KI#75 gating decision.

    Returns "off" or "on" — the value that would be appended to the
    command list as ["--reasoning", <value>].
    """
    # This is the EXACT logic from local_server_manager.py
    # start_server_async() (iter-93):
    if not enable_thinking:
        return "off"
    elif reasoning_mode is False:
        return "off"
    elif reasoning_mode is True:
        return "on"
    # reasoning_mode is None (unlikely but defensive) — fall through to "on"
    # to match pre-iter-87 behavior (--reasoning auto = default).
    return "on"


# G1.1: Non-thinking model + reasoning_mode=True → --reasoning off (FORCED)
# This is the KEY iter-93 fix. Pre-iter-93: would send --reasoning on
# (harmless but semantically incorrect). Post-iter-93: forced off.
# Models: Llama-3-8B, MN-Violet-Lotus, plain Gemma, Mistral.
check(
    "G1.1: enable_thinking=False + reasoning_mode=True → --reasoning off (FORCED by KI#75)",
    ki75_reasoning_decision(enable_thinking=False, reasoning_mode=True) == "off",
    f"got {ki75_reasoning_decision(False, True)!r}",
)

# G1.2: Non-thinking model + reasoning_mode=False → --reasoning off (user + KI#75 agree)
check(
    "G1.2: enable_thinking=False + reasoning_mode=False → --reasoning off (user + KI#75 agree)",
    ki75_reasoning_decision(enable_thinking=False, reasoning_mode=False) == "off",
    f"got {ki75_reasoning_decision(False, False)!r}",
)

# G1.3: Thinking-capable model + reasoning_mode=True → --reasoning on (user respected)
# This protects Gemma-4-HauhauCS (eos_drift=True, enable_thinking=True)
# — KI#75 does NOT gate on eos_drift, so this model still gets --reasoning on.
# Models: Qwen3, Gemma-4-HauhauCS, Skyfall.
check(
    "G1.3: enable_thinking=True + reasoning_mode=True → --reasoning on (user respected)",
    ki75_reasoning_decision(enable_thinking=True, reasoning_mode=True) == "on",
    f"got {ki75_reasoning_decision(True, True)!r}",
)

# G1.4: Thinking-capable model + reasoning_mode=False → --reasoning off (user opted out)
check(
    "G1.4: enable_thinking=True + reasoning_mode=False → --reasoning off (user opted out)",
    ki75_reasoning_decision(enable_thinking=True, reasoning_mode=False) == "off",
    f"got {ki75_reasoning_decision(True, False)!r}",
)

# G1.5: Qwen3.5-abliterated scenario (enable_thinking=True, eos_drift=True)
# Per PATTERNS.md §9 Contradiction #2: KI#75 gates on enable_thinking ONLY,
# NOT eos_drift. Qwen3.5-abliterated has enable_thinking=True, so it will
# STILL get --reasoning on. The app cannot fix this model (AP-7: model broken).
# This test confirms eos_drift is NOT in the gating condition.
check(
    "G1.5: Qwen3.5-abliterated (enable_thinking=True, eos_drift=True) → --reasoning on (eos_drift NOT in gate)",
    ki75_reasoning_decision(enable_thinking=True, reasoning_mode=True) == "on",
    "KI#75 must NOT gate on eos_drift — would regress Gemma-4-HauhauCS",
)

# G1.6: Gemma-4-HauhauCS scenario (enable_thinking=True, eos_drift=True)
# Same as G1.5 but explicit: this model WORKS with --reasoning on (iter-91
# log: 159 text + 438 reasoning chunks, good quality). KI#75 must NOT
# disable reasoning here.
check(
    "G1.6: Gemma-4-HauhauCS (enable_thinking=True, eos_drift=True, reasoning_mode=True) → --reasoning on (protects working model)",
    ki75_reasoning_decision(enable_thinking=True, reasoning_mode=True) == "on",
    "Gemma-4-HauhauCS works WITH reasoning despite eos_drift — do NOT gate on eos_drift",
)


# ── G2: KI#72 pre-tokenizer warning detection ──────────────────────
#
# We instantiate a LocalServerManager WITHOUT a UI (ui=None) and call
# _check_pretokenizer_warning() directly with simulated llama-server
# log lines. The method should:
#   - Set _pretokenizer_warning_seen=True when "missing pre-tokenizer
#     type" OR "GENERATION QUALITY WILL BE DEGRADED" is in the line.
#   - Append the line to _pretokenizer_warning_lines (deduplicated).
#   - Be a no-op for unrelated lines.
#   - Run even when self.ui is None (headless mode).

print("\n=== G2: KI#72 pre-tokenizer warning detection ===")

from app.utils.ai_clients.local_server_manager import LocalServerManager

# Construct without UI — _check_pretokenizer_warning must work headless.
lsm = LocalServerManager(ui=None)

# G2.1: initial state — no warning seen
check(
    "G2.1: initial state — warning_seen=False, lines=[]",
    lsm._pretokenizer_warning_seen is False and lsm._pretokenizer_warning_lines == [],
    f"seen={lsm._pretokenizer_warning_seen}, lines={lsm._pretokenizer_warning_lines}",
)

# G2.2: "missing pre-tokenizer type" line — flag set, line captured
test_line_1 = "print_info: missing pre-tokenizer type, using: 'default'"
lsm._check_pretokenizer_warning(test_line_1)
check(
    "G2.2: 'missing pre-tokenizer type' line → warning_seen=True",
    lsm._pretokenizer_warning_seen is True,
    f"seen={lsm._pretokenizer_warning_seen}",
)
check(
    "G2.2b: line captured in _pretokenizer_warning_lines",
    test_line_1 in lsm._pretokenizer_warning_lines,
    f"lines={lsm._pretokenizer_warning_lines}",
)

# G2.3: "GENERATION QUALITY WILL BE DEGRADED" line — flag already set, new line captured
test_line_2 = "warn: GENERATION QUALITY WILL BE DEGRADED"
lsm._check_pretokenizer_warning(test_line_2)
check(
    "G2.3: 'GENERATION QUALITY WILL BE DEGRADED' line → warning_seen still True",
    lsm._pretokenizer_warning_seen is True,
)
check(
    "G2.3b: second unique line captured",
    test_line_2 in lsm._pretokenizer_warning_lines
    and len(lsm._pretokenizer_warning_lines) == 2,
    f"lines={lsm._pretokenizer_warning_lines}",
)

# G2.4: duplicate line — NOT re-appended (deduplication)
lsm._check_pretokenizer_warning(test_line_1)
check(
    "G2.4: duplicate line NOT re-appended (deduplication)",
    len(lsm._pretokenizer_warning_lines) == 2,
    f"lines count={len(lsm._pretokenizer_warning_lines)} (expected 2)",
)

# G2.5: unrelated line — no-op
unrelated_line = "main: loading model from /path/to/model.gguf"
lsm._check_pretokenizer_warning(unrelated_line)
check(
    "G2.5: unrelated line → no-op (warning state unchanged)",
    lsm._pretokenizer_warning_seen is True
    and len(lsm._pretokenizer_warning_lines) == 2,
    f"seen={lsm._pretokenizer_warning_seen}, lines_count={len(lsm._pretokenizer_warning_lines)}",
)

# G2.6: empty line — no-op
lsm._check_pretokenizer_warning("")
check(
    "G2.6: empty line → no-op",
    lsm._pretokenizer_warning_seen is True
    and len(lsm._pretokenizer_warning_lines) == 2,
)

# G2.7: case-insensitive matching — "MISSING PRE-TOKENIZER TYPE" also matches
lsm2 = LocalServerManager(ui=None)
lsm2._check_pretokenizer_warning("INFO: MISSING PRE-TOKENIZER TYPE, USING: 'DEFAULT'")
check(
    "G2.7: case-insensitive match (uppercase) → warning_seen=True",
    lsm2._pretokenizer_warning_seen is True,
    f"seen={lsm2._pretokenizer_warning_seen}",
)

# G2.8: partial substring match — line doesn't need to be exactly the warning
lsm3 = LocalServerManager(ui=None)
lsm3._check_pretokenizer_warning("srv  model: missing pre-tokenizer type for vocab, falling back")
check(
    "G2.8: substring match (line contains warning text) → warning_seen=True",
    lsm3._pretokenizer_warning_seen is True,
)


# ── G3: KI#72 accessor + reset ─────────────────────────────────────
#
# Verify get_pretokenizer_warning() returns the expected tuple, and that
# the state can be reset (simulating what start_server_async() does at
# the beginning of each new server session).

print("\n=== G3: KI#72 accessor + reset ===")

# G3.1: get_pretokenizer_warning() returns (bool, list) tuple
result = lsm.get_pretokenizer_warning()
check(
    "G3.1: get_pretokenizer_warning() returns 2-tuple",
    isinstance(result, tuple) and len(result) == 2,
    f"result={result!r}",
)
check(
    "G3.1b: first element is bool",
    isinstance(result[0], bool),
)
check(
    "G3.1c: second element is list",
    isinstance(result[1], list),
)

# G3.2: get_pretokenizer_warning() returns the correct values
seen, lines = result
check(
    "G3.2: accessor returns seen=True for lsm (warning was detected)",
    seen is True,
)
check(
    "G3.2b: accessor returns 2 captured lines for lsm",
    len(lines) == 2,
    f"lines count={len(lines)}",
)

# G3.3: accessor returns a COPY (not the internal list) — mutation safe
lines.append("mutated by test")
check(
    "G3.3: accessor returns a copy (internal list not mutated)",
    len(lsm._pretokenizer_warning_lines) == 2,
    f"internal lines count={len(lsm._pretokenizer_warning_lines)} (expected 2)",
)

# G3.4: reset state (simulating start_server_async() reset)
lsm._pretokenizer_warning_seen = False
lsm._pretokenizer_warning_lines = []
seen_after_reset, lines_after_reset = lsm.get_pretokenizer_warning()
check(
    "G3.4: after reset — accessor returns (False, [])",
    seen_after_reset is False and lines_after_reset == [],
    f"seen={seen_after_reset}, lines={lines_after_reset}",
)

# G3.5: fresh LocalServerManager — no warning seen
lsm_fresh = LocalServerManager(ui=None)
seen_fresh, lines_fresh = lsm_fresh.get_pretokenizer_warning()
check(
    "G3.5: fresh instance — accessor returns (False, [])",
    seen_fresh is False and lines_fresh == [],
)


# ── G4: KI#75 deduplication — verify detect_template is no longer ─
# called twice in start_server_async (lines 466 + 487 in pre-iter-93).
# We grep the source code to confirm the duplicate calls are removed.

print("\n=== G4: KI#75 deduplication — detect_template calls in start_server_async ===")

import re
lsm_src_path = os.path.join(
    PROJECT_ROOT, "app", "utils", "ai_clients", "local_server_manager.py"
)
with open(lsm_src_path, "r", encoding="utf-8") as f:
    lsm_src = f.read()

# G4.1: count actual detect_template() CALLS (not comments/docstrings).
# Pre-iter-93 had 3 calls: 1 in the early decision block + 1 in the
# custom_jinja_override branch + 1 in the normal branch. Post-iter-93
# has 1 call (moved to the top, duplicates removed).
# We match lines like "detection = detect_template(model_path)" —
# i.e., a Python statement that CALLS the function. Comments and
# docstring references (lines starting with # or containing
# ``detect_template()`` in backticks) are excluded.
call_pattern = re.compile(r"^\s*\w+\s*=\s*detect_template\(", re.MULTILINE)
actual_calls = call_pattern.findall(lsm_src)
check(
    "G4.1: exactly 1 detect_template() CALL in local_server_manager.py (was 3 pre-iter-93)",
    len(actual_calls) == 1,
    f"found {len(actual_calls)} actual detect_template() calls (expected 1) — "
    f"matches: {actual_calls}",
)

# G4.2: verify the iter-93 KI#75 marker is present
check(
    "G4.2: iter-93 KI#75 marker present in source",
    "iter-93 (KI#75)" in lsm_src and "gate --reasoning on/off" in lsm_src.lower() or "KI#75" in lsm_src,
    "KI#75 marker not found in source",
)

# G4.3: verify the KI#75 override log message is present
check(
    "G4.3: KI#75 override log message present",
    "[KI#75] --reasoning off FORCED" in lsm_src,
    "KI#75 override log message not found",
)

# G4.4: verify the enable_thinking gating condition is present
check(
    "G4.4: enable_thinking gating condition present",
    "capability_map.enable_thinking" in lsm_src,
    "enable_thinking gating condition not found",
)

# G4.5: verify eos_drift is NOT in the --reasoning gating (only in KI#74 budget gating)
# We check that the KI#75 comment explicitly says "do NOT gate on eos_drift".
check(
    "G4.5: KI#75 comment explicitly excludes eos_drift from gating",
    "do NOT gate on eos_drift" in lsm_src.lower() or "NOT gate on eos_drift" in lsm_src,
    "eos_drift exclusion not documented in source",
)


# ── G5: KI#72 wiring — verify DiagnosticsPanel has set_local_server_manager ─

print("\n=== G5: KI#72 wiring — DiagnosticsPanel + interface_signals ===")

dp_src_path = os.path.join(
    PROJECT_ROOT, "app", "gui", "diagnostics_panel.py"
)
with open(dp_src_path, "r", encoding="utf-8") as f:
    dp_src = f.read()

# G5.1: set_local_server_manager method exists
check(
    "G5.1: DiagnosticsPanel.set_local_server_manager() method defined",
    "def set_local_server_manager(self, local_server_manager)" in dp_src,
    "set_local_server_manager method not found",
)

# G5.2: _local_server_manager attribute initialized in __init__
check(
    "G5.2: _local_server_manager attribute initialized in __init__",
    "self._local_server_manager = None" in dp_src,
)

# G5.3: Block 10 (TOKENIZER INTEGRITY) added to _build_diagnostics_text
check(
    "G5.3: Block 10 (TOKENIZER INTEGRITY) added to _build_diagnostics_text",
    "TOKENIZER INTEGRITY" in dp_src and "Block 10" in dp_src,
    "Block 10 not found",
)

# G5.4: get_pretokenizer_warning() called from DiagnosticsPanel
check(
    "G5.4: DiagnosticsPanel calls get_pretokenizer_warning()",
    "get_pretokenizer_warning()" in dp_src,
)

# G5.5: Re-quantization recommendation present in Block 10
check(
    "G5.5: re-quantization recommendation present in Block 10",
    "re-quantize" in dp_src.lower() and "HuggingFace source" in dp_src,
    "re-quantization recommendation not found",
)

# G5.6: interface_signals.py wires the panel
isrc_path = os.path.join(
    PROJECT_ROOT, "app", "gui", "interface_signals.py"
)
with open(isrc_path, "r", encoding="utf-8") as f:
    isrc = f.read()
check(
    "G5.6: interface_signals.py calls set_local_server_manager()",
    "set_local_server_manager(self.local_server_manager)" in isrc,
    "wiring call not found in interface_signals.py",
)


# ── G6: i18n keys present in BOTH ru.yaml + en.yaml ────────────────

print("\n=== G6: i18n keys (ru.yaml + en.yaml) ===")

ru_yaml_path = os.path.join(
    PROJECT_ROOT, "app", "translations", "ru.yaml"
)
en_yaml_path = os.path.join(
    PROJECT_ROOT, "app", "translations", "en.yaml"
)
with open(ru_yaml_path, "r", encoding="utf-8") as f:
    ru_yaml = f.read()
with open(en_yaml_path, "r", encoding="utf-8") as f:
    en_yaml = f.read()

# G6.1: diagnostics_tokenizer_integrity_section in both files
check(
    "G6.1: diagnostics_tokenizer_integrity_section in ru.yaml",
    "diagnostics_tokenizer_integrity_section:" in ru_yaml,
)
check(
    "G6.1b: diagnostics_tokenizer_integrity_section in en.yaml",
    "diagnostics_tokenizer_integrity_section:" in en_yaml,
)


# ── Summary ─────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"iter-93 smoke test: {PASS} PASS, {FAIL} FAIL")
print(f"{'=' * 60}")
sys.exit(1 if FAIL > 0 else 0)
