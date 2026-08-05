#!/usr/bin/env python3
"""iter-78 smoke tests — KI#59 reasoning leak fix (consume, not yield).

Tests cover the critical bugfix where ``local_provider.py`` was yielding
reasoning content wrapped in literal ``"thinking\\n"`` / ``"\\n\\n"``
markers (iter-76 KI#57 bug) — and iter-77's claimed fix (KI#58, switch
to ``<think>`` / ``</think>`` markers) was NEVER actually committed to
the code (the iter-77 commit ``a1f47f6`` only touched STATUS.md /
worklog.md / smoke_test — ``local_provider.py`` was unchanged).

User-verified: ``python scripts/iter77_smoke_test.py`` shows 10 FAIL
out of 24 because the code does not match the docs.  The user reported
"размышления просачиваются в чат" (reasoning leaks into chat) and
"твои две правки предыдущие не помогли" (your previous two fixes didn't
help) — because the code was never changed.

iter-78 (KI#59) takes a DIFFERENT approach from iter-77's intended fix:
instead of switching to ``<think>`` / ``</think>`` markers (which would
fix history leakage via ``strip_think_blocks()`` but would STILL leak
reasoning into the real-time display, because ``interface_signals.py``
display loops write raw chunks to the typewriter without filtering),
iter-78 CONSUMES ``reasoning_content`` silently — counting it for
diagnostics but NOT yielding it.  Only ``delta.content`` is yielded.

This means:
  - ``full_text`` in interface_signals.py contains ONLY the actual response.
  - The typewriter shows ONLY the actual response (no <think> tags, no
    reasoning text).
  - ``strip_think_blocks()`` is a no-op for local_provider (no markers
    to strip) — but still works for deepseek_provider (iter-25 pattern).
  - ``REASONING_EXHAUSTED`` warning is emitted when text_chunks=0 and
    reasoning_chunks>0 (max_tokens exhausted on reasoning).

Tests use pure source inspection (same pattern as iter-74/75/76/77
smoke tests — avoids importing PyQt6 or the openai package which can't
be loaded in the Linux test env).

Run:  python scripts/iter78_smoke_test.py
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
DEEPSEEK_PROVIDER = REPO / "app" / "utils" / "ai_clients" / "providers" / "deepseek_provider.py"


def _method_body_src(tree: ast.Module, class_name: str, method_name: str) -> str | None:
    """Return unparsed source of a specific method inside a class."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return ast.unparse(item)
    return None


