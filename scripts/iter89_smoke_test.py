"""iter-89 smoke test — verifies KI#68 + KI#69 fixes.

Two test groups:
  G1 — KI#68 (template_detector pattern reorder): unique-family markers
       (gemma3, mistral-v0-1, command-r, alpaca) are now checked BEFORE
       qwen3-thinking. Mixed-marker Jinja (Gemma4-HauhauCS-style with both
       ``<start_of_turn>`` AND ``<think>`` markers) resolves to gemma3, not
       qwen3-thinking. Regression: plain Qwen3-thinking Jinja still resolves
       to qwen3-thinking.
  G2 — KI#69 (eos_token_id drift detection): ``_check_eos_drift()`` detects
       when GGUF eos_token_id does not contain any canonical eos for the
       resolved template family. Qwen3.5 eos=[248046] → drift warning.
       Llama-3 eos=[128001] → no drift. Mistral eos=[2] → no drift.

Run: python /home/z/my-project/repos/Soul-of-Waifu/scripts/iter89_smoke_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root discovery — try multiple known locations
# ---------------------------------------------------------------------------

def _find_repo_root() -> Path:
    """Find the SoW repo root by looking for main.py + STATUS.md."""
    candidates = [
        Path(__file__).resolve().parent.parent,  # scripts/ → repo root
        Path("/home/z/my-project/Soul-of-Waifu"),
        Path("/home/z/my-project/repos/Soul-of-Waifu"),
    ]
    for c in candidates:
        if (c / "main.py").exists() and (c / "STATUS.md").exists():
            return c
    raise RuntimeError(
        f"Could not find SoW repo root. Tried: {[str(c) for c in candidates]}"
    )

REPO_ROOT = _find_repo_root()
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Test framework (minimal — matches prior iter smoke tests)
# ---------------------------------------------------------------------------

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(group: str, name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {group}: {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{group}: {name} — {detail}")
        print(f"  [FAIL] {group}: {name} — {detail}")


# ---------------------------------------------------------------------------
# G1 — KI#68: pattern reorder (unique-family markers BEFORE qwen3-thinking)
# ---------------------------------------------------------------------------

def test_ki68_pattern_reorder():
    print("\n=== G1 — KI#68: pattern reorder (unique-family BEFORE qwen3-thinking) ===")

    from app.utils.ai_clients.template_detector import (
        _JINJA_TEMPLATE_PATTERNS,
        _infer_template_from_jinja,
        Confidence,
    )

    # G1.1: all expected patterns present
    template_names = [t for (_, t, _) in _JINJA_TEMPLATE_PATTERNS]
    for expected in ["llama-3", "gpt-oss", "gemma3", "mistral-v0-1",
                     "command-r", "alpaca", "qwen3-thinking", "chatml",
                     "phi-3", "deepseek"]:
        check(f"G1.1.{expected}", f"pattern '{expected}' present",
              expected in template_names,
              f"template_names={template_names}")

    # G1.2: ordering — unique-family patterns BEFORE qwen3-thinking
    def _idx(name: str) -> int:
        for i, (_, t, _) in enumerate(_JINJA_TEMPLATE_PATTERNS):
            if t == name:
                return i
        return -1

    qwen3_idx = _idx("qwen3-thinking")
    check("G1.2a", "qwen3-thinking pattern exists", qwen3_idx >= 0,
          f"qwen3_idx={qwen3_idx}")

    for family in ["gemma3", "mistral-v0-1", "command-r", "alpaca"]:
        fam_idx = _idx(family)
        check(f"G1.2b.{family}", f"'{family}' pattern placed BEFORE qwen3-thinking",
              fam_idx >= 0 and fam_idx < qwen3_idx,
              f"{family}_idx={fam_idx}, qwen3_idx={qwen3_idx}")

    # G1.2c: chatml still AFTER qwen3-thinking (KI#66 ordering preserved)
    chatml_idx = _idx("chatml")
    check("G1.2c", "chatml pattern placed AFTER qwen3-thinking (KI#66 preserved)",
          chatml_idx > qwen3_idx,
          f"chatml_idx={chatml_idx}, qwen3_idx={qwen3_idx}")

    # G1.3: KEY TEST — Gemma4-HauhauCS-style mixed Jinja (gemma + qwen3 markers)
    # resolves to gemma3 (NOT qwen3-thinking). This is the bug from the user's
    # iter-88 verification log that KI#68 fixes.
    gemma4_hauhau_jinja = """{%- for message in messages %}
    {{- '<start_of_turn>' + message['role'] + '\\n' }}
    {%- if message['role'] == 'assistant' %}
        {%- if enable_thinking and message['reasoning_content'] %}
            {{- '<think>\\n' + message['reasoning_content'] + '\\n</think>\\n' }}
        {%- endif %}
    {%- endif %}
    {{- message['content'] + '<end_of_turn>\\n' }}
{%- endfor %}
{%- if add_generation_prompt %}
    {{- '<start_of_turn>assistant\\n' }}
    {%- if enable_thinking %}
        {{- '<think>\\n' }}
    {%- endif %}
{%- endif %}"""
    resolved, conf = _infer_template_from_jinja(gemma4_hauhau_jinja)
    check("G1.3", "Gemma4-HauhauCS mixed Jinja (gemma + qwen3 markers) → gemma3",
          resolved == "gemma3",
          f"expected gemma3, got {resolved} (conf={conf})")
    check("G1.3b", "confidence is HIGH",
          conf == Confidence.HIGH,
          f"expected HIGH, got {conf}")

    # G1.4: Mistral finetune with <think> customization → mistral-v0-1 (NOT qwen3-thinking)
    mistral_thinking_jinja = """{%- for message in messages %}
{%- if message['role'] == 'user' %}
{{- '[INST] ' + message['content'] + ' [/INST]\\n' }}
{%- else %}
{%- if enable_thinking %}
{{- '<think>\\n' + message['reasoning_content'] + '\\n</think>\\n' }}
{%- endif %}
{{- message['content'] + '</s>\\n' }}
{%- endif %}
{%- endfor %}"""
    resolved, _ = _infer_template_from_jinja(mistral_thinking_jinja)
    check("G1.4", "Mistral finetune with <think> customization → mistral-v0-1",
          resolved == "mistral-v0-1",
          f"expected mistral-v0-1, got {resolved}")

    # G1.5: Command-R finetune with <think> customization → command-r (NOT qwen3-thinking)
    commandr_thinking_jinja = """{%- for message in messages %}
{{- '<|START_OF_TURN_TOKEN|><|USER_TOKEN|>' + message['content'] + '<|END_OF_TURN_TOKEN|>' }}
{%- if message['role'] == 'assistant' %}
{{- '<think>' + message['reasoning_content'] + '</think>' }}
{%- endif %}
{%- endfor %}"""
    resolved, _ = _infer_template_from_jinja(commandr_thinking_jinja)
    check("G1.5", "Command-R finetune with <think> customization → command-r",
          resolved == "command-r",
          f"expected command-r, got {resolved}")

    # G1.6: Alpaca finetune with <think> customization → alpaca (NOT qwen3-thinking)
    # NOTE: the Alpaca pattern uses ``\n### Instruction:`` (real newline + marker).
    # In the Jinja source, the marker appears at the START of a line (after a
    # Jinja ``{{- }}`` expression on the previous line). We write the test Jinja
    # with real newlines before ``### Instruction:`` / ``### Response:`` so the
    # pattern matches — ``\\n`` (literal backslash-n) would NOT match.
    alpaca_thinking_jinja = (
        "{%- for message in messages %}\n"
        "{%- if message['role'] == 'user' %}\n"
        "### Instruction:\n"
        "{{- message['content'] }}\n"
        "{%- else %}\n"
        "{%- if enable_thinking %}\n"
        "{{- '<think>\\n' + message['reasoning_content'] + '\\n</think>\\n' }}\n"
        "{%- endif %}\n"
        "### Response:\n"
        "{{- message['content'] }}\n"
        "{%- endif %}\n"
        "{%- endfor %}"
    )
    resolved, _ = _infer_template_from_jinja(alpaca_thinking_jinja)
    check("G1.6", "Alpaca finetune with <think> customization → alpaca",
          resolved == "alpaca",
          f"expected alpaca, got {resolved}")

    # --- Regression tests (must NOT break) ---

    # G1.7: regression — plain Qwen3.5 Jinja (enable_thinking + <think>, NO gemma/mistral markers)
    # still resolves to qwen3-thinking. This is the iter-88 KI#66 contract.
    qwen35_jinja = """{%- if tools %}
    {{- '<|im_start|>system\\n' }}
    {%- if messages[0]['role'] == 'system' %}
        {{- messages[0]['content'] }}
    {%- endif %}
    {{- "<tools>" }}
    {%- for tool in tools %}
    {{- tool | tojson }}
    {%- endfor %}
    {{- "</tools>\\n" }}
{%- endif %}
{%- for message in messages %}
    {%- if message['role'] == 'user' %}
        {{- '<|im_start|>user\\n' + message['content'] + '<|im_end|>\\n' }}
    {%- elif message['role'] == 'assistant' %}
        {%- if message['reasoning_content'] %}
            {{- '<|im_start|>assistant\\n<think>\\n' + message['reasoning_content'] + '\\n</think>\\n' + message['content'] + '<|im_end|>\\n' }}
        {%- else %}
            {{- '<|im_start|>assistant\\n' + message['content'] + '<|im_end|>\\n' }}
        {%- endif %}
    {%- endif %}
{%- endfor %}
{%- if add_generation_prompt %}
    {{- '<|im_start|>assistant\\n' }}
    {%- if enable_thinking %}
        {{- '<think>\\n' }}
    {%- endif %}
{%- endif %}"""
    resolved, conf = _infer_template_from_jinja(qwen35_jinja)
    check("G1.7", "regression: plain Qwen3.5 Jinja still resolves to qwen3-thinking",
          resolved == "qwen3-thinking",
          f"expected qwen3-thinking, got {resolved} (conf={conf})")
    check("G1.7b", "confidence is HIGH",
          conf == Confidence.HIGH,
          f"expected HIGH, got {conf}")

    # G1.8: regression — plain ChatML Jinja (no thinking markers) → chatml
    plain_chatml_jinja = """{%- for message in messages %}
{{- '<|im_start|>' + message['role'] + '\\n' + message['content'] + '<|im_end|>\\n' }}
{%- endfor %}
{%- if add_generation_prompt %}
{{- '<|im_start|>assistant\\n' }}
{%- endif %}"""
    resolved, _ = _infer_template_from_jinja(plain_chatml_jinja)
    check("G1.8", "regression: plain ChatML Jinja → chatml",
          resolved == "chatml",
          f"expected chatml, got {resolved}")

    # G1.9: regression — Llama-3 Jinja → llama-3
    llama3_jinja = """{%- for message in messages %}
{{- '<|start_header_id|>' + message['role'] + '<|end_header_id|>\\n' + message['content'] + '<|eot_id|>\\n' }}
{%- endfor %}"""
    resolved, _ = _infer_template_from_jinja(llama3_jinja)
    check("G1.9", "regression: Llama-3 Jinja → llama-3",
          resolved == "llama-3",
          f"expected llama-3, got {resolved}")

    # G1.10: regression — GPT-OSS Jinja → gpt-oss
    gpt_oss_jinja = """{%- for message in messages %}
{{- '<|im_start|>' + message['role'] + '<|im_end|>\\n' }}
{%- if message['role'] == 'assistant' %}
{{- '<|channel|>analysis<|message|>' + message['content'] + '<|return|>' }}
{%- endif %}
{%- endfor %}"""
    resolved, _ = _infer_template_from_jinja(gpt_oss_jinja)
    check("G1.10", "regression: GPT-OSS Jinja → gpt-oss",
          resolved == "gpt-oss",
          f"expected gpt-oss, got {resolved}")

    # G1.11: regression — plain Mistral Jinja (no <think>) → mistral-v0-1
    plain_mistral_jinja = """{%- for message in messages %}
{%- if message['role'] == 'user' %}
{{- '[INST] ' + message['content'] + ' [/INST]\\n' }}
{%- else %}
{{- message['content'] + '</s>\\n' }}
{%- endif %}
{%- endfor %}"""
    resolved, _ = _infer_template_from_jinja(plain_mistral_jinja)
    check("G1.11", "regression: plain Mistral Jinja → mistral-v0-1",
          resolved == "mistral-v0-1",
          f"expected mistral-v0-1, got {resolved}")

    # G1.12: regression — plain Gemma Jinja (no <think>) → gemma3
    plain_gemma_jinja = """{%- for message in messages %}
{{- '<start_of_turn>' + message['role'] + '\\n' + message['content'] + '<end_of_turn>\\n' }}
{%- endfor %}"""
    resolved, _ = _infer_template_from_jinja(plain_gemma_jinja)
    check("G1.12", "regression: plain Gemma Jinja → gemma3",
          resolved == "gemma3",
          f"expected gemma3, got {resolved}")

    # G1.13: regression — plain Alpaca Jinja (no <think>) → alpaca
    # NOTE: ``### Instruction:`` / ``### Response:`` must be at the START of
    # a line (real newline before them) for the Alpaca pattern to match.
    plain_alpaca_jinja = (
        "{%- for message in messages %}\n"
        "{%- if message['role'] == 'user' %}\n"
        "### Instruction:\n"
        "{{- message['content'] }}\n"
        "{%- else %}\n"
        "### Response:\n"
        "{{- message['content'] }}\n"
        "{%- endif %}\n"
        "{%- endfor %}"
    )
    resolved, _ = _infer_template_from_jinja(plain_alpaca_jinja)
    check("G1.13", "regression: plain Alpaca Jinja → alpaca",
          resolved == "alpaca",
          f"expected alpaca, got {resolved}")


# ---------------------------------------------------------------------------
# G2 — KI#69: eos_token_id drift detection
# ---------------------------------------------------------------------------

def test_ki69_eos_drift():
    print("\n=== G2 — KI#69: eos_token_id drift detection ===")

    from app.utils.ai_clients.template_detector import (
        _CANONICAL_EOS_BY_TEMPLATE,
        _check_eos_drift,
    )

    # G2.1: canonical table has expected entries
    expected_families = [
        "qwen3-thinking", "qwen3-non-thinking", "qwen", "chatml",
        "llama-3", "mistral-v0-1", "mistral-v3-tekken", "gemma3", "gemma",
    ]
    for fam in expected_families:
        check(f"G2.1.{fam}", f"canonical eos entry for '{fam}'",
              fam in _CANONICAL_EOS_BY_TEMPLATE,
              f"missing {fam} from _CANONICAL_EOS_BY_TEMPLATE")

    # G2.2: canonical values are correct
    check("G2.2a", "qwen3-thinking canonical eos = [151645]",
          _CANONICAL_EOS_BY_TEMPLATE["qwen3-thinking"] == [151645],
          f"got {_CANONICAL_EOS_BY_TEMPLATE.get('qwen3-thinking')}")
    check("G2.2b", "chatml canonical eos = [151645]",
          _CANONICAL_EOS_BY_TEMPLATE["chatml"] == [151645],
          f"got {_CANONICAL_EOS_BY_TEMPLATE.get('chatml')}")
    check("G2.2c", "llama-3 canonical eos = [128001, 128008, 128009]",
          _CANONICAL_EOS_BY_TEMPLATE["llama-3"] == [128001, 128008, 128009],
          f"got {_CANONICAL_EOS_BY_TEMPLATE.get('llama-3')}")
    check("G2.2d", "mistral-v0-1 canonical eos = [2]",
          _CANONICAL_EOS_BY_TEMPLATE["mistral-v0-1"] == [2],
          f"got {_CANONICAL_EOS_BY_TEMPLATE.get('mistral-v0-1')}")
    check("G2.2e", "gemma3 canonical eos = [1]",
          _CANONICAL_EOS_BY_TEMPLATE["gemma3"] == [1],
          f"got {_CANONICAL_EOS_BY_TEMPLATE.get('gemma3')}")

    # G2.3: SKIPPED families (gpt-oss, command-r, phi-3, deepseek, alpaca)
    for skipped in ["gpt-oss", "command-r", "phi-3", "deepseek", "alpaca"]:
        check(f"G2.3.{skipped}", f"'{skipped}' intentionally NOT in canonical table",
              skipped not in _CANONICAL_EOS_BY_TEMPLATE,
              f"found {skipped} in table — should be skipped per KI#69 design")

    # G2.4: KEY TEST — Qwen3.5 eos=[248046] → DRIFT detected
    # (this is the actual case from the user's iter-88 verification log)
    warning = _check_eos_drift("qwen3-thinking", [248046])
    check("G2.4", "Qwen3.5 eos=[248046] → drift warning (iter-88 log case)",
          warning is not None and "248046" in warning and "151645" in warning,
          f"warning={warning!r}")

    # G2.5: Llama-3 eos=[128001] → NO drift (128001 is canonical)
    warning = _check_eos_drift("llama-3", [128001])
    check("G2.5", "Llama-3 eos=[128001] → no drift (128001 is canonical)",
          warning is None,
          f"warning={warning!r}")

    # G2.6: Mistral eos=[2] → NO drift (MN Violet Lotus case)
    warning = _check_eos_drift("mistral-v0-1", [2])
    check("G2.6", "Mistral eos=[2] → no drift (MN Violet Lotus case)",
          warning is None,
          f"warning={warning!r}")

    # G2.7: Gemma eos=[1] → NO drift (Gemma4 case from iter-88 log, before KI#68 fix)
    warning = _check_eos_drift("gemma3", [1])
    check("G2.7", "Gemma eos=[1] → no drift",
          warning is None,
          f"warning={warning!r}")

    # G2.8: Qwen3 eos=[151645] → NO drift (canonical)
    warning = _check_eos_drift("qwen3-thinking", [151645])
    check("G2.8", "Qwen3 eos=[151645] → no drift (canonical)",
          warning is None,
          f"warning={warning!r}")

    # G2.9: Qwen3 multi-eos=[151645, 151643] → NO drift (151645 is canonical)
    warning = _check_eos_drift("qwen3-thinking", [151645, 151643])
    check("G2.9", "Qwen3 multi-eos=[151645, 151643] → no drift",
          warning is None,
          f"warning={warning!r}")

    # G2.10: Llama-3 eos=[128009] → NO drift (128009 is <|eot_id|>, canonical)
    warning = _check_eos_drift("llama-3", [128009])
    check("G2.10", "Llama-3 eos=[128009] (<|eot_id|>) → no drift",
          warning is None,
          f"warning={warning!r}")

    # G2.11: Unknown template (e.g. "gpt-oss") → no drift check (skip)
    warning = _check_eos_drift("gpt-oss", [12345])
    check("G2.11", "Unknown template 'gpt-oss' → no drift check (skipped)",
          warning is None,
          f"warning={warning!r}")

    # G2.12: Empty eos_token_id → no drift check
    warning = _check_eos_drift("qwen3-thinking", [])
    check("G2.12", "Empty eos_token_id → no drift check",
          warning is None,
          f"warning={warning!r}")

    # G2.13: None eos_token_id → no drift check
    warning = _check_eos_drift("qwen3-thinking", None)
    check("G2.13", "None eos_token_id → no drift check",
          warning is None,
          f"warning={warning!r}")

    # G2.14: None resolved_name → no drift check
    warning = _check_eos_drift(None, [151645])
    check("G2.14", "None resolved_name → no drift check",
          warning is None,
          f"warning={warning!r}")

    # G2.15: Empty resolved_name → no drift check
    warning = _check_eos_drift("", [151645])
    check("G2.15", "Empty resolved_name → no drift check",
          warning is None,
          f"warning={warning!r}")

    # G2.16: warning message contains actionable text
    warning = _check_eos_drift("qwen3-thinking", [999999])
    check("G2.16", "drift warning contains 'EOS drift' prefix",
          warning is not None and warning.startswith("EOS drift:"),
          f"warning={warning!r}")
    check("G2.16b", "drift warning contains 'manual override' advice",
          warning is not None and "manual override" in warning.lower(),
          f"warning={warning!r}")
    check("G2.16c", "drift warning contains the GGUF eos value",
          warning is not None and "999999" in warning,
          f"warning={warning!r}")
    check("G2.16d", "drift warning contains the canonical eos value",
          warning is not None and "151645" in warning,
          f"warning={warning!r}")


# ---------------------------------------------------------------------------
# G3 — integration: detect_template() with real GGUF paths (if available)
# ---------------------------------------------------------------------------

def test_g3_integration_with_real_models():
    """If the user's GGUF files are available at the expected path,
    run detect_template() on them and verify KI#68 + KI#69 produce the
    correct results. Skipped (not FAIL) if files are not present — this
    is a Linux agent env without the multi-GB model files."""
    print("\n=== G3 — integration with real GGUF files (if available) ===")

    from app.utils.ai_clients.template_detector import detect_template

    # Expected models from the user's iter-88 verification log
    test_cases = [
        # (filename, expected_template, expected_eos_list, expect_drift_warning)
        ("Qwen3.5-9B-abliterated.Q5_K_M.gguf", "qwen3-thinking", [248046], True),
        ("Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf", "gemma3", [1], False),
        ("Meta-Llama-3-8B.Q4_K_M.gguf", "llama-3", [128001], False),
        ("MN-Violet-Lotus-12B.i1-Q4_K_M.gguf", "mistral-v0-1", [2], False),
    ]

    found_any = False
    for filename, expected_template, expected_eos, expect_drift in test_cases:
        # Try common model paths
        for base in [
            REPO_ROOT / "assets" / "local_llm",
            Path("/home/z/my-project/assets/local_llm"),
        ]:
            model_path = base / filename
            if model_path.exists():
                found_any = True
                try:
                    result = detect_template(str(model_path))
                    check(f"G3.{filename}.template",
                          f"{filename}: resolved_template_name={expected_template}",
                          result.resolved_template_name == expected_template,
                          f"expected {expected_template}, got {result.resolved_template_name}")
                    check(f"G3.{filename}.eos",
                          f"{filename}: stop_token_ids={expected_eos}",
                          result.stop_token_ids == expected_eos,
                          f"expected {expected_eos}, got {result.stop_token_ids}")
                    has_drift = any("EOS drift" in w for w in result.warnings)
                    check(f"G3.{filename}.drift",
                          f"{filename}: drift_warning={'expected' if expect_drift else 'not expected'}",
                          has_drift == expect_drift,
                          f"warnings={result.warnings}")
                except Exception as e:
                    check(f"G3.{filename}", f"{filename}: detect_template() succeeded",
                          False, f"exception: {e}")
                break

    if not found_any:
        print("  [SKIP] No GGUF files found in expected paths — G3 integration tests skipped")
        print("         (this is expected in the Linux agent env — models are gitignored per §4)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("iter-89 smoke test — KI#68 (pattern reorder) + KI#69 (eos drift)")
    print(f"REPO_ROOT = {REPO_ROOT}")
    print("=" * 70)
    test_ki68_pattern_reorder()
    test_ki69_eos_drift()
    test_g3_integration_with_real_models()
    print("\n" + "=" * 70)
    print(f"PASS: {PASS}   FAIL: {FAIL}")
    print("=" * 70)
    if FAIL:
        print("\nFAILURES:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
