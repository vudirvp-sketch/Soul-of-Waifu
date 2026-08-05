#!/usr/bin/env python3
"""iter-79 smoke tests — Diagnostics Panel in-place expand toggle.

Tests verify the new "More space" / "Less space" button that toggles
the embedded diagnostics text_edit height between 200px (normal) and
500px (expanded) WITHOUT opening a separate dialog.  This complements
the existing "Развернуть" button (iter-64, opens a separate 1200x800
dialog) and addresses the user's complaint:

  "окну диагностики нужна кнопка типа 'развернуть' а то листать и
   читать в крохотном фиксированном окне неудобно."

Uses pure source inspection (same pattern as iter-74/75/76/77/78 smoke
tests — avoids importing PyQt6 which can't be loaded in the Linux test env).

Run:  python scripts/iter79_smoke_test.py
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
DIAGNOSTICS_PANEL = REPO / "app" / "gui" / "diagnostics_panel.py"
RU_YAML = REPO / "app" / "translations" / "ru.yaml"
EN_YAML = REPO / "app" / "translations" / "en.yaml"


def _class_body_src(tree: ast.Module, class_name: str) -> str | None:
    """Return unparsed source of a class body."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.unparse(node)
    return None


def _method_body_src(tree: ast.Module, class_name: str, method_name: str) -> str | None:
    """Return unparsed source of a specific method inside a class."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return ast.unparse(item)
    return None


def main():
    print("=== iter-79 smoke tests ===\n")

    dp_src = DIAGNOSTICS_PANEL.read_text(encoding="utf-8")
    dp_tree = ast.parse(dp_src)

    # ==== Group 1: _expand_inplace_button created in _build_ui ====
    print("Group 1: _expand_inplace_button created in _build_ui")

    _result("G1.1 diagnostics_panel.py parses cleanly", True)

    build_ui_body = _method_body_src(dp_tree, "DiagnosticsPanel", "_build_ui")
    _result(
        "G1.2 _build_ui method exists",
        build_ui_body is not None,
        "method body found via AST",
    )

    if build_ui_body:
        # The new button must be created.
        _result(
            "G1.3 _expand_inplace_button created in _build_ui",
            "_expand_inplace_button" in build_ui_body
            and "QPushButton" in build_ui_body,
            "new in-place expand toggle button",
        )

        # The button must be connected to _on_expand_inplace_clicked.
        _result(
            "G1.4 button connected to _on_expand_inplace_clicked",
            "_on_expand_inplace_clicked" in build_ui_body
            and "clicked.connect" in build_ui_body,
            "click handler wired",
        )

        # The button must be added to the header layout.
        _result(
            "G1.5 button added to header layout",
            "header.addWidget(self._expand_inplace_button)" in build_ui_body,
            "button is in the header row",
        )

        # The button must have setFixedHeight(32) like other header buttons.
        _result(
            "G1.6 button has setFixedHeight(32)",
            "setFixedHeight(32)" in build_ui_body,
            "matches other header buttons (Refresh, Validate, etc.)",
        )

        # The button label must use the i18n key diagnostics_expand_inplace_button.
        _result(
            "G1.7 button label uses diagnostics_expand_inplace_button i18n key",
            "diagnostics_expand_inplace_button" in build_ui_body,
            "i18n key for 'More space' label",
        )

    # ==== Group 2: _inplace_expanded state variable in __init__ ====
    print("\nGroup 2: _inplace_expanded state variable in __init__")

    init_body = _method_body_src(dp_tree, "DiagnosticsPanel", "__init__")
    _result(
        "G2.1 __init__ method exists",
        init_body is not None,
        "method body found via AST",
    )

    if init_body:
        # The state variable must be initialized BEFORE _build_ui().
        # Check that _inplace_expanded = False appears before _build_ui() call.
        expanded_pos = init_body.find("_inplace_expanded")
        build_ui_pos = init_body.find("self._build_ui()")
        _result(
            "G2.2 _inplace_expanded initialized before _build_ui()",
            expanded_pos != -1 and build_ui_pos != -1 and expanded_pos < build_ui_pos,
            "prevents KI#56-style crash (init order matters)",
        )

        # The state variable must be a bool, initialized to False.
        _result(
            "G2.3 _inplace_expanded is bool, initialized to False",
            "_inplace_expanded: bool = False" in init_body
            or "_inplace_expanded = False" in init_body,
            "collapsed by default",
        )

    # ==== Group 3: _on_expand_inplace_clicked method ====
    print("\nGroup 3: _on_expand_inplace_clicked toggle method")

    toggle_body = _method_body_src(dp_tree, "DiagnosticsPanel", "_on_expand_inplace_clicked")
    _result(
        "G3.1 _on_expand_inplace_clicked method exists",
        toggle_body is not None,
        "method body found via AST",
    )

    if toggle_body:
        # The method must toggle _inplace_expanded.
        _result(
            "G3.2 method toggles _inplace_expanded",
            "not self._inplace_expanded" in toggle_body,
            "flips the state on each click",
        )

        # The method must call setMinimumHeight with the new height.
        _result(
            "G3.3 method calls setMinimumHeight",
            "setMinimumHeight" in toggle_body,
            "changes the text_edit min height",
        )

        # The method must call _sync_inplace_button_label.
        _result(
            "G3.4 method calls _sync_inplace_button_label",
            "_sync_inplace_button_label" in toggle_body,
            "updates button label after toggle",
        )

        # The method must reference both height constants.
        _result(
            "G3.5 method references _INPLACE_EXPANDED_HEIGHT",
            "_INPLACE_EXPANDED_HEIGHT" in toggle_body,
            "expanded height constant",
        )
        _result(
            "G3.6 method references _INPLACE_NORMAL_HEIGHT",
            "_INPLACE_NORMAL_HEIGHT" in toggle_body,
            "normal height constant",
        )

    # ==== Group 4: _sync_inplace_button_label method ====
    print("\nGroup 4: _sync_inplace_button_label method")

    sync_body = _method_body_src(dp_tree, "DiagnosticsPanel", "_sync_inplace_button_label")
    _result(
        "G4.1 _sync_inplace_button_label method exists",
        sync_body is not None,
        "method body found via AST",
    )

    if sync_body:
        # The method must check _inplace_expanded and set the appropriate label.
        _result(
            "G4.2 method checks _inplace_expanded state",
            "_inplace_expanded" in sync_body and "if" in sync_body,
            "conditional label based on state",
        )

        # The method must use diagnostics_collapse_inplace_button for expanded.
        _result(
            "G4.3 uses diagnostics_collapse_inplace_button when expanded",
            "diagnostics_collapse_inplace_button" in sync_body,
            "'Less space' label",
        )

        # The method must use diagnostics_expand_inplace_button for collapsed.
        _result(
            "G4.4 uses diagnostics_expand_inplace_button when collapsed",
            "diagnostics_expand_inplace_button" in sync_body,
            "'More space' label",
        )

        # The method must call setText on the button.
        _result(
            "G4.5 method calls setText on _expand_inplace_button",
            "_expand_inplace_button.setText" in sync_body,
            "updates the button label",
        )

    # ==== Group 5: height constants ====
    print("\nGroup 5: height constants")

    class_body = _class_body_src(dp_tree, "DiagnosticsPanel")
    if class_body:
        # _INPLACE_NORMAL_HEIGHT must be 200 (matches iter-74 default).
        _result(
            "G5.1 _INPLACE_NORMAL_HEIGHT = 200",
            "_INPLACE_NORMAL_HEIGHT = 200" in class_body,
            "matches iter-74 default min height",
        )

        # _INPLACE_EXPANDED_HEIGHT must be 500 (taller for reading).
        _result(
            "G5.2 _INPLACE_EXPANDED_HEIGHT = 500",
            "_INPLACE_EXPANDED_HEIGHT = 500" in class_body,
            "tall enough to read multi-block diagnostics without scrolling",
        )

    # ==== Group 6: i18n keys in both ru.yaml and en.yaml ====
    print("\nGroup 6: i18n keys in both ru.yaml and en.yaml")

    ru_src = RU_YAML.read_text(encoding="utf-8")
    en_src = EN_YAML.read_text(encoding="utf-8")

    # diagnostics_expand_inplace_button must be in both files.
    _result(
        "G6.1 diagnostics_expand_inplace_button in ru.yaml",
        "diagnostics_expand_inplace_button:" in ru_src,
        "'Больше места' label",
    )
    _result(
        "G6.2 diagnostics_expand_inplace_button in en.yaml",
        "diagnostics_expand_inplace_button:" in en_src,
        "'More space' label",
    )

    # diagnostics_collapse_inplace_button must be in both files.
    _result(
        "G6.3 diagnostics_collapse_inplace_button in ru.yaml",
        "diagnostics_collapse_inplace_button:" in ru_src,
        "'Меньше места' label",
    )
    _result(
        "G6.4 diagnostics_collapse_inplace_button in en.yaml",
        "diagnostics_collapse_inplace_button:" in en_src,
        "'Less space' label",
    )

    # Verify the ru.yaml values are Russian.
    for line in ru_src.splitlines():
        if line.startswith("diagnostics_expand_inplace_button:"):
            _result(
                "G6.5 ru.yaml value is Russian",
                "Больше места" in line,
                f"value: {line.split(':', 1)[1].strip()}",
            )
        if line.startswith("diagnostics_collapse_inplace_button:"):
            _result(
                "G6.6 ru.yaml collapse value is Russian",
                "Меньше места" in line,
                f"value: {line.split(':', 1)[1].strip()}",
            )

    # Verify the en.yaml values are English.
    for line in en_src.splitlines():
        if line.startswith("diagnostics_expand_inplace_button:"):
            _result(
                "G6.7 en.yaml value is English",
                "More space" in line,
                f"value: {line.split(':', 1)[1].strip()}",
            )
        if line.startswith("diagnostics_collapse_inplace_button:"):
            _result(
                "G6.8 en.yaml collapse value is English",
                "Less space" in line,
                f"value: {line.split(':', 1)[1].strip()}",
            )

    # ==== Group 7: existing "Развернуть" button still present (iter-64) ====
    print("\nGroup 7: existing 'Развернуть' button (iter-64) still present")

    # The existing _expand_button must still exist (iter-79 is ADDITIVE, not replacing).
    _result(
        "G7.1 existing _expand_button still created in _build_ui",
        "self._expand_button = QtWidgets.QPushButton" in dp_src,
        "iter-64 separate-dialog button preserved",
    )

    # The existing _on_expand_clicked method must still exist.
    _result(
        "G7.2 existing _on_expand_clicked method still exists",
        "def _on_expand_clicked(self):" in dp_src,
        "iter-64 separate-dialog handler preserved",
    )

    # The existing _ExpandedDiagnosticsDialog class must still exist.
    _result(
        "G7.3 existing _ExpandedDiagnosticsDialog class still exists",
        "class _ExpandedDiagnosticsDialog" in dp_src,
        "iter-64 separate dialog preserved",
    )

    # ==== Group 8: file syntax + sanity ====
    print("\nGroup 8: file syntax + sanity")

    _result("G8.1 diagnostics_panel.py syntax OK", True)

    # No duplicate _on_expand_inplace_clicked method.
    toggle_count = dp_src.count("def _on_expand_inplace_clicked(self):")
    _result(
        "G8.2 no duplicate _on_expand_inplace_clicked",
        toggle_count == 1,
        f"count={toggle_count} — additive-edit rule preserved",
    )

    # No duplicate _sync_inplace_button_label method.
    sync_count = dp_src.count("def _sync_inplace_button_label(self):")
    _result(
        "G8.3 no duplicate _sync_inplace_button_label",
        sync_count == 1,
        f"count={sync_count} — additive-edit rule preserved",
    )

    # iter-79 comment must be present.
    _result(
        "G8.4 iter-79 comment present",
        "iter-79" in dp_src,
        "documents the in-place expand toggle",
    )

    print(f"\n=== Summary: {PASS} PASS, {FAIL} FAIL ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