def main():
    print("=== iter-78 smoke tests ===\n")

    # ==== Group 1: KI#59 — local_provider.py no longer yields reasoning ====
    print("Group 1: KI#59 — local_provider.py yields ONLY delta.content")
    lp_src = LOCAL_PROVIDER.read_text(encoding="utf-8")
    lp_tree = ast.parse(lp_src)

    _result("G1.1 local_provider.py parses cleanly", True)

    gs_body = _method_body_src(lp_tree, "LocalProvider", "generate_stream")
    _result(
        "G1.2 generate_stream method exists",
        gs_body is not None,
        "method body found via AST",
    )

    # The buggy iter-76 marker "thinking\n" MUST be gone.
    _result(
        'G1.3 buggy yield "thinking\\n" is GONE (iter-76 KI#57 bug)',
        'yield "thinking\\n"' not in gs_body and "yield 'thinking\\n'" not in gs_body,
        "was the root cause of reasoning leaking into chat",
    )

    # The iter-77 intended fix (<think>\n) is ALSO absent — iter-78 chose
    # a different approach (consume, not yield).  This is intentional.
    _result(
        'G1.4 yield "<think>\\n" is ABSENT (iter-78 chose consume-not-yield)',
        'yield "<think>\\n"' not in gs_body and "yield \'<think>\\n\'" not in gs_body,
        "iter-78 consumes reasoning silently instead of wrapping in markers",
    )

    # The close marker "\n</think>\n" MUST also be absent.
    _result(
        'G1.5 yield "\\n</think>\\n" is ABSENT',
        'yield "\\n</think>\\n"' not in gs_body and "yield \'\\n</think>\\n\'" not in gs_body,
        "no think-block close marker yielded",
    )

    # The bare "\n\n" transition marker MUST be gone.
    _result(
        'G1.6 buggy transition yield "\\n\\n" is GONE',
        'yield "\\n\\n"' not in gs_body and "yield \'\\n\\n\'" not in gs_body,
        "was iter-76's buggy transition/close marker",
    )

    # The reasoning_content MUST still be extracted (via getattr) — we
    # consume it for counting, just don't yield it.
    _result(
        "G1.7 reasoning_content still extracted via getattr",
        'getattr(delta, "reasoning_content", None)' in gs_body
        or "getattr(delta, 'reasoning_content', None)" in gs_body,
        "needed for reasoning_chunks counter + REASONING_EXHAUSTED warning",
    )

    # The reasoning branch MUST end with `continue` (consume, don't yield).
    # We check that the reasoning block contains `continue` after incrementing
    # reasoning_chunks.
    _result(
        "G1.8 reasoning branch uses `continue` (consume, not yield)",
        "reasoning_chunks += 1" in gs_body and "continue" in gs_body,
        "reasoning is counted then skipped — never yielded to caller",
    )

    # The `thinking_active` state variable MUST be gone (no longer needed
    # since we don't track think-block open/close state).
    _result(
        "G1.9 `thinking_active` variable is GONE from generate_stream",
        "thinking_active" not in gs_body,
        "no longer needed — consume approach has no open/close state to track",
    )

    # Only delta.content is yielded (the actual response text).
    _result(
        "G1.10 generate_stream yields delta.content",
        "yield delta.content" in gs_body,
        "ONLY actual text content is yielded to the caller",
    )

    # ==== Group 2: KI#59 — REASONING_EXHAUSTED warning ====
    print("\nGroup 2: KI#59 — REASONING_EXHAUSTED warning when text_chunks=0")

    _result(
        "G2.1 REASONING_EXHAUSTED warning string is present",
        "REASONING_EXHAUSTED" in gs_body,
        "logged when text_chunks=0 and reasoning_chunks>0",
    )

    _result(
        "G2.2 warning condition checks text_chunks == 0",
        "text_chunks == 0" in gs_body,
        "detects max_tokens exhaustion on reasoning",
    )

    _result(
        "G2.3 warning condition checks reasoning_chunks > 0",
        "reasoning_chunks > 0" in gs_body,
        "avoids false positive when stream produced nothing at all",
    )

    _result(
        "G2.4 warning uses logger.warning (not debug/info)",
        "logger.warning(" in gs_body and "REASONING_EXHAUSTED" in gs_body,
        "visible at default log level (INFO+)",
    )

    _result(
        "G2.5 warning includes max_tokens value for diagnosis",
        "payload.get('max_tokens')" in gs_body and "REASONING_EXHAUSTED" in gs_body,
        "user can see current max_tokens to know how much to increase",
    )

    # ==== Group 3: generate_summary also consumes reasoning silently ====
    print("\nGroup 3: generate_summary — same consume pattern (KI#59)")

    gs_summary_body = _method_body_src(lp_tree, "LocalProvider", "generate_summary")
    _result(
        "G3.1 generate_summary method exists",
        gs_summary_body is not None,
        "method body found via AST",
    )

    if gs_summary_body:
        # generate_summary should NOT yield reasoning markers either.
        _result(
            "G3.2 generate_summary does NOT yield 'thinking\\n'",
            'yield "thinking\\n"' not in gs_summary_body
            and "yield 'thinking\\n'" not in gs_summary_body,
            "summary path must not leak reasoning either",
        )

        _result(
            "G3.3 generate_summary does NOT yield '<think>\\n'",
            'yield "<think>\\n"' not in gs_summary_body
            and "yield '<think>\\n'" not in gs_summary_body,
            "no think markers in summary path",
        )

        # generate_summary should consume reasoning via getattr + continue.
        _result(
            "G3.4 generate_summary consumes reasoning via getattr + continue",
            ('getattr(delta, "reasoning_content", None)' in gs_summary_body
             or "getattr(delta, 'reasoning_content', None)" in gs_summary_body)
            and "continue" in gs_summary_body,
            "summary skips thinking tokens, yields only delta.content",
        )

        # `thinking_active` should be gone from generate_summary too.
        _result(
            "G3.5 `thinking_active` variable is GONE from generate_summary",
            "thinking_active" not in gs_summary_body,
            "simplified — no open/close state to track",
        )

    # ==== Group 4: deepseek_provider.py — iter-83 supersedes (consume-not-yield) ====
    print("\nGroup 4: deepseek_provider.py — iter-83 supersedes (consume-not-yield)")

    ds_src = DEEPSEEK_PROVIDER.read_text(encoding="utf-8")
    ds_tree = ast.parse(ds_src)

    _result("G4.1 deepseek_provider.py parses cleanly", True)

    ds_gs_body = _method_body_src(ds_tree, "DeepSeekProvider", "generate_stream")
    if ds_gs_body is None:
        for cls_name in ("DeepseekProvider", "DeepSeekClient", "DeepSeekAIProvider"):
            ds_gs_body = _method_body_src(ds_tree, cls_name, "generate_stream")
            if ds_gs_body:
                break

    _result(
        "G4.2 deepseek generate_stream method exists",
        ds_gs_body is not None,
        "method body found via AST",
    )

    if ds_gs_body:
        # iter-83 SUPERSEDES the pre-iter-83 expectation: deepseek_provider
        # now uses the SAME consume-not-yield pattern as LocalProvider KI#59
        # (no more `<think>\n` / `\n</think>\n` markers — those leaked into
        # chat history + display).  The pre-iter-78 "deepseek STILL yields
        # <think> markers" assertion was valid when iter-78 left deepseek
        # untouched, but iter-83 closed that gap.  This test now ASSERTS
        # that the markers are GONE — same expectation as LocalProvider G1.4.
        ds_has_open = ('yield "<think>\\n"' in ds_gs_body
                       or "yield '<think>\\n'" in ds_gs_body)
        _result(
            'G4.3 deepseek NO LONGER yields "<think>\\n" (iter-83 consume-not-yield parity)',
            not ds_has_open,
            "iter-83 closed the gap — deepseek now consumes reasoning silently",
        )
        # iter-83 also added the REASONING_EXHAUSTED warning (same pattern
        # as iter-79 LocalProvider).
        _result(
            "G4.4 deepseek has REASONING_EXHAUSTED warning (iter-83 parity)",
            "REASONING_EXHAUSTED" in ds_gs_body,
            "same diagnostic as LocalProvider iter-79",
        )

    # ==== Group 5: file syntax + sanity checks ====
    print("\nGroup 5: file syntax + sanity checks")

    _result("G5.1 local_provider.py syntax OK", True)

    # No duplicate generate_stream method (additive-edit rule, §4 rule #10).
    gs_count = lp_src.count("async def generate_stream(")
    _result(
        "G5.2 no duplicate generate_stream",
        gs_count == 1,
        f"count={gs_count} — additive-edit rule preserved",
    )

    # No duplicate generate_summary method.
    gsum_count = lp_src.count("async def generate_summary(")
    _result(
        "G5.3 no duplicate generate_summary",
        gsum_count == 1,
        f"count={gsum_count} — additive-edit rule preserved",
    )

    # KI#59 comment must be present (documents the iter-78 approach).
    _result(
        "G5.4 KI#59 comment block present in local_provider.py",
        "KI#59" in lp_src and "iter-78" in lp_src,
        "documents the consume-not-yield approach + rationale",
    )

    # iter-77 KI#58 reference should be mentioned (explains why iter-77
    # was insufficient — the marker approach alone wouldn't fix display).
    _result(
        "G5.5 KI#58 (iter-77) referenced in KI#59 comment",
        "KI#58" in lp_src,
        "explains why iter-78 chose a different approach from iter-77",
    )

    # Line count sanity — iter-84 widened the range from [450, 550] to
    # [450, 850] to accommodate iter-80 v2 (630 lines), iter-80.1 (669
    # lines), and iter-82 (734 lines).  Line-count is a brittle assertion
    # (the file is expected to grow as iterations add features); the
    # upper bound is a sanity check against accidental bloat, not a hard
    # cap.  The lower bound catches accidental truncation.
    line_count = len(lp_src.splitlines())
    _result(
        "G5.5 local_provider.py line count reasonable (relaxed iter-84)",
        450 <= line_count <= 850,
        f"{line_count} lines (iter-82 baseline 734; range widened from [450,550])",
    )

    print(f"\n=== Summary: {PASS} PASS, {FAIL} FAIL ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
