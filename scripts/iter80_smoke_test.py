#!/usr/bin/env python3
"""iter-80 v2 smoke tests — KI#60 per-request reasoning sub-cap.

Tests cover the iter-80 v2 implementation of the per-request reasoning
sub-cap (``reasoning_budget_tokens``) in ``local_provider.py`` and the
``reasoning_mode`` kwarg wiring in ``ai_factory.py``.

iter-80 v2 supersedes the iter-80 paper iteration (which was never
committed — only existed as a zip on tmpfiles.org).  KI#60 is RE-OPENED
at the start of this iteration (because iter-80 paper never landed in
the repo) and CLOSED at the end (because iter-80 v2 implements the
fix correctly per the 12-resolutions table from the iter-80 v2 plan).

Key design decisions verified by these tests:
  1. Canonical field name ``reasoning_budget_tokens`` (NOT
     ``thinking_budget_tokens`` — that's a back-compat alias for the
     deprecated PR #17750, not guaranteed on intermediate builds).
     Resolution #1 from the 12-resolutions table.
  2. Sub-cap semantics (NOT split): the model still sees ``max_tokens``
     as the total cap; ``reasoning_budget_tokens`` overrides the CLI
     ``--reasoning-budget`` default for THIS request only.
  3. ``_compute_reasoning_budget`` floor is 256, fraction is 0.6.
     ``max_tokens <= 0`` returns 0 (no sub-cap).
  4. ``reasoning_budget_message`` intentionally NOT injected (Variant B
     from the iter-80 v2 plan).  Requires bundled llama-server >= PR
     #22740 (issue #22717 regression avoidance).  Bundled binaries are
     gitignored (§4) and not present in the clone, so version cannot
     be verified — Variant B chosen as the safer default.  Will be
     re-enabled in iter-80.1 after bundled binary update.
  5. ``_build_extra_body`` returns None when both advanced_params is
     empty AND reasoning sub-cap is not applicable (reasoning_mode off
     OR max_tokens <= 0).  This preserves iter-22 behavior when
     reasoning_mode is off (no extra_body sent).
  6. All 3 generation methods (``generate_stream``, ``generate``,
     ``generate_summary``) use the unified ``_build_extra_body`` helper.
     The old per-method ``if self.advanced_params:`` pattern is GONE
     from all 3.
  7. ``ai_factory.py`` reads ``reasoning_mode`` from
     ``settings.json::main_settings.reasoning_mode`` (same checkbox
     that controls the CLI ``--reasoning off`` flag, iter-29.1) and
     forwards it to ``LocalProvider``.
  8. Regression: iter-78 KI#59 (consume-not-yield) is preserved —
     reasoning_content is still consumed via getattr + continue, not
     yielded to the caller.
  9. Regression: iter-79 REASONING_EXHAUSTED warning is preserved.

Uses pure source inspection (same pattern as iter-74/75/76/77/78/79
smoke tests — avoids importing PyQt6 or the openai package which can't
be loaded in the Linux test env).

Run:  python scripts/iter80_smoke_test.py
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
DEEPSEEK_PROVIDER = REPO / "app" / "utils" / "ai_clients" / "providers" / "deepseek_provider.py"


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
    print("=== iter-80 v2 smoke tests ===\n")

    # ==== Group 1: class constants + __init__ kwarg ====
    print("Group 1: class constants + __init__ reasoning_mode kwarg")
    lp_src = LOCAL_PROVIDER.read_text(encoding="utf-8")
    lp_tree = ast.parse(lp_src)

    _result("G1.1 local_provider.py parses cleanly", True)

    cls_body = _class_body_src(lp_tree, "LocalProvider")
    _result(
        "G1.2 LocalProvider class body found",
        cls_body is not None,
        "AST traversal found the class",
    )

    _result(
        "G1.3 _REASONING_BUDGET_FRACTION = 0.6 constant present",
        "_REASONING_BUDGET_FRACTION = 0.6" in lp_src,
        "sub-cap = 60% of max_tokens for thinking",
    )

    _result(
        "G1.4 _REASONING_BUDGET_MIN = 256 constant present",
        "_REASONING_BUDGET_MIN = 256" in lp_src,
        "floor — models need some thinking room",
    )

    _result(
        'G1.5 _REASONING_BUDGET_MESSAGE = "Final Answer:" constant present',
        '_REASONING_BUDGET_MESSAGE = "Final Answer:"' in lp_src
        or "_REASONING_BUDGET_MESSAGE = 'Final Answer:'" in lp_src,
        "s1 paper pattern, arXiv:2501.19393 — reserved for iter-80.1",
    )

    # __init__ must accept reasoning_mode kwarg.
    init_body = _method_body_src(lp_tree, "LocalProvider", "__init__")
    _result(
        "G1.6 __init__ method found",
        init_body is not None,
        "method body found via AST",
    )

    if init_body:
        _result(
            "G1.7 __init__ signature includes reasoning_mode: bool = False",
            "reasoning_mode: bool = False" in init_body
            or "reasoning_mode: bool=False" in init_body,
            "kwarg added per iter-80 v2 plan",
        )

        _result(
            "G1.8 __init__ stores self._reasoning_mode = bool(reasoning_mode)",
            "self._reasoning_mode = bool(reasoning_mode)" in init_body,
            "stored as bool — normalises None/0/1 → False/True",
        )

    # ==== Group 2: _compute_reasoning_budget helper ====
    print("\nGroup 2: _compute_reasoning_budget helper — boundary cases")

    crb_body = _method_body_src(lp_tree, "LocalProvider", "_compute_reasoning_budget")
    _result(
        "G2.1 _compute_reasoning_budget method exists",
        crb_body is not None,
        "method body found via AST",
    )

    if crb_body:
        # max_tokens <= 0 returns 0 (no sub-cap).
        _result(
            "G2.2 _compute_reasoning_budget returns 0 when max_tokens <= 0",
            "max_tokens <= 0" in crb_body and "return 0" in crb_body,
            "no sub-cap — thinking unrestricted up to max_tokens",
        )

        # max(_REASONING_BUDGET_MIN, int(max_tokens * FRACTION))
        # iter-84 update: iter-82 changed the fraction reference from the
        # class-level ``_REASONING_BUDGET_FRACTION`` constant to the
        # per-instance ``self._reasoning_budget_fraction`` attribute (so
        # the user-controllable UI slider takes effect).  The class
        # constant is still present as the default fallback when the kwarg
        # is None.  This assertion now accepts EITHER form — both are
        # valid; iter-82 uses the instance attribute, pre-iter-82 used the
        # class constant.
        _result(
            "G2.3 _compute_reasoning_budget uses max(MIN, int(max_tokens * FRACTION))",
            "max(self._REASONING_BUDGET_MIN" in crb_body
            and ("int(max_tokens * self._REASONING_BUDGET_FRACTION)" in crb_body
                 or "int(max_tokens * self._reasoning_budget_fraction)" in crb_body),
            "floor + fraction — always >= 256 when max_tokens > 0 (iter-82: instance attr or class const)",
        )

    # Boundary case verification via direct call (mock-free, the method
    # has no external deps — just arithmetic on self).
    if crb_body:
        # Stub heavy modules so LocalProvider can be imported without
        # PyQt6 / openai (same pattern as iter-77/78 smoke tests).
        # Use a permissive stub that accepts any constructor args and
        # supports attribute access (covers httpx.Timeout(5.0, connect=5.0),
        # httpx.AsyncClient(timeout=...), openai.AsyncOpenAI, etc.).
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

        # Provide a minimal stub for BaseAIProvider so the class can be
        # defined without the real one.
        class _StubBase:
            pass

        sys.modules["app.utils.ai_clients.base_provider"].BaseAIProvider = _StubBase

        # Now import the provider module and instantiate.
        sys.path.insert(0, str(REPO))
        try:
            from app.utils.ai_clients.providers.local_provider import LocalProvider

            p = LocalProvider(reasoning_mode=True)

            # max_tokens=0 → 0
            r0 = p._compute_reasoning_budget(0)
            _result(
                "G2.4 _compute_reasoning_budget(0) == 0",
                r0 == 0,
                f"got {r0}",
            )

            # max_tokens=-5 → 0 (negative also short-circuits)
            r_neg = p._compute_reasoning_budget(-5)
            _result(
                "G2.5 _compute_reasoning_budget(-5) == 0",
                r_neg == 0,
                f"got {r_neg}",
            )

            # max_tokens=100 → max(256, int(100*0.6)=60) = 256 (floor wins)
            r100 = p._compute_reasoning_budget(100)
            _result(
                "G2.6 _compute_reasoning_budget(100) == 256 (floor wins)",
                r100 == 256,
                f"got {r100} — int(100*0.6)=60 < 256 → floor",
            )

            # max_tokens=427 → max(256, int(427*0.6)=256) = 256 (boundary)
            r427 = p._compute_reasoning_budget(427)
            _result(
                "G2.7 _compute_reasoning_budget(427) == 256 (boundary — fraction ties floor)",
                r427 == 256,
                f"got {r427} — int(427*0.6)=256 == 256 → 256",
            )

            # max_tokens=428 → max(256, int(428*0.6)=256) = 256 (still floor)
            r428 = p._compute_reasoning_budget(428)
            _result(
                "G2.8 _compute_reasoning_budget(428) == 256 (still floor)",
                r428 == 256,
                f"got {r428} — int(428*0.6)=256 == 256 → 256",
            )

            # max_tokens=1000 → max(256, int(1000*0.6)=600) = 600
            r1000 = p._compute_reasoning_budget(1000)
            _result(
                "G2.9 _compute_reasoning_budget(1000) == 600",
                r1000 == 600,
                f"got {r1000} — int(1000*0.6)=600 > 256 → 600",
            )

            # max_tokens=4096 → max(256, int(4096*0.6)=2457) = 2457
            r4096 = p._compute_reasoning_budget(4096)
            _result(
                "G2.10 _compute_reasoning_budget(4096) == 2457",
                r4096 == 2457,
                f"got {r4096} — int(4096*0.6)=2457 > 256 → 2457",
            )

            # max_tokens=2048 → max(256, int(2048*0.6)=1228) = 1228
            # (this is the recommended max_tokens for thinking models per
            # iter-78 stop-point note — sub-cap leaves 820 for the answer)
            r2048 = p._compute_reasoning_budget(2048)
            _result(
                "G2.11 _compute_reasoning_budget(2048) == 1228 (recommended max_tokens leaves 820 for answer)",
                r2048 == 1228,
                f"got {r2048} — 2048-1228=820 visible-answer tokens",
            )

        except Exception as e:
            _result(
                "G2.4-G2.11 _compute_reasoning_budget direct-call tests",
                False,
                f"import or call failed: {e!r}",
            )
        finally:
            sys.path.pop(0)

    # ==== Group 3: _build_extra_body helper ====
    print("\nGroup 3: _build_extra_body helper — field name + Variant B deferral")

    beb_body = _method_body_src(lp_tree, "LocalProvider", "_build_extra_body")
    _result(
        "G3.1 _build_extra_body method exists",
        beb_body is not None,
        "method body found via AST",
    )

    if beb_body:
        # Must use canonical field name reasoning_budget_tokens (NOT
        # thinking_budget_tokens — back-compat alias, not guaranteed on
        # intermediate builds per resolution #1).  ast.unparse may use
        # single or double quotes — check both.
        _result(
            "G3.2 _build_extra_body injects canonical 'reasoning_budget_tokens' field",
            'extra["reasoning_budget_tokens"]' in beb_body
            or "extra['reasoning_budget_tokens']" in beb_body,
            "canonical name per PR #22740 (resolution #1)",
        )

        # Must NOT inject the deprecated alias thinking_budget_tokens.
        _result(
            "G3.3 _build_extra_body does NOT inject deprecated 'thinking_budget_tokens' alias",
            "thinking_budget_tokens" not in beb_body,
            "back-compat alias for PR #17750 — not guaranteed on intermediate builds",
        )

        # iter-80.1 SUPERSEDES Variant B: reasoning_budget_message is now
        # OPT-IN via the ``reasoning_budget_message_enabled`` kwarg (default
        # False = Variant B preserved).  When True AND reasoning_mode is True
        # AND max_tokens > 0, the message is injected.  Pre-iter-80.1 this
        # test asserted the assignment was ABSENT (Variant B); iter-84
        # updates the assertion to check that the assignment is CONDITIONAL
        # (gated on ``self._reasoning_budget_message_enabled``) — matches
        # iter-80.1 behavior.  See STATUS.md iter-80.1 for the opt-in rationale.
        _result(
            "G3.4 _build_extra_body injects reasoning_budget_message CONDITIONALLY (iter-80.1 opt-in)",
            ('extra["reasoning_budget_message"]' in beb_body
             or "extra['reasoning_budget_message']" in beb_body)
            and "self._reasoning_budget_message_enabled" in beb_body,
            "gated on reasoning_budget_message_enabled flag (Variant B default preserved)",
        )

        # Must respect self._reasoning_mode — only inject when on.
        _result(
            "G3.5 _build_extra_body gates on self._reasoning_mode",
            "self._reasoning_mode" in beb_body and "max_tokens > 0" in beb_body,
            "sub-cap only when reasoning_mode on AND max_tokens > 0",
        )

        # Must start from a copy of advanced_params (defensive copy).
        _result(
            "G3.6 _build_extra_body starts from dict(self.advanced_params) (defensive copy)",
            "dict(self.advanced_params)" in beb_body,
            "preserves iter-22 advanced sampling params",
        )

        # Must return None when both advanced_params is empty AND reasoning
        # sub-cap is not applicable.
        _result(
            "G3.7 _build_extra_body returns None when nothing to inject",
            "return extra if extra else None" in beb_body,
            "preserves iter-22 behavior when reasoning_mode off + no advanced_params",
        )

    # ==== Group 4: 3 call sites use unified _build_extra_body ====
    print("\nGroup 4: 3 call sites use unified _build_extra_body (replaces iter-22 pattern)")

    # Old pattern must be GONE from all 3 methods.
    gs_body = _method_body_src(lp_tree, "LocalProvider", "generate_stream")
    gsum_body = _method_body_src(lp_tree, "LocalProvider", "generate_summary")
    g_body = _method_body_src(lp_tree, "LocalProvider", "generate")

    _result(
        "G4.1 generate_stream uses _build_extra_body",
        gs_body is not None and "_build_extra_body(payload['max_tokens'])" in gs_body,
        "replaces iter-22 if-self.advanced_params pattern",
    )

    _result(
        "G4.2 generate_stream no longer has raw 'if self.advanced_params: payload[\"extra_body\"]'",
        gs_body is not None
        and "if self.advanced_params:\n            payload[\"extra_body\"] = self.advanced_params" not in gs_body,
        "iter-22 pattern replaced by unified helper",
    )

    _result(
        "G4.3 generate uses _build_extra_body",
        g_body is not None and "_build_extra_body(payload['max_tokens'])" in g_body,
        "replaces iter-22 if-self.advanced_params pattern",
    )

    _result(
        "G4.4 generate no longer has raw 'if self.advanced_params: payload[\"extra_body\"]'",
        g_body is not None
        and "if self.advanced_params:\n            payload[\"extra_body\"] = self.advanced_params" not in g_body,
        "iter-22 pattern replaced by unified helper",
    )

    _result(
        "G4.5 generate_summary uses _build_extra_body (NEW in iter-80 v2)",
        gsum_body is not None and "_build_extra_body(payload['max_tokens'])" in gsum_body,
        "iter-22 did NOT inject advanced_params here — iter-80 v2 adds unified helper for symmetry",
    )

    # ==== Group 5: regression — iter-78 KI#59 consume-not-yield preserved ====
    print("\nGroup 5: regression — iter-78 KI#59 (consume-not-yield) preserved")

    _result(
        "G5.1 generate_stream still consumes reasoning via getattr",
        gs_body is not None
        and ('getattr(delta, "reasoning_content", None)' in gs_body
             or "getattr(delta, 'reasoning_content', None)" in gs_body),
        "KI#59 — reasoning_content extracted for diagnostics, not yielded",
    )

    _result(
        "G5.2 generate_stream still uses `continue` to consume reasoning",
        gs_body is not None and "reasoning_chunks += 1" in gs_body and "continue" in gs_body,
        "reasoning is counted then skipped — never yielded",
    )

    _result(
        "G5.3 generate_stream still yields only delta.content",
        gs_body is not None and "yield delta.content" in gs_body,
        "ONLY actual text content is yielded to the caller",
    )

    _result(
        "G5.4 generate_summary still consumes reasoning via getattr + continue",
        gsum_body is not None
        and ('getattr(delta, "reasoning_content", None)' in gsum_body
             or "getattr(delta, 'reasoning_content', None)" in gsum_body)
        and "continue" in gsum_body,
        "KI#59 — summary path consumes reasoning silently too",
    )

    # ==== Group 6: regression — iter-79 REASONING_EXHAUSTED warning preserved ====
    print("\nGroup 6: regression — iter-79 REASONING_EXHAUSTED warning preserved")

    _result(
        "G6.1 REASONING_EXHAUSTED warning string still present in generate_stream",
        gs_body is not None and "REASONING_EXHAUSTED" in gs_body,
        "logged when text_chunks=0 and reasoning_chunks>0",
    )

    _result(
        "G6.2 warning condition still checks text_chunks == 0",
        gs_body is not None and "text_chunks == 0" in gs_body,
        "detects max_tokens exhaustion on reasoning",
    )

    _result(
        "G6.3 warning condition still checks reasoning_chunks > 0",
        gs_body is not None and "reasoning_chunks > 0" in gs_body,
        "avoids false positive when stream produced nothing at all",
    )

    _result(
        "G6.4 warning still uses logger.warning",
        gs_body is not None and "logger.warning(" in gs_body,
        "visible at default log level (INFO+)",
    )

    _result(
        "G6.5 warning still includes max_tokens value",
        gs_body is not None and "payload.get('max_tokens')" in gs_body,
        "user can see current max_tokens to know how much to increase",
    )

    # ==== Group 7: ai_factory.py wiring ====
    print("\nGroup 7: ai_factory.py — reasoning_mode kwarg wiring")

    af_src = AI_FACTORY.read_text(encoding="utf-8")
    af_tree = ast.parse(af_src)

    _result("G7.1 ai_factory.py parses cleanly", True)

    _result(
        "G7.2 ai_factory reads reasoning_mode from config_settings",
        'config_settings.get_main_setting("reasoning_mode")' in af_src,
        "same checkbox that controls CLI --reasoning off flag (iter-29.1)",
    )

    _result(
        "G7.3 ai_factory normalises None → False via 'or False'",
        'or False' in af_src and "reasoning_mode" in af_src,
        "get_main_setting returns None when key absent — bool(None or False) == False",
    )

    _result(
        "G7.4 ai_factory forwards reasoning_mode to LocalProvider",
        "reasoning_mode=reasoning_mode" in af_src,
        "kwarg passed through to LocalProvider.__init__",
    )

    # ==== Group 8: deepseek_provider.py UNCHANGED (reference) ====
    print("\nGroup 8: deepseek_provider.py UNCHANGED (iter-80 v2 did not touch it)")

    ds_src = DEEPSEEK_PROVIDER.read_text(encoding="utf-8")
    ds_tree = ast.parse(ds_src)

    _result("G8.1 deepseek_provider.py parses cleanly", True)

    # deepseek_provider must NOT have reasoning_budget_tokens (it's
    # llama.cpp-specific — DeepSeek API doesn't expose this field).
    _result(
        "G8.2 deepseek_provider does NOT inject reasoning_budget_tokens",
        "reasoning_budget_tokens" not in ds_src,
        "llama.cpp-specific field — DeepSeek API uses different mechanism",
    )

    # deepseek_provider must NOT have _build_extra_body (iter-80 v2 is
    # LocalProvider-only).
    _result(
        "G8.3 deepseek_provider does NOT have _build_extra_body helper",
        "_build_extra_body" not in ds_src,
        "iter-80 v2 is LocalProvider-only — DeepSeek parity deferred (iter-83)",
    )

    # ==== Group 9: file syntax + sanity ====
    print("\nGroup 9: file syntax + sanity checks")

    _result("G9.1 local_provider.py syntax OK", True)
    _result("G9.2 ai_factory.py syntax OK", True)

    # No duplicate methods (additive-edit rule, §4 rule #10).
    gs_count = lp_src.count("async def generate_stream(")
    _result(
        "G9.3 no duplicate generate_stream",
        gs_count == 1,
        f"count={gs_count} — additive-edit rule preserved",
    )

    gsum_count = lp_src.count("async def generate_summary(")
    _result(
        "G9.4 no duplicate generate_summary",
        gsum_count == 1,
        f"count={gsum_count} — additive-edit rule preserved",
    )

    g_count = lp_src.count("async def generate(")
    _result(
        "G9.5 no duplicate generate",
        g_count == 1,
        f"count={g_count} — additive-edit rule preserved",
    )

    crb_count = lp_src.count("def _compute_reasoning_budget(")
    _result(
        "G9.6 no duplicate _compute_reasoning_budget",
        crb_count == 1,
        f"count={crb_count} — additive-edit rule preserved",
    )

    beb_count = lp_src.count("def _build_extra_body(")
    _result(
        "G9.7 no duplicate _build_extra_body",
        beb_count == 1,
        f"count={beb_count} — additive-edit rule preserved",
    )

    # KI#60 comment must be present (documents the iter-80 v2 approach).
    _result(
        "G9.8 KI#60 comment block present in local_provider.py",
        "KI#60" in lp_src and "iter-80 v2" in lp_src,
        "documents the per-request reasoning sub-cap + Variant B deferral",
    )

    # iter-80.1 deferral note must be present (explains why message not sent).
    _result(
        "G9.9 iter-80.1 deferral note present (Variant B)",
        "iter-80.1" in lp_src and "Variant B" not in lp_src or "iter-80.1" in lp_src,
        "documents why reasoning_budget_message is deferred",
    )

    # Line count sanity — iter-84 widened the range from [580, 720] to
    # [580, 850] to accommodate iter-80.1 (669 lines) + iter-82 (734 lines).
    # Line-count is a brittle assertion (file grows per iteration); the
    # upper bound is a sanity check against accidental bloat.
    line_count = len(lp_src.splitlines())
    _result(
        "G9.10 local_provider.py line count reasonable (relaxed iter-84)",
        580 <= line_count <= 850,
        f"{line_count} lines (iter-82 baseline 734; range widened from [580,720])",
    )

    print(f"\n=== Summary: {PASS} PASS, {FAIL} FAIL ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
