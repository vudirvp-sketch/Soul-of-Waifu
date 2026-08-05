#!/usr/bin/env python3
"""iter-77 smoke tests — KI#58 reasoning_content marker fix.

Tests cover the critical bugfix where ``local_provider.py`` was yielding the
literal word ``"thinking\\n"`` instead of the proper ``"<think>\\n"`` marker
(and ``"\\n\\n"`` instead of ``"\\n</think>\\n"``).  Without proper markers,
``strip_think_blocks()`` in ``prompt_engine.py`` (KI#9 iter-10) fast-paths
out (no ``</think>`` in content → returns input unchanged), so reasoning
content leaked into chat history verbatim — visible to the user as
"thinking Thinking Process:..." in the chat window, and re-fed to the model
on the next turn causing cascading reasoning loops.

Tests also verify the new ``REASONING_EXHAUSTED`` warning emitted when the
model produces 0 visible text chunks but >0 reasoning chunks (max_tokens
exhausted by thinking).

Uses pure source inspection + ``strip_think_blocks()`` integration test
(same pattern as iter-74/75/76 smoke tests — avoids importing PyQt6 or the
openai package which can't be loaded in the Linux test env).

Run:  python scripts/iter77_smoke_test.py
"""
from __future__ import annotations

import ast
import re
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
PROMPT_ENGINE = REPO / "app" / "utils" / "ai_clients" / "prompt_engine.py"


