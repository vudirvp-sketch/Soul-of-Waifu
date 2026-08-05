"""iter-72 smoke test: capability-aware UI — replaces _ENABLE_THINKING_TEMPLATES.

Q4 sub-iter 4 completion. Changes:
  - interface_signals.py: _update_enable_thinking_visibility() renamed to
    _update_capability_aware_visibility(), adds reasoning_mode visibility,
    replaces _ENABLE_THINKING_TEMPLATES name-set with
    _capability_map_from_template_name() lazy import.
  - diagnostics_panel.py: Block 4 uses capability_map instead of
    supports_enable_thinking() / ENABLE_THINKING_TEMPLATES.
  - template_capabilities.py: ENABLE_THINKING_TEMPLATES and
    supports_enable_thinking() marked as DEPRECATED.
  - ru.yaml + en.yaml: 2 new i18n keys each.

Groups:
  1. AST parse + py_compile on all changed files.
  2. _update_enable_thinking_visibility() NO LONGER EXISTS in interface_signals.py.
  3. _update_capability_aware_visibility() EXISTS and references
     _capability_map_from_template_name, caps_enable_thinking, caps_reasoning_budget.
  4. _ENABLE_THINKING_TEMPLATES import REMOVED from interface_signals.py.
  5. All 4 call sites use _update_capability_aware_visibility().
  6. _capability_map_from_template_name() handles all 13 combobox template names.
  7. Functional test: 12-case visibility decision matrix.
  8. diagnostics_panel.py: ENABLE_THINKING_TEMPLATES / supports_enable_thinking
     REMOVED from imports, capability_map used in Block 4.
  9. template_capabilities.py: DEPRECATED markers present.
  10. i18n keys: 2 new keys in both yaml files.
  11. No forbidden-path regressions.

Run: python scripts/iter72_smoke_test.py
"""
from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# --- Mock PyQt6 / qasync / heavy deps BEFORE importing -------------------
_MOCK_MODULES = [
    "PyQt6", "PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtGui",
    "qasync",
]
for mod_name in _MOCK_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# Mock gguf / hf_template_cache for template_detector
sys.modules.setdefault("gguf", MagicMock())
sys.modules.setdefault("app.utils.ai_clients.hf_template_cache", MagicMock())

# --- Paths + AST parse ---------------------------------------------------
IS_PATH = REPO_ROOT / "app" / "gui" / "interface_signals.py"
IS_SOURCE = IS_PATH.read_text(encoding="utf-8")
IS_AST = ast.parse(IS_SOURCE)

DIAG_PATH = REPO_ROOT / "app" / "gui" / "diagnostics_panel.py"
DIAG_SOURCE = DIAG_PATH.read_text(encoding="utf-8")
DIAG_AST = ast.parse(DIAG_SOURCE)

TC_PATH = REPO_ROOT / "app" / "utils" / "ai_clients" / "template_capabilities.py"
TC_SOURCE = TC_PATH.read_text(encoding="utf-8")

TD_PATH = REPO_ROOT / "app" / "utils" / "ai_clients" / "template_detector.py"
TD_SOURCE = TD_PATH.read_text(encoding="utf-8")

EN_YAML = (REPO_ROOT / "app" / "translations" / "en.yaml").read_text(encoding="utf-8")
RU_YAML = (REPO_ROOT / "app" / "translations" / "ru.yaml").read_text(encoding="utf-8")


# --- Helper: find method in class ----------------------------------------
def _find_method(class_body: list[ast.stmt], name: str) -> ast.FunctionDef | None:
    for node in class_body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _method_body_source(method: ast.FunctionDef) -> str:
    """Return the source of a method body as a single string."""
    lines = IS_SOURCE.splitlines()
    start = method.body[0].lineno - 1
    end = method.end_lineno if hasattr(method, 'end_lineno') else len(lines)
    return "\n".join(lines[start:end])


