"""iter-70 smoke test: crash fix — _jinja_override_text init order.

The crash was: ``'DiagnosticsPanel' object has no attribute '_jinja_override_text'``.
Root cause: ``_build_ui()`` (called in __init__) references ``self._jinja_override_text``
and ``self._jinja_override_applied``, but these were initialized AFTER ``_build_ui()``.

Fix: move the two attribute assignments BEFORE the ``_build_ui()`` call.

Groups:
  1. AST parse + module imports cleanly (no SyntaxError).
  2. ``DiagnosticsPanel.__init__`` sets ``_jinja_override_text`` and
     ``_jinja_override_applied`` BEFORE the ``_build_ui()`` call.
  3. ``_build_ui`` reads ``self._jinja_override_text`` and
     ``self._jinja_override_applied`` (confirming the fix is needed).
  4. No other instance attrs accessed in ``_build_ui`` that are set after
     ``_build_ui()`` (regression guard for future init reordering).
  5. No forbidden-path regressions.

Run: python scripts/iter70_smoke_test.py
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
_PYQT6_MODULES = ["PyQt6", "PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtGui"]
for mod_name in _PYQT6_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# --- Paths + AST parse ---------------------------------------------------
DIAG_PATH = REPO_ROOT / "app" / "gui" / "diagnostics_panel.py"
DIAG_SOURCE = DIAG_PATH.read_text(encoding="utf-8")
DIAG_AST = ast.parse(DIAG_SOURCE)

# Try real import
try:
    import app.gui.diagnostics_panel as diag_mod  # noqa: F401
    MODULE_IMPORTED = True
    IMPORT_ERROR = None
except SyntaxError as exc:
    diag_mod = None
    MODULE_IMPORTED = False
    IMPORT_ERROR = repr(exc)
except ImportError as exc:
    diag_mod = None
    MODULE_IMPORTED = False
    IMPORT_ERROR = repr(exc)
except Exception as exc:
    diag_mod = None
    MODULE_IMPORTED = False
    IMPORT_ERROR = repr(exc)


# --- Helpers -------------------------------------------------------------

def _find_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _find_method(cls: ast.ClassDef, name: str) -> ast.FunctionDef | None:
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _class_method_names(cls: ast.ClassDef) -> set[str]:
    return {
        node.name
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _method_assigns_attr(method: ast.FunctionDef, attr_name: str) -> bool:
    """True if the method assigns ``self.<attr_name>``."""
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
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Attribute)
                and isinstance(node.target.value, ast.Name)
                and node.target.value.id == "self"
                and node.target.attr == attr_name
            ):
                return True
    return False


def _method_reads_attr(method: ast.FunctionDef, attr_name: str) -> bool:
    """True if the method reads ``self.<attr_name>``."""
    for node in ast.walk(method):
        if isinstance(node, ast.Attribute) and node.attr == attr_name:
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                return True
    return False


def _init_assigns_attr_before_call(
    init_method: ast.FunctionDef, attr_name: str, call_name: str
) -> bool:
    """True if ``self.<attr_name>`` is assigned before ``self.<call_name>()`` in __init__.

    Walks the __init__ body in order (top-level statements only — the
    attr assignment and method call are both at the top level of __init__,
    not nested inside if/try blocks).
    """
    for i, stmt in enumerate(init_method.body):
        # If the call is found first (before the attr assignment), fail.
        if _stmt_calls_self_method(stmt, call_name):
            return False
        # If the attr assignment is found before the call, success.
        if _stmt_assigns_self_attr(stmt, attr_name):
            return True
    # Neither found — fail (attr must be assigned and call must exist).
    return False


def _stmt_assigns_self_attr(stmt: ast.stmt, attr_name: str) -> bool:
    """Check if a single statement assigns self.<attr_name>."""
    if isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr == attr_name
            ):
                return True
    elif isinstance(stmt, ast.AnnAssign):
        if (
            isinstance(stmt.target, ast.Attribute)
            and isinstance(stmt.target.value, ast.Name)
            and stmt.target.value.id == "self"
            and stmt.target.attr == attr_name
        ):
            return True
    return False


def _stmt_calls_self_method(stmt: ast.stmt, method_name: str) -> bool:
    """Check if a single statement calls self.<method_name>()."""
    for node in ast.walk(stmt):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "self"
                and func.attr == method_name
            ):
                return True
    return False


def _self_attrs_read_in_method(method: ast.FunctionDef) -> set[str]:
    """Return all ``self.<attr>`` names read in the method (for regression guard)."""
    attrs = set()
    for node in ast.walk(method):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "self" and not isinstance(node.ctx, ast.Store):
                attrs.add(node.attr)
    return attrs


def _self_attrs_assigned_in_method(method: ast.FunctionDef) -> set[str]:
    """Return all ``self.<attr>`` names assigned in the method."""
    attrs = set()
    for node in ast.walk(method):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    attrs.add(target.attr)
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Attribute)
                and isinstance(node.target.value, ast.Name)
                and node.target.value.id == "self"
            ):
                attrs.add(node.target.attr)
    return attrs


# --- Test cases ----------------------------------------------------------

class TestIter70Smoke(unittest.TestCase):
    """iter-70 smoke tests — crash fix: _jinja_override_text init order."""

    # Group 1: AST + import-time
    def test_g1_ast_parses(self):
        self.assertIsNotNone(DIAG_AST, "AST parse failed")

    def test_g1_module_imports_cleanly(self):
        if IMPORT_ERROR and "SyntaxError" in IMPORT_ERROR:
            self.fail(f"Module has SyntaxError: {IMPORT_ERROR}")
        if not MODULE_IMPORTED:
            print(f"\n[INFO] module not imported (expected in Linux test env): {IMPORT_ERROR}")

    # Group 2: _jinja_override_text and _jinja_override_applied are set BEFORE _build_ui()
    def test_g2_jinja_override_text_before_build_ui(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        init = _find_method(cls, "__init__")
        self.assertIsNotNone(init)
        self.assertTrue(
            _init_assigns_attr_before_call(init, "_jinja_override_text", "_build_ui"),
            "__init__ must set self._jinja_override_text BEFORE calling self._build_ui() "
            "(this was the crash: AttributeError '_jinja_override_text').",
        )

    def test_g2_jinja_override_applied_before_build_ui(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        init = _find_method(cls, "__init__")
        self.assertIsNotNone(init)
        self.assertTrue(
            _init_assigns_attr_before_call(init, "_jinja_override_applied", "_build_ui"),
            "__init__ must set self._jinja_override_applied BEFORE calling self._build_ui() "
            "(this was the crash: _build_ui reads it for button enabled state).",
        )

    # Group 3: _build_ui DOES read these attrs (confirming the fix was needed)
    def test_g3_build_ui_reads_jinja_override_text(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        method = _find_method(cls, "_build_ui")
        self.assertIsNotNone(method)
        self.assertTrue(
            _method_reads_attr(method, "_jinja_override_text"),
            "_build_ui reads self._jinja_override_text (pre-populating the Jinja text edit) "
            "— confirming the fix was necessary.",
        )

    def test_g3_build_ui_reads_jinja_override_applied(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        method = _find_method(cls, "_build_ui")
        self.assertIsNotNone(method)
        self.assertTrue(
            _method_reads_attr(method, "_jinja_override_applied"),
            "_build_ui reads self._jinja_override_applied (button enabled state, "
            "status label) — confirming the fix was necessary.",
        )

    # Group 4: regression guard — no other attrs read in _build_ui that are
    # set after _build_ui() in __init__
    def test_g4_no_other_stale_attr_reads_in_build_ui(self):
        """All self.<attr> read in _build_ui must be set before _build_ui() is called."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        init = _find_method(cls, "__init__")
        build_ui = _find_method(cls, "_build_ui")
        self.assertIsNotNone(init)
        self.assertIsNotNone(build_ui)

        # Attrs set in __init__ before _build_ui()
        attrs_before_build_ui: set[str] = set()
        build_ui_called = False
        for stmt in init.body:
            if _stmt_calls_self_method(stmt, "_build_ui"):
                build_ui_called = True
                break
            # Collect all self.<attr> assignments in this statement
            for node in ast.walk(stmt):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            attrs_before_build_ui.add(target.attr)
                elif isinstance(node, ast.AnnAssign):
                    if (
                        isinstance(node.target, ast.Attribute)
                        and isinstance(node.target.value, ast.Name)
                        and node.target.value.id == "self"
                    ):
                        attrs_before_build_ui.add(node.target.attr)

        # Attrs read in _build_ui
        attrs_read_in_build_ui = _self_attrs_read_in_method(build_ui)

        # Also include attrs inherited from QWidget (via super().__init__)
        # and the translations dict — these are fine to read.
        known_safe = {
            "translations",  # set in __init__ before _build_ui
            "_configuration_settings",  # set in __init__ before _build_ui
            "_first_show",  # set in __init__ before _build_ui
            "_jinja_override_text",  # FIXED: now set before _build_ui
            "_jinja_override_applied",  # FIXED: now set before _build_ui
        }

        # Attrs read in _build_ui but NOT set before _build_ui and NOT known safe
        # Also filter out attrs that are assigned within _build_ui itself
        # (e.g. self._refresh_button = QPushButton(...) — these are created
        # inside _build_ui, not read from __init__).
        attrs_assigned_in_build_ui = _self_attrs_assigned_in_method(build_ui)
        stale = attrs_read_in_build_ui - attrs_before_build_ui - known_safe - attrs_assigned_in_build_ui
        # Filter out method calls (they're read as attrs for .connect())
        method_names = _class_method_names(cls)
        stale = stale - method_names

        # Also filter out Qt signals (class-level attributes)
        for node in cls.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            stale.discard(t.id)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    stale.discard(node.target.id)

        if stale:
            self.fail(
                f"_build_ui reads these self.<attr> that are NOT set before _build_ui() "
                f"in __init__: {stale}. This would cause an AttributeError at startup. "
                f"Attrs set before _build_ui: {attrs_before_build_ui}. "
                f"Known safe: {known_safe}."
            )

    # Group 5: no forbidden-path regressions
    def test_g5_no_forbidden_paths_in_git_status(self):
        """git status --porcelain must show only expected files."""
        import subprocess
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            self.skipTest(f"git status failed: {result.stderr}")
        changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        forbidden_patterns = [
            ".soul/",
            "app/data/",
            "app/cache/",
            "app/voices/",
            "app/ffmpeg/",
            "app/font/",
            "ai_clients/backend",
            "all-MiniLM-L6-v2",
            "emotions/detector",
            "soul_companion/plugins",
            "assets/local_llm",
            "assets/rvc_models",
            "assets/ambient",
            "assets/backgrounds",
            "assets/emotions/images",
            "assets/emotions/live2d",
            "assets/emotions/vrm",
            "logs/",
        ]
        forbidden_exts = (
            ".dll", ".pyd", ".lib", ".pdb", ".wasm", ".exe",
            ".pt", ".pth", ".bin", ".gguf", ".safetensors", ".onnx", ".ckpt",
        )
        for line in changed:
            parts = line.split(" -> ")
            paths = [p.split(maxsplit=1)[-1] if " " in p else p for p in parts]
            for p in paths:
                low = p.lower()
                for pat in forbidden_patterns:
                    if pat in low:
                        self.fail(f"Forbidden path in git status: {p} (pattern {pat})")
                for ext in forbidden_exts:
                    if low.endswith(ext):
                        self.fail(f"Forbidden binary in git status: {p} (ext {ext})")
        # Verify .gitkeep files are intact
        gitkeep_count = sum(
            1 for root, dirs, files in os.walk(REPO_ROOT)
            if ".git" not in root
            for f in files
            if f == ".gitkeep"
        )
        self.assertGreaterEqual(
            gitkeep_count, 15,
            f"Expected >=15 .gitkeep files, found {gitkeep_count} — do NOT delete .gitkeep files.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
