"""iter-88 smoke test — verifies KI#66 + KI#67 fixes against the user's actual
runtime logs (llama_server_2026-08-01_02-33-40.log + sow_2026-08-01_02-33-40.log).

Two test groups:
  G1 — KI#66 (template_detector): Qwen3-thinking Jinja pattern correctly matches
       a real Qwen3.5 Jinja source (containing enable_thinking + <think>/</think>)
       and resolves to "qwen3-thinking" instead of "chatml".
  G2 — KI#67 (local_server_manager._parse_ui_progress): new patterns match the
       b10214 llama-server log lines from the user's log file, and would set
       model_loaded=True + UI status "online".

Run: python /home/z/my-project/scripts/iter88_smoke_test.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Ensure repo root is on sys.path so we can import app.utils.* without PyQt6.
REPO_ROOT = Path("/home/z/my-project/Soul-of-Waifu").resolve()
sys.path.insert(0, str(REPO_ROOT))

# We CANNOT import local_server_manager (PyQt6 not installed in this env),
# but we CAN import template_detector (it only depends on gguf + jinja2 +
# app.utils.ai_clients.hf_template_cache + app.utils.ai_clients.template_capabilities).
# For G2, we replicate the pattern-matching logic inline (no class import needed).

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
# G1 — KI#66: Qwen3-thinking Jinja pattern
# ---------------------------------------------------------------------------

def test_ki66_qwen3_thinking_pattern():
    print("\n=== G1 — KI#66: Qwen3-thinking Jinja pattern ===")

    # Import the module under test
    from app.utils.ai_clients.template_detector import (
        _JINJA_TEMPLATE_PATTERNS,
        _infer_template_from_jinja,
    )

    # G1.1: pattern exists in the list
    qwen3_entries = [
        (p, t, c) for (p, t, c) in _JINJA_TEMPLATE_PATTERNS
        if t == "qwen3-thinking"
    ]
    check("G1.1", "qwen3-thinking pattern exists in _JINJA_TEMPLATE_PATTERNS",
          len(qwen3_entries) == 1,
          f"expected 1 entry, found {len(qwen3_entries)}: {qwen3_entries}")

    if not qwen3_entries:
        return

    qwen3_pattern, qwen3_template, qwen3_conf = qwen3_entries[0]

    # G1.2: pattern is HIGH confidence
    from app.utils.ai_clients.template_detector import Confidence
    check("G1.2", "qwen3-thinking pattern is HIGH confidence",
          qwen3_conf == Confidence.HIGH,
          f"expected HIGH, got {qwen3_conf}")

    # G1.3: pattern placed BEFORE ChatML (ordering rule)
    chatml_idx = next(
        i for i, (p, t, c) in enumerate(_JINJA_TEMPLATE_PATTERNS)
        if t == "chatml"
    )
    qwen3_idx = next(
        i for i, (p, t, c) in enumerate(_JINJA_TEMPLATE_PATTERNS)
        if t == "qwen3-thinking"
    )
    check("G1.3", "qwen3-thinking pattern placed BEFORE ChatML",
          qwen3_idx < chatml_idx,
          f"qwen3 idx={qwen3_idx}, chatml idx={chatml_idx}")

    # G1.4: realistic Qwen3.5 Jinja source resolves to qwen3-thinking
    # (this is the canonical Qwen3 chat_template, containing enable_thinking + <think>)
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
    check("G1.4", "realistic Qwen3.5 Jinja (enable_thinking + <think>) resolves to qwen3-thinking",
          resolved == "qwen3-thinking",
          f"expected qwen3-thinking, got {resolved} (conf={conf})")
    check("G1.4b", "confidence is HIGH",
          conf == Confidence.HIGH,
          f"expected HIGH, got {conf}")

    # G1.5: plain ChatML Jinja (no enable_thinking, no <think>) still resolves to chatml
    plain_chatml_jinja = """{%- for message in messages %}
{{- '<|im_start|>' + message['role'] + '\\n' + message['content'] + '<|im_end|>\\n' }}
{%- endfor %}
{%- if add_generation_prompt %}
{{- '<|im_start|>assistant\\n' }}
{%- endif %}"""
    resolved, conf = _infer_template_from_jinja(plain_chatml_jinja)
    check("G1.5", "plain ChatML Jinja (no thinking markers) still resolves to chatml",
          resolved == "chatml",
          f"expected chatml, got {resolved} (conf={conf})")

    # G1.6: regression — Llama-3 Jinja still resolves to llama-3
    llama3_jinja = """{%- for message in messages %}
{{- '<|start_header_id|>' + message['role'] + '<|end_header_id|>\\n' + message['content'] + '<|eot_id|>\\n' }}
{%- endfor %}"""
    resolved, _ = _infer_template_from_jinja(llama3_jinja)
    check("G1.6", "regression: Llama-3 Jinja still resolves to llama-3",
          resolved == "llama-3",
          f"expected llama-3, got {resolved}")

    # G1.7: regression — GPT-OSS Jinja still resolves to gpt-oss
    gpt_oss_jinja = """{%- for message in messages %}
{{- '<|im_start|>' + message['role'] + '<|im_end|>\\n' }}
{%- if message['role'] == 'assistant' %}
{{- '<|channel|>analysis<|message|>' + message['content'] + '<|return|>' }}
{%- endif %}
{%- endfor %}"""
    resolved, _ = _infer_template_from_jinja(gpt_oss_jinja)
    check("G1.7", "regression: GPT-OSS Jinja still resolves to gpt-oss",
          resolved == "gpt-oss",
          f"expected gpt-oss, got {resolved}")

    # G1.8: regression — Mistral Jinja still resolves to mistral-v0-1
    mistral_jinja = """{%- for message in messages %}
{%- if message['role'] == 'user' %}
{{- '[INST] ' + message['content'] + ' [/INST]\\n' }}
{%- else %}
{{- message['content'] + '</s>\\n' }}
{%- endif %}
{%- endfor %}"""
    resolved, _ = _infer_template_from_jinja(mistral_jinja)
    check("G1.8", "regression: Mistral Jinja still resolves to mistral-v0-1",
          resolved == "mistral-v0-1",
          f"expected mistral-v0-1, got {resolved}")


# ---------------------------------------------------------------------------
# G2 — KI#67: _parse_ui_progress patterns match b10214 logs
# ---------------------------------------------------------------------------

def test_ki67_parse_ui_progress_patterns():
    print("\n=== G2 — KI#67: _parse_ui_progress patterns match b10214 logs ===")

    # We can't import local_server_manager (PyQt6). Instead, we replicate the
    # NEW pattern-matching logic from _parse_ui_progress (post-iter-88) and
    # verify it matches the actual b10214 log lines from the user's log file.

    # Replicate the post-iter-88 pattern logic
    def match_progress(decoded_line: str, model_loaded: bool) -> tuple[int | None, str | None, bool]:
        """Returns (progress_pct, label_key, sets_model_loaded) — or (None, None, False)."""
        if "main: loading model" in decoded_line or "load_model: loading model" in decoded_line:
            return (20, "model_loading_step_1", False)
        elif "print_info: file format" in decoded_line:
            return (40, "model_loading_step_2", False)
        elif "load_tensors: loading model tensors" in decoded_line:
            return (50, "model_loading_step_3", False)
        elif "llama_context: constructing llama_context" in decoded_line:
            return (70, "model_loading_step_4", False)
        elif ("main: model loaded" in decoded_line or "llama_server: model loaded" in decoded_line) and not model_loaded:
            return (85, "model_loading_step_5", False)
        elif "all slots are idle" in decoded_line or "listening on" in decoded_line:
            return (100, "model_loading_step_6", True)
        return (None, None, False)

    # G2.1: read actual b10214 log lines from user's llama_server log
    log_path = Path("/home/z/my-project/upload/llama_server_2026-08-01_02-33-40.log")
    if not log_path.exists():
        check("G2.1", "user's llama_server log file exists", False, f"path={log_path}")
        return

    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    # Strip the SOW logging prefix to recover the raw llama-server stream content
    # Each line looks like:
    #   "2026-08-01 02:36:26,059 [INFO] - Llama Server Stream: 0.00.100.797 W DEPRECATED: ..."
    # We want the part after "Llama Server Stream: "
    stream_lines = []
    for line in log_lines:
        if "Llama Server Stream: " in line:
            stream_lines.append(line.split("Llama Server Stream: ", 1)[1])
    check("G2.1", f"parsed {len(stream_lines)} raw stream lines from user's log",
          len(stream_lines) >= 4,
          f"expected >=4, got {len(stream_lines)}")

    # G2.2: at least one line matches the "loading model" pattern
    loading_matches = [
        l for l in stream_lines
        if match_progress(l, False)[0] == 20
    ]
    check("G2.2", "at least one stream line matches 'loading model' pattern (20%)",
          len(loading_matches) >= 1,
          f"matches: {loading_matches}")

    # G2.3: at least one line matches the "model loaded" pattern
    loaded_matches = [
        l for l in stream_lines
        if match_progress(l, False)[0] == 85
    ]
    check("G2.3", "at least one stream line matches 'model loaded' pattern (85%)",
          len(loaded_matches) >= 1,
          f"matches: {loaded_matches}")

    # G2.4: at least one line matches the "listening on" pattern (CRITICAL — this
    # is the readiness signal that sets model_loaded=True and transitions UI to online)
    listening_matches = [
        l for l in stream_lines
        if match_progress(l, False)[0] == 100
    ]
    check("G2.4", "at least one stream line matches 'listening on' pattern (100% + model_loaded=True)",
          len(listening_matches) >= 1,
          f"matches: {listening_matches}")

    # G2.5: simulating the full startup sequence — model_loaded becomes True
    model_loaded = False
    final_progress = 0
    sets_online_count = 0
    for line in stream_lines:
        pct, _, sets_loaded = match_progress(line, model_loaded)
        if pct is not None and pct > final_progress:
            final_progress = pct
        if sets_loaded:
            model_loaded = True
            sets_online_count += 1

    check("G2.5", "simulated startup sets model_loaded=True",
          model_loaded is True,
          f"final_progress={final_progress}, sets_online_count={sets_online_count}")
    check("G2.5b", "simulated startup reaches 100% progress",
          final_progress == 100,
          f"final_progress={final_progress}")

    # G2.6: regression — old `main:` format still matches
    old_lines = [
        "0.0 I main: loading model 'model.gguf'",
        "0.5 I main: model loaded",
        "0.6 I main: all slots are idle",
    ]
    model_loaded = False
    progresses = []
    for line in old_lines:
        pct, _, sets_loaded = match_progress(line, model_loaded)
        if pct is not None:
            progresses.append(pct)
        if sets_loaded:
            model_loaded = True
    check("G2.6", "regression: old `main:` format still matches all 3 stages",
          progresses == [20, 85, 100] and model_loaded is True,
          f"progresses={progresses}, model_loaded={model_loaded}")

    # G2.7: NEW: pure `listening on` line (without "all slots are idle") still
    # sets model_loaded=True. This is the b10214 readiness path.
    test_line = "0.03.094.345 I srv  llama_server: listening on http://127.0.0.1:48596"
    pct, _, sets_loaded = match_progress(test_line, False)
    check("G2.7", "pure 'listening on' line sets model_loaded=True",
          pct == 100 and sets_loaded is True,
          f"pct={pct}, sets_loaded={sets_loaded}")

    # G2.8: the actual `llama_server: model loaded` line matches (not just `main: model loaded`)
    test_line = "0.03.094.336 I srv  llama_server: model loaded"
    pct, _, _ = match_progress(test_line, False)
    check("G2.8", "'llama_server: model loaded' line matches (85%)",
          pct == 85,
          f"pct={pct}")

    # G2.9: the actual `load_model: loading model` line matches (not just `main: loading model`)
    test_line = "0.00.173.829 I srv    load_model: loading model 'assets\\local_llm\\Qwen3.5-9B-abliterated.Q5_K_M.gguf'"
    pct, _, _ = match_progress(test_line, False)
    check("G2.9", "'load_model: loading model' line matches (20%)",
          pct == 20,
          f"pct={pct}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("iter-88 smoke test — KI#66 (template detector) + KI#67 (local_server_manager)")
    print("=" * 70)
    test_ki66_qwen3_thinking_pattern()
    test_ki67_parse_ui_progress_patterns()
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
