#!/usr/bin/env python3
"""iter-83 smoke tests — DeepSeek provider parity with LocalProvider KI#59.

Tests cover the iter-83 refactor of ``deepseek_provider.py``:

  1. **API parameter cleanup**: removed the bogus ``extra_body`` with
     Anthropic-style ``{"thinking": {"type": "enabled"}}`` parameter
     (NOT a valid DeepSeek API parameter — copy-paste bug pre-iter-83).
  2. **reasoning_effort semantics fix**: when ``reasoning_mode=False``,
     the param is now OMITTED entirely (was: sent as ``"low"`` which
     DeepSeek docs say maps to ``"high"`` — counter-intuitive for an
     "off" toggle).
  3. **KI#59 parity (consume-not-yield)**: reasoning_content is now
     consumed silently (counted for diagnostics, NOT yielded).  Pre-
     iter-83 the provider yielded reasoning wrapped in ``<think>\n`` /
     ``\n</think>\n`` markers — same iter-76 KI#57 bug pattern that
     iter-78 fixed for LocalProvider.
  4. **REASONING_EXHAUSTED warning**: same pattern as iter-79
     LocalProvider — when text_chunks=0 and reasoning_chunks>0, the
     model exhausted max_tokens on reasoning and the user sees an empty
     response.  Warning logged at WARNING level.
  5. **Diagnostic counters**: ``chunk_count``, ``text_chunks``,
     ``reasoning_chunks`` tracked in generate_stream + generate_summary,
     logged at DEBUG level.
  6. **API docs verification**: iter-83 changes verified against
     DeepSeek API docs (api-docs.deepseek.com, 2026-08-01):
       - Reasoning is model-name based (R1 = always-on, V3 = always-off,
         V4 Pro/Flash = supports ``reasoning_effort``).
       - Reasoning content returned in ``delta.reasoning_content``
         (same field name as OpenAI o-series / Qwen3 / GLM-4.6 /
         LocalProvider).
       - ``reasoning_effort`` compatibility values ``"low"`` / ``"medium"``
         map to ``"high"`` (so sending ``"low"`` for "off" is a footgun).

Tests use pure source inspection (same pattern as iter-78/79/80/80.1/82
smoke tests — avoids importing the openai package which can't be loaded
in the Linux test env).

Run:  python scripts/iter83_smoke_test.py
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
    print("=== iter-83 smoke tests ===\n")

    ds_src = DEEPSEEK_PROVIDER.read_text(encoding="utf-8")
    ds_tree = ast.parse(ds_src)

    # ==== Group 1: file sanity + class structure ====
    print("Group 1: file sanity + class structure")
    _result("G1.1 deepseek_provider.py parses cleanly", True)

    _result(
        "G1.2 DeepSeekProvider class present",
        any(isinstance(n, ast.ClassDef) and n.name == "DeepSeekProvider"
            for n in ast.walk(ds_tree)),
        "class definition found via AST",
    )

    _result(
        "G1.3 iter-83 comment block present (documents API verification)",
        "iter-83" in ds_src and "api-docs.deepseek.com" in ds_src,
        "documents the DeepSeek API docs verification (2026-08-01)",
    )

    # ==== Group 2: bogus Anthropic-style thinking param REMOVED ====
    print("\nGroup 2: bogus Anthropic-style thinking param REMOVED")

    gs_body = _method_body_src(ds_tree, "DeepSeekProvider", "generate_stream")
    _result(
        "G2.1 generate_stream method exists",
        gs_body is not None,
        "method body found via AST",
    )

    if gs_body:
        # The pre-iter-83 code sent: payload["extra_body"] = {"thinking": {"type": "enabled"}}
        # This is Anthropic-style, NOT DeepSeek API.  Must be GONE.
        _result(
            'G2.2 "extra_body" with "thinking" dict is GONE from generate_stream',
            '"thinking"' not in gs_body and "'thinking'" not in gs_body,
            "Anthropic-style param removed — DeepSeek API doesn't accept it",
        )
        _result(
            'G2.3 "type": "enabled" Anthropic pattern is GONE',
            '"type": "enabled"' not in gs_body and "'type': 'enabled'" not in gs_body,
            "pre-iter-83 copy-paste bug from Anthropic provider",
        )

    # ==== Group 3: reasoning_effort semantics fix ====
    print("\nGroup 3: reasoning_effort semantics fix")

    if gs_body:
        # When reasoning_mode=True, send "high" (effective on V4 Pro/Flash,
        # silently ignored on R1/V3).
        _result(
            'G3.1 reasoning_effort="high" sent when reasoning_mode=True',
            "'high'" in gs_body and "reasoning_effort" in gs_body,
            "activates deeper thinking on V4 models",
        )

        # When reasoning_mode=False, do NOT send "low" (docs say "low" maps
        # to "high" — counter-intuitive for an "off" toggle).  Omit entirely.
        _result(
            'G3.2 reasoning_effort="low" is GONE (was a footgun)',
            "'low'" not in gs_body and '"low"' not in gs_body,
            "docs: 'low'/'medium' map to 'high' — sending for 'off' is wrong",
        )

        # The "pro" in model name heuristic (pre-iter-83 fallback) is GONE.
        _result(
            "G3.3 'pro' in model.lower() heuristic is GONE",
            '"pro" in self.model.lower()' not in gs_body
            and "'pro' in self.model.lower()" not in gs_body,
            "reasoning_effort is now model-agnostic; model name controls reasoning",
        )

        # The pre-iter-83 thinking_active state variable MUST be gone.
        _result(
            "G3.4 thinking_active state variable is GONE",
            "thinking_active" not in gs_body,
            "no longer needed — consume approach has no open/close state",
        )

    # ==== Group 4: KI#59 parity — consume-not-yield ====
    print("\nGroup 4: KI#59 parity — consume-not-yield")

    if gs_body:
        # reasoning_content MUST be extracted via getattr (OpenAI SDK uses
        # extra="allow" so the field is accessible even though it's not in
        # the typed ChoiceDelta schema).
        _result(
            "G4.1 reasoning_content extracted via getattr",
            "getattr(delta, 'reasoning_content', None)" in gs_body
            or 'getattr(delta, "reasoning_content", None)' in gs_body,
            "needed for reasoning_chunks counter + REASONING_EXHAUSTED warning",
        )

        # The reasoning branch MUST end with `continue` (consume, don't yield).
        _result(
            "G4.2 reasoning branch uses continue (consume, not yield)",
            "reasoning_chunks += 1" in gs_body and "continue" in gs_body,
            "reasoning is counted then skipped — never yielded to caller",
        )

        # The buggy iter-76 marker pattern MUST be GONE.
        _result(
            'G4.3 yield "<think>\\n" is GONE (KI#57 bug pattern)',
            '"<think>\\n"' not in gs_body and "'<think>\\n'" not in gs_body,
            "pre-iter-83 leaked reasoning into chat via markers",
        )
        _result(
            'G4.4 yield "\\n</think>\\n" is GONE',
            '"\\n</think>\\n"' not in gs_body and "'\\n</think>\\n'" not in gs_body,
            "close marker also removed",
        )

        # Only delta.content is yielded.
        _result(
            "G4.5 generate_stream yields delta.content",
            "yield delta.content" in gs_body,
            "ONLY actual text content is yielded to the caller",
        )

    # ==== Group 5: REASONING_EXHAUSTED warning (iter-79 parity) ====
    print("\nGroup 5: REASONING_EXHAUSTED warning (iter-79 parity)")

    if gs_body:
        _result(
            "G5.1 REASONING_EXHAUSTED warning string present",
            "REASONING_EXHAUSTED" in gs_body,
            "logged when text_chunks=0 and reasoning_chunks>0",
        )
        _result(
            "G5.2 warning condition checks text_chunks == 0",
            "text_chunks == 0" in gs_body,
            "detects max_tokens exhaustion on reasoning",
        )
        _result(
            "G5.3 warning condition checks reasoning_chunks > 0",
            "reasoning_chunks > 0" in gs_body,
            "avoids false positive when stream produced nothing at all",
        )
        _result(
            "G5.4 warning uses logger.warning (not debug/info)",
            "logger.warning(" in gs_body and "REASONING_EXHAUSTED" in gs_body,
            "visible at default log level (INFO+)",
        )
        _result(
            "G5.5 warning includes max_tokens value for diagnosis",
            "max_tokens" in gs_body and "REASONING_EXHAUSTED" in gs_body,
            "user can see current max_tokens to know how much to increase",
        )
        _result(
            "G5.6 warning includes model name for diagnosis",
            "model=" in gs_body and "self.model" in gs_body,
            "helps user identify which model is exhausting (R1/V4/etc.)",
        )

    # ==== Group 6: diagnostic counters ====
    print("\nGroup 6: diagnostic counters")

    if gs_body:
        _result(
            "G6.1 chunk_count counter present",
            "chunk_count" in gs_body and "chunk_count += 1" in gs_body,
            "tracks total stream chunks received",
        )
        _result(
            "G6.2 text_chunks counter present",
            "text_chunks" in gs_body and "text_chunks += 1" in gs_body,
            "tracks visible-answer chunks yielded",
        )
        _result(
            "G6.3 reasoning_chunks counter present",
            "reasoning_chunks" in gs_body and "reasoning_chunks += 1" in gs_body,
            "tracks reasoning chunks consumed (not yielded)",
        )
        _result(
            "G6.4 DEBUG log line with all 3 counters",
            "logger.debug(" in gs_body and "stream_chunks=" in gs_body
            and "text_chunks=" in gs_body and "reasoning_chunks=" in gs_body,
            "diagnostic log at DEBUG level for troubleshooting",
        )

    # ==== Group 7: generate_summary parity ====
    print("\nGroup 7: generate_summary parity")

    gs_summary_body = _method_body_src(ds_tree, "DeepSeekProvider", "generate_summary")
    _result(
        "G7.1 generate_summary method exists",
        gs_summary_body is not None,
        "method body found via AST",
    )

    if gs_summary_body:
        # generate_summary should ALSO consume reasoning (not yield markers).
        _result(
            "G7.2 generate_summary does NOT yield '<think>\\n'",
            '"<think>\\n"' not in gs_summary_body
            and "'<think>\\n'" not in gs_summary_body,
            "summary path must not leak reasoning either",
        )
        _result(
            "G7.3 generate_summary does NOT yield '\\n</think>\\n'",
            '"\\n</think>\\n"' not in gs_summary_body
            and "'\\n</think>\\n'" not in gs_summary_body,
            "no think-block close marker yielded",
        )
        _result(
            "G7.4 generate_summary consumes reasoning via getattr + continue",
            ("getattr(delta, 'reasoning_content', None)" in gs_summary_body
             or 'getattr(delta, "reasoning_content", None)' in gs_summary_body)
            and "continue" in gs_summary_body,
            "summary skips thinking tokens, yields only delta.content",
        )
        _result(
            "G7.5 generate_summary has REASONING_EXHAUSTED warning",
            "REASONING_EXHAUSTED" in gs_summary_body and "logger.warning" in gs_summary_body,
            "same diagnostic as generate_stream",
        )
        _result(
            "G7.6 thinking_active variable is GONE from generate_summary",
            "thinking_active" not in gs_summary_body,
            "simplified — no open/close state to track",
        )

    # ==== Group 8: generate() non-streaming parity ====
    print("\nGroup 8: generate() non-streaming parity")

    gen_body = _method_body_src(ds_tree, "DeepSeekProvider", "generate")
    _result(
        "G8.1 generate method exists",
        gen_body is not None,
        "method body found via AST",
    )

    if gen_body:
        # generate() should also use the new reasoning_effort semantics:
        # only send "high" when reasoning_mode=True, omit otherwise.
        _result(
            'G8.2 generate sends reasoning_effort="high" when True',
            "'high'" in gen_body and "reasoning_effort" in gen_body,
            "same semantics as generate_stream",
        )
        _result(
            'G8.3 generate does NOT send "low" when False',
            "'low'" not in gen_body and '"low"' not in gen_body,
            "avoids the 'low' → 'high' mapping footgun",
        )
        _result(
            "G8.4 generate does NOT send Anthropic-style thinking param",
            '"thinking"' not in gen_body and "'thinking'" not in gen_body,
            "Anthropic-style param removed from all 3 methods",
        )

    # ==== Group 9: file sanity + regression ====
    print("\nGroup 9: file sanity + regression")

    _result(
        "G9.1 no duplicate generate_stream method",
        ds_src.count("async def generate_stream(") == 1,
        "additive-edit rule preserved (§4 rule #10)",
    )
    _result(
        "G9.2 no duplicate generate_summary method",
        ds_src.count("async def generate_summary(") == 1,
        "additive-edit rule preserved",
    )
    _result(
        "G9.3 no duplicate generate method",
        ds_src.count("async def generate(") == 1,
        "additive-edit rule preserved",
    )

    # Line count sanity (pre-iter-83 was 130 lines; iter-83 adds ~80 lines
    # of comment + 30 lines of consume-not-yield logic + 20 lines of
    # REASONING_EXHAUSTED warning + counters = ~260 lines).
    line_count = len(ds_src.splitlines())
    _result(
        "G9.4 deepseek_provider.py line count reasonable",
        200 <= line_count <= 320,
        f"{line_count} lines (pre-iter-83 was 130 + iter-83 additions)",
    )

    # iter-83 comment block must be present at the top of generate_stream.
    _result(
        "G9.5 iter-83 API docs verification comment present",
        "api-docs.deepseek.com" in ds_src and "2026-08-01" in ds_src,
        "documents the DeepSeek API docs verification date",
    )
    _result(
        "G9.6 KI#59 parity documented in comment",
        "KI#59" in ds_src and "consume" in ds_src,
        "documents the consume-not-yield rationale",
    )
    _result(
        "G9.7 reasoning_effort 'low' footgun documented",
        "footgun" in ds_src.lower() or "counter-intuitive" in ds_src.lower(),
        "explains why 'low' is no longer sent",
    )

    print(f"\n=== Summary: {PASS} PASS, {FAIL} FAIL ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
