#!/usr/bin/env python3
"""iter-76 smoke tests — KI#57 reasoning_content + auto-fallthrough + KI#13 cleanup.

Tests cover three changes:
  1. KI#57: local_provider.py now yields reasoning_content from delta (wrapped
     in audiences markers, same pattern as deepseek_provider.py).
  2. Auto-fallthrough to Layer 2 on validation failure (strategy §13 step 4)
     in template_detector.py.
  3. KI#13: checkBox_enable_thinking widget removed from sowInterface.py and
     its handler removed from interface_signals.py.

Uses pure source inspection (same pattern as iter-74/75 smoke tests) — avoids
importing PyQt6 or the openai package directly.

Run:  python scripts/iter76_smoke_test.py
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
TEMPLATE_DETECTOR = REPO / "app" / "utils" / "ai_clients" / "template_detector.py"
SOW_INTERFACE = REPO / "app" / "gui" / "sowInterface.py"
INTERFACE_SIGNALS = REPO / "app" / "gui" / "interface_signals.py"


def _method_body_src(tree: ast.Module, class_name: str | None, method_name: str) -> str | None:
    """Return unparsed source of a specific method inside a class (or top-level)."""
    if class_name is None:
        # Top-level function
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
                return ast.unparse(node)
    else:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                        return ast.unparse(item)
    return None


def _class_source(tree: ast.Module, class_name: str) -> str | None:
    """Return unparsed source of a class."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.unparse(node)
    return None


