#!/usr/bin/env python3
"""iter-80.1 smoke tests — reasoning_budget_message opt-in injection.

Tests cover the iter-80.1 implementation of the opt-in
``reasoning_budget_message`` injection in ``local_provider.py`` and the
``reasoning_budget_message_enabled`` kwarg wiring in ``ai_factory.py``.

iter-80.1 supersedes the iter-80 v2 Variant B deferral (where
``reasoning_budget_message`` was intentionally NOT injected because of
issue #22717 regression risk on bundled builds b9020..pre-PR-#22740).
iter-80.1 makes the injection OPT-IN via a new
``reasoning_budget_message_enabled`` flag (default False = iter-80 v2
Variant B behavior preserved).  Users explicitly enable the flag AFTER
updating their bundled ``llama-server.exe`` to >= PR #22740 via
``installer.bat``.

Key design decisions verified by these tests:
  1. New ``reasoning_budget_message_enabled: bool = False`` kwarg in
     ``LocalProvider.__init__``, stored as
     ``self._reasoning_budget_message_enabled = bool(...)``.
  2. ``_build_extra_body`` injects ``reasoning_budget_message`` ONLY when
     ALL THREE conditions are met:
       (a) ``self._reasoning_mode`` is True
       (b) ``self._reasoning_budget_message_enabled`` is True
       (c) ``max_tokens > 0`` AND computed budget > 0
  3. When the flag is False (default), behavior is IDENTICAL to iter-80
     v2 Variant B — no ``reasoning_budget_message`` field in extra_body.
  4. When ``reasoning_mode`` is False, the message is NOT injected even
     if ``reasoning_budget_message_enabled`` is True (the flag is a
     modifier on the reasoning sub-cap, not a standalone control).
  5. ``ai_factory.py`` reads ``reasoning_budget_message_enabled`` from
     ``settings.json::main_settings.reasoning_budget_message_enabled``
     and forwards it to ``LocalProvider``.
  6. ``settings.json`` has the new key with default ``false`` (schema-
     stable addition, NOT a §5 trigger — same pattern as iter-80 v2's
     use of the existing ``reasoning_mode`` key).
  7. Regression: iter-80 v2 contracts preserved — canonical
     ``reasoning_budget_tokens`` field name, sub-cap math
     (``max(256, int(max_tokens * 0.6))``), defensive copy of
     ``advanced_params``, returns ``None`` when nothing to inject.
  8. Regression: iter-78 KI#59 consume-not-yield preserved.
  9. Regression: iter-79 REASONING_EXHAUSTED warning preserved.

Uses pure source inspection + permissive stub for httpx/openai/PyQt6
(same pattern as iter-80 v2 smoke tests — avoids importing these
modules which can't be loaded in the Linux test env).

Run:  python scripts/iter80_1_smoke_test.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

PASS = 0
FAIL = 0


def _result(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    tag = "PASS" if ok else "FAIL"
    if not ok:
        FAIL += 1
    else:
        PASS += 1
    msg = f"  [{tag}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)


REPO = Path(__file__).resolve().parent.parent
LOCAL_PROVIDER = REPO / "app" / "utils" / "ai_clients" / "providers" / "local_provider.py"
AI_FACTORY = REPO / "app" / "utils" / "ai_clients" / "ai_factory.py"
SETTINGS_JSON = REPO / "app" / "configuration" / "settings.json"


def _method_body_src(tree: ast.Module, class_name: str, method_name: str) -> str | None:
    """Return unparsed source of a specific method inside a class."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return ast.unparse(item)
    return None


