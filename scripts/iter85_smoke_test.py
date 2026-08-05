#!/usr/bin/env python3
"""iter-85 smoke tests — Cloud API provider fixes (Z.AI / Qwen / Anthropic / OpenAI).

Tests cover the iter-85 cloud-provider correctness fixes verified against
official docs (2026-08-01).  Each provider had independent API-correctness
bugs that would either fail API validation or silently drop reasoning
content.

== Z.AI (zai_provider.py) — most critical bug ==

  Pre-iter-85: the provider had a comment "Z.AI does not currently expose
  a reasoning-mode API parameter" — this was OUTDATED.  Z.AI added thinking
  mode support with GLM-4.5 (late 2025) and formalized it in GLM-4.6.
  The ``thinking: {"type": "enabled"}`` parameter (Anthropic-style syntax)
  was never sent — reasoning_mode toggle had NO EFFECT on GLM-4.6.

  Verified: https://docs.z.ai/guides/capabilities/thinking-mode
  Confirmed by: https://github.com/RooCodeInc/Roo-Code/issues/8547

  iter-85 fix: send ``extra_body: {"thinking": {"type": "enabled"}}`` when
  reasoning_mode=True; consume reasoning_content silently (KI#59 parity
  with LocalProvider iter-78); add REASONING_EXHAUSTED warning.

== Qwen (qwen_provider.py) — KI#59 parity ==

  Pre-iter-85: ``enable_thinking`` parameter was correctly sent (verified),
  but reasoning_content was only IMPLICITLY dropped (the ``if delta.content``
  guard filtered reasoning chunks because they have content=None).  No
  REASONING_EXHAUSTED warning when reasoning used up all max_tokens.

  Verified: https://www.alibabacloud.com/help/en/model-studio/deep-thinking
  Confirmed by: https://github.com/vllm-project/vllm/issues/40816 (Qwen3.6
  streaming emits final answer in reasoning_content).

  iter-85 fix: explicit consume via getattr + REASONING_EXHAUSTED warning,
  matching the iter-78/79/83/85-zai pattern.

== Anthropic (anthropic_provider.py) — API constraint violations ==

  Pre-iter-85: when ``thinking.type=enabled`` was sent, the provider also
  sent ``temperature=0.7`` (the user default) — but Anthropic API REQUIRES
  ``temperature=1.0`` when thinking is enabled (else returns 400).  Also
  used a hardcoded ``budget_tokens=10000`` (works, but not adaptive to
  ``max_tokens``).

  Verified: https://platform.claude.com/docs/en/build-with-claude/extended-thinking
  Confirmed by: https://www.reddit.com/r/ClaudeAI/comments/1iyfi6x (Feb 2025)

  iter-85 fix: force ``temperature=1.0`` when thinking enabled; adaptive
  ``budget_tokens = min(max_tokens-1024, max(1024, int(max_tokens*0.6)))``
  (matches the iter-82 reasoning budget fraction default 0.6); explicit
  ``delta.type`` check in streaming to differentiate thinking_delta from
  text_delta.

== OpenAI (openai_provider.py) — deprecated max_tokens ==

  Pre-iter-85: used the deprecated ``max_tokens`` parameter — works for
  non-o-series models (gpt-4o, etc.) but FAILS for o-series (o1, o3,
  o4-mini) which require ``max_completion_tokens`` (deprecated since
  Sept 2024).  No reasoning_content handling (o-series reasoning chunks
  were silently dropped).

  Verified: https://community.openai.com/t/why-was-max-tokens-changed-to-max-completion-tokens/938077
  Confirmed by: https://github.com/simonw/llm/issues/724

  iter-85 fix: always use ``max_completion_tokens`` (works for all current
  models per OpenAI migration guide); explicit consume reasoning_content
  + REASONING_EXHAUSTED warning (KI#59 parity).

Tests use pure source inspection (same pattern as iter-78/79/80/80.1/82/83
smoke tests — avoids importing PyQt6 / openai which can't be loaded in
the Linux test env).

Run:  python scripts/iter85_smoke_test.py
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
ZAI_PROVIDER = REPO / "app" / "utils" / "ai_clients" / "providers" / "zai_provider.py"
QWEN_PROVIDER = REPO / "app" / "utils" / "ai_clients" / "providers" / "qwen_provider.py"
ANTHROPIC_PROVIDER = REPO / "app" / "utils" / "ai_clients" / "providers" / "anthropic_provider.py"
OPENAI_PROVIDER = REPO / "app" / "utils" / "ai_clients" / "providers" / "openai_provider.py"


def _method_body_src(tree: ast.Module, class_name: str, method_name: str) -> str | None:
    """Return unparsed source of a specific method inside a class."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return ast.unparse(item)
    return None


