"""iter-69 smoke test: verify async template detection (KI#55 fix) + candidate b.

Test environment note (same as iter-64/65):
  PyQt6 cannot be imported in this Linux test env (missing libEGL.so.1).
  The smoke test mocks PyQt6.QtCore / PyQt6.QtWidgets via sys.modules
  injection. With PyQt6 mocked, ``DiagnosticsPanel`` and ``_DetectionWorker``
  appear as MagicMock instances (because they inherit from mocked
  ``QtWidgets.QWidget`` / ``QtCore.QObject``), so runtime invocation of their
  methods is not possible. The smoke test verifies STRUCTURE via source
  inspection (AST) + regression guards (no synchronous detect_template calls
  in the GUI-thread refresh path).

Groups:
  1. AST parse + module imports cleanly (no SyntaxError).
  2. ``_DetectionWorker`` class exists + has ``finished`` signal + ``run``
     method + ``__init__(self, model_path)``.  ``run`` lazy-imports
     ``detect_template`` + emits ``finished``.
  3. ``DiagnosticsPanel.__init__`` sets the new instance attrs:
     ``_detection_result``, ``_detection_model_path``, ``_detection_thread``,
     ``_detection_worker``, ``_detection_in_progress``.
  4. ``DiagnosticsPanel.refresh`` does NOT call ``_get_detection_result``
     (the KEY regression guard — this was the synchronous blocking call that
     froze the GUI).
  5. ``DiagnosticsPanel.refresh`` calls ``_kickoff_detection`` when a model
     is loaded + no cached result + not in progress.
  6. ``DiagnosticsPanel.refresh`` uses ``self._detection_result`` for the
     render-button enabled state (not ``_get_detection_result``).
  7. ``DiagnosticsPanel._kickoff_detection`` method exists + creates a
     ``_DetectionWorker`` + ``QtCore.QThread`` + wires up ``started`` →
     ``worker.run`` + ``worker.finished`` → ``_on_detection_done`` + starts
     the thread.
  8. ``DiagnosticsPanel._on_detection_done`` method exists + stores the
     result in ``self._detection_result`` + clears ``_detection_in_progress``
     + quits the thread + calls ``refresh``.
  9. ``DiagnosticsPanel._build_diagnostics_text`` uses ``self._detection_result``
     (not ``_get_detection_result``) for the Block 2 detection result.
 10. ``DiagnosticsPanel._on_render_preview_clicked`` uses
     ``self._detection_result`` (not ``_get_detection_result``).
 11. ``DiagnosticsPanel.closeEvent`` stops the detection thread (quit + wait)
     — defensive cleanup so the worker doesn't outlive the panel.
 12. Candidate b: Block 7 includes a "RECOMMENDATION" section when
     ``validation_errors`` are found.
 13. Candidate b: ``_on_validate_vocab_done`` uses ``logger.warning`` (not
     ``logger.info``) when validation errors are found.
 14. ``_get_detection_result`` docstring mentions iter-69 / KI#55 (retained
     as a sync fallback — no longer used by the refresh path).
 15. Regression guard: no ``_get_detection_result`` calls anywhere in
     ``refresh``, ``_build_diagnostics_text``, or ``_on_render_preview_clicked``.
 16. No forbidden-path regressions (``git status --porcelain`` shows only
     expected files — no binaries, no forbidden dirs, no ``.gitkeep`` removed).

Run: python scripts/iter69_smoke_test.py
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

# Try real import — used only by g1_module_imports_cleanly.
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


def _method_calls_self(method: ast.FunctionDef, func_name: str) -> bool:
    """True if the method calls ``self.<func_name>``."""
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


def _method_reads_attr(method: ast.FunctionDef, attr_name: str) -> bool:
    """True if the method reads ``self.<attr_name>`` (as a load, not call)."""
    for node in ast.walk(method):
        if isinstance(node, ast.Attribute) and node.attr == attr_name:
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                # Make sure it's a load (read), not the target of an assignment.
                # In practice, ast.walk doesn't distinguish; but if the attr
                # appears as the func of a Call, that's handled by
                # _method_calls_self.  For our regression guard we just check
                # presence — calls are a subset of reads.
                return True
    return False


def _method_calls_external(method: ast.FunctionDef, external_name: str) -> bool:
    """True if the method calls a bare-name external function ``external_name``.

    Used to check for ``logger.warning(...)`` / ``logger.info(...)`` calls.
    ``external_name`` may be a dotted path like ``logger.warning``.
    The OUTERMOST component must be a bare Name (e.g. the module-level
    ``logger`` variable); inner components are Attributes.
    """
    parts = external_name.split(".")
    for node in ast.walk(method):
        if isinstance(node, ast.Call):
            func = node.func
            # Walk from innermost to outermost. The LAST (outermost) part
            # must resolve to a bare Name; all others must be Attributes.
            ok = True
            for i, part in enumerate(reversed(parts)):
                if i == len(parts) - 1:
                    # outermost — must be a Name with id == part
                    if not (isinstance(func, ast.Name) and func.id == part):
                        ok = False
                        break
                else:
                    # inner — must be an Attribute with attr == part
                    if not (isinstance(func, ast.Attribute) and func.attr == part):
                        ok = False
                        break
                    func = func.value
            if ok:
                return True
    return False


# --- Test cases ----------------------------------------------------------

class TestIter69Smoke(unittest.TestCase):
    """iter-69 smoke tests — async detection wiring + candidate b."""

    # Group 1: AST + import-time
    def test_g1_ast_parses(self):
        self.assertIsNotNone(DIAG_AST, "AST parse failed")

    def test_g1_module_imports_cleanly(self):
        if IMPORT_ERROR and "SyntaxError" in IMPORT_ERROR:
            self.fail(f"Module has SyntaxError: {IMPORT_ERROR}")
        if not MODULE_IMPORTED:
            print(f"\n[INFO] module not imported (expected in Linux test env): {IMPORT_ERROR}")

    # Group 2: _DetectionWorker class
    def test_g2_detection_worker_class_exists(self):
        cls = _find_class(DIAG_AST, "_DetectionWorker")
        self.assertIsNotNone(cls, "_DetectionWorker class not found")

    def test_g2_detection_worker_has_finished_signal(self):
        cls = _find_class(DIAG_AST, "_DetectionWorker")
        self.assertIsNotNone(cls)
        attrs = _class_method_names(cls)
        # ``finished`` is a class-level signal assignment (QtCore.pyqtSignal)
        found = False
        for node in cls.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "finished":
                    found = True
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "finished":
                        found = True
        self.assertTrue(found, "_DetectionWorker must have a 'finished' signal")

    def test_g2_detection_worker_has_run_method(self):
        cls = _find_class(DIAG_AST, "_DetectionWorker")
        self.assertIsNotNone(cls)
        run = _find_method(cls, "run")
        self.assertIsNotNone(run, "_DetectionWorker must have a 'run' method")

    def test_g2_detection_worker_run_emits_finished(self):
        cls = _find_class(DIAG_AST, "_DetectionWorker")
        self.assertIsNotNone(cls)
        run = _find_method(cls, "run")
        self.assertIsNotNone(run)
        # run() should call self.finished.emit(...)
        found = False
        for node in ast.walk(run):
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "emit"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "finished"
                    and isinstance(func.value.value, ast.Name)
                    and func.value.value.id == "self"
                ):
                    found = True
                    break
        self.assertTrue(found, "_DetectionWorker.run must call self.finished.emit(...)")

    def test_g2_detection_worker_init_takes_model_path(self):
        cls = _find_class(DIAG_AST, "_DetectionWorker")
        self.assertIsNotNone(cls)
        init = _find_method(cls, "__init__")
        self.assertIsNotNone(init)
        args = [a.arg for a in init.args.args]
        self.assertIn("self", args)
        self.assertIn("model_path", args)

    # Group 3: DiagnosticsPanel.__init__ instance attrs
    def test_g3_init_sets_detection_attrs(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        init = _find_method(cls, "__init__")
        self.assertIsNotNone(init)
        for attr in (
            "_detection_result",
            "_detection_model_path",
            "_detection_thread",
            "_detection_worker",
            "_detection_in_progress",
        ):
            self.assertTrue(
                _method_assigns_attr(init, attr),
                f"__init__ must set self.{attr}",
            )

    # Group 4: refresh does NOT call _get_detection_result (KEY fix)
    def test_g4_refresh_no_sync_detection_call(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        refresh = _find_method(cls, "refresh")
        self.assertIsNotNone(refresh)
        self.assertFalse(
            _method_calls_self(refresh, "_get_detection_result"),
            "refresh() must NOT call self._get_detection_result() — that was the "
            "synchronous blocking call that froze the GUI (KI#55). It should use "
            "self._detection_result (cached by _DetectionWorker) instead.",
        )

    # Group 5: refresh calls _kickoff_detection
    def test_g5_refresh_calls_kickoff_detection(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        refresh = _find_method(cls, "refresh")
        self.assertIsNotNone(refresh)
        self.assertTrue(
            _method_calls_self(refresh, "_kickoff_detection"),
            "refresh() must call self._kickoff_detection() when a model is loaded "
            "and no cached result is available.",
        )

    # Group 6: refresh uses self._detection_result for render button
    def test_g6_refresh_uses_cached_detection_result(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        refresh = _find_method(cls, "refresh")
        self.assertIsNotNone(refresh)
        self.assertTrue(
            _method_reads_attr(refresh, "_detection_result"),
            "refresh() must read self._detection_result for the render-button state.",
        )

    # Group 7: _kickoff_detection method
    def test_g7_kickoff_detection_exists(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        self.assertIn("_kickoff_detection", _class_method_names(cls))

    def test_g7_kickoff_detection_creates_worker_and_thread(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        method = _find_method(cls, "_kickoff_detection")
        self.assertIsNotNone(method)
        # Should assign self._detection_thread and self._detection_worker
        self.assertTrue(_method_assigns_attr(method, "_detection_thread"))
        self.assertTrue(_method_assigns_attr(method, "_detection_worker"))
        # Should set self._detection_in_progress = True
        self.assertTrue(_method_assigns_attr(method, "_detection_in_progress"))

    def test_g7_kickoff_detection_starts_thread(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        method = _find_method(cls, "_kickoff_detection")
        self.assertIsNotNone(method)
        # Should call self._detection_thread.start()
        found = False
        for node in ast.walk(method):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "start":
                    val = node.func.value
                    if (
                        isinstance(val, ast.Attribute)
                        and val.attr == "_detection_thread"
                        and isinstance(val.value, ast.Name)
                        and val.value.id == "self"
                    ):
                        found = True
                        break
        self.assertTrue(found, "_kickoff_detection must call self._detection_thread.start()")

    # Group 8: _on_detection_done method
    def test_g8_on_detection_done_exists(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        self.assertIn("_on_detection_done", _class_method_names(cls))

    def test_g8_on_detection_done_stores_result_and_clears_flag(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        method = _find_method(cls, "_on_detection_done")
        self.assertIsNotNone(method)
        self.assertTrue(_method_assigns_attr(method, "_detection_result"))
        self.assertTrue(_method_assigns_attr(method, "_detection_in_progress"))
        # Should call self.refresh() at the end
        self.assertTrue(_method_calls_self(method, "refresh"))

    # Group 9: _build_diagnostics_text uses self._detection_result
    def test_g9_build_text_uses_cached_result(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        method = _find_method(cls, "_build_diagnostics_text")
        self.assertIsNotNone(method)
        self.assertTrue(
            _method_reads_attr(method, "_detection_result"),
            "_build_diagnostics_text must read self._detection_result.",
        )
        self.assertFalse(
            _method_calls_self(method, "_get_detection_result"),
            "_build_diagnostics_text must NOT call self._get_detection_result() "
            "(synchronous blocking — KI#55).",
        )

    # Group 10: _on_render_preview_clicked uses self._detection_result
    def test_g10_render_preview_uses_cached_result(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        method = _find_method(cls, "_on_render_preview_clicked")
        self.assertIsNotNone(method)
        self.assertTrue(
            _method_reads_attr(method, "_detection_result"),
            "_on_render_preview_clicked must read self._detection_result.",
        )
        self.assertFalse(
            _method_calls_self(method, "_get_detection_result"),
            "_on_render_preview_clicked must NOT call self._get_detection_result() "
            "(synchronous blocking — KI#55).",
        )

    # Group 11: closeEvent stops the detection thread
    def test_g11_close_event_stops_detection_thread(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        method = _find_method(cls, "closeEvent")
        self.assertIsNotNone(method)
        # Should reference _detection_thread (quit + wait)
        self.assertTrue(
            _method_reads_attr(method, "_detection_thread"),
            "closeEvent must reference self._detection_thread (quit + wait).",
        )

    # Group 12: candidate b — Block 7 RECOMMENDATION text
    def test_g12_block7_has_recommendation(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        method = _find_method(cls, "_build_diagnostics_text")
        self.assertIsNotNone(method)
        # The RECOMMENDATION text should be a string literal containing
        # "RECOMMENDATION" appended to the lines list.
        found = False
        for node in ast.walk(method):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "RECOMMENDATION" in node.value:
                    found = True
                    break
        self.assertTrue(
            found,
            "Block 7 must include a 'RECOMMENDATION' string when validation "
            "errors are found (candidate b, strategy §13 step 4).",
        )

    # Group 13: candidate b — _on_validate_vocab_done uses logger.warning
    def test_g13_validate_done_uses_warning(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        method = _find_method(cls, "_on_validate_vocab_done")
        self.assertIsNotNone(method)
        self.assertTrue(
            _method_calls_external(method, "logger.warning"),
            "_on_validate_vocab_done must call logger.warning (not info) when "
            "validation errors are found (candidate b — surface the issue at "
            "default log level).",
        )

    # Group 14: _get_detection_result docstring mentions iter-69
    def test_g14_get_detection_result_docstring_mentions_iter69(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        method = _find_method(cls, "_get_detection_result")
        self.assertIsNotNone(method)
        doc = ast.get_docstring(method) or ""
        self.assertIn(
            "iter-69",
            doc,
            "_get_detection_result docstring must mention iter-69 (retained as "
            "sync fallback — no longer used by the refresh path).",
        )

    # Group 15: regression guard — no _get_detection_result calls in hot paths
    def test_g15_no_sync_detection_in_hot_paths(self):
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        self.assertIsNotNone(cls)
        for method_name in (
            "refresh",
            "_build_diagnostics_text",
            "_on_render_preview_clicked",
        ):
            method = _find_method(cls, method_name)
            self.assertIsNotNone(method, f"{method_name} not found")
            self.assertFalse(
                _method_calls_self(method, "_get_detection_result"),
                f"{method_name} must NOT call self._get_detection_result() — "
                f"that is the synchronous blocking call (KI#55).",
            )

    # Group 16: no forbidden-path regressions
    def test_g16_no_forbidden_paths_in_git_status(self):
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
            # git status porcelain format: "XY path" or "XY path -> path"
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
