#!/usr/bin/env python3
"""iter-109 smoke tests — KI#84 Mistral-family role-alternation fix.

Tests cover the iter-109 implementation of the
``CapabilityMap.requires_role_alternation`` flag and its end-to-end wiring
into ``LocalProvider._strip_role_alternation_placeholders()``.

Background (KI#84):
  KI#80 (iter-101) added ``_strip_role_alternation_placeholders()`` in
  ``local_provider.py`` to remove ``[conversation continued]`` placeholder
  messages before sending to llama-server.  This was correct for Llama-3-8B
  (the model echoed the placeholder text in its response, degrading quality).

  BUT: Mistral-family templates (mistral-v0-1, mistral-v3-tekken,
  mistral-v7-tekken) embed a Jinja ``raise_exception`` guard that enforces
  strict user/assistant alternation after an optional leading system
  message.  Stripping the placeholder makes the prompt
  ``system → assistant → user`` — Jinja validation fails with HTTP 400
  before generation starts.  User-reported on ``MN-Violet-Lotus-12B``
  (Tekken tokenizer, embedded Jinja = mistral-v0-1).

Fix (3 layers):
  1. ``template_detector.py``: new ``CapabilityMap.requires_role_alternation``
     field, populated by Jinja-source inspection (``"roles must alternate"``
     substring) in ``compute_capability_map()`` AND by template-name fallback
     (``"mistral"`` substring) in ``_capability_map_from_template_name()``.
  2. ``ai_factory.py``: forwards ``requires_role_alternation`` from
     ``detection_result.capability_map`` to ``LocalProvider.__init__()``.
  3. ``local_provider.py``: ``__init__`` accepts kwarg
     (``self._requires_role_alternation``);
     ``_strip_role_alternation_placeholders()`` accepts
     ``requires_role_alternation`` kwarg → NO-OP when True (returns input
     unchanged).  All 3 generation methods pass ``self._requires_role_alternation``.

Key design decisions verified by these tests:
  1. ``CapabilityMap`` has a ``requires_role_alternation: bool = False``
     field (default False preserves iter-108 behavior for non-Mistral).
  2. ``compute_capability_map()`` sets the flag True when the Jinja source
     contains the substring ``"roles must alternate"`` (canonical for
     Mistral-family raise_exception guards).
  3. ``_capability_map_from_template_name()`` sets the flag True for any
     template name containing ``"mistral"`` (covers mistral-v0-1,
     mistral-v3-tekken, mistral-v7-tekken, mixtral — name-based fallback
     used when Jinja source is unavailable).
  4. ``_capability_map_from_template_name()`` leaves the flag False for
     non-Mistral templates (llama-3, chatml, gemma3, qwen3, deepseek,
     phi-3, command-r, gpt-oss, exaone, granite, olmo, alpaca).
  5. ``ai_factory.py`` reads ``requires_role_alternation`` from
     ``detection_result.capability_map`` and forwards it to LocalProvider.
  6. ``LocalProvider.__init__`` accepts the kwarg and stores
     ``self._requires_role_alternation = bool(...)``.
  7. ``_strip_role_alternation_placeholders`` is a NO-OP when
     ``requires_role_alternation=True`` (placeholder preserved, input list
     returned unchanged — alternation invariant holds).
  8. ``_strip_role_alternation_placeholders`` strips normally when
     ``requires_role_alternation=False`` (KI#80 Llama-3 echo fix preserved).
  9. All 3 generation methods (``generate_stream``, ``generate``,
     ``generate_summary``) pass ``requires_role_alternation=self._requires_role_alternation``
     to the helper.
 10. Regression: KI#80 stripping logic intact when flag is False —
     placeholder removed, same-role messages merged with ``\\n\\n``.
 11. Regression: iter-108 KI#83 fairseq stub unrelated — not touched.
 12. File syntax OK; no duplicate methods (additive-edit rule §4 #10).

Uses pure source inspection + permissive stub for httpx/openai/PyQt6
(same pattern as iter-80/80.1/108 smoke tests — avoids importing these
modules which can't be loaded in the Linux test env).

Run:  python scripts/iter109_smoke_test.py
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
TEMPLATE_DETECTOR = REPO / "app" / "utils" / "ai_clients" / "template_detector.py"
AI_FACTORY = REPO / "app" / "utils" / "ai_clients" / "ai_factory.py"
LOCAL_PROVIDER = REPO / "app" / "utils" / "ai_clients" / "providers" / "local_provider.py"


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


# Minimal Mistral-v0-1 Jinja snippet containing the raise_exception guard.
# Real Mistral templates have ~50 lines; we keep only the validation block
# because that's what ``compute_capability_map()`` matches on.
_MISTRAL_JINJA_SAMPLE = (
    "{% if messages[0]['role'] == 'system' %}"
    "{% set system_message = messages[0]['content'] %}"
    "{% set messages_start = 1 %}"
    "{% else %}"
    "{% set system_message = '' %}"
    "{% set messages_start = 0 %}"
    "{% endif %}"
    "{% for message in messages %}"
    "{% if (message['role'] == 'user') != (loop.index0 % 2 == messages_start % 0) %}"
    "{{- raise_exception(\"After the optional system message, conversation "
    "roles must alternate user/assistant/user/assistant/...\") }}"
    "{% endif %}"
    "{% endfor %}"
)

# Minimal Llama-3 Jinja snippet (NO alternation guard).
_LLAMA3_JINJA_SAMPLE = (
    "{% for message in messages %}"
    "{{- '<|start_header_id|>' + message['role'] + '<|end_header_id|>\\n\\n' }}"
    "{{- message['content'] | trim + '<|eot_id|>' }}"
    "{% endfor %}"
)


def main():
    print("=== iter-109 smoke tests ===\n")

    # ==== Group 1: CapabilityMap field ====
    print("Group 1: CapabilityMap.requires_role_alternation field")
    td_src = TEMPLATE_DETECTOR.read_text(encoding="utf-8")
    td_tree = ast.parse(td_src)

    _result("G1.1 template_detector.py parses cleanly", True)

    cls_body = _class_body_src(td_tree, "CapabilityMap")
    _result(
        "G1.2 CapabilityMap class body found",
        cls_body is not None,
        "AST traversal found the class",
    )

    _result(
        "G1.3 CapabilityMap has 'requires_role_alternation: bool = False' field",
        "requires_role_alternation: bool = False" in (cls_body or ""),
        "iter-109 (KI#84) — gates KI#80 placeholder stripping in LocalProvider",
    )

    # The field MUST have a default of False (preserves iter-108 behavior
    # for non-Mistral models — they get the KI#80 strip as before).
    _result(
        "G1.4 requires_role_alternation defaults to False",
        "requires_role_alternation: bool = False" in (cls_body or ""),
        "default False preserves iter-108 (KI#80 strip active for non-Mistral)",
    )

    # ==== Group 2: compute_capability_map() — Jinja-source detection ====
    print("\nGroup 2: compute_capability_map() — Jinja-source detection")

    ccm_body = _method_body_src(td_tree, None, "compute_capability_map") \
        or _module_function_body_src(td_tree, "compute_capability_map")

    _result(
        "G2.1 compute_capability_map function found",
        ccm_body is not None,
        "function body found via AST",
    )

    _result(
        "G2.2 compute_capability_map checks 'roles must alternate' substring",
        ccm_body is not None and "roles must alternate" in ccm_body,
        "canonical substring in Mistral raise_exception guard",
    )

    _result(
        "G2.3 compute_capability_map sets requires_role_alternation = True",
        ccm_body is not None and "requires_role_alternation = True" in ccm_body,
        "flag flipped when substring matched",
    )

    # Direct functional test — import template_detector and call the function.
    # Stub heavy modules so template_detector can be imported without gguf /
    # PyQt6 / struct / numpy (same pattern as iter-80 smoke test stubs).
    sys.path.insert(0, str(REPO))
    try:
        # Stub gguf — used by template_detector for reading GGUF metadata.
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

        for mod_name in ("gguf", "PyQt6", "PyQt6.QtCore", "PyQt6.QtGui",
                         "PyQt6.QtWidgets", "qasync", "httpx", "openai",
                         "app.utils.ai_clients.base_provider",
                         "app.configuration",
                         "app.configuration.configuration"):
            if mod_name not in sys.modules:
                sys.modules[mod_name] = _StubModule(mod_name)

        from app.utils.ai_clients.template_detector import (
            compute_capability_map,
            _capability_map_from_template_name,
            CapabilityMap,
        )

        # G2.4: Mistral Jinja sample → requires_role_alternation=True
        caps_mistral = compute_capability_map(_MISTRAL_JINJA_SAMPLE)
        _result(
            "G2.4 Mistral Jinja sample → requires_role_alternation=True",
            caps_mistral.requires_role_alternation is True,
            f"got {caps_mistral.requires_role_alternation!r}",
        )

        # G2.5: Llama-3 Jinja sample (no guard) → requires_role_alternation=False
        caps_llama3 = compute_capability_map(_LLAMA3_JINJA_SAMPLE)
        _result(
            "G2.5 Llama-3 Jinja sample → requires_role_alternation=False",
            caps_llama3.requires_role_alternation is False,
            f"got {caps_llama3.requires_role_alternation!r}",
        )

        # G2.6: empty Jinja source → no crash, False default
        caps_empty = compute_capability_map("")
        _result(
            "G2.6 empty Jinja source → requires_role_alternation=False (no crash)",
            caps_empty.requires_role_alternation is False,
            "CapabilityMap() default",
        )

        # G2.7: None Jinja source → no crash, False default
        caps_none = compute_capability_map(None)
        _result(
            "G2.7 None Jinja source → requires_role_alternation=False (no crash)",
            caps_none.requires_role_alternation is False,
            "CapabilityMap() default — function short-circuits on falsy input",
        )

    except Exception as e:
        _result(
            "G2.4-G2.7 compute_capability_map direct-call tests",
            False,
            f"import or call failed: {e!r}",
        )
    finally:
        sys.path.pop(0)

    # ==== Group 3: _capability_map_from_template_name() — name fallback ====
    print("\nGroup 3: _capability_map_from_template_name() — name-based fallback")

    sys.path.insert(0, str(REPO))
    try:
        # Reuse the stubs set up in Group 2 (still in sys.modules).
        from app.utils.ai_clients.template_detector import (
            _capability_map_from_template_name,
        )

        # Mistral family — all MUST return True
        for name in ("mistral-v0-1", "mistral-v3-tekken", "mistral-v7-tekken",
                     "mistral", "Mistral", "MISTRAL-V0-1", "mixtral"):
            caps = _capability_map_from_template_name(name)
            _result(
                f"G3.{name!r:30s} → True",
                caps.requires_role_alternation is True,
                f"got {caps.requires_role_alternation!r}",
            )

        # Non-Mistral families — all MUST return False
        for name in ("llama-3", "chatml", "gemma3", "qwen3-thinking",
                     "deepseek", "phi-3", "command-r", "gpt-oss",
                     "exaone", "granite", "olmo", "alpaca"):
            caps = _capability_map_from_template_name(name)
            _result(
                f"G3.{name!r:30s} → False",
                caps.requires_role_alternation is False,
                f"got {caps.requires_role_alternation!r}",
            )

        # Empty / None name → False (no crash)
        caps_empty = _capability_map_from_template_name("")
        _result(
            "G3.'' (empty) → False (no crash)",
            caps_empty.requires_role_alternation is False,
            "function short-circuits on falsy name",
        )

        caps_none = _capability_map_from_template_name(None)
        _result(
            "G3.None → False (no crash)",
            caps_none.requires_role_alternation is False,
            "function short-circuits on falsy name",
        )

    except Exception as e:
        _result(
            "G3 _capability_map_from_template_name direct-call tests",
            False,
            f"import or call failed: {e!r}",
        )
    finally:
        sys.path.pop(0)

    # ==== Group 4: ai_factory.py — forwarding ====
    print("\nGroup 4: ai_factory.py — requires_role_alternation forwarding")

    af_src = AI_FACTORY.read_text(encoding="utf-8")
    af_tree = ast.parse(af_src)

    _result("G4.1 ai_factory.py parses cleanly", True)

    _result(
        "G4.2 ai_factory declares 'requires_role_alternation: bool = False' default",
        "requires_role_alternation: bool = False" in af_src,
        "default False preserves iter-108 behavior when detection_result is None",
    )

    _result(
        "G4.3 ai_factory reads cap_map.requires_role_alternation via getattr",
        "getattr(cap_map, \"requires_role_alternation\"" in af_src
        or "getattr(cap_map, 'requires_role_alternation'" in af_src,
        "defensive getattr — works on CapabilityMap instances missing the field",
    )

    _result(
        "G4.4 ai_factory forwards requires_role_alternation=... to LocalProvider",
        "requires_role_alternation=requires_role_alternation" in af_src,
        "kwarg passed through to LocalProvider.__init__",
    )

    _result(
        "G4.5 ai_factory fallback message mentions requires_role_alternation=False",
        "requires_role_alternation=False" in af_src,
        "logged in exception handler — fallback path is explicit",
    )

    # ==== Group 5: LocalProvider.__init__ — kwarg + storage ====
    print("\nGroup 5: LocalProvider.__init__ — requires_role_alternation kwarg")

    lp_src = LOCAL_PROVIDER.read_text(encoding="utf-8")
    lp_tree = ast.parse(lp_src)

    _result("G5.1 local_provider.py parses cleanly", True)

    init_body = _method_body_src(lp_tree, "LocalProvider", "__init__")
    _result(
        "G5.2 __init__ method found",
        init_body is not None,
        "method body found via AST",
    )

    if init_body:
        # ast.unparse may emit 'bool = False' or 'bool=False' (with or without
        # space). Accept both forms — iter-80.1 smoke test uses the same pattern.
        _result(
            "G5.3 __init__ signature includes 'requires_role_alternation: bool = False'",
            "requires_role_alternation: bool = False" in init_body
            or "requires_role_alternation: bool=False" in init_body,
            "kwarg added per iter-109 plan",
        )

        _result(
            "G5.4 __init__ stores self._requires_role_alternation = bool(...)",
            "self._requires_role_alternation = bool(requires_role_alternation)" in init_body
            or "self._requires_role_alternation: bool = bool(requires_role_alternation)" in init_body,
            "stored as bool — normalises None/0/1 → False/True (annotation optional)",
        )

    # ==== Group 6: _strip_role_alternation_placeholders — NO-OP gate ====
    print("\nGroup 6: _strip_role_alternation_placeholders — NO-OP gate (KI#84)")

    fn_body = _module_function_body_src(lp_tree, "_strip_role_alternation_placeholders")
    _result(
        "G6.1 _strip_role_alternation_placeholders function found",
        fn_body is not None,
        "function body found via AST",
    )

    if fn_body:
        # ast.unparse may emit 'bool = False' or 'bool=False' — accept both.
        _result(
            "G6.2 function accepts 'requires_role_alternation: bool = False' kwarg",
            "requires_role_alternation: bool = False" in fn_body
            or "requires_role_alternation: bool=False" in fn_body,
            "keyword-only arg (after *) — caller must name it explicitly",
        )

        # G6.3: 'if requires_role_alternation:' must appear BEFORE the Phase 1
        # strip loop. ast.unparse DROPS comments, so we check code structure:
        # the early-return ``return messages`` inside the if block must come
        # BEFORE the ``for msg in messages:`` loop (which is Phase 1).
        if_idx = fn_body.find("if requires_role_alternation:")
        loop_idx = fn_body.find("for msg in messages:")
        _result(
            "G6.3 function checks 'if requires_role_alternation:' BEFORE strip loop",
            if_idx != -1 and loop_idx != -1 and if_idx < loop_idx,
            f"if@{if_idx} < for@{loop_idx} — early return path skips Phase 1+2 entirely",
        )

        _result(
            "G6.4 NO-OP path returns input list unchanged (return messages)",
            "return messages" in fn_body,
            "input list returned as-is when flag is True",
        )

        # G6.5 + G6.6 + G6.7 + G6.8: ast.unparse DROPS comments, so we use
        # raw source text (lp_src) for comment-based assertions instead of
        # the unparsed function body.
        _result(
            "G6.5 NO-OP path logs '[KI#84]' debug message (raw source)",
            "[KI#84]" in lp_src and "requires_role_alternation=True" in lp_src,
            "diagnostic log line for debugging Mistral-family behavior",
        )

        # Regression: KI#80 strip logic still present (Phase 1 comment).
        _result(
            "G6.6 regression: KI#80 strip logic still present (Phase 1 comment)",
            "Phase 1: strip placeholder messages" in lp_src,
            "KI#80 behavior preserved when flag is False",
        )

        _result(
            "G6.7 regression: KI#80 merge logic still present (Phase 2 comment)",
            "Phase 2: merge consecutive same-role messages" in lp_src,
            "same-role merge preserved when flag is False",
        )

        _result(
            "G6.8 regression: '[KI#80] stripped' log message still present (raw source)",
            "[KI#80] stripped" in lp_src,
            "KI#80 diagnostic log line preserved",
        )

    # ==== Group 7: direct functional test of the strip helper ====
    print("\nGroup 7: _strip_role_alternation_placeholders — direct functional tests")

    sys.path.insert(0, str(REPO))
    try:
        # Stub heavy modules so LocalProvider can be imported.
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

        from app.utils.ai_clients.providers.local_provider import (
            _strip_role_alternation_placeholders,
            LocalProvider,
        )

        # Build a canonical Mistral-breaking prompt:
        #   system → user(placeholder) → assistant(history) → user(input)
        # This is exactly what prompt_engine.py produces per the user log.
        messages_with_placeholder = [
            {"role": "system", "content": "You are Vivy."},
            {"role": "user", "content": "[conversation continued]"},
            {"role": "assistant", "content": "*nods politely*"},
            {"role": "user", "content": "hello"},
        ]

        # G7.1: requires_role_alternation=True → NO-OP, placeholder preserved
        out_true = _strip_role_alternation_placeholders(
            messages_with_placeholder,
            requires_role_alternation=True,
        )
        _result(
            "G7.1 flag=True → returns 4 messages (placeholder preserved)",
            len(out_true) == 4,
            f"got {len(out_true)} messages — KI#84 NO-OP",
        )
        _result(
            "G7.2 flag=True → placeholder message still present",
            any(m.get("content") == "[conversation continued]" for m in out_true),
            "alternation invariant preserved for Mistral Jinja",
        )
        _result(
            "G7.3 flag=True → alternation correct (system,user,assistant,user)",
            [m["role"] for m in out_true] == ["system", "user", "assistant", "user"],
            "Jinja raise_exception guard would NOT fire",
        )
        _result(
            "G7.4 flag=True → input list is the SAME object (no copy)",
            out_true is messages_with_placeholder,
            "early return path — no list construction overhead",
        )

        # G7.5: requires_role_alternation=False → KI#80 strip active
        out_false = _strip_role_alternation_placeholders(
            messages_with_placeholder,
            requires_role_alternation=False,
        )
        _result(
            "G7.5 flag=False → returns 3 messages (placeholder stripped)",
            len(out_false) == 3,
            f"got {len(out_false)} messages — KI#80 strip active",
        )
        _result(
            "G7.6 flag=False → placeholder removed",
            not any(m.get("content") == "[conversation continued]" for m in out_false),
            "Llama-3-8B echo fix preserved",
        )
        _result(
            "G7.7 flag=False → resulting sequence is system,assistant,user",
            [m["role"] for m in out_false] == ["system", "assistant", "user"],
            "KI#80 behavior — would violate Mistral Jinja but acceptable for Llama-3",
        )

        # G7.8: default (no kwarg) → KI#80 strip active (back-compat)
        out_default = _strip_role_alternation_placeholders(messages_with_placeholder)
        _result(
            "G7.8 default (no kwarg) → KI#80 strip active (3 messages)",
            len(out_default) == 3,
            "iter-101 default preserved — non-Mistral models unaffected",
        )

        # G7.9: no placeholder in messages → no-op regardless of flag
        messages_no_placeholder = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        out_no_ph_true = _strip_role_alternation_placeholders(
            messages_no_placeholder, requires_role_alternation=True
        )
        out_no_ph_false = _strip_role_alternation_placeholders(
            messages_no_placeholder, requires_role_alternation=False
        )
        _result(
            "G7.9 no placeholder → both flags return 2 messages unchanged",
            len(out_no_ph_true) == 2 and len(out_no_ph_false) == 2,
            "function is a no-op when there's nothing to strip",
        )

        # G7.10: LocalProvider instantiation with the new kwarg
        p = LocalProvider(requires_role_alternation=True)
        _result(
            "G7.10 LocalProvider(requires_role_alternation=True) instantiates",
            p._requires_role_alternation is True,
            f"got {p._requires_role_alternation!r}",
        )

        p_false = LocalProvider(requires_role_alternation=False)
        _result(
            "G7.11 LocalProvider(requires_role_alternation=False) instantiates",
            p_false._requires_role_alternation is False,
            f"got {p_false._requires_role_alternation!r}",
        )

        # G7.12: default (no kwarg) → False (back-compat)
        p_default = LocalProvider()
        _result(
            "G7.12 LocalProvider() default → _requires_role_alternation=False",
            p_default._requires_role_alternation is False,
            "iter-108 default preserved for non-Mistral callers",
        )

    except Exception as e:
        _result(
            "G7 direct functional tests",
            False,
            f"import or call failed: {e!r}",
        )
    finally:
        sys.path.pop(0)

    # ==== Group 8: 3 call sites updated + regression ====
    print("\nGroup 8: 3 call sites pass self._requires_role_alternation")

    gs_body = _method_body_src(lp_tree, "LocalProvider", "generate_stream")
    gsum_body = _method_body_src(lp_tree, "LocalProvider", "generate_summary")
    g_body = _method_body_src(lp_tree, "LocalProvider", "generate")

    # All 3 methods must call the helper with the kwarg.
    _result(
        "G8.1 generate_stream passes requires_role_alternation=self._requires_role_alternation",
        gs_body is not None
        and "requires_role_alternation=self._requires_role_alternation" in gs_body,
        "kwarg forwarded from instance attribute",
    )
    _result(
        "G8.2 generate_summary passes requires_role_alternation=self._requires_role_alternation",
        gsum_body is not None
        and "requires_role_alternation=self._requires_role_alternation" in gsum_body,
        "kwarg forwarded from instance attribute",
    )
    _result(
        "G8.3 generate passes requires_role_alternation=self._requires_role_alternation",
        g_body is not None
        and "requires_role_alternation=self._requires_role_alternation" in g_body,
        "kwarg forwarded from instance attribute",
    )

    # All 3 must still call the helper (KI#80 entry point preserved).
    _result(
        "G8.4 regression: generate_stream still calls _strip_role_alternation_placeholders",
        gs_body is not None and "_strip_role_alternation_placeholders(" in gs_body,
        "KI#80 entry point preserved",
    )
    _result(
        "G8.5 regression: generate_summary still calls _strip_role_alternation_placeholders",
        gsum_body is not None and "_strip_role_alternation_placeholders(" in gsum_body,
        "KI#80 entry point preserved",
    )
    _result(
        "G8.6 regression: generate still calls _strip_role_alternation_placeholders",
        g_body is not None and "_strip_role_alternation_placeholders(" in g_body,
        "KI#80 entry point preserved",
    )

    # ==== Group 9: file syntax + sanity ====
    print("\nGroup 9: file syntax + sanity checks")

    _result("G9.1 template_detector.py syntax OK", True)
    _result("G9.2 ai_factory.py syntax OK", True)
    _result("G9.3 local_provider.py syntax OK", True)

    # No duplicate _strip_role_alternation_placeholders definitions.
    fn_count = lp_src.count("def _strip_role_alternation_placeholders(")
    _result(
        "G9.4 no duplicate _strip_role_alternation_placeholders",
        fn_count == 1,
        f"count={fn_count} — additive-edit rule preserved",
    )

    # ``requires_role_alternation: bool = False`` appears in 3 places:
    #   1. ``CapabilityMap`` field definition (template_detector.py)
    #   2. ``LocalProvider.__init__`` signature (local_provider.py)
    #   3. ``_strip_role_alternation_placeholders`` signature (local_provider.py)
    td_field_count = td_src.count("requires_role_alternation: bool = False")
    lp_field_count = lp_src.count("requires_role_alternation: bool = False")
    total_field_count = td_field_count + lp_field_count
    _result(
        "G9.5 'requires_role_alternation: bool = False' appears in 3 places (CapabilityMap + __init__ + strip helper)",
        total_field_count == 3,
        f"total={total_field_count} — td={td_field_count} (CapabilityMap), lp={lp_field_count} (__init__ + strip helper signatures)",
    )

    # KI#84 comment block present in local_provider.py.
    _result(
        "G9.6 KI#84 comment block present in local_provider.py",
        "KI#84" in lp_src and "iter-109" in lp_src,
        "documents the Mistral-family exception",
    )

    # KI#84 comment present in template_detector.py.
    _result(
        "G9.7 KI#84 comment present in template_detector.py",
        "KI#84" in td_src and "iter-109" in td_src,
        "documents the CapabilityMap field + detection logic",
    )

    # KI#84 comment present in ai_factory.py.
    _result(
        "G9.8 KI#84 comment present in ai_factory.py",
        "KI#84" in af_src and "iter-109" in af_src,
        "documents the forwarding path",
    )

    # iter-108 KI#83 fairseq stub unrelated — text_to_speech.py NOT touched.
    tts_path = REPO / "app" / "utils" / "text_to_speech.py"
    if tts_path.exists():
        tts_stat = tts_path.stat()
        # We didn't touch this file; just verify it still parses (sanity).
        try:
            ast.parse(tts_path.read_text(encoding="utf-8"))
            _result("G9.9 regression: text_to_speech.py (iter-108 KI#83) still parses", True)
        except Exception as e:
            _result(
                "G9.9 regression: text_to_speech.py (iter-108 KI#83) still parses",
                False,
                f"parse error: {e!r}",
            )
    else:
        _result("G9.9 regression: text_to_speech.py present", False, "file missing")

    # Line count sanity — iter-109 adds ~25 lines to local_provider.py
    # (kwarg + storage + 3 updated call sites + KI#84 comment block).
    # iter-108 baseline was 936 lines (per repo file size); +50 upper bound
    # accommodates the new docstring expansion.
    lp_line_count = len(lp_src.splitlines())
    _result(
        "G9.10 local_provider.py line count reasonable",
        936 <= lp_line_count <= 1050,
        f"{lp_line_count} lines (iter-108 baseline 936; +~25 expected)",
    )

    td_line_count = len(td_src.splitlines())
    _result(
        "G9.11 template_detector.py line count reasonable",
        1816 <= td_line_count <= 1900,
        f"{td_line_count} lines (iter-108 baseline 1816; +~30 expected)",
    )

    af_line_count = len(af_src.splitlines())
    _result(
        "G9.12 ai_factory.py line count reasonable",
        249 <= af_line_count <= 280,
        f"{af_line_count} lines (iter-108 baseline 249; +~15 expected)",
    )

    print(f"\n=== Summary: {PASS} PASS, {FAIL} FAIL ===")
    sys.exit(1 if FAIL else 0)


def _module_function_body_src(tree: ast.Module, fn_name: str) -> str | None:
    """Return unparsed source of a module-level function (not inside a class)."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            return ast.unparse(node)
    return None


if __name__ == "__main__":
    main()
