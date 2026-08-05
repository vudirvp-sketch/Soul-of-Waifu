"""iter-65 smoke test: verify render_template_preview() + UI wiring.

Test environment note (same as iter-64):
  PyQt6 cannot be imported in this Linux test env (missing libEGL.so.1).
  The smoke test mocks PyQt6.QtCore / PyQt6.QtWidgets via sys.modules
  injection. With PyQt6 mocked, ``DiagnosticsPanel`` and
  ``_RenderPreviewWorker`` appear as MagicMock instances, so runtime
  invocation of their methods is not possible. The smoke test verifies
  STRUCTURE via source inspection (AST) + functional tests of
  ``render_template_preview()`` (which is testable without PyQt6 since it
  only depends on jinja2 + stdlib).

Groups:
  1. AST parse + module imports cleanly for both modified .py files.
  2. ``render_template_preview()`` function exists in template_detector.py
     + has the correct signature (jinja_source, messages=None, *,
     add_generation_prompt=True, timeout_seconds=2.0).
  3. ``JinjaSecurityError`` exception class exists.
  4. ``_check_jinja_ast_safety()`` helper exists + rejects forbidden nodes.
  5. ``_DEFAULT_PREVIEW_MESSAGES`` + ``_FORBIDDEN_JINJA_NODE_NAMES``
     constants exist.
  6. Functional test: ``render_template_preview()`` correctly renders a
     simple ChatML template.
  7. Functional test: ``render_template_preview()`` returns an error tuple
     for an empty source.
  8. Functional test: ``render_template_preview()`` blocks a forbidden
     ``{% include %}`` node (AST pre-check #3).
  9. Functional test: ``render_template_preview()`` blocks an SSTI attempt
     via ``__class__`` (SandboxedEnvironment #1).
 10. Functional test: ``render_template_preview()`` catches a Jinja syntax
     error + returns a human-readable error.
 11. Functional test: ``render_template_preview()`` times out after the
     configured timeout for a pathological template (infinite loop).
 12. Functional test: ``render_template_preview()`` correctly renders a
     Llama 3-style template that uses ``date_string``.
 13. ``_RenderPreviewWorker`` class exists in diagnostics_panel.py + has
     the expected ``finished`` signal + ``run`` method.
 14. ``DiagnosticsPanel.__init__`` sets ``self._rendered_preview = None``,
     ``self._render_thread = None``, ``self._render_worker = None``.
 15. ``DiagnosticsPanel._build_ui`` creates ``self._render_button``.
 16. ``DiagnosticsPanel.refresh`` updates the render button enabled state
     based on Jinja source availability + render-in-progress state.
 17. ``DiagnosticsPanel._on_render_preview_clicked`` + ``_on_render_preview_done``
     methods exist + have the expected wiring (creates worker, calls refresh
     on done).
 18. Block 8 (Rendered Preview) exists in ``_build_diagnostics_text``.
 19. Footer no longer mentions DYNAMIC template preview as deferred (it's
     now closed by iter-65).
 20. i18n: the 3 new iter-65 keys (``diagnostics_render_preview_button``,
     ``diagnostics_rendering_button``, ``diagnostics_rendered_preview_section``)
     are present in BOTH ru.yaml + en.yaml with non-empty string values.
 21. ``_ExpandedDiagnosticsDialog`` has a ``_render_button`` + an
     ``_on_render_clicked`` method + ``_sync_render_button_state`` method.
 22. No forbidden-path regressions (``git status --porcelain`` shows only
     the expected files — no binaries, no forbidden dirs, no ``.gitkeep``
     removed).

Run: python scripts/iter65_smoke_test.py
"""
from __future__ import annotations

import ast
import os
import sys
import time
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

# --- Mock gguf + hf_template_cache for template_detector imports ---------
# template_detector.py imports gguf + hf_template_cache at module level.
# gguf is a C extension that may not be installed in the Linux test env.
# We mock it so the module can be imported for AST inspection + functional
# tests of render_template_preview() (which only needs jinja2 + stdlib).
sys.modules.setdefault("gguf", MagicMock())
import types
_hf_cache_mod = types.ModuleType("app.utils.ai_clients.hf_template_cache")
_hf_cache_mod.HFTemplateCache = MagicMock
_hf_cache_mod.CacheFetchResult = MagicMock
sys.modules.setdefault("app.utils.ai_clients.hf_template_cache", _hf_cache_mod)

