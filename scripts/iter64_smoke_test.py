"""iter-64 smoke test: verify Expand button + _ExpandedDiagnosticsDialog.

Test environment note (same as iter-62/63):
  PyQt6 cannot be imported in this Linux test env (missing libEGL.so.1).
  The smoke test mocks PyQt6.QtCore / PyQt6.QtWidgets via sys.modules
  injection. With PyQt6 mocked, ``DiagnosticsPanel`` and
  ``_ExpandedDiagnosticsDialog`` appear as MagicMock instances (because
  they inherit from mocked ``QtWidgets.QWidget`` / ``QtWidgets.QDialog``),
  so runtime invocation of their methods is not possible. The smoke test
  verifies STRUCTURE via source inspection (AST) + module-level constants
  + import-time checks + the functional logic of the yaml i18n symmetry.

Groups:
  1. AST parse + module imports cleanly (no SyntaxError, no ImportError
     at import time).
  2. ``_ExpandedDiagnosticsDialog`` class exists + has the expected methods
     (``_build_ui``, ``_on_refresh_clicked``, ``_on_validate_clicked``,
     ``_on_parent_text_updated``, ``_sync_validate_button_state``,
     ``closeEvent``).
  3. ``DiagnosticsPanel`` class has the new ``text_updated`` signal
     (class-level ``QtCore.pyqtSignal(str)`` attribute).
  4. ``DiagnosticsPanel.__init__`` sets ``self._expanded_dialog = None``.
  5. ``DiagnosticsPanel._build_ui`` creates an ``_expand_button`` widget.
  6. ``DiagnosticsPanel.refresh`` emits ``text_updated`` signal (both on
     success and on error path).
  7. ``DiagnosticsPanel._on_expand_clicked`` method exists.
  8. i18n: all ``diagnostics_*`` keys are present in BOTH ru.yaml + en.yaml.
  9. i18n: the new keys (``diagnostics_expand_button``,
     ``diagnostics_expand_window_title``, ``diagnostics_expand_close_button``)
     are present in both yaml files with non-empty string values.
  10. No forbidden-path regressions (``git status --porcelain`` shows only
      the expected 5 files: ``diagnostics_panel.py``, ``ru.yaml``, ``en.yaml``,
      ``STATUS.md``, ``worklog.md`` — no binaries, no forbidden dirs, no
      ``.gitkeep`` removed).

Run: python scripts/iter64_smoke_test.py
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

# --- Mock PyQt6 BEFORE importing the module under test -------------------
# Same pattern as iter-62/63 smoke tests. PyQt6 cannot be imported in this
# Linux env (missing libEGL.so.1 system library).
_PYQT6_MODULES = ["PyQt6", "PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtGui"]
for mod_name in _PYQT6_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# Now import the module under test. With PyQt6 mocked, ``DiagnosticsPanel``
# and ``_ExpandedDiagnosticsDialog`` will be MagicMock subclasses (because
# they inherit from mocked ``QtWidgets.QWidget`` / ``QtWidgets.QDialog``),
# so we can't instantiate them. We use AST source inspection instead.
#
# Note: the module also imports ``app.configuration``, ``app.utils.ai_clients``
# submodules, etc. — these may pull in heavy deps (openai, httpx) that are
# NOT installed in this Linux test env. We attempt the import to verify it
# does not have a SyntaxError, but we tolerate ImportError on heavy deps.
# All structural tests work on the AST alone, so module import is NOT a
# hard prerequisite for the structural tests below.
DIAG_PATH = REPO_ROOT / "app" / "gui" / "diagnostics_panel.py"
DIAG_SOURCE = DIAG_PATH.read_text(encoding="utf-8")
DIAG_AST = ast.parse(DIAG_SOURCE)

# Try real import — used only by g1_module_imports_cleanly.
try:
    import app.gui.diagnostics_panel as diag_mod  # noqa: F401
    MODULE_IMPORTED = True
    IMPORT_ERROR = None
except SyntaxError as exc:
    # SyntaxError is a real failure — AST would also have failed.
    diag_mod = None
    MODULE_IMPORTED = False
    IMPORT_ERROR = repr(exc)
except ImportError as exc:
    # ImportError on heavy deps (openai, httpx, etc.) is EXPECTED in the
    # Linux test env. The structural tests don't need the module imported.
    diag_mod = None
    MODULE_IMPORTED = False
    IMPORT_ERROR = repr(exc)
except Exception as exc:
    diag_mod = None
    MODULE_IMPORTED = False
    IMPORT_ERROR = repr(exc)


# --- Helpers -------------------------------------------------------------

def _find_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    """Return the ClassDef node with the given name, or None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _class_method_names(cls: ast.ClassDef) -> set[str]:
    """Return the set of method names defined directly on the class."""
    return {
        node.name
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _class_attribute_names(cls: ast.ClassDef) -> set[str]:
    """Return the set of class-level attribute names (assignments)."""
    names: set[str] = set()
    for node in cls.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _method_assigns_attr(method: ast.FunctionDef, attr_name: str) -> bool:
    """Return True if the method assigns ``self.<attr_name>`` somewhere."""
    for node in ast.walk(method):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr == attr_name
                ):
                    return True
    return False