def main():
    print("=== iter-85 smoke tests ===\n")

    # ============================================================
    # Group 1-4: Z.AI provider
    # ============================================================
    print("Group 1: Z.AI provider — file sanity + iter-85 comment")
    zai_src = ZAI_PROVIDER.read_text(encoding="utf-8")
    zai_tree = ast.parse(zai_src)
    _result("G1.1 zai_provider.py parses cleanly", True)

    _result(
        "G1.2 iter-85 comment block present (documents Z.AI thinking-mode docs)",
        "iter-85" in zai_src and "docs.z.ai" in zai_src,
        "documents the Z.AI developer docs verification (2026-08-01)",
    )
    _result(
        "G1.3 Roo-Code #8547 reference present (confirms thinking param requirement)",
        "Roo-Code" in zai_src or "8547" in zai_src,
        "external confirmation that GLM-4.6 needs thinking:{type:enabled}",
    )

    # ==== Group 2: Z.AI thinking parameter wiring ====
    print("\nGroup 2: Z.AI — thinking parameter wiring")

    zai_gs = _method_body_src(zai_tree, "ZAIProvider", "generate_stream")
    _result(
        "G2.1 generate_stream method exists",
        zai_gs is not None,
        "method body found via AST",
    )

    if zai_gs:
        _result(
            "G2.2 thinking:{type:enabled} sent when reasoning_mode=True",
            "'thinking'" in zai_gs and "'type': 'enabled'" in zai_gs
            or "'thinking'" in zai_gs and '"type": "enabled"' in zai_gs,
            "activates GLM-4.6 thinking mode",
        )
        _result(
            "G2.3 thinking:{type:disabled} sent when reasoning_mode=False",
            "'type': 'disabled'" in zai_gs or '"type": "disabled"' in zai_gs,
            "explicitly disables thinking (overrides model default)",
        )
        _result(
            "G2.4 thinking parameter sent via extra_body",
            "extra_body" in zai_gs,
            "OpenAI SDK forwards extra_body as additional JSON fields",
        )
        _result(
            "G2.5 reasoning_mode=None case omits thinking param (if/elif without else)",
            "if reasoning_mode is True:" in zai_gs
            and "elif reasoning_mode is False:" in zai_gs
            and "else:" not in zai_gs.split("if reasoning_mode is True:")[1].split("elif reasoning_mode is False:")[0],
            "lets the model default apply when user hasn't toggled (no else branch)",
        )

    # ==== Group 3: Z.AI KI#59 parity ====
    print("\nGroup 3: Z.AI — KI#59 consume-not-yield parity")

    if zai_gs:
        _result(
            "G3.1 reasoning_content extracted via getattr",
            "getattr(delta, 'reasoning_content', None)" in zai_gs
            or 'getattr(delta, "reasoning_content", None)' in zai_gs,
            "needed for reasoning_chunks counter + REASONING_EXHAUSTED",
        )
        _result(
            "G3.2 reasoning branch uses continue (consume, not yield)",
            "reasoning_chunks += 1" in zai_gs and "continue" in zai_gs,
            "reasoning counted then skipped — never yielded to caller",
        )
        _result(
            "G3.3 generate_stream yields delta.content",
            "yield delta.content" in zai_gs,
            "ONLY actual text content yielded",
        )

    # ==== Group 4: Z.AI REASONING_EXHAUSTED + counters ====
    print("\nGroup 4: Z.AI — REASONING_EXHAUSTED warning + diagnostic counters")

    if zai_gs:
        _result(
            "G4.1 REASONING_EXHAUSTED warning present",
            "REASONING_EXHAUSTED" in zai_gs and "logger.warning" in zai_gs,
            "logged when text_chunks=0 and reasoning_chunks>0",
        )
        _result(
            "G4.2 warning includes model name",
            "model=" in zai_gs and "self.model" in zai_gs,
            "helps diagnose which GLM variant is exhausting",
        )
        _result(
            "G4.3 chunk_count + text_chunks + reasoning_chunks counters",
            "chunk_count" in zai_gs and "text_chunks" in zai_gs
            and "reasoning_chunks" in zai_gs,
            "diagnostic counters for troubleshooting",
        )
        _result(
            "G4.4 DEBUG log line with all 3 counters",
            "logger.debug(" in zai_gs and "stream_chunks=" in zai_gs,
            "diagnostic log at DEBUG level",
        )

    # ==== Group 5: Z.AI generate_summary + generate parity ====
    print("\nGroup 5: Z.AI — generate_summary + generate parity")

    zai_sum = _method_body_src(zai_tree, "ZAIProvider", "generate_summary")
    if zai_sum:
        _result(
            "G5.1 generate_summary consumes reasoning_content via getattr",
            "getattr(msg, 'reasoning_content', None)" in zai_sum
            or 'getattr(msg, "reasoning_content", None)' in zai_sum,
            "non-streaming response: reasoning in msg.reasoning_content",
        )

    zai_gen = _method_body_src(zai_tree, "ZAIProvider", "generate")
    if zai_gen:
        _result(
            "G5.2 generate sends thinking param when reasoning_mode=True",
            "'thinking'" in zai_gen and "extra_body" in zai_gen,
            "same wiring as generate_stream",
        )
        _result(
            "G5.3 generate consumes reasoning_content via getattr",
            "getattr(msg, 'reasoning_content', None)" in zai_gen
            or 'getattr(msg, "reasoning_content", None)' in zai_gen,
            "non-streaming response: reasoning consumed silently",
        )

    # ============================================================
    # Group 6-9: Qwen provider
    # ============================================================
    print("\nGroup 6: Qwen provider — file sanity + iter-85 comment")
    qwen_src = QWEN_PROVIDER.read_text(encoding="utf-8")
    qwen_tree = ast.parse(qwen_src)
    _result("G6.1 qwen_provider.py parses cleanly", True)

    _result(
        "G6.2 iter-85 comment block present (documents Alibaba Cloud docs)",
        "iter-85" in qwen_src and "alibabacloud.com" in qwen_src,
        "documents the Alibaba Cloud Model Studio docs verification",
    )

    # ==== Group 7: Qwen KI#59 parity ====
    print("\nGroup 7: Qwen — KI#59 consume-not-yield parity")

    qwen_gs = _method_body_src(qwen_tree, "QwenProvider", "generate_stream")
    _result(
        "G7.1 generate_stream method exists",
        qwen_gs is not None,
        "method body found via AST",
    )

    if qwen_gs:
        _result(
            "G7.2 reasoning_content extracted via getattr",
            "getattr(delta, 'reasoning_content', None)" in qwen_gs
            or 'getattr(delta, "reasoning_content", None)' in qwen_gs,
            "explicit consume (was implicit pre-iter-85 via if delta.content)",
        )
        _result(
            "G7.3 reasoning branch uses continue",
            "reasoning_chunks += 1" in qwen_gs and "continue" in qwen_gs,
            "reasoning counted then skipped — never yielded to caller",
        )
        _result(
            "G7.4 enable_thinking parameter still sent (KI#19 preserved)",
            "'enable_thinking'" in qwen_gs,
            "Qwen3 reasoning toggle — verified correct per Alibaba docs",
        )

    # ==== Group 8: Qwen REASONING_EXHAUSTED ====
    print("\nGroup 8: Qwen — REASONING_EXHAUSTED warning + counters")

    if qwen_gs:
        _result(
            "G8.1 REASONING_EXHAUSTED warning present",
            "REASONING_EXHAUSTED" in qwen_gs and "logger.warning" in qwen_gs,
            "logged when text_chunks=0 and reasoning_chunks>0",
        )
        _result(
            "G8.2 warning mentions qwen-plus as non-thinking alternative",
            "qwen-plus" in qwen_gs or "qwen-turbo" in qwen_gs,
            "actionable advice for the user",
        )
        _result(
            "G8.3 chunk_count + text_chunks + reasoning_chunks counters",
            "chunk_count" in qwen_gs and "text_chunks" in qwen_gs
            and "reasoning_chunks" in qwen_gs,
            "diagnostic counters",
        )

    # ==== Group 9: Qwen generate_summary + generate parity ====
    print("\nGroup 9: Qwen — generate_summary + generate parity")

    qwen_sum = _method_body_src(qwen_tree, "QwenProvider", "generate_summary")
    if qwen_sum:
        _result(
            "G9.1 generate_summary consumes reasoning_content via getattr",
            "getattr(msg, 'reasoning_content', None)" in qwen_sum
            or 'getattr(msg, "reasoning_content", None)' in qwen_sum,
            "non-streaming response: reasoning consumed silently",
        )

    qwen_gen = _method_body_src(qwen_tree, "QwenProvider", "generate")
    if qwen_gen:
        _result(
            "G9.2 generate consumes reasoning_content via getattr",
            "getattr(msg, 'reasoning_content', None)" in qwen_gen
            or 'getattr(msg, "reasoning_content", None)' in qwen_gen,
            "non-streaming response: reasoning consumed silently",
        )

    # ============================================================
    # Group 10-13: Anthropic provider
    # ============================================================
    print("\nGroup 10: Anthropic provider — file sanity + iter-85 comment")
    anthropic_src = ANTHROPIC_PROVIDER.read_text(encoding="utf-8")
    anthropic_tree = ast.parse(anthropic_src)
    _result("G10.1 anthropic_provider.py parses cleanly", True)

    _result(
        "G10.2 iter-85 comment block present (documents Claude Platform docs)",
        "iter-85" in anthropic_src and "platform.claude.com" in anthropic_src,
        "documents the Anthropic Claude Platform docs verification",
    )

    # ==== Group 11: Anthropic temperature=1.0 constraint ====
    print("\nGroup 11: Anthropic — temperature=1.0 constraint when thinking enabled")

    ant_gs = _method_body_src(anthropic_tree, "AnthropicProvider", "generate_stream")
    _result(
        "G11.1 generate_stream method exists",
        ant_gs is not None,
        "method body found via AST",
    )

    if ant_gs:
        _result(
            "G11.2 temperature=1.0 forced when thinking_enabled",
            "1.0 if thinking_enabled" in ant_gs,
            "Anthropic API REQUIRES temperature=1.0 when thinking enabled",
        )
        _result(
            "G11.3 thinking_enabled derived from reasoning_mode is True",
            "thinking_enabled = reasoning_mode is True" in ant_gs,
            "single source of truth for the thinking flag",
        )

    # ==== Group 12: Anthropic adaptive budget_tokens ====
    print("\nGroup 12: Anthropic — adaptive budget_tokens")

    if ant_gs:
        _result(
            "G12.1 budget_tokens is adaptive (uses max_toks)",
            "max_toks" in ant_gs and "budget" in ant_gs,
            "was hardcoded 10000 pre-iter-85",
        )
        _result(
            "G12.2 budget formula: min(max_tokens-1024, max(1024, int(max_tokens*0.6)))",
            "max_toks - 1024" in ant_gs and "max_toks * 0.6" in ant_gs,
            "leaves >= 1024 for visible answer, uses 60% for thinking (s1 pattern)",
        )
        _result(
            "G12.3 budget floor is 1024 (Anthropic API minimum)",
            "1024" in ant_gs,
            "API rejects budget_tokens < 1024",
        )

    # ==== Group 13: Anthropic explicit delta.type check ====
    print("\nGroup 13: Anthropic — explicit delta.type check (KI#59 parity)")

    if ant_gs:
        _result(
            "G13.1 delta_type variable extracted from delta",
            "delta_type" in ant_gs,
            "differentiates thinking_delta from text_delta",
        )
        _result(
            "G13.2 thinking_delta explicitly consumed (continue)",
            "thinking_delta" in ant_gs and "continue" in ant_gs,
            "thinking tokens consumed silently, not yielded",
        )
        _result(
            "G13.3 text_delta yields delta.text",
            "text_delta" in ant_gs and "delta.get" in ant_gs,
            "ONLY actual text content yielded",
        )
        _result(
            "G13.4 REASONING_EXHAUSTED warning present",
            "REASONING_EXHAUSTED" in ant_gs and "logger.warning" in ant_gs,
            "same pattern as LocalProvider iter-79 + DeepSeek iter-83",
        )
        _result(
            "G13.5 text_chunks + reasoning_chunks counters",
            "text_chunks" in ant_gs and "reasoning_chunks" in ant_gs,
            "diagnostic counters",
        )

    # ==== Group 14: Anthropic generate() parity ====
    print("\nGroup 14: Anthropic — generate() thinking constraints parity")

    ant_gen = _method_body_src(anthropic_tree, "AnthropicProvider", "generate")
    if ant_gen:
        _result(
            "G14.1 generate forces temperature=1.0 when thinking_enabled",
            "1.0 if thinking_enabled" in ant_gen,
            "same constraint as generate_stream",
        )
        _result(
            "G14.2 generate uses adaptive budget_tokens",
            "max_toks" in ant_gen and "budget" in ant_gen,
            "same adaptive formula as generate_stream",
        )

    # ============================================================
    # Group 15-18: OpenAI provider
    # ============================================================
    print("\nGroup 15: OpenAI provider — file sanity + iter-85 comment")
    openai_src = OPENAI_PROVIDER.read_text(encoding="utf-8")
    openai_tree = ast.parse(openai_src)
    _result("G15.1 openai_provider.py parses cleanly", True)

    _result(
        "G15.2 iter-85 comment block present (documents max_completion_tokens)",
        "iter-85" in openai_src and "max_completion_tokens" in openai_src,
        "documents the OpenAI migration guide reference",
    )
    _result(
        "G15.3 simonw/llm#724 reference present (confirms o1 requires new param)",
        "simonw" in openai_src or "724" in openai_src,
        "external confirmation that o1 rejects max_tokens",
    )

    # ==== Group 16: OpenAI max_completion_tokens ====
    print("\nGroup 16: OpenAI — max_completion_tokens (replaces deprecated max_tokens)")

    _result(
        "G16.1 _build_max_tokens_param helper method exists",
        _method_body_src(openai_tree, "OpenAIProvider", "_build_max_tokens_param") is not None,
        "centralised param-name logic",
    )
    _result(
        "G16.2 _is_reasoning_model helper method exists",
        _method_body_src(openai_tree, "OpenAIProvider", "_is_reasoning_model") is not None,
        "detects o-series models for parameter gating",
    )
    _result(
        "G16.3 _REASONING_MODELS tuple includes o1, o3, o4",
        '"o1"' in openai_src and '"o3"' in openai_src and '"o4"' in openai_src,
        "o-series model name prefixes",
    )

    bmtp_body = _method_body_src(openai_tree, "OpenAIProvider", "_build_max_tokens_param")
    if bmtp_body:
        _result(
            "G16.4 _build_max_tokens_param returns 'max_completion_tokens'",
            "max_completion_tokens" in bmtp_body,
            "always uses the new param name (works for all current models)",
        )
        _result(
            "G16.5 _build_max_tokens_param does NOT return 'max_tokens'",
            "return \"max_tokens\"" not in bmtp_body and "return 'max_tokens'" not in bmtp_body,
            "deprecated param name avoided",
        )

    oai_gs = _method_body_src(openai_tree, "OpenAIProvider", "generate_stream")
    if oai_gs:
        _result(
            "G16.6 generate_stream uses _build_max_tokens_param",
            "_build_max_tokens_param" in oai_gs,
            "centralised param-name logic",
        )
        _result(
            "G16.7 generate_stream uses max_tokens_key as dict key",
            "max_tokens_key" in oai_gs,
            "dynamic key (supports both param names)",
        )

    # ==== Group 17: OpenAI KI#59 parity ====
    print("\nGroup 17: OpenAI — KI#59 consume-not-yield parity")

    if oai_gs:
        _result(
            "G17.1 reasoning_content extracted via getattr",
            "getattr(delta, 'reasoning_content', None)" in oai_gs
            or 'getattr(delta, "reasoning_content", None)' in oai_gs,
            "o-series reasoning emitted in delta.reasoning_content",
        )
        _result(
            "G17.2 reasoning branch uses continue",
            "reasoning_chunks += 1" in oai_gs and "continue" in oai_gs,
            "reasoning counted then skipped — never yielded to caller",
        )

    # ==== Group 18: OpenAI REASONING_EXHAUSTED + parity ====
    print("\nGroup 18: OpenAI — REASONING_EXHAUSTED + parity across methods")

    if oai_gs:
        _result(
            "G18.1 REASONING_EXHAUSTED warning present",
            "REASONING_EXHAUSTED" in oai_gs and "logger.warning" in oai_gs,
            "same pattern as LocalProvider iter-79 + others",
        )
        _result(
            "G18.2 reasoning_effort='high' sent when reasoning_mode=True (preserved)",
            "'high'" in oai_gs and "reasoning_effort" in oai_gs,
            "KI#19 iter-25 contract preserved",
        )

    oai_gen = _method_body_src(openai_tree, "OpenAIProvider", "generate")
    if oai_gen:
        _result(
            "G18.3 generate uses _build_max_tokens_param",
            "_build_max_tokens_param" in oai_gen,
            "same param-name logic as generate_stream",
        )
        _result(
            "G18.4 generate consumes reasoning_content via getattr",
            "getattr(msg, 'reasoning_content', None)" in oai_gen
            or 'getattr(msg, "reasoning_content", None)' in oai_gen,
            "non-streaming response: reasoning consumed silently",
        )

    oai_sum = _method_body_src(openai_tree, "OpenAIProvider", "generate_summary")
    if oai_sum:
        _result(
            "G18.5 generate_summary uses _build_max_tokens_param",
            "_build_max_tokens_param" in oai_sum,
            "same param-name logic as generate_stream",
        )
        _result(
            "G18.6 generate_summary consumes reasoning_content via getattr",
            "getattr(delta, 'reasoning_content', None)" in oai_sum
            or 'getattr(delta, "reasoning_content", None)' in oai_sum,
            "summary path also consumes reasoning silently",
        )

    # ============================================================
    # Group 19: Cross-provider parity check
    # ============================================================
    print("\nGroup 19: Cross-provider parity — all 4 providers consume reasoning_content")

    providers = [
        ("ZAIProvider", ZAI_PROVIDER, "zai"),
        ("QwenProvider", QWEN_PROVIDER, "qwen"),
        ("AnthropicProvider", ANTHROPIC_PROVIDER, "anthropic"),
        ("OpenAIProvider", OPENAI_PROVIDER, "openai"),
    ]
    for class_name, path, short in providers:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        gs = _method_body_src(tree, class_name, "generate_stream")
        has_consume = (
            gs is not None
            and ("getattr(delta, 'reasoning_content', None)" in gs
                 or 'getattr(delta, "reasoning_content", None)' in gs
                 or "thinking_delta" in gs)  # Anthropic uses delta_type check
            and "continue" in gs
        )
        _result(
            f"G19.{short} {class_name} consumes reasoning_content (KI#59 parity)",
            has_consume,
            "all 4 cloud providers now match LocalProvider iter-78 pattern",
        )

    # ============================================================
    # Group 20: Regression — iter-25 KI#19 contracts preserved
    # ============================================================
    print("\nGroup 20: Regression — iter-25 KI#19 contracts preserved")

    # Z.AI: thinking param sent (replaces the pre-iter-85 "ignored" log)
    _result(
        "G20.1 Z.AI no longer logs 'reasoning_mode ignored' (now wired)",
        "ignored by Z.AI Provider" not in zai_src,
        "pre-iter-85 had a debug log saying reasoning_mode is ignored",
    )
    # Qwen: enable_thinking still sent
    _result(
        "G20.2 Qwen still sends enable_thinking=True",
        "'enable_thinking': True" in qwen_src or '"enable_thinking": True' in qwen_src,
        "KI#19 iter-25 Qwen contract preserved",
    )
    # Anthropic: thinking param still sent
    _result(
        "G20.3 Anthropic still sends thinking:{type:enabled}",
        "'type': 'enabled'" in anthropic_src or '"type": "enabled"' in anthropic_src,
        "KI#19 iter-25 Anthropic contract preserved",
    )
    # OpenAI: reasoning_effort still sent
    # ast.unparse normalises "double quotes" → 'single quotes', so we accept
    # either form for the 'high' string literal.
    _result(
        "G20.4 OpenAI still sends reasoning_effort='high' when True",
        ("'high'" in openai_src or '"high"' in openai_src) and "reasoning_effort" in openai_src,
        "KI#19 iter-25 OpenAI contract preserved",
    )

    # ============================================================
    # Group 21: File sanity
    # ============================================================
    print("\nGroup 21: File sanity")

    for idx, (class_name, path, short) in enumerate(providers, start=1):
        src = path.read_text(encoding="utf-8")
        line_count = len(src.splitlines())
        _result(
            f"G21.{idx}a {class_name} line count reasonable",
            80 <= line_count <= 350,
            f"{line_count} lines",
        )
        # No duplicate generate_stream
        gs_count = src.count("async def generate_stream(")
        _result(
            f"G21.{idx}b {class_name} no duplicate generate_stream",
            gs_count == 1,
            f"count={gs_count} — additive-edit rule preserved",
        )

    print(f"\n=== Summary: {PASS} PASS, {FAIL} FAIL ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
