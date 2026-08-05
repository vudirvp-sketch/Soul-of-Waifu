#!/usr/bin/env python3
"""iter-74 smoke tests — expanded dialog size + font + embedded panel minimum height.

Run:  python scripts/iter74_smoke_test.py
"""

import ast
import sys
import textwrap

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


def main():
    panel_path = "app/gui/diagnostics_panel.py"

    # ---- Group 1: _ExpandedDiagnosticsDialog size constraints ----
    with open(panel_path, "r", encoding="utf-8") as f:
        source = f.read()

    _result(
        "Expanded dialog resize(1200, 800)",
        "self.resize(1200, 800)" in source,
        "default size increased from 1000x700",
    )
    _result(
        "Expanded dialog setMinimumSize(800, 600)",
        "self.setMinimumSize(800, 600)" in source,
        "prevents dialog from being resized too small",
    )

    # ---- Group 2: Expanded dialog font size ----
    _result(
        "Expanded dialog font-size: 15px",
        "font-size: 15px" in source,
        "increased from 13px for comfortable reading",
    )
    _result(
        "Expanded dialog padding: 12px",
        "padding: 12px" in source,
        "increased from 10px for comfortable reading",
    )

    # ---- Group 3: Embedded panel minimum height ----
    _result(
        "Embedded panel text edit setMinimumHeight(200)",
        "self._text_edit.setMinimumHeight(200)" in source,
        "prevents text edit from being squished to nothing",
    )

    # ---- Group 4: Expand button still exists ----
    _result(
        "Expand button exists",
        'diagnostics_expand_button' in source,
        "expand button from iter-64 unchanged",
    )

    # ---- Group 5: Syntax check ----
    try:
        ast.parse(source)
        _result("diagnostics_panel.py syntax", True)
    except SyntaxError as e:
        _result("diagnostics_panel.py syntax", False, str(e))

    # ---- Group 6: No duplicate minimum height ----
    count = source.count("setMinimumHeight")
    _result(
        "No duplicate setMinimumHeight",
        count == 1,
        f"found {count} occurrences (expected 1)",
    )

    print(f"\n{'='*60}")
    print(f"Results: {PASS} PASS, {FAIL} FAIL out of {PASS+FAIL}")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