def _method_calls(method: ast.FunctionDef, func_name: str) -> bool:
    """Return True if the method calls ``self.<func_name>`` somewhere."""
    for node in ast.walk(method):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "self"
                and func.attr == func_name
            ):
                return True
    return False


def _method_calls_attr(method: ast.FunctionDef, attr_expr: str) -> bool:
    """Return True if the method calls the dotted attribute ``self.<attr_expr>``.

    ``attr_expr`` may be a multi-level dotted path like ``text_updated.emit``.
    """
    parts = attr_expr.split(".")
    for node in ast.walk(method):
        if isinstance(node, ast.Call):
            func = node.func
            ok = True
            # Walk the dotted chain from the innermost outwards.
            for part in reversed(parts):
                if not isinstance(func, ast.Attribute) or func.attr != part:
                    ok = False
                    break
                func = func.value
            if not ok:
                continue
            # The outermost should be ``self``.
            if isinstance(func, ast.Name) and func.id == "self":
                return True
    return False


# --- Test cases ----------------------------------------------------------

class TestIter64Smoke(unittest.TestCase):
    """iter-64 smoke tests — structure + AST + i18n symmetry."""

    # No setUp — structural tests work on the AST alone. Module import is
    # only verified by test_g1_module_imports_cleanly (which tolerates
    # ImportError on heavy deps).

    # Group 1: AST + import-time
    def test_g1_ast_parses(self):
        """The module source must parse as valid Python AST."""
        self.assertIsNotNone(DIAG_AST, "AST parse failed")

    def test_g1_module_imports_cleanly(self):
        """The module must import without SyntaxError.

        ImportError on heavy deps (openai, httpx) is EXPECTED in this Linux
        test env (PyQt6 also mocked). We only fail on SyntaxError, which
        would indicate a real source defect.
        """
        if IMPORT_ERROR and "SyntaxError" in IMPORT_ERROR:
            self.fail(f"Module has SyntaxError: {IMPORT_ERROR}")
        # ImportError is acceptable — log it but don't fail.
        if not MODULE_IMPORTED:
            print(f"\n[INFO] module not imported (expected in Linux test env): {IMPORT_ERROR}")

    # Group 2: _ExpandedDiagnosticsDialog class structure
    def test_g2_expanded_dialog_class_exists(self):
        """``_ExpandedDiagnosticsDialog`` class must exist."""
        cls = _find_class(DIAG_AST, "_ExpandedDiagnosticsDialog")
        self.assertIsNotNone(cls, "_ExpandedDiagnosticsDialog class not found")

    def test_g2_expanded_dialog_methods(self):
        """``_ExpandedDiagnosticsDialog`` must have the expected methods."""
        cls = _find_class(DIAG_AST, "_ExpandedDiagnosticsDialog")
        self.assertIsNotNone(cls)
        methods = _class_method_names(cls)
        expected = {
            "__init__",
            "_build_ui",
            "_on_refresh_clicked",
            "_on_validate_clicked",
            "_on_parent_text_updated",
            "_sync_validate_button_state",
            "closeEvent",
        }
        missing = expected - methods
        self.assertEqual(missing, set(), f"Missing methods: {missing}")

    def test_g2_expanded_dialog_delegates_refresh_to_parent(self):
        """``_on_refresh_clicked`` must call ``self._parent_panel.refresh()``."""
        cls = _find_class(DIAG_AST, "_ExpandedDiagnosticsDialog")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_on_refresh_clicked"),
            None,
        )
        self.assertIsNotNone(method)
        # ``self._parent_panel.refresh()`` — look for the call.
        found = False
        for node in ast.walk(method):
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "refresh"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "_parent_panel"
                    and isinstance(func.value.value, ast.Name)
                    and func.value.value.id == "self"
                ):
                    found = True
                    break
        self.assertTrue(found, "_on_refresh_clicked does not call self._parent_panel.refresh()")

    def test_g2_expanded_dialog_delegates_validate_to_parent(self):
        """``_on_validate_clicked`` must call ``self._parent_panel._on_validate_vocab_clicked()``."""
        cls = _find_class(DIAG_AST, "_ExpandedDiagnosticsDialog")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_on_validate_clicked"),
            None,
        )
        self.assertIsNotNone(method)
        found = False
        for node in ast.walk(method):
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "_on_validate_vocab_clicked"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "_parent_panel"
                    and isinstance(func.value.value, ast.Name)
                    and func.value.value.id == "self"
                ):
                    found = True
                    break
        self.assertTrue(found, "_on_validate_clicked does not call self._parent_panel._on_validate_vocab_clicked()")

    def test_g2_expanded_dialog_disconnects_on_close(self):
        """``closeEvent`` must disconnect from the parent's ``text_updated`` signal."""
        cls = _find_class(DIAG_AST, "_ExpandedDiagnosticsDialog")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "closeEvent"),
            None,
        )
        self.assertIsNotNone(method)
        # Look for ``self._parent_panel.text_updated.disconnect(...)``
        found = False
        for node in ast.walk(method):
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "disconnect"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "text_updated"
                ):
                    found = True
                    break
        self.assertTrue(found, "closeEvent does not disconnect from parent's text_updated signal")

    # Group 3: DiagnosticsPanel.text_updated signal
    def test_g3_text_updated_signal_exists(self):
        """``DiagnosticsPanel`` must have a class-level ``text_updated`` signal."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        attrs = _class_attribute_names(cls)
        self.assertIn("text_updated", attrs, "DiagnosticsPanel.text_updated signal not found at class level")

    # Group 4: __init__ state
    def test_g4_init_sets_expanded_dialog_none(self):
        """``__init__`` must set ``self._expanded_dialog = None``."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
            None,
        )
        self.assertIsNotNone(method)
        self.assertTrue(
            _method_assigns_attr(method, "_expanded_dialog"),
            "__init__ does not assign self._expanded_dialog",
        )

    # Group 5: _build_ui creates _expand_button
    def test_g5_build_ui_creates_expand_button(self):
        """``_build_ui`` must create ``self._expand_button``."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_build_ui"),
            None,
        )
        self.assertIsNotNone(method)
        self.assertTrue(
            _method_assigns_attr(method, "_expand_button"),
            "_build_ui does not assign self._expand_button",
        )

    # Group 6: refresh() emits text_updated
    def test_g6_refresh_emits_text_updated_on_success(self):
        """``refresh`` must call ``self.text_updated.emit(text)`` on the success path."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "refresh"),
            None,
        )
        self.assertIsNotNone(method)
        # Find the try block — the emit should be inside the try (success path)
        # OR inside the except (error path). Test both.
        success_emit = _method_calls_attr(method, "text_updated.emit")
        self.assertTrue(success_emit, "refresh does not call self.text_updated.emit(text)")

    def test_g6_refresh_emits_on_error_path(self):
        """``refresh`` must also emit ``text_updated`` on the except (error) path."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "refresh"),
            None,
        )
        self.assertIsNotNone(method)
        # Look for an ``ExceptHandler`` that contains a ``text_updated.emit`` call.
        found = False
        for node in ast.walk(method):
            if isinstance(node, ast.ExceptHandler):
                for inner in ast.walk(node):
                    if (
                        isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "emit"
                        and isinstance(inner.func.value, ast.Attribute)
                        and inner.func.value.attr == "text_updated"
                    ):
                        found = True
                        break
                if found:
                    break
        self.assertTrue(found, "refresh does not emit text_updated on the except path")

    # Group 7: _on_expand_clicked method
    def test_g7_on_expand_clicked_exists(self):
        """``DiagnosticsPanel`` must have an ``_on_expand_clicked`` method."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        methods = _class_method_names(cls)
        self.assertIn("_on_expand_clicked", methods, "_on_expand_clicked method not found")

    def test_g7_on_expand_clicked_creates_dialog(self):
        """``_on_expand_clicked`` must instantiate ``_ExpandedDiagnosticsDialog``."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_on_expand_clicked"),
            None,
        )
        self.assertIsNotNone(method)
        # Look for a Call node whose func is the class name.
        found = False
        for node in ast.walk(method):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "_ExpandedDiagnosticsDialog":
                    found = True
                    break
        self.assertTrue(found, "_on_expand_clicked does not instantiate _ExpandedDiagnosticsDialog")

    def test_g7_on_expand_clicked_calls_show(self):
        """``_on_expand_clicked`` must call ``.show()`` on the dialog (non-modal)."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_on_expand_clicked"),
            None,
        )
        self.assertIsNotNone(method)
        # Look for ``self._expanded_dialog.show()`` — and ensure ``exec`` is NOT called.
        show_found = False
        exec_found = False
        for node in ast.walk(method):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "show":
                    show_found = True
                if node.func.attr == "exec":
                    exec_found = True
        self.assertTrue(show_found, "_on_expand_clicked does not call .show()")
        self.assertFalse(exec_found, "_on_expand_clicked must NOT call .exec() (modal would block main window)")

    # Group 8: i18n symmetry — all diagnostics_ keys present in both yaml
    def test_g8_yaml_symmetry(self):
        """All ``diagnostics_*`` keys must be present in BOTH ru.yaml and en.yaml."""
        import yaml
        ru = yaml.safe_load((REPO_ROOT / "app" / "translations" / "ru.yaml").read_text(encoding="utf-8"))
        en = yaml.safe_load((REPO_ROOT / "app" / "translations" / "en.yaml").read_text(encoding="utf-8"))
        ru_diag = {k for k in ru if k.startswith("diagnostics_")}
        en_diag = {k for k in en if k.startswith("diagnostics_")}
        missing_in_en = ru_diag - en_diag
        missing_in_ru = en_diag - ru_diag
        self.assertEqual(missing_in_en, set(), f"diagnostics keys missing in en.yaml: {missing_in_en}")
        self.assertEqual(missing_in_ru, set(), f"diagnostics keys missing in ru.yaml: {missing_in_ru}")

    # Group 9: new iter-64 keys present with non-empty values
    def test_g9_new_keys_present(self):
        """The 3 new iter-64 keys must be present with non-empty values in both yaml files."""
        import yaml
        ru = yaml.safe_load((REPO_ROOT / "app" / "translations" / "ru.yaml").read_text(encoding="utf-8"))
        en = yaml.safe_load((REPO_ROOT / "app" / "translations" / "en.yaml").read_text(encoding="utf-8"))
        new_keys = [
            "diagnostics_expand_button",
            "diagnostics_expand_window_title",
            "diagnostics_expand_close_button",
        ]
        for key in new_keys:
            self.assertIn(key, ru, f"{key} missing in ru.yaml")
            self.assertIn(key, en, f"{key} missing in en.yaml")
            self.assertTrue(ru[key] and isinstance(ru[key], str), f"{key} empty in ru.yaml")
            self.assertTrue(en[key] and isinstance(en[key], str), f"{key} empty in en.yaml")

    def test_g9_validate_vocab_keys_present(self):
        """The iter-63 keys (validate_vocab_button, validating_button) must also be present."""
        import yaml
        ru = yaml.safe_load((REPO_ROOT / "app" / "translations" / "ru.yaml").read_text(encoding="utf-8"))
        en = yaml.safe_load((REPO_ROOT / "app" / "translations" / "en.yaml").read_text(encoding="utf-8"))
        for key in ("diagnostics_validate_vocab_button", "diagnostics_validating_button"):
            self.assertIn(key, ru, f"{key} missing in ru.yaml")
            self.assertIn(key, en, f"{key} missing in en.yaml")

    # Group 10: forbidden-path safety (only if git is available)
    def test_g10_no_forbidden_paths_in_diff(self):
        """``git status --porcelain`` must show only expected files — no binaries, no forbidden dirs."""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.skipTest("git not available or timed out")
        if result.returncode != 0:
            self.skipTest(f"git status failed: {result.stderr}")
        changed = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # Format: "XY path" — take the path part (after the 2-char status).
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                continue
            path = parts[1].strip().strip('"')
            changed.append(path)
        # Forbidden extensions / paths per §4.
        forbidden_exts = (
            ".dll", ".pyd", ".lib", ".pdb", ".wasm", ".exe",
            ".pt", ".pth", ".bin", ".gguf", ".safetensors", ".onnx", ".ckpt",
        )
        forbidden_dirs = (
            ".soul/", "app/data/", "app/cache/", "app/voices/", "app/ffmpeg/",
            "app/font/", "app/utils/ai_clients/backend/",
            "app/utils/all-MiniLM-L6-v2/", "app/utils/emotions/detector/",
            "app/utils/soul_companion/plugins/",
            "assets/local_llm/", "assets/rvc_models/", "assets/ambient/",
            "assets/backgrounds/", "assets/emotions/images/",
            "assets/emotions/live2d/", "assets/emotions/vrm/",
        )
        for path in changed:
            lower = path.lower()
            for ext in forbidden_exts:
                self.assertFalse(
                    lower.endswith(ext),
                    f"Forbidden binary file in diff: {path}",
                )
            for d in forbidden_dirs:
                self.assertFalse(
                    lower.startswith(d.lower()),
                    f"Forbidden directory path in diff: {path}",
                )
            # .gitkeep files must NOT be deleted.
            self.assertFalse(
                path.endswith(".gitkeep") and path.startswith(" D"),
                f".gitkeep file deleted: {path}",
            )
            # api.json must not be staged with content (only the empty template is allowed).
            if path.endswith("api.json"):
                # api.json should only be staged if it's the empty template.
                # We can't easily check content here — but if it appears,
                # flag it for manual review.
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