# =========================================================================
class TestIter72(unittest.TestCase):
    """iter-72 smoke tests."""

    # --- Group 1: AST parse + py_compile ---------------------------------
    def test_g1_ast_parse_all_files(self):
        """All 4 changed files parse cleanly."""
        for path in [IS_PATH, DIAG_PATH, TC_PATH, TD_PATH]:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                ast.parse(source)  # no SyntaxError

    def test_g1_py_compile_utils(self):
        """Utils files compile cleanly (no PyQt6 deps)."""
        import py_compile
        for path in [TC_PATH, TD_PATH]:
            with self.subTest(path=path.name):
                py_compile.compile(str(path), doraise=True)

    # --- Group 2: old method name removed --------------------------------
    def test_g2_old_method_name_removed(self):
        """_update_enable_thinking_visibility() NO LONGER EXISTS."""
        is_cls = _find_class(IS_AST, "InterfaceSignals")
        self.assertIsNotNone(is_cls)
        method = _find_method(is_cls.body, "_update_enable_thinking_visibility")
        self.assertIsNone(method, "old method name should be removed")

    # --- Group 3: new method exists with correct content -----------------
    def test_g3_new_method_exists(self):
        """_update_capability_aware_visibility() EXISTS."""
        is_cls = _find_class(IS_AST, "InterfaceSignals")
        self.assertIsNotNone(is_cls)
        method = _find_method(is_cls.body, "_update_capability_aware_visibility")
        self.assertIsNotNone(method, "new method name should exist")

    def test_g3_new_method_references_capability_map_from_name(self):
        """New method lazy-imports _capability_map_from_template_name."""
        method = _find_method(
            _find_class(IS_AST, "InterfaceSignals").body,
            "_update_capability_aware_visibility",
        )
        body = _method_body_source(method)
        self.assertIn("_capability_map_from_template_name", body)

    def test_g3_new_method_references_caps_enable_thinking(self):
        """New method uses caps_enable_thinking variable."""
        method = _find_method(
            _find_class(IS_AST, "InterfaceSignals").body,
            "_update_capability_aware_visibility",
        )
        body = _method_body_source(method)
        self.assertIn("caps_enable_thinking", body)

    def test_g3_new_method_references_caps_reasoning_budget(self):
        """New method uses caps_reasoning_budget variable."""
        method = _find_method(
            _find_class(IS_AST, "InterfaceSignals").body,
            "_update_capability_aware_visibility",
        )
        body = _method_body_source(method)
        self.assertIn("caps_reasoning_budget", body)

    def test_g3_new_method_sets_reasoning_mode_visible(self):
        """New method sets checkBox_reasoning_mode.setVisible."""
        method = _find_method(
            _find_class(IS_AST, "InterfaceSignals").body,
            "_update_capability_aware_visibility",
        )
        body = _method_body_source(method)
        self.assertIn("checkBox_reasoning_mode.setVisible", body)

    # --- Group 4: _ENABLE_THINKING_TEMPLATES import removed ---------------
    def test_g4_enable_thinking_templates_import_removed(self):
        """_ENABLE_THINKING_TEMPLATES import REMOVED from interface_signals.py."""
        # The import line should not exist as a top-level import
        for node in ast.walk(IS_AST):
            if isinstance(node, ast.ImportFrom):
                if node.module and "template_capabilities" in node.module:
                    for alias in node.names:
                        self.assertNotEqual(
                            alias.name,
                            "ENABLE_THINKING_TEMPLATES",
                            "ENABLE_THINKING_TEMPLATES should not be imported at module level",
                        )
        # Also check the class-level import is gone
        self.assertNotIn(
            "from app.utils.ai_clients.template_capabilities import ENABLE_THINKING_TEMPLATES",
            IS_SOURCE,
        )

    # --- Group 5: all 4 call sites use new name --------------------------
    def test_g5_all_call_sites_use_new_name(self):
        """All call sites use _update_capability_aware_visibility()."""
        # Count occurrences of old and new method calls
        old_count = IS_SOURCE.count("_update_enable_thinking_visibility()")
        new_count = IS_SOURCE.count("_update_capability_aware_visibility()")
        self.assertEqual(old_count, 0, "old method name should not be called")
        self.assertGreaterEqual(new_count, 4, "new method should be called at least 4 times")

    # --- Group 6: _capability_map_from_template_name handles all 13 names
    def test_g6_capability_map_from_template_name_combobox_items(self):
        """_capability_map_from_template_name() handles all 13 combobox items."""
        from app.utils.ai_clients.template_detector import _capability_map_from_template_name

        combobox_items = [
            "Auto", "ChatML", "Llama-3", "DeepSeek", "DeepSeek-R1",
            "Qwen", "Qwen3-Thinking", "Qwen3-Non-Thinking", "Mistral",
            "Mistral-v3-Tekken", "Mistral-v7-Tekken", "Gemma3", "Alpaca",
        ]
        for name in combobox_items:
            with self.subTest(template=name):
                caps = _capability_map_from_template_name(name)
                # Should return a CapabilityMap without error
                self.assertIsNotNone(caps)
                self.assertIsInstance(caps.enable_thinking, bool)
                self.assertIsInstance(caps.reasoning_budget, bool)

    def test_g6_qwen3_thinking_enable_thinking_true(self):
        """Qwen3-Thinking → enable_thinking=True."""
        from app.utils.ai_clients.template_detector import _capability_map_from_template_name
        caps = _capability_map_from_template_name("Qwen3-Thinking")
        self.assertTrue(caps.enable_thinking)

    def test_g6_qwen3_non_thinking_enable_thinking_true(self):
        """Qwen3-Non-Thinking → enable_thinking=True."""
        from app.utils.ai_clients.template_detector import _capability_map_from_template_name
        caps = _capability_map_from_template_name("Qwen3-Non-Thinking")
        self.assertTrue(caps.enable_thinking)

    def test_g6_llama3_enable_thinking_false(self):
        """Llama-3 → enable_thinking=False."""
        from app.utils.ai_clients.template_detector import _capability_map_from_template_name
        caps = _capability_map_from_template_name("Llama-3")
        self.assertFalse(caps.enable_thinking)

    def test_g6_mistral_enable_thinking_false(self):
        """Mistral → enable_thinking=False."""
        from app.utils.ai_clients.template_detector import _capability_map_from_template_name
        caps = _capability_map_from_template_name("Mistral")
        self.assertFalse(caps.enable_thinking)

    def test_g6_chatml_reasoning_budget_false(self):
        """ChatML → reasoning_budget=False."""
        from app.utils.ai_clients.template_detector import _capability_map_from_template_name
        caps = _capability_map_from_template_name("ChatML")
        self.assertFalse(caps.reasoning_budget)

    # --- Group 7: functional test — 12-case visibility decision matrix ---
    def test_g7_functional_12_cases(self):
        """Functional test: 12-case visibility decision matrix."""
        from app.utils.ai_clients.template_detector import (
            CapabilityMap,
            DetectionResult,
            DetectionSource,
            Confidence,
            _capability_map_from_template_name,
        )

        # Simulate the visibility logic from _update_capability_aware_visibility
        def compute_visibility(template, is_local_provider, detection=None):
            caps_enable_thinking = False
            caps_reasoning_budget = False
            is_capability_confirmed = False

            if template == "Auto" and is_local_provider:
                if detection is not None and detection.capability_map is not None:
                    caps_enable_thinking = bool(detection.capability_map.enable_thinking)
                    caps_reasoning_budget = bool(detection.capability_map.reasoning_budget)
                    is_capability_confirmed = True
                else:
                    caps_enable_thinking = True
                    caps_reasoning_budget = True
                    is_capability_confirmed = False
            elif template == "Auto" and not is_local_provider:
                caps_enable_thinking = True
                caps_reasoning_budget = True
                is_capability_confirmed = False
            else:
                caps = _capability_map_from_template_name(template)
                caps_enable_thinking = bool(caps.enable_thinking)
                caps_reasoning_budget = bool(caps.reasoning_budget)
                is_capability_confirmed = True

            return caps_enable_thinking, caps_reasoning_budget, is_capability_confirmed

        # Case 1: Auto + Local LLM + Qwen3 detection → enable_thinking=True, reasoning_budget=False
        det_qwen3 = DetectionResult(
            resolved_template_name="qwen3-thinking",
            source=DetectionSource.EMBEDDED,
            confidence=Confidence.HIGH,
            jinja_source="{% if enable_thinking %}",
            capability_map=CapabilityMap(enable_thinking=True, reasoning_budget=False),
        )
        et, rm, cc = compute_visibility("Auto", True, det_qwen3)
        self.assertTrue(et, "Case 1: enable_thinking should be visible")
        self.assertFalse(rm, "Case 1: reasoning_mode should be hidden")
        self.assertTrue(cc, "Case 1: capability confirmed")

        # Case 2: Auto + Local LLM + Llama-3 detection → enable_thinking=False, reasoning_budget=False
        det_llama3 = DetectionResult(
            resolved_template_name="llama-3",
            source=DetectionSource.EMBEDDED,
            confidence=Confidence.HIGH,
            jinja_source="{% if date_string %}",
            capability_map=CapabilityMap(enable_thinking=False, reasoning_budget=False),
        )
        et, rm, cc = compute_visibility("Auto", True, det_llama3)
        self.assertFalse(et, "Case 2: enable_thinking should be hidden")
        self.assertFalse(rm, "Case 2: reasoning_mode should be hidden")
        self.assertTrue(cc, "Case 2: capability confirmed")

        # Case 3: Auto + Local LLM + no detection → both visible, unconfirmed
        et, rm, cc = compute_visibility("Auto", True, None)
        self.assertTrue(et, "Case 3: enable_thinking visible (conservative)")
        self.assertTrue(rm, "Case 3: reasoning_mode visible (conservative)")
        self.assertFalse(cc, "Case 3: capability unconfirmed")

        # Case 4: Auto + Cloud → both visible, unconfirmed
        et, rm, cc = compute_visibility("Auto", False, None)
        self.assertTrue(et, "Case 4: enable_thinking visible (cloud)")
        self.assertTrue(rm, "Case 4: reasoning_mode visible (cloud)")
        self.assertFalse(cc, "Case 4: capability unconfirmed")

        # Case 5: Qwen3-Thinking explicit → enable_thinking=True
        et, rm, cc = compute_visibility("Qwen3-Thinking", True, None)
        self.assertTrue(et, "Case 5: enable_thinking visible")
        self.assertTrue(cc, "Case 5: capability confirmed")

        # Case 6: Qwen3-Non-Thinking explicit → enable_thinking=True
        et, rm, cc = compute_visibility("Qwen3-Non-Thinking", True, None)
        self.assertTrue(et, "Case 6: enable_thinking visible")
        self.assertTrue(cc, "Case 6: capability confirmed")

        # Case 7: Llama-3 explicit → enable_thinking=False
        et, rm, cc = compute_visibility("Llama-3", True, None)
        self.assertFalse(et, "Case 7: enable_thinking hidden")
        self.assertTrue(cc, "Case 7: capability confirmed")

        # Case 8: Mistral explicit → enable_thinking=False
        et, rm, cc = compute_visibility("Mistral", True, None)
        self.assertFalse(et, "Case 8: enable_thinking hidden")
        self.assertTrue(cc, "Case 8: capability confirmed")

        # Case 9: ChatML explicit → enable_thinking=False, reasoning_budget=False
        et, rm, cc = compute_visibility("ChatML", True, None)
        self.assertFalse(et, "Case 9: enable_thinking hidden")
        self.assertFalse(rm, "Case 9: reasoning_mode hidden")
        self.assertTrue(cc, "Case 9: capability confirmed")

        # Case 10: DeepSeek explicit → enable_thinking=False
        et, rm, cc = compute_visibility("DeepSeek", True, None)
        self.assertFalse(et, "Case 10: enable_thinking hidden")
        self.assertTrue(cc, "Case 10: capability confirmed")

        # Case 11: Gemma3 explicit → enable_thinking=False
        et, rm, cc = compute_visibility("Gemma3", True, None)
        self.assertFalse(et, "Case 11: enable_thinking hidden")
        self.assertTrue(cc, "Case 11: capability confirmed")

        # Case 12: Auto + Local LLM + gpt-oss detection (reasoning_budget=True)
        det_gptoss = DetectionResult(
            resolved_template_name="gpt-oss",
            source=DetectionSource.EMBEDDED,
            confidence=Confidence.HIGH,
            jinja_source="{% if reasoning_budget %}",
            capability_map=CapabilityMap(enable_thinking=False, reasoning_budget=True),
        )
        et, rm, cc = compute_visibility("Auto", True, det_gptoss)
        self.assertFalse(et, "Case 12: enable_thinking hidden")
        self.assertTrue(rm, "Case 12: reasoning_mode visible")
        self.assertTrue(cc, "Case 12: capability confirmed")

    # --- Group 8: diagnostics_panel.py changes ---------------------------
    def test_g8_diag_enable_thinking_templates_removed_from_imports(self):
        """ENABLE_THINKING_TEMPLATES and supports_enable_thinking REMOVED from diagnostics_panel imports."""
        for node in ast.walk(DIAG_AST):
            if isinstance(node, ast.ImportFrom):
                if node.module and "template_capabilities" in node.module:
                    imported_names = [alias.name for alias in node.names]
                    self.assertNotIn("ENABLE_THINKING_TEMPLATES", imported_names)
                    self.assertNotIn("supports_enable_thinking", imported_names)

    def test_g8_diag_capability_map_used_in_block4(self):
        """Block 4 uses capability_map / _capability_map_from_template_name."""
        self.assertIn("_capability_map_from_template_name", DIAG_SOURCE)
        self.assertIn("caps.enable_thinking", DIAG_SOURCE)
        self.assertIn("caps.reasoning_budget", DIAG_SOURCE)

    def test_g8_diag_reasoning_mode_visible_in_block4(self):
        """Block 4 shows reasoning_mode control visibility."""
        self.assertIn("reasoning_mode control visible", DIAG_SOURCE)

    # --- Group 9: template_capabilities.py deprecation markers -----------
    def test_g9_deprecated_markers_present(self):
        """DEPRECATED markers present in template_capabilities.py."""
        self.assertIn("DEPRECATED", TC_SOURCE)
        self.assertIn("iter-72", TC_SOURCE)

    def test_g9_enable_thinking_templates_still_exists(self):
        """ENABLE_THINKING_TEMPLATES constant still exists (backward compat)."""
        self.assertIn("ENABLE_THINKING_TEMPLATES", TC_SOURCE)

    def test_g9_supports_enable_thinking_still_exists(self):
        """supports_enable_thinking() function still exists (backward compat)."""
        self.assertIn("def supports_enable_thinking", TC_SOURCE)

    # --- Group 10: i18n keys ---------------------------------------------
    def test_g10_new_i18n_keys_en(self):
        """2 new i18n keys present in en.yaml."""
        self.assertIn("reasoning_mode_capability_unknown_tooltip:", EN_YAML)
        self.assertIn("reasoning_mode_tooltip:", EN_YAML)

    def test_g10_new_i18n_keys_ru(self):
        """2 new i18n keys present in ru.yaml."""
        self.assertIn("reasoning_mode_capability_unknown_tooltip:", RU_YAML)
        self.assertIn("reasoning_mode_tooltip:", RU_YAML)

    # --- Group 11: forbidden-path safety ---------------------------------
    def test_g11_no_forbidden_paths(self):
        """git status --porcelain shows only expected files, no binaries."""
        import subprocess
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        lines = result.stdout.strip().splitlines()
        forbidden_exts = {".dll", ".pyd", ".lib", ".pdb", ".wasm", ".exe",
                          ".pt", ".pth", ".bin", ".gguf", ".safetensors", ".onnx", ".ckpt"}
        forbidden_dirs = {".soul/", "app/data/", "app/cache/", "app/voices/",
                          "app/ffmpeg/", "app/font/", "logs/",
                          "app/utils/ai_clients/backend/",
                          "app/utils/all-MiniLM-L6-v2/",
                          "app/utils/emotions/detector/",
                          "assets/local_llm/", "assets/rvc_models/",
                          "assets/ambient/", "assets/backgrounds/",
                          "assets/emotions/images/", "assets/emotions/live2d/",
                          "assets/emotions/vrm/"}
        for line in lines:
            if not line.strip():
                continue
            filepath = line[3:]  # strip XY prefix
            ext = Path(filepath).suffix.lower()
            self.assertNotIn(ext, forbidden_exts, f"Forbidden binary: {filepath}")
            for d in forbidden_dirs:
                self.assertFalse(filepath.startswith(d), f"Forbidden dir: {filepath}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
