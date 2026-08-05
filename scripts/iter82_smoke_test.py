#!/usr/bin/env python3
"""iter-82 smoke tests — UI slider for reasoning_budget_fraction.

Tests cover the iter-82 implementation of the user-controllable
``reasoning_budget_fraction`` slider.  The slider lets power users tune
the per-request thinking-vs-answer tradeoff (range 0.20-0.80, step 0.05,
default 0.60) without editing ``settings.json`` by hand.

Scope of iter-82 changes verified by these tests:
  1. ``local_provider.py``:
     - New class constants ``_REASONING_BUDGET_FRACTION_MIN`` (0.2) and
       ``_REASONING_BUDGET_FRACTION_MAX`` (0.8) for the clamp range.
     - New ``reasoning_budget_fraction: float = None`` kwarg in ``__init__``.
     - Stored as ``self._reasoning_budget_fraction`` (clamped to [0.2, 0.8]).
     - ``None`` → falls back to ``_REASONING_BUDGET_FRACTION = 0.6``.
     - ``_compute_reasoning_budget`` uses ``self._reasoning_budget_fraction``
       (NOT the class-level constant).
  2. ``ai_factory.py``:
     - Reads ``reasoning_budget_fraction`` from ``settings.json``.
     - Handles None (fresh install), str/number, and bad values.
     - Forwards to ``LocalProvider`` via the new kwarg.
  3. ``settings.json``:
     - New ``"reasoning_budget_fraction": 0.6`` key (default = iter-80 v2
       value, preserves behavior for existing users).
  4. ``sowInterface.py``:
     - New ``reasoning_budget_fraction_horizontalSlider`` widget.
     - New ``lineEdit_reasoning_budget_fraction`` widget.
     - Slider range 20-80 step 5 (maps to 0.20-0.80 step 0.05).
     - Both hidden by default (visibility toggled by capability logic).
  5. ``interface_signals.py``:
     - New ``initialize_reasoning_budget_fraction_horizontalSlider``.
     - New ``save_reasoning_budget_fraction_in_real_time``.
     - New ``update_reasoning_budget_fraction_from_line_edit``.
     - ``apply_main_settings_to_ui`` calls the new initialize method.
     - ``_update_capability_aware_visibility`` toggles slider visibility.
     - ``on_checkBox_reasoning_mode_stateChanged`` calls
       ``_update_capability_aware_visibility`` after persisting state.
  6. ``main.py``:
     - Slider ``valueChanged`` signal connected.
     - LineEdit ``editingFinished`` signal connected.
     - ``initialize_reasoning_budget_fraction_horizontalSlider`` called
       during initial slider setup.
  7. ``ru.yaml`` + ``en.yaml``:
     - ``reasoning_budget_fraction_text`` key present.
     - ``reasoning_budget_fraction_tooltip`` key present.

Tests use pure source inspection (same pattern as iter-74/75/76/77/78/79/80
smoke tests — avoids importing PyQt6 or the openai package which can't
be loaded in the Linux test env).

Run:  python scripts/iter82_smoke_test.py
"""
from __future__ import annotations

import ast
import json
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
AI_FACTORY = REPO / "app" / "utils" / "ai_clients" / "ai_factory.py"
SETTINGS_JSON = REPO / "app" / "configuration" / "settings.json"
SOW_INTERFACE = REPO / "app" / "gui" / "sowInterface.py"
INTERFACE_SIGNALS = REPO / "app" / "gui" / "interface_signals.py"
MAIN_PY = REPO / "main.py"
RU_YAML = REPO / "app" / "translations" / "ru.yaml"
EN_YAML = REPO / "app" / "translations" / "en.yaml"


