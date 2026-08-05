#!/usr/bin/env python3
"""iter-75 smoke tests — Maximize/Restore button on _ExpandedDiagnosticsDialog.

Uses pure source inspection (same pattern as iter-74 smoke tests) — avoids
importing diagnostics_panel.py directly because it transitively imports
``app.utils.ai_clients.providers.local_provider`` which requires the ``openai``
package (not installed in the Linux test env).

Run:  python scripts/iter75_smoke_test.py
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
PANEL = REPO / "app" / "gui" / "diagnostics_panel.py"
EN_YAML = REPO / "app" / "translations" / "en.yaml"
RU_YAML = REPO / "app" / "translations" / "ru.yaml"


def _class_source(tree: ast.Module, class_name: str) -> str | None:
    """Return the source-text slice of a class definition, or None if absent."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            # Reconstruct a minimal source view by walking its methods.
            return ast.unparse(node)
    return None


def _method_body_src(tree: ast.Module, class_name: str, method_name: str) -> str | None:
    """Return unparsed source of a specific method inside a class."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return ast.unparse(item)
    return None


def main():
    print("=== iter-75 smoke tests ===\n")

    src = PANEL.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # ---- Group 1: _ExpandedDiagnosticsDialog has iter-75 additions ----
    print("Group 1: _ExpandedDiagnosticsDialog has iter-75 additions")
    dialog_src = _class_source(tree, "_ExpandedDiagnosticsDialog")
    _result(
        "G1.1 class _ExpandedDiagnosticsDialog exists",
        dialog_src is not None,
        "class definition not found",
    )
    if dialog_src:
        _result(
            "G1.2 _maximize_button QPushButton created",
            "self._maximize_button = QtWidgets.QPushButton(" in dialog_src,
            "QPushButton instantiation not found",
        )
        _result(
            "G1.3 _maximize_button.clicked.connect(_on_maximize_clicked)",
            "self._maximize_button.clicked.connect(self._on_maximize_clicked)" in dialog_src,
            "signal/slot wiring not found",
        )
        _result(
            "G1.4 _on_maximize_clicked method defined",
            "def _on_maximize_clicked(self):" in dialog_src,
            "method definition not found",
        )
        _result(
            "G1.5 _sync_maximize_button_label method defined",
            "def _sync_maximize_button_label(self):" in dialog_src,
            "method definition not found",
        )
        _result(
            "G1.6 changeEvent override defined",
            "def changeEvent(self, event):" in dialog_src,
            "changeEvent override not found",
        )
        _result(
            "G1.7 keyPressEvent override defined",
            "def keyPressEvent(self, event):" in dialog_src,
            "keyPressEvent override not found",
        )

    # ---- Group 2: _on_maximize_clicked logic ----
    print("\nGroup 2: _on_maximize_clicked toggle logic")
    on_max = _method_body_src(tree, "_ExpandedDiagnosticsDialog", "_on_maximize_clicked")
    _result("G2.1 method resolved", on_max is not None, "method not found")
    if on_max:
        _result(
            "G2.2 checks isMaximized()",
            "self.isMaximized()" in on_max,
            "isMaximized() call missing",
        )
        _result(
            "G2.3 setWindowState(WindowMaximized) on maximize branch",
            "WindowMaximized" in on_max,
            "WindowMaximized branch missing",
        )
        _result(
            "G2.4 setWindowState(WindowNoState) on restore branch",
            "WindowNoState" in on_max,
            "WindowNoState branch missing",
        )

    # ---- Group 3: changeEvent reacts to WindowStateChange ----
    print("\nGroup 3: changeEvent WindowStateChange handling")
    ce = _method_body_src(tree, "_ExpandedDiagnosticsDialog", "changeEvent")
    _result("G3.1 method resolved", ce is not None, "method not found")
    if ce:
        _result(
            "G3.2 checks WindowStateChange event type",
            "WindowStateChange" in ce,
            "WindowStateChange check missing",
        )
        _result(
            "G3.3 calls _sync_maximize_button_label on state change",
            "self._sync_maximize_button_label()" in ce,
            "label sync call missing",
        )
        _result(
            "G3.4 delegates to super().changeEvent(event)",
            "super().changeEvent(event)" in ce,
            "super() delegation missing",
        )

    # ---- Group 4: keyPressEvent handles F11 + delegates other keys ----
    print("\nGroup 4: keyPressEvent F11 handling")
    kp = _method_body_src(tree, "_ExpandedDiagnosticsDialog", "keyPressEvent")
    _result("G4.1 method resolved", kp is not None, "method not found")
    if kp:
        _result(
            "G4.2 checks Key_F11",
            "Key_F11" in kp,
            "Key_F11 check missing",
        )
        _result(
            "G4.3 calls _on_maximize_clicked on F11",
            "self._on_maximize_clicked()" in kp,
            "maximize call missing",
        )
        _result(
            "G4.4 event.accept() on F11 (consumed)",
            "event.accept()" in kp,
            "event.accept() missing",
        )
        _result(
            "G4.5 delegates to super().keyPressEvent(event) for other keys",
            "super().keyPressEvent(event)" in kp,
            "super() delegation missing",
        )

    # ---- Group 5: _sync_maximize_button_label uses correct translation keys ----
    print("\nGroup 5: _sync_maximize_button_label translation keys")
    sync = _method_body_src(tree, "_ExpandedDiagnosticsDialog", "_sync_maximize_button_label")
    _result("G5.1 method resolved", sync is not None, "method not found")
    if sync:
        _result(
            "G5.2 uses diagnostics_restore_button key when maximized",
            "diagnostics_restore_button" in sync,
            "restore key missing",
        )
        _result(
            "G5.3 uses diagnostics_maximize_button key when not maximized",
            "diagnostics_maximize_button" in sync,
            "maximize key missing",
        )
        _result(
            "G5.4 defensive try/except (logger.debug on failure)",
            "logger.debug" in sync and "except Exception" in sync,
            "defensive pattern missing",
        )

    # ---- Group 6: button placement order in _build_ui ----
    print("\nGroup 6: button placement order in _build_ui")
    build = _method_body_src(tree, "_ExpandedDiagnosticsDialog", "_build_ui")
    _result("G6.1 _build_ui resolved", build is not None, "method not found")
    if build:
        i_render = build.find("header.addWidget(self._render_button)")
        i_maximize = build.find("header.addWidget(self._maximize_button)")
        i_stretch = build.find("header.addStretch()")
        i_close = build.find("header.addWidget(self._close_button)")
        _result(
            "G6.2 _render_button added before _maximize_button",
            i_render != -1 and i_maximize != -1 and i_render < i_maximize,
            f"render_idx={i_render}, max_idx={i_maximize}",
        )
        _result(
            "G6.3 _maximize_button added before stretch",
            i_maximize != -1 and i_stretch != -1 and i_maximize < i_stretch,
            f"max_idx={i_maximize}, stretch_idx={i_stretch}",
        )
        _result(
            "G6.4 stretch added before _close_button",
            i_stretch != -1 and i_close != -1 and i_stretch < i_close,
            f"stretch_idx={i_stretch}, close_idx={i_close}",
        )

    # ---- Group 7: translations present in both yaml files ----
    print("\nGroup 7: translations present (en + ru)")
    import yaml
    en = yaml.safe_load(EN_YAML.read_text(encoding="utf-8"))
    ru = yaml.safe_load(RU_YAML.read_text(encoding="utf-8"))

    _result(
        "G7.1 en.yaml has diagnostics_maximize_button",
        "diagnostics_maximize_button" in en,
        "key missing",
    )
    _result(
        "G7.2 en.yaml has diagnostics_restore_button",
        "diagnostics_restore_button" in en,
        "key missing",
    )
    _result(
        "G7.3 ru.yaml has diagnostics_maximize_button",
        "diagnostics_maximize_button" in ru,
        "key missing",
    )
    _result(
        "G7.4 ru.yaml has diagnostics_restore_button",
        "diagnostics_restore_button" in ru,
        "key missing",
    )
    _result(
        "G7.5 en.yaml Maximize value is 'Maximize'",
        en.get("diagnostics_maximize_button") == "Maximize",
        f"got: {en.get('diagnostics_maximize_button')!r}",
    )
    _result(
        "G7.6 en.yaml Restore value is 'Restore'",
        en.get("diagnostics_restore_button") == "Restore",
        f"got: {en.get('diagnostics_restore_button')!r}",
    )
    _result(
        "G7.7 ru.yaml Maximize value is non-empty",
        isinstance(ru.get("diagnostics_maximize_button"), str)
        and len(ru.get("diagnostics_maximize_button")) > 0,
        f"got: {ru.get('diagnostics_maximize_button')!r}",
    )
    _result(
        "G7.8 ru.yaml Restore value is non-empty",
        isinstance(ru.get("diagnostics_restore_button"), str)
        and len(ru.get("diagnostics_restore_button")) > 0,
        f"got: {ru.get('diagnostics_restore_button')!r}",
    )

    # ---- Group 8: no duplicate method definitions ----
    print("\nGroup 8: no duplicate method definitions (additive-edit rule)")
    method_counts: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "_ExpandedDiagnosticsDialog":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_counts[item.name] = method_counts.get(item.name, 0) + 1

    dups = sorted(n for n, c in method_counts.items() if c > 1)
    _result(
        "G8.1 no duplicate methods in _ExpandedDiagnosticsDialog",
        not dups,
        f"duplicates: {dups}",
    )
    _result(
        "G8.2 _on_maximize_clicked defined exactly once",
        method_counts.get("_on_maximize_clicked", 0) == 1,
        f"count: {method_counts.get('_on_maximize_clicked', 0)}",
    )
    _result(
        "G8.3 _sync_maximize_button_label defined exactly once",
        method_counts.get("_sync_maximize_button_label", 0) == 1,
        f"count: {method_counts.get('_sync_maximize_button_label', 0)}",
    )
    _result(
        "G8.4 changeEvent defined exactly once",
        method_counts.get("changeEvent", 0) == 1,
        f"count: {method_counts.get('changeEvent', 0)}",
    )
    _result(
        "G8.5 keyPressEvent defined exactly once",
        method_counts.get("keyPressEvent", 0) == 1,
        f"count: {method_counts.get('keyPressEvent', 0)}",
    )

    # ---- Group 9: file syntax + line count sanity ----
    print("\nGroup 9: file syntax sanity")
    try:
        ast.parse(src)
        _result("G9.1 diagnostics_panel.py parses cleanly", True)
    except SyntaxError as e:
        _result("G9.1 diagnostics_panel.py parses cleanly", False, str(e))

    total_lines = src.count("\n") + 1
    _result(
        "G9.2 file line count reasonable (2200-2400)",
        2200 <= total_lines <= 2400,
        f"got {total_lines} lines (iter-74 baseline was 2176, +~30 expected)",
    )

    # ---- Group 10: translations file still parses (YAML sanity) ----
    print("\nGroup 10: YAML files parse cleanly")
    try:
        yaml.safe_load(EN_YAML.read_text(encoding="utf-8"))
        _result("G10.1 en.yaml parses OK", True)
    except Exception as e:
        _result("G10.1 en.yaml parses OK", False, str(e))
    try:
        yaml.safe_load(RU_YAML.read_text(encoding="utf-8"))
        _result("G10.2 ru.yaml parses OK", True)
    except Exception as e:
        _result("G10.2 ru.yaml parses OK", False, str(e))

    # ---- Summary ----
    print(f"\n{'='*60}")
    print(f"Results: {PASS} PASS, {FAIL} FAIL out of {PASS+FAIL}")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