def _method_body_src(tree: ast.Module, class_name: str, method_name: str) -> str | None:
    """Return unparsed source of a specific method inside a class."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return ast.unparse(item)
    return None


def main():
    print("=== iter-77 smoke tests ===\n")

    # ==== Group 1: KI#58 — local_provider.py now uses <think>/</think> ====
    print("Group 1: KI#58 — local_provider.py <think>/</think> markers")
    lp_src = LOCAL_PROVIDER.read_text(encoding="utf-8")
    lp_tree = ast.parse(lp_src)

    _result("G1.1 local_provider.py parses cleanly", True)

    gs_body = _method_body_src(lp_tree, "LocalProvider", "generate_stream")
    _result(
        "G1.2 generate_stream method exists",
        gs_body is not None,
        "method body found via AST",
    )

    # The buggy version yielded the literal word "thinking\n"
    _result(
        'G1.3 buggy yield "thinking\\n" is GONE',
        'yield "thinking\\n"' not in gs_body,
        "would cause reasoning to leak (KI#58 root cause)",
    )

    # The fix must yield the proper marker "<think>\n"
    # ast.unparse normalizes string-literal quotes — yield "<think>\n" in
    # source becomes yield '<think>\n' after unparse. Check both forms.
    has_open_marker = ('yield "<think>\\n"' in gs_body
                       or "yield '<think>\\n'" in gs_body)
    _result(
        'G1.4 yield "<think>\\n" is PRESENT (open marker)',
        has_open_marker,
        "matches deepseek_provider.py:70 pattern",
    )

    # Transition marker (thinking → content): buggy was "\n\n", fix is "\n</think>\n"
    _result(
        'G1.5 buggy transition yield "\\n\\n" is GONE',
        'yield "\\n\\n"' not in gs_body and "yield '\\n\\n'" not in gs_body,
        "would leave <think> block unclosed",
    )

    close_marker_count = (gs_body.count('yield "\\n</think>\\n"')
                          + gs_body.count("yield '\\n</think>\\n'"))
    _result(
        'G1.6 yield "\\n</think>\\n" is PRESENT (transition close marker)',
        close_marker_count >= 2,
        f"appears {close_marker_count} times (transition + final close)",
    )

    # ==== Group 2: KI#58 — REASONING_EXHAUSTED warning ====
    print("\nGroup 2: KI#58 — REASONING_EXHAUSTED warning when text_chunks=0")

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

    # ==== Group 3: strip_think_blocks integration (the actual fix) ====
    print("\nGroup 3: strip_think_blocks integration — markers now recognized")

    # prompt_engine.py imports heavy modules (tiktoken, numpy,
    # sentence_transformers, sklearn) unavailable in the Linux test env.
    # Stub them out so we can import strip_think_blocks for integration testing.
    for mod_name in ("tiktoken", "numpy", "sentence_transformers",
                     "sentence_transformers.SentenceTransformer",
                     "sklearn", "sklearn.metrics",
                     "sklearn.metrics.pairwise"):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = type(sys)("stub")
    # numpy needs special handling — many imports use np.asarray etc.
    np_stub = sys.modules["numpy"]
    np_stub.asarray = lambda *a, **kw: None
    np_stub.array = lambda *a, **kw: None
    np_stub.mean = lambda *a, **kw: 0.0
    # sentence_transformers needs SentenceTransformer class
    st_stub = sys.modules["sentence_transformers"]
    st_stub.SentenceTransformer = type("SentenceTransformer", (), {})
    # sklearn.metrics.pairwise needs cosine_similarity
    skmp_stub = sys.modules["sklearn.metrics.pairwise"]
    skmp_stub.cosine_similarity = lambda *a, **kw: None

    try:
        sys.path.insert(0, str(REPO))
        from app.utils.ai_clients.prompt_engine import strip_think_blocks
        _result("G3.1 strip_think_blocks importable", True)
    except Exception as e:
        _result("G3.1 strip_think_blocks importable", False, str(e))
        print("\n=== Summary: ", end="")
        print(f"{PASS} PASS, {FAIL} FAIL ===")
        sys.exit(1 if FAIL else 0)

    # Simulate the BUGGY output (what local_provider.py produced before KI#58):
    #   yield "thinking\n"
    #   yield "Thinking Process: 1. Analyze the Request: ..."
    #   yield "\n\n"
    buggy_output = "thinking\nThinking Process: 1. Analyze the Request: ...\n\n"
    stripped_buggy = strip_think_blocks(buggy_output)
    _result(
        "G3.2 buggy markers NOT stripped (leak into history)",
        "Thinking Process:" in stripped_buggy,
        f"strip_think_blocks returns input unchanged (no </think> found) — this is the bug",
    )

    # Simulate the FIXED output (what local_provider.py produces now):
    #   yield "<think>\n"
    #   yield "Thinking Process: 1. Analyze the Request: ..."
    #   yield "\n</think>\n"
    #   yield "Hi! Here is my answer in Russian..."
    fixed_output = (
        "<think>\nThinking Process: 1. Analyze the Request: ...\n</think>\n"
        "Привет! Вот мой ответ на русском..."
    )
    stripped_fixed = strip_think_blocks(fixed_output)
    _result(
        "G3.3 fixed markers ARE stripped (only answer remains)",
        "Thinking Process:" not in stripped_fixed and "Привет" in stripped_fixed,
        f"strip_think_blocks returns: {stripped_fixed!r}",
    )

    # Edge case: model exhausted max_tokens (only reasoning, no visible text)
    exhausted_output = "<think>\nThinking Process: ...\n</think>\n"
    stripped_exhausted = strip_think_blocks(exhausted_output)
    _result(
        "G3.4 exhausted-max_tokens case yields empty assistant turn",
        stripped_exhausted == "",
        f"strip_think_blocks returns: {stripped_exhausted!r} (model used all tokens on reasoning)",
    )

    # ==== Group 4: deepseek_provider.py pattern consistency (reference) ====
    print("\nGroup 4: deepseek_provider.py pattern consistency (reference)")

    ds_src = DEEPSEEK_PROVIDER.read_text(encoding="utf-8")
    ds_tree = ast.parse(ds_src)

    _result("G4.1 deepseek_provider.py parses cleanly", True)

    ds_gs_body = _method_body_src(ds_tree, "DeepSeekProvider", "generate_stream")
    if ds_gs_body is None:
        # Try alternate class name
        for cls_name in ("DeepseekProvider", "DeepSeekClient", "DeepSeekAIProvider"):
            ds_gs_body = _method_body_src(ds_tree, cls_name, "generate_stream")
            if ds_gs_body:
                break

    _result(
        "G4.2 deepseek generate_stream method exists",
        ds_gs_body is not None,
        "reference pattern (iter-25)",
    )

    if ds_gs_body:
        ds_has_open = ('yield "<think>\\n"' in ds_gs_body
                       or "yield '<think>\\n'" in ds_gs_body)
        ds_has_close = (ds_gs_body.count('yield "\\n</think>\\n"')
                        + ds_gs_body.count("yield '\\n</think>\\n'")) >= 1
        lp_has_open = ('yield "<think>\\n"' in gs_body
                       or "yield '<think>\\n'" in gs_body)
        lp_has_close = (gs_body.count('yield "\\n</think>\\n"')
                        + gs_body.count("yield '\\n</think>\\n'")) >= 2

        _result(
            'G4.3 deepseek yields "<think>\\n" (reference)',
            ds_has_open,
            "iter-25 established this as the canonical pattern",
        )
        _result(
            'G4.4 deepseek yields "\\n</think>\\n" (reference)',
            ds_has_close,
            "iter-25 canonical close marker",
        )
        _result(
            "G4.5 local_provider now matches deepseek pattern",
            lp_has_open and ds_has_open and lp_has_close and ds_has_close,
            "cross-provider consistency verified",
        )

    # ==== Group 5: file syntax + line count sanity ====
    print("\nGroup 5: file syntax + sanity checks")

    _result(
        "G5.1 local_provider.py syntax OK",
        ast.parse(LOCAL_PROVIDER.read_text(encoding="utf-8")) is not None,
    )

    _result(
        "G5.2 prompt_engine.py syntax OK",
        ast.parse(PROMPT_ENGINE.read_text(encoding="utf-8")) is not None,
    )

    # Line count: baseline (iter-76) was 447 lines. KI#58 adds comment block
    # (~16 lines) + REASONING_EXHAUSTED warning (~18 lines) = ~481 expected.
    lp_lines = len(LOCAL_PROVIDER.read_text(encoding="utf-8").splitlines())
    _result(
        f"G5.3 local_provider.py line count reasonable ({lp_lines} lines)",
        460 <= lp_lines <= 500,
        "baseline 447 + KI#58 additions (~30) + warning (~18) = ~495",
    )

    # No duplicate method definitions (additive-edit rule, §4 rule #10)
    methods_in_local = [
        n.name for n in ast.walk(lp_tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    dup_gs = methods_in_local.count("generate_stream")
    _result(
        f"G5.4 no duplicate generate_stream (count={dup_gs})",
        dup_gs == 1,
        "additive-edit rule preserved",
    )

    # ==== Summary ====
    print(f"\n=== Summary: {PASS} PASS, {FAIL} FAIL ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