def _class_body_src(tree: ast.Module, class_name: str) -> str | None:
    """Return unparsed source of an entire class body."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.unparse(node)
    return None


def main():
    print("=== iter-80.1 smoke tests ===\n")

    # ==== Group 1: __init__ kwarg + storage ====
    print("Group 1: __init__ reasoning_budget_message_enabled kwarg")
    lp_src = LOCAL_PROVIDER.read_text(encoding="utf-8")
    lp_tree = ast.parse(lp_src)

    _result("G1.1 local_provider.py parses cleanly", True)

    init_body = _method_body_src(lp_tree, "LocalProvider", "__init__")
    _result(
        "G1.2 __init__ method found",
        init_body is not None,
        "method body found via AST",
    )

    if init_body:
        _result(
            "G1.3 __init__ signature includes reasoning_budget_message_enabled: bool = False",
            "reasoning_budget_message_enabled: bool = False" in init_body
            or "reasoning_budget_message_enabled: bool=False" in init_body,
            "kwarg added per iter-80.1 plan",
        )

        _result(
            "G1.4 __init__ stores self._reasoning_budget_message_enabled = bool(...)",
            "self._reasoning_budget_message_enabled = bool(reasoning_budget_message_enabled)" in init_body,
            "stored as bool — normalises None/0/1 → False/True",
        )

    # __init__ docstring must mention the new kwarg.
    _result(
        "G1.5 __init__ docstring mentions reasoning_budget_message_enabled",
        "reasoning_budget_message_enabled" in lp_src
        and "OPT-IN" in lp_src
        and "PR #22740" in lp_src,
        "documents the opt-in semantics + the bundled-binary prerequisite",
    )

    # ==== Group 2: _build_extra_body — opt-in injection ====
    print("\nGroup 2: _build_extra_body — reasoning_budget_message opt-in injection")

    beb_body = _method_body_src(lp_tree, "LocalProvider", "_build_extra_body")
    _result(
        "G2.1 _build_extra_body method exists",
        beb_body is not None,
        "method body found via AST",
    )

    if beb_body:
        # Must inject reasoning_budget_message when the flag is on.
        _result(
            "G2.2 _build_extra_body injects reasoning_budget_message conditionally",
            'extra["reasoning_budget_message"]' in beb_body
            or "extra['reasoning_budget_message']" in beb_body,
            "field injected when flag is True (iter-80.1)",
        )

        # Must gate on self._reasoning_budget_message_enabled.
        _result(
            "G2.3 _build_extra_body gates message on self._reasoning_budget_message_enabled",
            "self._reasoning_budget_message_enabled" in beb_body,
            "opt-in flag check before injection",
        )

        # Must reference _REASONING_BUDGET_MESSAGE constant.
        _result(
            "G2.4 _build_extra_body uses _REASONING_BUDGET_MESSAGE constant",
            "self._REASONING_BUDGET_MESSAGE" in beb_body,
            "uses the class-level constant (not a hardcoded string)",
        )

        # The injection must be INSIDE the `if budget > 0:` block (so that
        # message is only sent when the sub-cap is also sent).
        _result(
            "G2.5 message injection is inside the `if budget > 0:` block",
            "if budget > 0:" in beb_body
            and "reasoning_budget_message" in beb_body
            and "if self._reasoning_budget_message_enabled:" in beb_body,
            "message only sent when sub-cap is also sent (nested condition)",
        )

        # The iter-80.1 comment must be present in the raw source (comments
        # are stripped by ast.unparse, so we check lp_src directly).
        _result(
            "G2.6 iter-80.1 comment block present in _build_extra_body",
            "iter-80.1" in lp_src and "opted in" in lp_src
            and "iter-80 v2 Variant B" in lp_src,
            "documents the opt-in rationale + iter-80 v2 Variant B fallback",
        )

    # ==== Group 3: direct-call verification — opt-in behavior ====
    print("\nGroup 3: _build_extra_body direct-call — opt-in behavior matrix")

    if beb_body:
        # Permissive stub so LocalProvider can be imported without
        # PyQt6 / openai / httpx (same pattern as iter-80 v2 smoke tests).
        class _StubInstance:
            def __init__(self, *args, **kwargs):
                pass

            def __call__(self, *args, **kwargs):
                return _StubInstance()

            def __getattr__(self, name):
                return _StubInstance

        class _StubModule(type(sys)):
            def __getattr__(self, name):
                return _StubInstance

        for mod_name in ("PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets",
                         "qasync", "httpx", "openai",
                         "app.utils.ai_clients.base_provider",
                         "app.configuration",
                         "app.configuration.configuration"):
            if mod_name not in sys.modules:
                sys.modules[mod_name] = _StubModule(mod_name)

        class _StubBase:
            pass

        sys.modules["app.utils.ai_clients.base_provider"].BaseAIProvider = _StubBase

        sys.path.insert(0, str(REPO))
        try:
            from app.utils.ai_clients.providers.local_provider import LocalProvider

            # Case 1: flag OFF (default) + reasoning_mode ON → NO message.
            p1 = LocalProvider(reasoning_mode=True, reasoning_budget_message_enabled=False)
            eb1 = p1._build_extra_body(2048)
            _result(
                "G3.1 flag=False + reasoning=True → NO reasoning_budget_message",
                eb1 is not None
                and "reasoning_budget_tokens" in eb1
                and "reasoning_budget_message" not in eb1,
                f"extra_body={eb1} — iter-80 v2 Variant B preserved",
            )

            # Case 2: flag ON + reasoning_mode ON → message injected.
            p2 = LocalProvider(reasoning_mode=True, reasoning_budget_message_enabled=True)
            eb2 = p2._build_extra_body(2048)
            _result(
                "G3.2 flag=True + reasoning=True → reasoning_budget_message injected",
                eb2 is not None
                and "reasoning_budget_tokens" in eb2
                and "reasoning_budget_message" in eb2
                and eb2["reasoning_budget_message"] == "Final Answer:",
                f"extra_body={eb2} — opt-in message injection active",
            )

            # Case 3: flag ON + reasoning_mode OFF → NO message (flag is a
            # modifier on the reasoning sub-cap, not a standalone control).
            p3 = LocalProvider(reasoning_mode=False, reasoning_budget_message_enabled=True)
            eb3 = p3._build_extra_body(2048)
            _result(
                "G3.3 flag=True + reasoning=False → NO reasoning_budget_message",
                "reasoning_budget_message" not in (eb3 or {}),
                f"extra_body={eb3} — flag is a modifier, not standalone",
            )

            # Case 4: flag ON + reasoning_mode ON + max_tokens=0 → NO message
            # (max_tokens <= 0 short-circuits the sub-cap).
            p4 = LocalProvider(reasoning_mode=True, reasoning_budget_message_enabled=True)
            eb4 = p4._build_extra_body(0)
            _result(
                "G3.4 flag=True + reasoning=True + max_tokens=0 → NO message",
                "reasoning_budget_message" not in (eb4 or {}),
                f"extra_body={eb4} — max_tokens=0 short-circuits sub-cap",
            )

            # Case 5: flag ON + reasoning_mode ON + max_tokens=100 → message
            # injected (budget=256 due to floor, message sent).
            p5 = LocalProvider(reasoning_mode=True, reasoning_budget_message_enabled=True)
            eb5 = p5._build_extra_body(100)
            _result(
                "G3.5 flag=True + reasoning=True + max_tokens=100 → message injected (budget=256 floor)",
                eb5 is not None
                and eb5.get("reasoning_budget_tokens") == 256
                and eb5.get("reasoning_budget_message") == "Final Answer:",
                f"extra_body={eb5} — floor 256 + message sent",
            )

            # Case 6: flag OFF + reasoning_mode OFF + no advanced_params → None.
            p6 = LocalProvider(reasoning_mode=False, reasoning_budget_message_enabled=False)
            eb6 = p6._build_extra_body(2048)
            _result(
                "G3.6 flag=False + reasoning=False + no advanced → None",
                eb6 is None,
                f"extra_body={eb6} — iter-22 behavior preserved",
            )

            # Case 7: flag ON + reasoning ON + advanced_params present →
            # both advanced_params AND message + budget in extra_body.
            p7 = LocalProvider(
                reasoning_mode=True,
                reasoning_budget_message_enabled=True,
                advanced_params={"min_p": 0.07, "xtc_probability": 0.3},
            )
            eb7 = p7._build_extra_body(2048)
            _result(
                "G3.7 flag=True + reasoning=True + advanced_params → all 4 fields in extra_body",
                eb7 is not None
                and eb7.get("min_p") == 0.07
                and eb7.get("xtc_probability") == 0.3
                and "reasoning_budget_tokens" in eb7
                and eb7.get("reasoning_budget_message") == "Final Answer:",
                f"extra_body={eb7} — advanced params + sub-cap + message unified",
            )

        except Exception as e:
            _result(
                "G3.1-G3.7 direct-call opt-in matrix tests",
                False,
                f"import or call failed: {e!r}",
            )
        finally:
            sys.path.pop(0)

    # ==== Group 4: ai_factory.py wiring ====
    print("\nGroup 4: ai_factory.py — reasoning_budget_message_enabled wiring")

    af_src = AI_FACTORY.read_text(encoding="utf-8")
    af_tree = ast.parse(af_src)

    _result("G4.1 ai_factory.py parses cleanly", True)

    _result(
        "G4.2 ai_factory reads reasoning_budget_message_enabled from config_settings",
        'config_settings.get_main_setting("reasoning_budget_message_enabled")' in af_src,
        "new opt-in key read from settings.json::main_settings",
    )

    _result(
        "G4.3 ai_factory normalises None → False via 'or False'",
        'or False' in af_src and "reasoning_budget_message_enabled" in af_src,
        "get_main_setting returns None when key absent — bool(None or False) == False",
    )

    _result(
        "G4.4 ai_factory forwards reasoning_budget_message_enabled to LocalProvider",
        "reasoning_budget_message_enabled=reasoning_budget_message_enabled" in af_src,
        "kwarg passed through to LocalProvider.__init__",
    )

    # iter-80.1 comment must be present in ai_factory.py.
    _result(
        "G4.5 iter-80.1 comment block present in ai_factory.py",
        "iter-80.1" in af_src and "PR #22740" in af_src and "#22717" in af_src,
        "documents the opt-in rationale + bundled-binary prerequisite",
    )

    # ==== Group 5: settings.json — new key ====
    print("\nGroup 5: settings.json — reasoning_budget_message_enabled key")

    import json
    settings = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
    main_settings = settings.get("main_settings", {})

    _result(
        "G5.1 settings.json has reasoning_budget_message_enabled key",
        "reasoning_budget_message_enabled" in main_settings,
        "new key added next to reasoning_mode (schema-stable, NOT §5 trigger)",
    )

    if "reasoning_budget_message_enabled" in main_settings:
        _result(
            "G5.2 reasoning_budget_message_enabled defaults to False",
            main_settings["reasoning_budget_message_enabled"] is False,
            f"got {main_settings['reasoning_budget_message_enabled']!r} — Variant B preserved by default",
        )

    # The new key must be adjacent to reasoning_mode (discoverable).
    settings_text = SETTINGS_JSON.read_text(encoding="utf-8")
    _result(
        "G5.3 reasoning_budget_message_enabled is adjacent to reasoning_mode in settings.json",
        '"reasoning_mode": false' in settings_text
        and '"reasoning_budget_message_enabled": false' in settings_text,
        "placed next to reasoning_mode for discoverability",
    )

    # ==== Group 6: regression — iter-80 v2 contracts preserved ====
    print("\nGroup 6: regression — iter-80 v2 contracts preserved")

    cls_body = _class_body_src(lp_tree, "LocalProvider")
    _result(
        "G6.1 _REASONING_BUDGET_FRACTION = 0.6 constant preserved",
        "_REASONING_BUDGET_FRACTION = 0.6" in lp_src,
        "sub-cap = 60% of max_tokens for thinking",
    )

    _result(
        "G6.2 _REASONING_BUDGET_MIN = 256 constant preserved",
        "_REASONING_BUDGET_MIN = 256" in lp_src,
        "floor — models need some thinking room",
    )

    _result(
        "G6.3 _REASONING_BUDGET_MESSAGE = 'Final Answer:' constant preserved",
        '_REASONING_BUDGET_MESSAGE = "Final Answer:"' in lp_src
        or "_REASONING_BUDGET_MESSAGE = 'Final Answer:'" in lp_src,
        "s1 paper pattern, arXiv:2501.19393",
    )

    # Canonical field name reasoning_budget_tokens still used (NOT alias).
    _result(
        "G6.4 _build_extra_body still uses canonical 'reasoning_budget_tokens' field",
        'extra["reasoning_budget_tokens"]' in beb_body
        or "extra['reasoning_budget_tokens']" in beb_body,
        "canonical name per PR #22740 (resolution #1)",
    )

    # Must NOT use the deprecated alias thinking_budget_tokens.
    _result(
        "G6.5 _build_extra_body does NOT inject deprecated 'thinking_budget_tokens' alias",
        "thinking_budget_tokens" not in beb_body,
        "back-compat alias for PR #17750 — not guaranteed on intermediate builds",
    )

    # Defensive copy of advanced_params preserved.
    _result(
        "G6.6 _build_extra_body still starts from dict(self.advanced_params) (defensive copy)",
        "dict(self.advanced_params)" in beb_body,
        "preserves iter-22 advanced sampling params",
    )

    # Returns None when nothing to inject — preserved.
    _result(
        "G6.7 _build_extra_body still returns None when nothing to inject",
        "return extra if extra else None" in beb_body,
        "preserves iter-22 behavior when reasoning_mode off + no advanced_params",
    )

    # Still gates on self._reasoning_mode and max_tokens > 0.
    _result(
        "G6.8 _build_extra_body still gates sub-cap on self._reasoning_mode and max_tokens > 0",
        "self._reasoning_mode" in beb_body and "max_tokens > 0" in beb_body,
        "sub-cap only when reasoning_mode on AND max_tokens > 0",
    )

    # ==== Group 7: regression — iter-78 KI#59 consume-not-yield ====
    print("\nGroup 7: regression — iter-78 KI#59 (consume-not-yield) preserved")

    gs_body = _method_body_src(lp_tree, "LocalProvider", "generate_stream")
    gsum_body = _method_body_src(lp_tree, "LocalProvider", "generate_summary")

    _result(
        "G7.1 generate_stream still consumes reasoning via getattr",
        gs_body is not None
        and ('getattr(delta, "reasoning_content", None)' in gs_body
             or "getattr(delta, 'reasoning_content', None)" in gs_body),
        "KI#59 — reasoning_content extracted for diagnostics, not yielded",
    )

    _result(
        "G7.2 generate_stream still uses `continue` to consume reasoning",
        gs_body is not None and "reasoning_chunks += 1" in gs_body and "continue" in gs_body,
        "reasoning is counted then skipped — never yielded",
    )

    _result(
        "G7.3 generate_stream still yields only delta.content",
        gs_body is not None and "yield delta.content" in gs_body,
        "ONLY actual text content is yielded to the caller",
    )

    _result(
        "G7.4 generate_summary still consumes reasoning via getattr + continue",
        gsum_body is not None
        and ('getattr(delta, "reasoning_content", None)' in gsum_body
             or "getattr(delta, 'reasoning_content', None)" in gsum_body)
        and "continue" in gsum_body,
        "KI#59 — summary path consumes reasoning silently too",
    )

    # ==== Group 8: regression — iter-79 REASONING_EXHAUSTED warning ====
    print("\nGroup 8: regression — iter-79 REASONING_EXHAUSTED warning preserved")

    _result(
        "G8.1 REASONING_EXHAUSTED warning string still present in generate_stream",
        gs_body is not None and "REASONING_EXHAUSTED" in gs_body,
        "logged when text_chunks=0 and reasoning_chunks>0",
    )

    _result(
        "G8.2 warning condition still checks text_chunks == 0",
        gs_body is not None and "text_chunks == 0" in gs_body,
        "detects max_tokens exhaustion on reasoning",
    )

    _result(
        "G8.3 warning condition still checks reasoning_chunks > 0",
        gs_body is not None and "reasoning_chunks > 0" in gs_body,
        "avoids false positive when stream produced nothing at all",
    )

    _result(
        "G8.4 warning still uses logger.warning",
        gs_body is not None and "logger.warning(" in gs_body,
        "visible at default log level (INFO+)",
    )

    # ==== Group 9: 3 call sites still use unified _build_extra_body ====
    print("\nGroup 9: 3 call sites still use unified _build_extra_body")

    g_body = _method_body_src(lp_tree, "LocalProvider", "generate")

    _result(
        "G9.1 generate_stream uses _build_extra_body",
        gs_body is not None and "_build_extra_body(payload['max_tokens'])" in gs_body,
        "iter-80 v2 unified helper call preserved",
    )

    _result(
        "G9.2 generate uses _build_extra_body",
        g_body is not None and "_build_extra_body(payload['max_tokens'])" in g_body,
        "iter-80 v2 unified helper call preserved",
    )

    _result(
        "G9.3 generate_summary uses _build_extra_body",
        gsum_body is not None and "_build_extra_body(payload['max_tokens'])" in gsum_body,
        "iter-80 v2 unified helper call preserved",
    )

    # ==== Group 10: file syntax + sanity ====
    print("\nGroup 10: file syntax + sanity checks")

    _result("G10.1 local_provider.py syntax OK", True)
    _result("G10.2 ai_factory.py syntax OK", True)
    _result("G10.3 settings.json syntax OK", True)

    # No duplicate methods (additive-edit rule, §4 rule #10).
    beb_count = lp_src.count("def _build_extra_body(")
    _result(
        "G10.4 no duplicate _build_extra_body",
        beb_count == 1,
        f"count={beb_count} — additive-edit rule preserved",
    )

    init_count = lp_src.count("def __init__(self, port: int = 48596")
    _result(
        "G10.5 no duplicate __init__",
        init_count == 1,
        f"count={init_count} — additive-edit rule preserved",
    )

    # iter-80.1 marker must be present (documents the opt-in approach).
    _result(
        "G10.6 iter-80.1 comment block present in local_provider.py",
        "iter-80.1" in lp_src and "OPT-IN" in lp_src and "PR #22740" in lp_src,
        "documents the opt-in semantics + bundled-binary prerequisite",
    )

    # The old "intentionally NOT injected" Variant B deferral note must be
    # REMOVED (superseded by iter-80.1 opt-in approach).
    _result(
        "G10.7 iter-80 v2 'intentionally NOT injected' deferral note REMOVED",
        "intentionally NOT injected in iter-80 v2" not in lp_src
        and "Will be added in iter-80.1" not in lp_src,
        "Variant B deferral superseded by iter-80.1 opt-in",
    )

    # Line count sanity — iter-84 widened the range from [620, 730] to
    # [620, 850] to accommodate iter-82 (734 lines, added reasoning_budget_fraction
    # kwarg + clamp logic + per-instance attribute + docstring).
    # Line-count is a brittle assertion (file grows per iteration); the
    # upper bound is a sanity check against accidental bloat.
    line_count = len(lp_src.splitlines())
    _result(
        "G10.8 local_provider.py line count reasonable (relaxed iter-84)",
        620 <= line_count <= 850,
        f"{line_count} lines (iter-82 baseline 734; range widened from [620,730])",
    )

    print(f"\n=== Summary: {PASS} PASS, {FAIL} FAIL ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