def _method_body_src(tree: ast.Module, class_name: str, method_name: str) -> str | None:
    """Return unparsed source of a specific method inside a class."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return ast.unparse(item)
    return None


def _class_body_src(tree: ast.Module, class_name: str) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.unparse(node)
    return None


def _has_attr_in_init(tree: ast.Module, class_name: str, attr_name: str) -> bool:
    """Check if ``self.<attr_name>`` is assigned in __init__."""
    init_body = _method_body_src(tree, class_name, "__init__")
    if init_body is None:
        return False
    return f"self.{attr_name}" in init_body


def main():
    print("=== iter-82 smoke tests ===\n")

    # ==== Group 1: local_provider.py — class constants ====
    print("Group 1: local_provider.py — iter-82 class constants")
    lp_src = LOCAL_PROVIDER.read_text(encoding="utf-8")
    lp_tree = ast.parse(lp_src)
    _result("G1.1 local_provider.py parses cleanly", True)

    _result(
        "G1.2 _REASONING_BUDGET_FRACTION_MIN = 0.2 constant present",
        "_REASONING_BUDGET_FRACTION_MIN = 0.2" in lp_src,
        "lower bound of the clamp range",
    )
    _result(
        "G1.3 _REASONING_BUDGET_FRACTION_MAX = 0.8 constant present",
        "_REASONING_BUDGET_FRACTION_MAX = 0.8" in lp_src,
        "upper bound of the clamp range",
    )
    _result(
        "G1.4 _REASONING_BUDGET_FRACTION = 0.6 default constant preserved",
        "_REASONING_BUDGET_FRACTION = 0.6" in lp_src,
        "default fallback when kwarg is None — preserves iter-80 v2 behavior",
    )

    # ==== Group 2: local_provider.py — __init__ kwarg ====
    print("\nGroup 2: local_provider.py — __init__ kwarg")

    init_body = _method_body_src(lp_tree, "LocalProvider", "__init__")
    _result(
        "G2.1 __init__ method exists",
        init_body is not None,
        "method body found via AST",
    )

    if init_body:
        # ast.unparse normalises whitespace: "float = None" → "float=None",
        # so we check for the signature components separately.
        _result(
            "G2.2 __init__ accepts reasoning_budget_fraction: float kwarg",
            "reasoning_budget_fraction: float" in init_body
            and "reasoning_budget_fraction: float=None" in init_body,
            "optional kwarg, default None falls back to class constant",
        )
        _result(
            "G2.3 __init__ stores self._reasoning_budget_fraction",
            "self._reasoning_budget_fraction" in init_body,
            "stored as instance attribute (per-instance override)",
        )
        _result(
            "G2.4 __init__ clamps to [MIN, MAX] via max/min",
            "max(" in init_body and "min(" in init_body
            and "_REASONING_BUDGET_FRACTION_MIN" in init_body
            and "_REASONING_BUDGET_FRACTION_MAX" in init_body,
            "defensive backstop for hand-edited settings.json",
        )
        _result(
            "G2.5 __init__ falls back to _REASONING_BUDGET_FRACTION when kwarg is None",
            "_REASONING_BUDGET_FRACTION" in init_body and "is None" in init_body,
            "preserves iter-80 v2 behavior for fresh installs",
        )
        _result(
            "G2.6 __init__ handles float() conversion errors",
            "except" in init_body and "TypeError" in init_body and "ValueError" in init_body,
            "graceful degradation for non-numeric values",
        )

    # ==== Group 3: local_provider.py — _compute_reasoning_budget uses instance attr ====
    print("\nGroup 3: local_provider.py — _compute_reasoning_budget uses self._reasoning_budget_fraction")

    crb_body = _method_body_src(lp_tree, "LocalProvider", "_compute_reasoning_budget")
    _result(
        "G3.1 _compute_reasoning_budget method exists",
        crb_body is not None,
        "method body found via AST",
    )

    if crb_body:
        _result(
            "G3.2 _compute_reasoning_budget uses self._reasoning_budget_fraction",
            "self._reasoning_budget_fraction" in crb_body,
            "instance attribute, NOT class-level constant",
        )
        _result(
            "G3.3 _compute_reasoning_budget does NOT use bare _REASONING_BUDGET_FRACTION",
            "self._REASONING_BUDGET_FRACTION)" not in crb_body,
            "must use instance attr to honor per-instance override",
        )
        _result(
            "G3.4 _compute_reasoning_budget still uses _REASONING_BUDGET_MIN floor",
            "self._REASONING_BUDGET_MIN" in crb_body,
            "256-token floor preserved from iter-80 v2",
        )
        _result(
            "G3.5 _compute_reasoning_budget returns 0 when max_tokens <= 0",
            "max_tokens <= 0" in crb_body and "return 0" in crb_body,
            "no sub-cap when max_tokens is unset",
        )

    # ==== Group 4: ai_factory.py wiring ====
    print("\nGroup 4: ai_factory.py wiring")

    af_src = AI_FACTORY.read_text(encoding="utf-8")
    af_tree = ast.parse(af_src)
    _result("G4.1 ai_factory.py parses cleanly", True)

    _result(
        "G4.2 ai_factory.py reads 'reasoning_budget_fraction' from config",
        '"reasoning_budget_fraction"' in af_src and "get_main_setting" in af_src,
        "reads from settings.json::main_settings.reasoning_budget_fraction",
    )
    _result(
        "G4.3 ai_factory.py handles None (fresh install fallback)",
        "is None" in af_src and "reasoning_budget_fraction" in af_src,
        "passes None to LocalProvider when key absent → class-constant fallback",
    )
    _result(
        "G4.4 ai_factory.py handles float() conversion errors",
        "except" in af_src and "TypeError" in af_src and "ValueError" in af_src,
        "graceful degradation for non-numeric settings.json values",
    )
    _result(
        "G4.5 ai_factory.py forwards reasoning_budget_fraction to LocalProvider",
        "reasoning_budget_fraction=reasoning_budget_fraction" in af_src,
        "kwarg forwarding in the LocalProvider(...) constructor call",
    )
    _result(
        "G4.6 ai_factory.py iter-82 comment present",
        "iter-82" in af_src,
        "documents the rationale + clamp range",
    )

    # ==== Group 5: settings.json new key ====
    print("\nGroup 5: settings.json new key")

    settings = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
    main_settings = settings.get("main_settings", {})

    _result(
        "G5.1 reasoning_budget_fraction key present in settings.json",
        "reasoning_budget_fraction" in main_settings,
        "new schema-stable key (NOT a §5 trigger — additive default)",
    )
    _result(
        "G5.2 reasoning_budget_fraction default is 0.6",
        main_settings.get("reasoning_budget_fraction") == 0.6,
        f"actual: {main_settings.get('reasoning_budget_fraction')}",
    )
    _result(
        "G5.3 reasoning_budget_fraction adjacent to reasoning_mode (discoverability)",
        list(main_settings).index("reasoning_mode") < list(main_settings).index("reasoning_budget_fraction"),
        "placed near reasoning_mode for logical grouping",
    )

    # ==== Group 6: sowInterface.py UI widgets ====
    print("\nGroup 6: sowInterface.py UI widgets")

    si_src = SOW_INTERFACE.read_text(encoding="utf-8")
    si_tree = ast.parse(si_src)
    _result("G6.1 sowInterface.py parses cleanly", True)

    _result(
        "G6.2 reasoning_budget_fraction_horizontalSlider widget created",
        "reasoning_budget_fraction_horizontalSlider" in si_src
        and "QtWidgets.QSlider()" in si_src,
        "QSlider instance for the fraction",
    )
    _result(
        "G6.3 lineEdit_reasoning_budget_fraction widget created",
        "lineEdit_reasoning_budget_fraction" in si_src
        and "QtWidgets.QLineEdit()" in si_src,
        "QLineEdit for hand-typed values",
    )
    _result(
        "G6.4 slider range 20-80 (maps to 0.20-0.80)",
        "20, 80, 5" in si_src,
        "create_slider_row(min=20, max=80, step=5)",
    )
    _result(
        "G6.5 slider hidden by default (setVisible(False))",
        "reasoning_budget_fraction_horizontalSlider.setVisible(False)" in si_src,
        "visibility toggled by capability-aware logic in interface_signals.py",
    )
    _result(
        "G6.6 lineEdit hidden by default (setVisible(False))",
        "lineEdit_reasoning_budget_fraction.setVisible(False)" in si_src,
        "both widgets hidden initially — visibility synced via capability logic",
    )
    _result(
        "G6.7 iter-82 comment present in sowInterface.py",
        "iter-82" in si_src,
        "documents the slider placement + visibility logic",
    )
    _result(
        "G6.8 reasoning_budget_fraction_text i18n key used",
        "reasoning_budget_fraction_text" in si_src,
        "label uses i18n key, falls back to 'Reasoning Budget Fraction'",
    )
    _result(
        "G6.9 reasoning_budget_fraction_tooltip i18n key used",
        "reasoning_budget_fraction_tooltip" in si_src,
        "tooltip uses i18n key",
    )

    # ==== Group 7: interface_signals.py handlers ====
    print("\nGroup 7: interface_signals.py handlers")

    is_src = INTERFACE_SIGNALS.read_text(encoding="utf-8")
    is_tree = ast.parse(is_src)
    _result("G7.1 interface_signals.py parses cleanly", True)

    _result(
        "G7.2 initialize_reasoning_budget_fraction_horizontalSlider method exists",
        _method_body_src(is_tree, "InterfaceSignals", "initialize_reasoning_budget_fraction_horizontalSlider") is not None,
        "loads value from settings.json into slider on startup",
    )
    _result(
        "G7.3 save_reasoning_budget_fraction_in_real_time method exists",
        _method_body_src(is_tree, "InterfaceSignals", "save_reasoning_budget_fraction_in_real_time") is not None,
        "slider valueChanged handler — persists in real time",
    )
    _result(
        "G7.4 update_reasoning_budget_fraction_from_line_edit method exists",
        _method_body_src(is_tree, "InterfaceSignals", "update_reasoning_budget_fraction_from_line_edit") is not None,
        "lineEdit editingFinished handler — syncs from hand-typed value",
    )

    init_rbf = _method_body_src(is_tree, "InterfaceSignals", "initialize_reasoning_budget_fraction_horizontalSlider")
    if init_rbf:
        _result(
            "G7.5 initialize_* clamps to [0.2, 0.8]",
            "max(0.2" in init_rbf and "min(0.8" in init_rbf,
            "defensive backstop for hand-edited settings.json",
        )
        _result(
            "G7.6 initialize_* falls back to 0.6 when settings is None",
            "val = 0.6" in init_rbf,
            "preserves iter-80 v2 default for fresh installs",
        )
        _result(
            "G7.7 initialize_* handles float() conversion errors",
            "except" in init_rbf and "TypeError" in init_rbf and "ValueError" in init_rbf,
            "graceful degradation for non-numeric settings",
        )
        _result(
            "G7.8 initialize_* sets slider int value (val * 100)",
            "* 100" in init_rbf and "setValue" in init_rbf,
            "slider int range 20-80 = fraction 0.20-0.80",
        )
        _result(
            "G7.9 initialize_* displays 2-decimal format in lineEdit",
            ":.2f" in init_rbf,
            "e.g. '0.60', '0.45' — consistent display format",
        )

    save_rbf = _method_body_src(is_tree, "InterfaceSignals", "save_reasoning_budget_fraction_in_real_time")
    if save_rbf:
        # ast.unparse normalises "double quotes" → 'single quotes', so we
        # accept either form.
        _result(
            "G7.10 save_* persists to 'reasoning_budget_fraction' setting",
            ("reasoning_budget_fraction" in save_rbf and "update_main_setting" in save_rbf),
            "writes back to settings.json on every slider move",
        )
        _result(
            "G7.11 save_* divides slider int by 100.0 to get fraction",
            "/ 100.0" in save_rbf,
            "converts slider int (20-80) to fraction (0.20-0.80)",
        )
        _result(
            "G7.12 save_* does NOT call _maybe_restart_local_server",
            "_maybe_restart_local_server" not in save_rbf,
            "per-request field — no server restart needed (unlike reasoning_mode)",
        )

    # ==== Group 8: apply_main_settings_to_ui + visibility logic ====
    print("\nGroup 8: apply_main_settings_to_ui + visibility logic")

    ams_body = _method_body_src(is_tree, "InterfaceSignals", "apply_main_settings_to_ui")
    if ams_body:
        _result(
            "G8.1 apply_main_settings_to_ui calls initialize_reasoning_budget_fraction_horizontalSlider",
            "initialize_reasoning_budget_fraction_horizontalSlider" in ams_body,
            "syncs slider when user navigates to LLM Settings tab",
        )

    ucav_body = _method_body_src(is_tree, "InterfaceSignals", "_update_capability_aware_visibility")
    if ucav_body:
        _result(
            "G8.2 _update_capability_aware_visibility toggles slider visibility",
            "reasoning_budget_fraction_horizontalSlider.setVisible" in ucav_body,
            "slider visibility tied to capability + reasoning_mode state",
        )
        _result(
            "G8.3 _update_capability_aware_visibility toggles lineEdit visibility",
            "lineEdit_reasoning_budget_fraction.setVisible" in ucav_body,
            "both slider + lineEdit shown/hidden together",
        )
        _result(
            "G8.4 visibility checks checkBox_reasoning_mode.isChecked()",
            "checkBox_reasoning_mode.isChecked()" in ucav_body,
            "slider visible ONLY when checkbox is checked (avoids dead control)",
        )

    rmode_handler = _method_body_src(is_tree, "InterfaceSignals", "on_checkBox_reasoning_mode_stateChanged")
    if rmode_handler:
        _result(
            "G8.5 on_checkBox_reasoning_mode_stateChanged calls _update_capability_aware_visibility",
            "_update_capability_aware_visibility" in rmode_handler,
            "slider visibility syncs immediately when checkbox toggled",
        )

    # ==== Group 9: main.py signal connections ====
    print("\nGroup 9: main.py signal connections")

    main_src = MAIN_PY.read_text(encoding="utf-8")
    main_tree = ast.parse(main_src)
    _result("G9.1 main.py parses cleanly", True)

    _result(
        "G9.2 slider valueChanged connected to save_reasoning_budget_fraction_in_real_time",
        "reasoning_budget_fraction_horizontalSlider.valueChanged.connect" in main_src
        and "save_reasoning_budget_fraction_in_real_time" in main_src,
        "real-time persistence on slider move",
    )
    _result(
        "G9.3 lineEdit editingFinished connected to update_reasoning_budget_fraction_from_line_edit",
        "lineEdit_reasoning_budget_fraction.editingFinished.connect" in main_src
        and "update_reasoning_budget_fraction_from_line_edit" in main_src,
        "hand-typed value sync on Enter/focus-loss",
    )
    _result(
        "G9.4 initialize_reasoning_budget_fraction_horizontalSlider called in setup",
        "initialize_reasoning_budget_fraction_horizontalSlider" in main_src,
        "slider value loaded on startup before LLM Settings tab opened",
    )

    # ==== Group 10: i18n keys ====
    print("\nGroup 10: i18n keys (ru.yaml + en.yaml)")

    try:
        import yaml
        ru = yaml.safe_load(RU_YAML.read_text(encoding="utf-8"))
        en = yaml.safe_load(EN_YAML.read_text(encoding="utf-8"))
    except ImportError:
        # Fallback: simple grep
        ru_src = RU_YAML.read_text(encoding="utf-8")
        en_src = EN_YAML.read_text(encoding="utf-8")
        _result(
            "G10.1 ru.yaml has reasoning_budget_fraction_text",
            "reasoning_budget_fraction_text:" in ru_src,
            "i18n label key",
        )
        _result(
            "G10.2 ru.yaml has reasoning_budget_fraction_tooltip",
            "reasoning_budget_fraction_tooltip:" in ru_src,
            "i18n tooltip key",
        )
        _result(
            "G10.3 en.yaml has reasoning_budget_fraction_text",
            "reasoning_budget_fraction_text:" in en_src,
            "i18n label key",
        )
        _result(
            "G10.4 en.yaml has reasoning_budget_fraction_tooltip",
            "reasoning_budget_fraction_tooltip:" in en_src,
            "i18n tooltip key",
        )
    else:
        _result(
            "G10.1 ru.yaml has reasoning_budget_fraction_text",
            "reasoning_budget_fraction_text" in ru,
            f"value: {ru.get('reasoning_budget_fraction_text')!r}",
        )
        _result(
            "G10.2 ru.yaml has reasoning_budget_fraction_tooltip",
            "reasoning_budget_fraction_tooltip" in ru,
            "tooltip key present",
        )
        _result(
            "G10.3 en.yaml has reasoning_budget_fraction_text",
            "reasoning_budget_fraction_text" in en,
            f"value: {en.get('reasoning_budget_fraction_text')!r}",
        )
        _result(
            "G10.4 en.yaml has reasoning_budget_fraction_tooltip",
            "reasoning_budget_fraction_tooltip" in en,
            "tooltip key present",
        )

    # ==== Group 11: Regression — iter-80 v2 + iter-80.1 contracts preserved ====
    print("\nGroup 11: Regression — iter-80 v2 + iter-80.1 contracts preserved")

    _result(
        "G11.1 _REASONING_BUDGET_MESSAGE = 'Final Answer:' preserved",
        '_REASONING_BUDGET_MESSAGE = "Final Answer:"' in lp_src,
        "iter-80.1 opt-in injection constant",
    )
    _result(
        "G11.2 _REASONING_BUDGET_MIN = 256 preserved",
        "_REASONING_BUDGET_MIN = 256" in lp_src,
        "iter-80 v2 floor — models need some thinking room",
    )
    _result(
        "G11.3 reasoning_mode kwarg preserved",
        "reasoning_mode: bool = False" in lp_src,
        "iter-80 v2 sub-cap toggle",
    )
    _result(
        "G11.4 reasoning_budget_message_enabled kwarg preserved",
        "reasoning_budget_message_enabled: bool = False" in lp_src,
        "iter-80.1 opt-in message injection",
    )
    _result(
        "G11.5 _build_extra_body gates on self._reasoning_mode and max_tokens > 0",
        "self._reasoning_mode" in lp_src and "max_tokens > 0" in lp_src,
        "sub-cap only injected when reasoning on AND max_tokens > 0",
    )
    _result(
        "G11.6 iter-78 KI#59 consume-not-yield preserved",
        "getattr(delta, \"reasoning_content\", None)" in lp_src and "continue" in lp_src,
        "reasoning_content extracted + consumed silently",
    )
    _result(
        "G11.7 iter-79 REASONING_EXHAUSTED warning preserved",
        "REASONING_EXHAUSTED" in lp_src and "logger.warning" in lp_src,
        "warning when text_chunks=0 and reasoning_chunks>0",
    )

    # ==== Group 12: file sanity ====
    print("\nGroup 12: file sanity")

    _result(
        "G12.1 local_provider.py line count reasonable",
        650 <= len(lp_src.splitlines()) <= 850,
        f"{len(lp_src.splitlines())} lines (iter-80.1 baseline 669 + iter-82 additions)",
    )
    _result(
        "G12.2 no duplicate _compute_reasoning_budget method",
        lp_src.count("def _compute_reasoning_budget(") == 1,
        "additive-edit rule preserved (§4 rule #10)",
    )
    _result(
        "G12.3 no duplicate _build_extra_body method",
        lp_src.count("def _build_extra_body(") == 1,
        "additive-edit rule preserved",
    )
    _result(
        "G12.4 no duplicate initialize_reasoning_budget_fraction_horizontalSlider",
        is_src.count("def initialize_reasoning_budget_fraction_horizontalSlider(") == 1,
        "single method definition",
    )
    _result(
        "G12.5 no duplicate save_reasoning_budget_fraction_in_real_time",
        is_src.count("def save_reasoning_budget_fraction_in_real_time(") == 1,
        "single method definition",
    )

    print(f"\n=== Summary: {PASS} PASS, {FAIL} FAIL ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