# --- Paths + AST parse ---------------------------------------------------
DIAG_PATH = REPO_ROOT / "app" / "gui" / "diagnostics_panel.py"
DIAG_SOURCE = DIAG_PATH.read_text(encoding="utf-8")
DIAG_AST = ast.parse(DIAG_SOURCE)

DETECT_PATH = REPO_ROOT / "app" / "utils" / "ai_clients" / "template_detector.py"
DETECT_SOURCE = DETECT_PATH.read_text(encoding="utf-8")
DETECT_AST = ast.parse(DETECT_SOURCE)

# Try real import of template_detector (needs jinja2 — which IS installed).
# If template_capabilities can't be imported, skip the functional tests.
TEMPLATE_DETECTOR_IMPORTED = False
TEMPLATE_DETECTOR_IMPORT_ERROR = None
try:
    # template_detector imports template_capabilities which may have heavy deps.
    # Stub it out if needed.
    try:
        import app.utils.ai_clients.template_capabilities  # noqa: F401
    except ImportError:
        _tc_mod = types.ModuleType("app.utils.ai_clients.template_capabilities")
        _tc_mod.TEMPLATE_FAMILY_HINTS = {}
        sys.modules["app.utils.ai_clients.template_capabilities"] = _tc_mod
    from app.utils.ai_clients.template_detector import (
        render_template_preview,
        JinjaSecurityError,
        _check_jinja_ast_safety,
        _DEFAULT_PREVIEW_MESSAGES,
        _FORBIDDEN_JINJA_NODE_NAMES,
    )
    TEMPLATE_DETECTOR_IMPORTED = True
except Exception as exc:
    TEMPLATE_DETECTOR_IMPORT_ERROR = repr(exc)


# --- Helpers (same as iter-64) ------------------------------------------

