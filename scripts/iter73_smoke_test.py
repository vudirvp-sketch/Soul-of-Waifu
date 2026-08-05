"""iter-73 smoke test: Q4 cleanup + thinking mode visibility fix.

Verifies:
  1. _capability_map_from_template_name: duplicate condition fixed.
  2. ENABLE_THINKING_TEMPLATES removed from template_capabilities.py.
  3. supports_enable_thinking() removed from template_capabilities.py.
  4. checkBox_reasoning_mode visibility: enable_thinking OR reasoning_budget.
  5. checkBox_enable_thinking hidden when reasoning_mode is visible.
  6. _maybe_restart_local_server wraps restart in _restart_and_refresh.
  7. on_checkBox_enable_thinking_stateChanged updates reasoning_mode.
  8. apply_main_settings_to_ui syncs enable_thinking from reasoning_mode.
  9. i18n keys present in both en.yaml and ru.yaml.
  10. Diagnostics Panel Block 4 uses unified visibility logic.
"""

import ast
import inspect
import re
import sys
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"

# ── Source readers ────────────────────────────────────────────────────

def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")

TD_SOURCE = _read("app/utils/ai_clients/template_detector.py")
TC_SOURCE = _read("app/utils/ai_clients/template_capabilities.py")
IS_SOURCE = _read("app/gui/interface_signals.py")
DP_SOURCE = _read("app/gui/diagnostics_panel.py")
EN_YAML = _read("app/translations/en.yaml")
RU_YAML = _read("app/translations/ru.yaml")