def main():
    print("=== iter-76 smoke tests ===\n")

    # ==== Group 1: KI#57 — local_provider.py reasoning_content ====
    print("Group 1: KI#57 — local_provider.py reasoning_content handling")
    lp_src = LOCAL_PROVIDER.read_text(encoding="utf-8")
    lp_tree = ast.parse(lp_src)

    _result("G1.1 local_provider.py parses cleanly", True)

    gs_src = _method_body_src(lp_tree, "LocalProvider", "generate_stream")
    _result("G1.2 generate_stream method found", gs_src is not None)

    if gs_src:
        _result(
            "G1.3 reasoning_content accessed via getattr",
            'getattr(delta, ' in gs_src and 'reasoning_content' in gs_src,
            "getattr pattern not found",
        )
        _result(
            "G1.4 thinking markers emitted (audiences)",
            "thinking_active" in gs_src,
            "thinking_active variable not found",
        )
        _result(
            "G1.5 thinking block opened with  tag",
            "yield 'thinking" in gs_src,
            "opening tag not found",
        )
        _result(
            "G1.6 thinking block closed with  tag",
            "thinking_active = False" in gs_src and "yield '\\n" in gs_src,
            "closing tag not found",
        )
        _result(
            "G1.7 reasoning_chunks counter present",
            "reasoning_chunks" in gs_src,
            "reasoning_chunks counter not found",
        )
        _result(
            "G1.8 stream log includes reasoning_chunks",
            "reasoning_chunks=" in gs_src,
            "reasoning_chunks not in debug log",
        )
        # Check that the old text_chunks-only path is removed
        _result(
            "G1.9 old single-line content check removed",
            "chunk.choices[0].delta.content" not in gs_src or "if delta.content:" in gs_src,
            "old pattern may still exist",
        )

    # ==== Group 2: KI#57 — generate_summary also handles reasoning_content ====
    print("\nGroup 2: KI#57 — generate_summary reasoning_content handling")
    gsum_src = _method_body_src(lp_tree, "LocalProvider", "generate_summary")
    _result("G2.1 generate_summary method found", gsum_src is not None)

    if gsum_src:
        _result(
            "G2.2 reasoning_content accessed via getattr",
            'getattr(delta, ' in gsum_src and 'reasoning_content' in gsum_src,
            "getattr pattern not found",
        )
        _result(
            "G2.3 thinking tokens skipped (continue) in summary",
            "thinking_active" in gsum_src,
            "thinking_active variable not found",
        )

    # ==== Group 3: KI#57 — DeepSeek provider pattern consistency ====
    print("\nGroup 3: KI#57 — DeepSeek provider pattern consistency check")
    ds_src = DEEPSEEK_PROVIDER.read_text(encoding="utf-8")
    ds_tree = ast.parse(ds_src)

    ds_gs_src = _method_body_src(ds_tree, "DeepSeekProvider", "generate_stream")
    _result("G3.1 DeepSeek generate_stream method found", ds_gs_src is not None)

    if ds_gs_src:
        _result(
            "G3.2 DeepSeek uses same getattr pattern",
            'getattr(delta, ' in ds_gs_src and 'reasoning_content' in ds_gs_src,
            "getattr pattern not found in DeepSeek",
        )
        _result(
            "G3.3 DeepSeek uses thinking_active variable",
            "thinking_active" in ds_gs_src,
            "thinking_active variable not found in DeepSeek",
        )

    # ==== Group 4: Auto-fallthrough to Layer 2 ====
    print("\nGroup 4: Auto-fallthrough to Layer 2 on validation failure")
    td_src = TEMPLATE_DETECTOR.read_text(encoding="utf-8")
    td_tree = ast.parse(td_src)

    dt_src = _method_body_src(td_tree, None, "detect_template")
    _result("G4.1 detect_template function found", dt_src is not None)

    if dt_src:
        _result(
            "G4.2 auto-fallthrough check for EMBEDDED source",
            "DetectionSource.EMBEDDED" in dt_src,
            "EMBEDDED source check not found",
        )
        _result(
            "G4.3 fallthrough to architecture heuristic",
            "_resolve_template_from_arch" in dt_src,
            "arch resolution call not found",
        )
        _result(
            "G4.4 source changed to ARCH on fallthrough",
            "DetectionSource.ARCH" in dt_src,
            "ARCH source assignment not found",
        )
        _result(
            "G4.5 confidence downgraded to MED on fallthrough",
            "Confidence.MED" in dt_src,
            "MED confidence not found",
        )
        _result(
            "G4.6 warning appended to result.warnings",
            "result.warnings.append" in dt_src,
            "warning append not found",
        )
        _result(
            "G4.7 stop tokens re-resolved on fallthrough",
            "_TEMPLATE_IMPLIED_STOPS" in dt_src,
            "stop token re-resolution not found",
        )

    # ==== Group 5: KI#13 — checkBox_enable_thinking removed ====
    print("\nGroup 5: KI#13 — checkBox_enable_thinking removed from sowInterface.py")
    si_src = SOW_INTERFACE.read_text(encoding="utf-8")
    _result(
        "G5.1 no self.checkBox_enable_thinking widget creation",
        "self.checkBox_enable_thinking =" not in si_src,
        "widget creation still present",
    )
    _result(
        "G5.2 no addWidget(checkBox_enable_thinking)",
        "addWidget(self.checkBox_enable_thinking)" not in si_src,
        "addWidget call still present",
    )
    _result(
        "G5.3 KI#13 comment present (removal note)",
        "KI#13" in si_src,
        "KI#13 removal comment not found",
    )

    # ==== Group 6: KI#13 — handler removed from interface_signals.py ====
    print("\nGroup 6: KI#13 — handler removed from interface_signals.py")
    is_src = INTERFACE_SIGNALS.read_text(encoding="utf-8")

    _result(
        "G6.1 no on_checkBox_enable_thinking_stateChanged handler",
        "def on_checkBox_enable_thinking_stateChanged" not in is_src,
        "handler still defined",
    )
    _result(
        "G6.2 no self.ui.checkBox_enable_thinking.setChecked",
        "self.ui.checkBox_enable_thinking.setChecked" not in is_src,
        "setChecked call still present",
    )
    _result(
        "G6.3 no self.ui.checkBox_enable_thinking.setVisible",
        "self.ui.checkBox_enable_thinking.setVisible" not in is_src,
        "setVisible call still present",
    )
    _result(
        "G6.4 no self.ui.checkBox_enable_thinking.setToolTip",
        "self.ui.checkBox_enable_thinking.setToolTip" not in is_src,
        "setToolTip call still present",
    )
    _result(
        "G6.5 checkBox_reasoning_mode still referenced",
        "checkBox_reasoning_mode" in is_src,
        "reasoning_mode checkbox unexpectedly removed",
    )
    _result(
        "G6.6 KI#13 comment present in interface_signals.py",
        "KI#13" in is_src,
        "KI#13 removal comment not found",
    )

    # ==== Group 7: File syntax sanity ====
    print("\nGroup 7: File syntax sanity")
    for path, name in [
        (LOCAL_PROVIDER, "local_provider.py"),
        (TEMPLATE_DETECTOR, "template_detector.py"),
        (SOW_INTERFACE, "sowInterface.py"),
        (INTERFACE_SIGNALS, "interface_signals.py"),
    ]:
        try:
            ast.parse(path.read_text(encoding="utf-8"))
            _result(f"G7.x {name} parses cleanly", True)
        except SyntaxError as e:
            _result(f"G7.x {name} parses cleanly", False, str(e))

    print("\n" + "=" * 60)
    print(f"Results: {PASS} PASS, {FAIL} FAIL out of {PASS + FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