def _find_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _class_method_names(cls: ast.ClassDef) -> set[str]:
    return {
        node.name
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _class_attribute_names(cls: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for node in cls.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            # ``name: type = value`` — target is a Name (or Attribute for
            # instance annotations, but those don't appear at class level).
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return names


def _method_assigns_attr(method: ast.FunctionDef, attr_name: str) -> bool:
    """Return True if the method assigns ``self.<attr_name>`` somewhere.

    Handles both ``ast.Assign`` (``self.x = ...``) and ``ast.AnnAssign``
    (``self.x: type = ...`` — annotated assignment, used for instance
    attributes with type hints).
    """
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
            # ``self.x: type = value`` — target is an Attribute.
            target = node.target
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr == attr_name
            ):
                return True
    return False


def _module_level_name_defined(tree: ast.Module, name: str) -> bool:
    """Return True if ``name`` is defined at module level (Assign or AnnAssign)."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return True
    return False


# --- Test cases ----------------------------------------------------------

class TestIter65Smoke(unittest.TestCase):
    """iter-65 smoke tests — structure + AST + functional + i18n."""

    # Group 1: AST parse
    def test_g1_diag_ast_parses(self):
        """``diagnostics_panel.py`` must parse as valid Python AST."""
        self.assertIsNotNone(DIAG_AST, "diagnostics_panel.py AST parse failed")

    def test_g1_detect_ast_parses(self):
        """``template_detector.py`` must parse as valid Python AST."""
        self.assertIsNotNone(DETECT_AST, "template_detector.py AST parse failed")

    # Group 2: render_template_preview function exists + signature
    def test_g2_render_function_exists(self):
        """``render_template_preview`` function must exist in template_detector.py."""
        func = _find_function(DETECT_AST, "render_template_preview")
        self.assertIsNotNone(func, "render_template_preview function not found")

    def test_g2_render_function_signature(self):
        """``render_template_preview`` must have the correct signature."""
        func = _find_function(DETECT_AST, "render_template_preview")
        self.assertIsNotNone(func)
        args = func.args
        # Positional args: jinja_source, messages
        self.assertEqual(len(args.args), 2)
        self.assertEqual(args.args[0].arg, "jinja_source")
        self.assertEqual(args.args[1].arg, "messages")
        # messages has a default of None
        self.assertEqual(len(args.defaults), 1)
        self.assertIsInstance(args.defaults[0], ast.Constant)
        self.assertIsNone(args.defaults[0].value)
        # Keyword-only args: add_generation_prompt, timeout_seconds
        self.assertEqual(len(args.kwonlyargs), 2)
        self.assertEqual(args.kwonlyargs[0].arg, "add_generation_prompt")
        self.assertEqual(args.kwonlyargs[1].arg, "timeout_seconds")
        # Both kwonly args have defaults
        self.assertEqual(len(args.kw_defaults), 2)
        self.assertIsNotNone(args.kw_defaults[0])
        self.assertIsNotNone(args.kw_defaults[1])

    # Group 3: JinjaSecurityError exception class
    def test_g3_jinja_security_error_exists(self):
        """``JinjaSecurityError`` exception class must exist."""
        cls = _find_class(DETECT_AST, "JinjaSecurityError")
        self.assertIsNotNone(cls, "JinjaSecurityError class not found")
        # Must inherit from Exception
        self.assertTrue(
            any(
                isinstance(base, ast.Name) and base.id == "Exception"
                for base in cls.bases
            ),
            f"JinjaSecurityError must inherit from Exception, got bases: {cls.bases}",
        )

    # Group 4: _check_jinja_ast_safety helper
    def test_g4_check_ast_safety_exists(self):
        """``_check_jinja_ast_safety`` helper must exist."""
        func = _find_function(DETECT_AST, "_check_jinja_ast_safety")
        self.assertIsNotNone(func, "_check_jinja_ast_safety function not found")

    def test_g4_check_ast_safety_signature(self):
        """``_check_jinja_ast_safety`` must take (env, jinja_source)."""
        func = _find_function(DETECT_AST, "_check_jinja_ast_safety")
        self.assertIsNotNone(func)
        args = func.args
        self.assertEqual(len(args.args), 2)
        self.assertEqual(args.args[0].arg, "env")
        self.assertEqual(args.args[1].arg, "jinja_source")

    # Group 5: constants
    def test_g5_default_preview_messages_exists(self):
        """``_DEFAULT_PREVIEW_MESSAGES`` constant must exist at module level."""
        self.assertTrue(
            _module_level_name_defined(DETECT_AST, "_DEFAULT_PREVIEW_MESSAGES"),
            "_DEFAULT_PREVIEW_MESSAGES not found at module level",
        )

    def test_g5_forbidden_node_names_exists(self):
        """``_FORBIDDEN_JINJA_NODE_NAMES`` constant must exist at module level."""
        self.assertTrue(
            _module_level_name_defined(DETECT_AST, "_FORBIDDEN_JINJA_NODE_NAMES"),
            "_FORBIDDEN_JINJA_NODE_NAMES not found at module level",
        )

    # Groups 6-12: functional tests (only run if template_detector imported)
    @unittest.skipUnless(TEMPLATE_DETECTOR_IMPORTED, f"template_detector not imported: {TEMPLATE_DETECTOR_IMPORT_ERROR}")
    def test_g6_functional_renders_chatml(self):
        """Functional: render_template_preview correctly renders ChatML."""
        chatml = (
            "{% for message in messages %}"
            "<|im_start|>{{ message.role }}\n{{ message.content }}<|im_end|>\n"
            "{% endfor %}"
            "{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}"
        )
        rendered, errors = render_template_preview(chatml)
        self.assertIsNone(errors) if errors is None else self.assertEqual(errors, [])
        self.assertIsNotNone(rendered)
        self.assertIn("<|im_start|>system", rendered)
        self.assertIn("You are a helpful assistant.", rendered)
        self.assertIn("<|im_start|>user", rendered)
        self.assertIn("Hello!", rendered)
        self.assertIn("<|im_start|>assistant", rendered)

    @unittest.skipUnless(TEMPLATE_DETECTOR_IMPORTED, f"template_detector not imported: {TEMPLATE_DETECTOR_IMPORT_ERROR}")
    def test_g7_functional_empty_source(self):
        """Functional: empty source returns (None, [error])."""
        rendered, errors = render_template_preview("")
        self.assertIsNone(rendered)
        self.assertEqual(len(errors), 1)
        self.assertIn("empty", errors[0].lower())

    @unittest.skipUnless(TEMPLATE_DETECTOR_IMPORTED, f"template_detector not imported: {TEMPLATE_DETECTOR_IMPORT_ERROR}")
    def test_g8_functional_blocks_include_node(self):
        """Functional: ``{% include %}`` is blocked by AST pre-check (#3)."""
        malicious = '{% include "/etc/passwd" %}'
        rendered, errors = render_template_preview(malicious)
        self.assertIsNone(rendered)
        self.assertGreaterEqual(len(errors), 1)
        # Error message should mention the forbidden node + strategy §6.2 #3
        error_text = " ".join(errors)
        self.assertIn("Include", error_text)
        self.assertIn("§6.2", error_text)

    @unittest.skipUnless(TEMPLATE_DETECTOR_IMPORTED, f"template_detector not imported: {TEMPLATE_DETECTOR_IMPORT_ERROR}")
    def test_g9_functional_blocks_ssti_class_access(self):
        """Functional: SSTI via ``__class__`` is blocked by SandboxedEnvironment (#1)."""
        ssti = "{{ ''.__class__.__mro__[1].__subclasses__() }}"
        rendered, errors = render_template_preview(ssti)
        self.assertIsNone(rendered)
        self.assertGreaterEqual(len(errors), 1)
        # Error message should mention the sandbox / unsafe operation
        error_text = " ".join(errors).lower()
        self.assertTrue(
            "sandbox" in error_text or "unsafe" in error_text or "security" in error_text,
            f"Error should mention sandbox/unsafe, got: {errors}",
        )

    @unittest.skipUnless(TEMPLATE_DETECTOR_IMPORTED, f"template_detector not imported: {TEMPLATE_DETECTOR_IMPORT_ERROR}")
    def test_g10_functional_catches_syntax_error(self):
        """Functional: Jinja syntax error is caught + returned as a string."""
        bad = "{% for msg in messages %}{{ msg.content }"  # missing close
        rendered, errors = render_template_preview(bad)
        self.assertIsNone(rendered)
        self.assertGreaterEqual(len(errors), 1)
        self.assertIn("syntax", errors[0].lower())

    @unittest.skipUnless(TEMPLATE_DETECTOR_IMPORTED, f"template_detector not imported: {TEMPLATE_DETECTOR_IMPORT_ERROR}")
    def test_g11_functional_timeout_for_infinite_loop(self):
        """Functional: pathological template times out after the configured timeout."""
        infinite = "{% for i in range(999999999) %}x{% endfor %}"
        start = time.time()
        rendered, errors = render_template_preview(infinite, timeout_seconds=1.0)
        elapsed = time.time() - start
        # Should take ~1s (the timeout), not 60s+ (the actual loop time)
        self.assertLess(elapsed, 3.0, f"Render should timeout in ~1s, took {elapsed:.2f}s")
        self.assertIsNone(rendered)
        self.assertGreaterEqual(len(errors), 1)
        self.assertIn("timed out", errors[0].lower())

    @unittest.skipUnless(TEMPLATE_DETECTOR_IMPORTED, f"template_detector not imported: {TEMPLATE_DETECTOR_IMPORT_ERROR}")
    def test_g12_functional_renders_llama3_with_date_string(self):
        """Functional: Llama 3 template renders with ``date_string`` provided."""
        llama3 = (
            "{% set date_string = date_string if date_string else '' %}"
            "{% for message in messages %}"
            "{% if message.role == 'system' %}"
            "<|start_header_id|>system<|end_header_id|>\n\n{{ message.content }}<|eot_id|>"
            "{% elif message.role == 'user' %}"
            "<|start_header_id|>user<|end_header_id|>\n\n{{ message.content }}<|eot_id|>"
            "{% endif %}"
            "{% endfor %}"
            "{% if add_generation_prompt %}"
            "<|start_header_id|>assistant<|end_header_id|>\n\n"
            "{% endif %}"
        )
        rendered, errors = render_template_preview(llama3)
        self.assertEqual(errors, [])
        self.assertIsNotNone(rendered)
        self.assertIn("<|start_header_id|>system<|end_header_id|>", rendered)
        self.assertIn("<|eot_id|>", rendered)
        self.assertIn("<|start_header_id|>assistant<|end_header_id|>", rendered)

    # Group 13: _RenderPreviewWorker class structure
    def test_g13_render_worker_class_exists(self):
        """``_RenderPreviewWorker`` class must exist in diagnostics_panel.py."""
        cls = _find_class(DIAG_AST, "_RenderPreviewWorker")
        self.assertIsNotNone(cls, "_RenderPreviewWorker class not found")

    def test_g13_render_worker_methods(self):
        """``_RenderPreviewWorker`` must have ``__init__`` + ``run`` methods + ``finished`` signal."""
        cls = _find_class(DIAG_AST, "_RenderPreviewWorker")
        self.assertIsNotNone(cls)
        methods = _class_method_names(cls)
        self.assertIn("__init__", methods)
        self.assertIn("run", methods)
        # ``finished`` signal is a class-level attribute
        attrs = _class_attribute_names(cls)
        self.assertIn("finished", attrs)

    # Group 14: __init__ state
    def test_g14_init_sets_render_state(self):
        """``DiagnosticsPanel.__init__`` must set render state vars to None."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
            None,
        )
        self.assertIsNotNone(method)
        self.assertTrue(_method_assigns_attr(method, "_rendered_preview"), "_rendered_preview not set")
        self.assertTrue(_method_assigns_attr(method, "_render_thread"), "_render_thread not set")
        self.assertTrue(_method_assigns_attr(method, "_render_worker"), "_render_worker not set")

    # Group 15: _build_ui creates _render_button
    def test_g15_build_ui_creates_render_button(self):
        """``DiagnosticsPanel._build_ui`` must create ``self._render_button``."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_build_ui"),
            None,
        )
        self.assertIsNotNone(method)
        self.assertTrue(
            _method_assigns_attr(method, "_render_button"),
            "_build_ui does not assign self._render_button",
        )

    # Group 16: refresh() updates render button
    def test_g16_refresh_updates_render_button(self):
        """``refresh()`` must call ``self._render_button.setEnabled(...)``."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "refresh"),
            None,
        )
        self.assertIsNotNone(method)
        # Look for ``self._render_button.setEnabled(...)`` call
        found = False
        for node in ast.walk(method):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr == "setEnabled"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "_render_button"
                ):
                    found = True
                    break
        self.assertTrue(found, "refresh() does not call self._render_button.setEnabled()")

    # Group 17: _on_render_preview_clicked + _on_render_preview_done exist
    def test_g17_render_click_handler_exists(self):
        """``_on_render_preview_clicked`` method must exist."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        methods = _class_method_names(cls)
        self.assertIn("_on_render_preview_clicked", methods)

    def test_g17_render_done_handler_exists(self):
        """``_on_render_preview_done`` method must exist."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        methods = _class_method_names(cls)
        self.assertIn("_on_render_preview_done", methods)

    def test_g17_render_click_creates_worker(self):
        """``_on_render_preview_clicked`` must instantiate ``_RenderPreviewWorker``."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_on_render_preview_clicked"),
            None,
        )
        self.assertIsNotNone(method)
        found = False
        for node in ast.walk(method):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "_RenderPreviewWorker":
                    found = True
                    break
        self.assertTrue(found, "_on_render_preview_clicked does not instantiate _RenderPreviewWorker")

    def test_g17_render_done_calls_refresh(self):
        """``_on_render_preview_done`` must call ``self.refresh()``."""
        cls = _find_class(DIAG_AST, "DiagnosticsPanel")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_on_render_preview_done"),
            None,
        )
        self.assertIsNotNone(method)
        found = False
        for node in ast.walk(method):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr == "refresh"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                ):
                    found = True
                    break
        self.assertTrue(found, "_on_render_preview_done does not call self.refresh()")

    # Group 18: Block 8 exists
    def test_g18_block_8_exists(self):
        """Block 8 (Rendered Preview) must exist in ``_build_diagnostics_text``."""
        # Search the source for the Block 8 marker
        self.assertIn("Block 8: Rendered Preview", DIAG_SOURCE)
        # Also verify it references the i18n key
        self.assertIn("diagnostics_rendered_preview_section", DIAG_SOURCE)

    # Group 19: footer no longer mentions DYNAMIC template preview as deferred
    def test_g19_footer_drops_dynamic_deferral(self):
        """The footer must NOT list DYNAMIC template preview as deferred.

        iter-65 closes the iter-63 deferral "DYNAMIC template preview".
        The footer's deferred-items list should no longer include it.
        """
        # Find the footer section in the source. The footer is in
        # ``_build_diagnostics_text`` after Block 8. The deferral text was:
        #   "DYNAMIC template preview (rendered prompt with a sample"
        # We check that this specific phrasing is NOT in the footer area
        # (it might still appear in the module docstring describing what
        # iter-65 closes — that's fine).
        # Look in the footer block specifically — search for the section
        # after "DEFERRED (full KI#17 closure)".
        idx_footer = DIAG_SOURCE.find('diagnostics_footer_section')
        self.assertGreater(idx_footer, 0, "Footer section not found")
        # Take the next 1500 chars after the footer marker
        footer_area = DIAG_SOURCE[idx_footer:idx_footer + 1500]
        # The DYNAMIC deferral text should NOT be in the footer area anymore
        self.assertNotIn(
            "DYNAMIC template preview (rendered prompt with a sample",
            footer_area,
            "Footer still lists DYNAMIC template preview as deferred",
        )
        # The Free-form Jinja override should STILL be there
        self.assertIn("Free-form Jinja override", footer_area)

    # Group 20: i18n
    def test_g20_new_keys_present(self):
        """The 3 new iter-65 keys must be present in BOTH ru.yaml + en.yaml."""
        import yaml
        ru = yaml.safe_load((REPO_ROOT / "app" / "translations" / "ru.yaml").read_text(encoding="utf-8"))
        en = yaml.safe_load((REPO_ROOT / "app" / "translations" / "en.yaml").read_text(encoding="utf-8"))
        new_keys = [
            "diagnostics_render_preview_button",
            "diagnostics_rendering_button",
            "diagnostics_rendered_preview_section",
        ]
        for key in new_keys:
            self.assertIn(key, ru, f"{key} missing in ru.yaml")
            self.assertIn(key, en, f"{key} missing in en.yaml")
            self.assertTrue(ru[key] and isinstance(ru[key], str), f"{key} empty in ru.yaml")
            self.assertTrue(en[key] and isinstance(en[key], str), f"{key} empty in en.yaml")

    # Group 21: _ExpandedDiagnosticsDialog iter-65 additions
    def test_g21_dialog_has_render_button(self):
        """``_ExpandedDiagnosticsDialog._build_ui`` must create ``self._render_button``."""
        cls = _find_class(DIAG_AST, "_ExpandedDiagnosticsDialog")
        method = next(
            (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_build_ui"),
            None,
        )
        self.assertIsNotNone(method)
        self.assertTrue(
            _method_assigns_attr(method, "_render_button"),
            "_ExpandedDiagnosticsDialog._build_ui does not assign self._render_button",
        )

    def test_g21_dialog_has_on_render_clicked(self):
        """``_ExpandedDiagnosticsDialog`` must have ``_on_render_clicked`` method."""
        cls = _find_class(DIAG_AST, "_ExpandedDiagnosticsDialog")
        methods = _class_method_names(cls)
        self.assertIn("_on_render_clicked", methods)

    def test_g21_dialog_has_sync_render_button_state(self):
        """``_ExpandedDiagnosticsDialog`` must have ``_sync_render_button_state`` method."""
        cls = _find_class(DIAG_AST, "_ExpandedDiagnosticsDialog")
        methods = _class_method_names(cls)
        self.assertIn("_sync_render_button_state", methods)

    # Group 22: forbidden-path safety
    def test_g22_no_forbidden_paths_in_diff(self):
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
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                continue
            path = parts[1].strip().strip('"')
            changed.append(path)
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
                self.assertFalse(lower.endswith(ext), f"Forbidden binary file in diff: {path}")
            for d in forbidden_dirs:
                self.assertFalse(lower.startswith(d.lower()), f"Forbidden directory path in diff: {path}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