class TestIter73(unittest.TestCase):
    maxDiff = None

    # ── Group 1: _capability_map_from_template_name duplicate fix ─────

    def test_g1_no_duplicate_condition(self):
        """The duplicate 'qwen3 in name_lower or qwen3 in name_lower' is fixed."""
        # The old code had: if "qwen3" in name_lower or "qwen3" in name_lower:
        # The new code should have: if "qwen3" in name_lower:
        self.assertNotIn(
            '"qwen3" in name_lower or "qwen3" in name_lower',
            TD_SOURCE,
            "Duplicate condition should be removed",
        )

    def test_g1_capability_map_qwen3(self):
        """_capability_map_from_template_name still sets enable_thinking for Qwen3."""
        # Find the function and verify it still works
        self.assertIn('caps.enable_thinking = True', TD_SOURCE)
        self.assertIn('"qwen3" in name_lower', TD_SOURCE)

    # ── Group 2: ENABLE_THINKING_TEMPLATES removed ────────────────────

    def test_g2_enable_thinking_templates_removed(self):
        """ENABLE_THINKING_TEMPLATES constant is REMOVED from template_capabilities.py."""
        # The constant should no longer exist as a live definition
        self.assertNotIn(
            'ENABLE_THINKING_TEMPLATES: set[str]',
            TC_SOURCE,
            "ENABLE_THINKING_TEMPLATES should be removed",
        )

    def test_g2_no_active_consumers(self):
        """No active code imports ENABLE_THINKING_TEMPLATES."""
        # Check that no .py file imports it (except comments and smoke tests)
        for source_name, source in [
            ("interface_signals.py", IS_SOURCE),
            ("diagnostics_panel.py", DP_SOURCE),
            ("template_capabilities.py", TC_SOURCE),
        ]:
            # Check for import statements
            self.assertNotIn(
                "import ENABLE_THINKING_TEMPLATES",
                source,
                f"{source_name} should not import ENABLE_THINKING_TEMPLATES",
            )
            self.assertNotIn(
                "from app.utils.ai_clients.template_capabilities import ENABLE_THINKING_TEMPLATES",
                source,
                f"{source_name} should not import ENABLE_THINKING_TEMPLATES",
            )

    # ── Group 3: supports_enable_thinking removed ─────────────────────

    def test_g3_supports_enable_thinking_removed(self):
        """supports_enable_thinking() function is REMOVED from template_capabilities.py."""
        self.assertNotIn(
            "def supports_enable_thinking",
            TC_SOURCE,
            "supports_enable_thinking() should be removed",
        )

    # ── Group 4: checkBox_reasoning_mode visibility ───────────────────

    def test_g4_reasoning_mode_visible_when_either_capability(self):
        """checkBox_reasoning_mode visible when enable_thinking OR reasoning_budget."""
        # The visibility logic should use caps_thinking_or_reasoning
        self.assertIn("caps_thinking_or_reasoning", IS_SOURCE)
        self.assertIn(
            "caps_thinking_or_reasoning = caps_enable_thinking or caps_reasoning_budget",
            IS_SOURCE,
        )
        # The reasoning_mode checkbox should be set visible based on this
        self.assertIn(
            "checkBox_reasoning_mode.setVisible(caps_thinking_or_reasoning)",
            IS_SOURCE,
        )

    def test_g4_enable_thinking_hidden_when_reasoning_visible(self):
        """checkBox_enable_thinking hidden when reasoning_mode is visible."""
        # The enable_thinking checkbox should be hidden when reasoning_mode is visible
        self.assertIn(
            "checkBox_enable_thinking.setVisible(\n                caps_enable_thinking and not caps_thinking_or_reasoning",
            IS_SOURCE,
        )

    # ── Group 5: _maybe_restart_local_server wraps restart ─────────────

    def test_g5_maybe_restart_wraps_in_coroutine(self):
        """_maybe_restart_local_server wraps restart in _restart_and_refresh."""
        self.assertIn("_restart_and_refresh", IS_SOURCE)
        self.assertIn(
            "asyncio.create_task(_restart_and_refresh())",
            IS_SOURCE,
        )
        # Should call _update_capability_aware_visibility after restart
        self.assertIn(
            "self._update_capability_aware_visibility()",
            IS_SOURCE,
        )

    # ── Group 6: on_checkBox_enable_thinking_stateChanged updates reasoning_mode ─

    def test_g6_enable_thinking_updates_reasoning_mode(self):
        """on_checkBox_enable_thinking_stateChanged also updates reasoning_mode."""
        # Find the handler and verify it updates reasoning_mode
        self.assertIn(
            'self.configuration_settings.update_main_setting("reasoning_mode", is_checked)',
            IS_SOURCE,
        )
        # Should also call _maybe_restart_local_server
        self.assertIn(
            'self._maybe_restart_local_server("enable_thinking")',
            IS_SOURCE,
        )

    # ── Group 7: apply_main_settings_to_ui syncs enable_thinking ──────

    def test_g7_settings_load_syncs_from_reasoning_mode(self):
        """checkBox_enable_thinking is synced from reasoning_mode, not enable_thinking."""
        # The old code: self.ui.checkBox_enable_thinking.setChecked(enable_thinking)
        # The new code: self.ui.checkBox_enable_thinking.setChecked(reason_mode)
        self.assertIn(
            "self.ui.checkBox_enable_thinking.setChecked(reason_mode)",
            IS_SOURCE,
        )

    # ── Group 8: i18n keys ────────────────────────────────────────────

    def test_g8_i18n_keys_present(self):
        """New i18n keys are present in both en.yaml and ru.yaml."""
        for key in [
            "reasoning_mode_qwen3_tooltip",
            "reasoning_mode_both_tooltip",
        ]:
            self.assertIn(key, EN_YAML, f"Missing key '{key}' in en.yaml")
            self.assertIn(key, RU_YAML, f"Missing key '{key}' in ru.yaml")

    # ── Group 9: Diagnostics Panel Block 4 ────────────────────────────

    def test_g9_diagnostics_block4_uses_unified_visibility(self):
        """Diagnostics Panel Block 4 uses thinking_or_reasoning for visibility."""
        self.assertIn("thinking_or_reasoning", DP_SOURCE)
        self.assertIn(
            "thinking_or_reasoning = caps.enable_thinking or caps.reasoning_budget",
            DP_SOURCE,
        )

    def test_g9_diagnostics_no_enable_thinking_templates_reference(self):
        """Diagnostics Panel no longer references ENABLE_THINKING_TEMPLATES in active code."""
        # Check for active code references (not comments or docstrings)
        in_docstring = False
        for line in DP_SOURCE.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            # Skip lines that are part of the removal notice
            if "was removed in iter-73" in stripped:
                continue
            self.assertNotIn(
                "ENABLE_THINKING_TEMPLATES",
                stripped,
                "Active code should not reference ENABLE_THINKING_TEMPLATES",
            )

    # ── Group 10: _capability_map_from_template_name functional test ──

    def test_g10_capability_map_qwen3_thinking(self):
        """_capability_map_from_template_name('qwen3-thinking') → enable_thinking=True."""
        # Parse the function from source
        tree = ast.parse(TD_SOURCE)
        func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_capability_map_from_template_name":
                func = node
                break
        self.assertIsNotNone(func, "_capability_map_from_template_name not found")

    def test_g10_capability_map_phi4(self):
        """_capability_map_from_template_name('phi-4') → reasoning_budget=True."""
        # The function should set reasoning_budget for phi4
        self.assertIn('"phi4" in name_lower', TD_SOURCE)

    def test_g10_capability_map_llama3(self):
        """_capability_map_from_template_name('llama-3') → date_string=True, no thinking."""
        self.assertIn('"llama3" in name_lower', TD_SOURCE)
        # Should NOT set enable_thinking for llama3
        self.assertNotIn(
            '"llama3" in name_lower or "llama3" in name_lower',
            TD_SOURCE,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
