#!/usr/bin/env python3
"""iter-90 smoke test — KI#74: gate reasoning_budget_tokens on
capability_map.enable_thinking + eos_drift.

Tests 3 layers:
  G1: DetectionResult.eos_drift field — set by detect_template() when
      _check_eos_drift() returns a warning.
  G2: LocalProvider._build_extra_body() — gating logic (skip when
      enable_thinking=False OR eos_drift=True).
  G3: ai_factory.py — extraction of enable_thinking + eos_drift from
      detection_result (simulated — no real settings.json needed).

Run: python scripts/iter90_smoke_test.py
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


# ── G1: DetectionResult.eos_drift field ─────────────────────────────

print("\n=== G1: DetectionResult.eos_drift field ===")

from app.utils.ai_clients.template_detector import (
    DetectionResult, DetectionSource, Confidence, CapabilityMap,
    _check_eos_drift, _CANONICAL_EOS_BY_TEMPLATE,
)

# G1.1: field exists and defaults to False
dr = DetectionResult(
    resolved_template_name="test",
    source=DetectionSource.EMBEDDED,
    confidence=Confidence.HIGH,
    jinja_source="",
    capability_map=CapabilityMap(),
)
check("G1.1: eos_drift field exists, default=False",
      hasattr(dr, "eos_drift") and dr.eos_drift is False,
      f"eos_drift={getattr(dr, 'eos_drift', 'MISSING')}")

# G1.2: _check_eos_drift returns warning for drifted eos
warning = _check_eos_drift("qwen3-thinking", [248046])
check("G1.2: _check_eos_drift returns warning for Qwen3.5 eos=[248046]",
      warning is not None and "EOS drift" in warning,
      f"warning={warning!r}")

# G1.3: _check_eos_drift returns None for canonical eos
warning = _check_eos_drift("qwen3-thinking", [151645])
check("G1.3: _check_eos_drift returns None for canonical Qwen3 eos=[151645]",
      warning is None)

# G1.4: _check_eos_drift returns None for Llama-3 canonical eos
warning = _check_eos_drift("llama-3", [128001])
check("G1.4: _check_eos_drift returns None for Llama-3 eos=[128001]",
      warning is None)

# G1.5: _check_eos_drift returns None for unknown family
warning = _check_eos_drift("unknown-template", [999])
check("G1.5: _check_eos_drift returns None for unknown family",
      warning is None)

# G1.6: _check_eos_drift returns None for empty/None inputs
check("G1.6a: None resolved_name → None", _check_eos_drift(None, [1]) is None)
check("G1.6b: None eos → None", _check_eos_drift("qwen3-thinking", None) is None)
check("G1.6c: Empty eos → None", _check_eos_drift("qwen3-thinking", []) is None)

# G1.7: _check_eos_drift for Gemma eos=[1] with qwen3-thinking template (the
# HauhauCS case — Gemma4 base with Qwen3 Jinja override)
warning = _check_eos_drift("qwen3-thinking", [1])
check("G1.7: Gemma eos=[1] with qwen3-thinking template → drift warning",
      warning is not None and "EOS drift" in warning,
      f"warning={warning!r}")

# G1.8: _check_eos_drift for multi-eos with at least one canonical match
warning = _check_eos_drift("llama-3", [128001, 99999])
check("G1.8: multi-eos [128001, 99999] for llama-3 → None (128001 is canonical)",
      warning is None)

# G1.9: _check_eos_drift for multi-eos with NO canonical match
warning = _check_eos_drift("llama-3", [99998, 99999])
check("G1.9: multi-eos [99998, 99999] for llama-3 → drift warning",
      warning is not None)


# ── G2: LocalProvider._build_extra_body() gating ───────────────────

print("\n=== G2: LocalProvider._build_extra_body() gating ===")

from app.utils.ai_clients.providers.local_provider import LocalProvider

# G2.1: reasoning_mode=True, enable_thinking=True, eos_drift=False
#       → budget IS injected (preserves iter-80 v2 behavior)
provider = LocalProvider(
    reasoning_mode=True,
    enable_thinking=True,
    eos_drift=False,
)
extra = provider._build_extra_body(1000)
check("G2.1: thinking-capable, no drift → budget injected",
      extra is not None and "reasoning_budget_tokens" in extra,
      f"extra={extra}")
if extra and "reasoning_budget_tokens" in extra:
    check("G2.1b: budget value = max(256, int(1000*0.6)) = 600",
          extra["reasoning_budget_tokens"] == 600,
          f"budget={extra['reasoning_budget_tokens']}")

# G2.2: reasoning_mode=True, enable_thinking=False (Llama-3 case)
#       → budget SKIPPED
provider = LocalProvider(
    reasoning_mode=True,
    enable_thinking=False,
    eos_drift=False,
)
extra = provider._build_extra_body(1000)
check("G2.2: non-thinking model (Llama-3) → budget SKIPPED",
      extra is None or "reasoning_budget_tokens" not in extra,
      f"extra={extra}")

# G2.3: reasoning_mode=True, enable_thinking=True, eos_drift=True
#       (Qwen3.5-abliterated case) → budget SKIPPED
provider = LocalProvider(
    reasoning_mode=True,
    enable_thinking=True,
    eos_drift=True,
)
extra = provider._build_extra_body(1000)
check("G2.3: eos-drift model (Qwen3.5-abliterated) → budget SKIPPED",
      extra is None or "reasoning_budget_tokens" not in extra,
      f"extra={extra}")

# G2.4: reasoning_mode=True, enable_thinking=False, eos_drift=True
#       → budget SKIPPED (both conditions — skip_reason should be
#       enable_thinking first per the elif chain)
provider = LocalProvider(
    reasoning_mode=True,
    enable_thinking=False,
    eos_drift=True,
)
extra = provider._build_extra_body(1000)
check("G2.4: non-thinking + eos-drift → budget SKIPPED",
      extra is None or "reasoning_budget_tokens" not in extra,
      f"extra={extra}")

# G2.5: reasoning_mode=False → budget NOT injected (regardless of capabilities)
provider = LocalProvider(
    reasoning_mode=False,
    enable_thinking=True,
    eos_drift=False,
)
extra = provider._build_extra_body(1000)
check("G2.5: reasoning_mode=False → no budget (preserves iter-78 behavior)",
      extra is None or "reasoning_budget_tokens" not in extra,
      f"extra={extra}")

# G2.6: reasoning_mode=True, enable_thinking=True, eos_drift=False,
#       max_tokens=0 → budget NOT injected (max_tokens guard)
provider = LocalProvider(
    reasoning_mode=True,
    enable_thinking=True,
    eos_drift=False,
)
extra = provider._build_extra_body(0)
check("G2.6: max_tokens=0 → no budget",
      extra is None or "reasoning_budget_tokens" not in extra,
      f"extra={extra}")

# G2.7: defaults preserve iter-80 v2 behavior (enable_thinking=True,
#       eos_drift=False by default)
provider = LocalProvider(reasoning_mode=True)
extra = provider._build_extra_body(1000)
check("G2.7: default enable_thinking=True, eos_drift=False → budget injected",
      extra is not None and "reasoning_budget_tokens" in extra,
      f"extra={extra}")

# G2.8: advanced_params still injected even when budget is skipped
provider = LocalProvider(
    reasoning_mode=True,
    enable_thinking=False,
    eos_drift=False,
    advanced_params={"min_p": 0.07},
)
extra = provider._build_extra_body(1000)
check("G2.8: advanced_params preserved when budget skipped",
      extra is not None and extra.get("min_p") == 0.07
      and "reasoning_budget_tokens" not in extra,
      f"extra={extra}")

# G2.9: reasoning_budget_message NOT injected when budget is skipped
provider = LocalProvider(
    reasoning_mode=True,
    enable_thinking=False,
    eos_drift=False,
    reasoning_budget_message_enabled=True,
)
extra = provider._build_extra_body(1000)
check("G2.9: reasoning_budget_message NOT injected when budget skipped",
      extra is None or "reasoning_budget_message" not in extra,
      f"extra={extra}")

# G2.10: reasoning_budget_message IS injected when budget is present
provider = LocalProvider(
    reasoning_mode=True,
    enable_thinking=True,
    eos_drift=False,
    reasoning_budget_message_enabled=True,
)
extra = provider._build_extra_body(1000)
check("G2.10: reasoning_budget_message injected when budget present",
      extra is not None and "reasoning_budget_message" in extra
      and "reasoning_budget_tokens" in extra,
      f"extra={extra}")

# G2.11: skip logged once (not on every call)
import io, logging as _logging
log_stream = io.StringIO()
handler = _logging.StreamHandler(log_stream)
handler.setLevel(_logging.INFO)
logger = _logging.getLogger("Local Provider")
logger.addHandler(handler)
logger.setLevel(_logging.INFO)

provider = LocalProvider(
    reasoning_mode=True,
    enable_thinking=False,
    eos_drift=False,
)
provider._build_extra_body(1000)  # first call — should log
first_log = log_stream.getvalue()
provider._build_extra_body(1000)  # second call — should NOT log
second_log = log_stream.getvalue()
check("G2.11a: first call logs KI#74 skip",
      "KI#74" in first_log and "SKIPPED" in first_log,
      f"first_log={first_log!r}")
check("G2.11b: second call does NOT log (already logged)",
      "KI#74" not in second_log[len(first_log):],
      f"second_log_delta={second_log[len(first_log):]!r}")
logger.removeHandler(handler)


# ── G3: ai_factory extraction (simulated) ──────────────────────────

print("\n=== G3: ai_factory extraction (simulated) ===")

# G3.1: DetectionResult with enable_thinking=True, eos_drift=False
#       → factory should pass enable_thinking=True, eos_drift=False
dr = DetectionResult(
    resolved_template_name="qwen3-thinking",
    source=DetectionSource.EMBEDDED,
    confidence=Confidence.HIGH,
    jinja_source="{% if enable_thinking %}",
    capability_map=CapabilityMap(enable_thinking=True),
    eos_drift=False,
)
check("G3.1: enable_thinking=True, eos_drift=False extracted correctly",
      dr.capability_map.enable_thinking is True and dr.eos_drift is False)

# G3.2: DetectionResult with enable_thinking=False (Llama-3)
dr = DetectionResult(
    resolved_template_name="llama-3",
    source=DetectionSource.EMBEDDED,
    confidence=Confidence.HIGH,
    jinja_source="no thinking vars",
    capability_map=CapabilityMap(enable_thinking=False),
    eos_drift=False,
)
check("G3.2: Llama-3 enable_thinking=False extracted correctly",
      dr.capability_map.enable_thinking is False and dr.eos_drift is False)

# G3.3: DetectionResult with eos_drift=True (Qwen3.5-abliterated)
dr = DetectionResult(
    resolved_template_name="qwen3-thinking",
    source=DetectionSource.EMBEDDED,
    confidence=Confidence.HIGH,
    jinja_source="{% if enable_thinking %}",
    capability_map=CapabilityMap(enable_thinking=True),
    eos_drift=True,
    warnings=["EOS drift: ..."],
)
check("G3.3: Qwen3.5-abliterated eos_drift=True extracted correctly",
      dr.capability_map.enable_thinking is True and dr.eos_drift is True)

# G3.4: compute_capability_map detects enable_thinking in Jinja
from app.utils.ai_clients.template_detector import compute_capability_map
caps = compute_capability_map("{% if enable_thinking %}think{% endif %}")
check("G3.4: compute_capability_map detects enable_thinking in Jinja",
      caps.enable_thinking is True)

# G3.5: compute_capability_map does NOT detect enable_thinking in plain Llama-3 Jinja
caps = compute_capability_map(
    "{% for message in messages %}{{ message.content }}{% endfor %}"
)
check("G3.5: plain Jinja (no enable_thinking) → enable_thinking=False",
      caps.enable_thinking is False)

# G3.6: compute_capability_map on empty Jinja
caps = compute_capability_map("")
check("G3.6: empty Jinja → enable_thinking=False",
      caps.enable_thinking is False)


# ── G4: Regression — iter-89 contracts preserved ───────────────────

print("\n=== G4: Regression — iter-89 contracts ===")

# G4.1: _CANONICAL_EOS_BY_TEMPLATE still has 9 families (iter-89 KI#69)
check("G4.1: _CANONICAL_EOS_BY_TEMPLATE has >= 9 entries",
      len(_CANONICAL_EOS_BY_TEMPLATE) >= 9,
      f"len={len(_CANONICAL_EOS_BY_TEMPLATE)}")

# G4.2: qwen3-thinking canonical eos = [151645]
check("G4.2: qwen3-thinking canonical eos = [151645]",
      _CANONICAL_EOS_BY_TEMPLATE.get("qwen3-thinking") == [151645])

# G4.3: llama-3 canonical eos = [128001, 128008, 128009]
check("G4.3: llama-3 canonical eos = [128001, 128008, 128009]",
      _CANONICAL_EOS_BY_TEMPLATE.get("llama-3") == [128001, 128008, 128009])

# G4.4: gemma3 canonical eos = [1]
check("G4.4: gemma3 canonical eos = [1]",
      _CANONICAL_EOS_BY_TEMPLATE.get("gemma3") == [1])

# G4.5: mistral-v0-1 canonical eos = [2]
check("G4.5: mistral-v0-1 canonical eos = [2]",
      _CANONICAL_EOS_BY_TEMPLATE.get("mistral-v0-1") == [2])


# ── Summary ─────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print(f"iter-90 smoke test: {PASS} PASS, {FAIL} FAIL")
print(f"{'='*60}")
sys.exit(1 if FAIL > 0 else 0)
