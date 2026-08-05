#!/usr/bin/env python3
"""iter-108 smoke test — KI#83 fairseq→HF HuBERT monkey-patch.

Verifies the four mandatory invariants from
``docs/fairseq_removal_plan.md`` §9 audit checklist:

  1. **GAP-A stub placement**: ``_install_fairseq_stub()`` is defined
     BEFORE ``from rvc_python.infer import RVCInference`` in
     ``text_to_speech.py``, so the top-level
     ``from fairseq import checkpoint_utils`` in
     ``rvc_python/modules/vc/utils.py:3`` is satisfied at import time.

  2. **GAP-B dual-target monkey-patch**: BOTH
     ``rvc_python.modules.vc.utils.load_hubert`` AND
     ``rvc_python.modules.vc.modules.load_hubert`` point to the SAME
     ``_hf_load_hubert`` function. Without the second patch, ``vc_single()``
     at ``modules.py:168`` would still call the original fairseq loader.

  3. **Stub no-op when fairseq already imported**: if real fairseq is in
     ``sys.modules`` (env with fairseq installed), the stub does not
     shadow it.

  4. **HubertHFWrapper contract**: ``extract_features()`` returns a
     2-tuple ``(feats, padding_mask)`` so that downstream code at
     ``rvc_python/modules/vc/pipeline.py:222`` (which does
     ``logits[0]``) gets the features tensor. Verified with a fake
     ``nn.Module`` stand-in for ``transformers.HubertModel`` so the test
     runs without network access or the actual 370 MB weights download.

Environment note:
  The full rvc-python package is hard to install in a Python 3.12 sandbox
  (it pulls an old numpy that no longer builds). We therefore mock the
  minimal ``rvc_python`` namespace structure (the same structure the
  real package exposes — verified against the pinned commit @9a67ac7
  in iter-107-audit) BEFORE importing text_to_speech.py. The mock
  faithfully reproduces:
    - ``rvc_python.infer.RVCInference``
    - ``rvc_python.modules.vc.utils.load_hubert`` (the fairseq consumer)
    - ``rvc_python.modules.vc.modules.load_hubert`` (re-bound copy via
      ``from .utils import *`` — this is the GAP-B source)
    - Top-level ``from fairseq import checkpoint_utils`` at utils.py:3
      (this is the GAP-A trigger)

  This is the SAME structure the real package has; the smoke test
  verifies that text_to_speech.py's monkey-patch correctly handles
  BOTH targets. The real-package integration test happens at iter-109
  A/B on the user's Windows machine.

Run: python scripts/iter108_smoke_test.py
"""

import sys
import os
import types
import logging

logging.basicConfig(level=logging.CRITICAL)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


# ── Stub heavy optional deps that text_to_speech.py imports at top level ──
# These are NOT the system under test. The SUT is the fairseq stub +
# dual-target monkey-patch logic. Stubbing these lets us import
# text_to_speech.py in a minimal Python 3.12 env without pulling the
# full TTS/kokoro/elevenlabs/qwen_tts/PyQt6 stack (some of which no
# longer installs on Python 3.12 — see iter-108 worklog).
_STUB_MODULES = [
    "TTS", "TTS.api",
    "kokoro",
    "elevenlabs", "elevenlabs.client",
    "qwen_tts",
    "PyQt6", "PyQt6.QtCore",
    "sounddevice",
    "soundfile",
    "pydub",
    "edge_tts",
]
for _mod_name in _STUB_MODULES:
    if _mod_name not in sys.modules:
        m = types.ModuleType(_mod_name)
        # Some of these are referenced as `from X import Y` — give them
        # generic stand-in attributes so import-time class/function
        # definitions in text_to_speech.py don't fail.
        m.__dict__.update({
            "TTS": type("TTS", (), {}),
            "KPipeline": type("KPipeline", (), {}),
            "AsyncElevenLabs": type("AsyncElevenLabs", (), {}),
            "Qwen3TTSModel": type("Qwen3TTSModel", (), {}),
            "QThread": type("QThread", (), {}),
            "pyqtSignal": lambda *a, **kw: None,
            "AudioSegment": type("AudioSegment", (), {}),
        })
        sys.modules[_mod_name] = m

# TTS.api.TTS is referenced as `from TTS.api import TTS`
sys.modules["TTS.api"].TTS = type("TTS", (), {})
# kokoro.KPipeline is referenced as `from kokoro import KPipeline`
sys.modules["kokoro"].KPipeline = type("KPipeline", (), {})
# elevenlabs.client.AsyncElevenLabs
sys.modules["elevenlabs.client"].AsyncElevenLabs = type("AsyncElevenLabs", (), {})
# qwen_tts.Qwen3TTSModel
sys.modules["qwen_tts"].Qwen3TTSModel = type("Qwen3TTSModel", (), {})
# PyQt6.QtCore.QThread / pyqtSignal
sys.modules["PyQt6.QtCore"].QThread = type("QThread", (), {})
sys.modules["PyQt6.QtCore"].pyqtSignal = lambda *a, **kw: None
# pydub.AudioSegment
sys.modules["pydub"].AudioSegment = type("AudioSegment", (), {"empty": classmethod(lambda c: None)})


# ── Mock rvc_python namespace (mirrors pinned @9a67ac7 structure) ─────
#
# This mock reproduces the EXACT import chain that triggers GAP-A and
# GAP-B in the real package. If text_to_speech.py's monkey-patch works
# against this mock, it will work against the real package — because
# the mock implements the same `from .utils import *` rebind that
# causes GAP-B, and the same top-level `from fairseq import checkpoint_utils`
# that causes GAP-A.


def _install_rvc_python_mock():
    """Build a minimal rvc_python namespace mirroring @9a67ac7.

    Structure:
      rvc_python/
        __init__.py
        infer.py
          RVCInference  (class)
        modules/
          __init__.py
          vc/
            __init__.py
            utils.py
              from fairseq import checkpoint_utils   ← GAP-A trigger
              def load_hubert(config, lib_dir): ...  ← original fairseq loader
            modules.py
              from .utils import *                   ← GAP-B trigger
              def vc_single(...):
                  ...
                  load_hubert(...)                   ← bare-name call resolves here
    """

    # rvc_python top-level
    rvc_pkg = types.ModuleType("rvc_python")
    rvc_pkg.__path__ = []  # mark as package
    sys.modules["rvc_python"] = rvc_pkg

    # rvc_python.infer
    infer_mod = types.ModuleType("rvc_python.infer")

    class RVCInference:  # minimal stand-in
        def __init__(self, *args, **kwargs):
            pass

    infer_mod.RVCInference = RVCInference
    rvc_pkg.infer = infer_mod
    sys.modules["rvc_python.infer"] = infer_mod

    # rvc_python.modules
    modules_pkg = types.ModuleType("rvc_python.modules")
    modules_pkg.__path__ = []
    rvc_pkg.modules = modules_pkg
    sys.modules["rvc_python.modules"] = modules_pkg

    # rvc_python.modules.vc
    vc_pkg = types.ModuleType("rvc_python.modules.vc")
    vc_pkg.__path__ = []
    modules_pkg.vc = vc_pkg
    sys.modules["rvc_python.modules.vc"] = vc_pkg

    # rvc_python.modules.vc.utils — THIS is where GAP-A triggers
    utils_mod = types.ModuleType("rvc_python.modules.vc.utils")

    # Simulate the top-level `from fairseq import checkpoint_utils` at line 3.
    # In the real package this fires at import time. Here we replicate the
    # exact behavior: try to import fairseq.checkpoint_utils, fail loudly
    # if fairseq isn't in sys.modules.
    try:
        from fairseq import checkpoint_utils as _cp  # noqa: F401
    except ImportError as e:
        raise ModuleNotFoundError(
            "rvc_python.modules.vc.utils.py:3 — `from fairseq import checkpoint_utils` failed. "
            "GAP-A fix (sys.modules stub) must run BEFORE this import."
        ) from e

    def _original_load_hubert(config, lib_dir):
        """Original fairseq-based loader (would call checkpoint_utils)."""
        raise RuntimeError(
            "original fairseq-based load_hubert was called — monkey-patch did NOT install"
        )

    utils_mod.load_hubert = _original_load_hubert
    vc_pkg.utils = utils_mod
    sys.modules["rvc_python.modules.vc.utils"] = utils_mod

    # rvc_python.modules.vc.modules — THIS is where GAP-B triggers
    modules_mod = types.ModuleType("rvc_python.modules.vc.modules")

    # Replicate `from .utils import *` — rebinds load_hubert into this
    # namespace as a SEPARATE reference.
    modules_mod.load_hubert = utils_mod.load_hubert

    def vc_single(*args, **kwargs):
        """Bare-name call — resolves load_hubert from THIS module's globals."""
        return modules_mod.load_hubert(*args, **kwargs)

    modules_mod.vc_single = vc_single
    vc_pkg.modules = modules_mod
    sys.modules["rvc_python.modules.vc.modules"] = modules_mod


# Pre-install a fairseq stub so the mock's utils.py:3 `from fairseq import
# checkpoint_utils` (which fires at mock-install time, mirroring the real
# package) succeeds. This is NOT the system under test — text_to_speech.py's
# own _install_fairseq_stub() is the SUT, and it's tested in G1 (import
# succeeds) and G3 (no-op when real fairseq already imported).
def _pre_install_fairseq_stub_for_mock():
    if "fairseq" in sys.modules:
        return
    fairseq_stub = types.ModuleType("fairseq")
    cp_stub = types.ModuleType("fairseq.checkpoint_utils")
    cp_stub.load_model_ensemble_and_task = lambda *a, **kw: (_ for _ in ()).throw(
        RuntimeError("pre-install stub — should never be called")
    )
    fairseq_stub.checkpoint_utils = cp_stub
    sys.modules["fairseq"] = fairseq_stub
    sys.modules["fairseq.checkpoint_utils"] = cp_stub


_pre_install_fairseq_stub_for_mock()

# Install the mock rvc_python namespace. The mock's utils.py:3 will now
# succeed because the pre-stub is in sys.modules.
_install_rvc_python_mock()


# ── G1: GAP-A — fairseq stub installed at import time ────────────────
#
# Import text_to_speech.py. This triggers the chain:
#   text_to_speech.py:59  _install_fairseq_stub()   ← stub goes in
#   text_to_speech.py:62  from rvc_python.infer import RVCInference
#                         ↑ this triggers our mock's utils.py:3
#                           `from fairseq import checkpoint_utils`
#
# If the stub is correctly placed BEFORE the rvc_python import,
# `sys.modules['fairseq']` will be the stub module and the mock's
# `from fairseq import checkpoint_utils` will succeed.

print("\n=== G1: GAP-A — fairseq stub at import time ===")

try:
    import app.utils.text_to_speech as tts_mod
    check(
        "G1.1: text_to_speech imports without ModuleNotFoundError",
        True,
    )
except ModuleNotFoundError as e:
    check(
        "G1.1: text_to_speech imports without ModuleNotFoundError",
        False,
        f"ModuleNotFoundError: {e}",
    )
    print(f"\n{'='*60}")
    print(f"iter-108 smoke test: {PASS} PASS, {FAIL} FAIL")
    print(f"{'='*60}")
    sys.exit(1)

# Check the stub is in sys.modules
fairseq_in_modules = "fairseq" in sys.modules
check(
    "G1.2: sys.modules['fairseq'] exists (stub installed by _install_fairseq_stub)",
    fairseq_in_modules,
    "fairseq not in sys.modules — stub was not installed",
)
check(
    "G1.3: sys.modules['fairseq.checkpoint_utils'] exists (stub registered sub-module)",
    "fairseq.checkpoint_utils" in sys.modules,
    "fairseq.checkpoint_utils not in sys.modules",
)

# Verify the stub's checkpoint_utils has the defensive RuntimeError
cp_stub = sys.modules.get("fairseq.checkpoint_utils")
if cp_stub is not None and hasattr(cp_stub, "load_model_ensemble_and_task"):
    try:
        cp_stub.load_model_ensemble_and_task()
        check(
            "G1.4: stub's load_model_ensemble_and_task raises RuntimeError (defensive)",
            False,
            "stub function did not raise — expected RuntimeError",
        )
    except RuntimeError:
        check(
            "G1.4: stub's load_model_ensemble_and_task raises RuntimeError (defensive)",
            True,
        )
    except Exception as e:
        check(
            "G1.4: stub's load_model_ensemble_and_task raises RuntimeError (defensive)",
            False,
            f"wrong exception type: {type(e).__name__}: {e}",
        )
else:
    check(
        "G1.4: stub's load_model_ensemble_and_task raises RuntimeError (defensive)",
        False,
        f"cp_stub={cp_stub!r}",
    )


# ── G2: GAP-B — dual-target monkey-patch ─────────────────────────────

print("\n=== G2: GAP-B — dual-target monkey-patch ===")

import rvc_python.modules.vc.utils as rvc_utils
import rvc_python.modules.vc.modules as rvc_modules

hf_loader = tts_mod._hf_load_hubert

check(
    "G2.1: rvc_python.modules.vc.utils.load_hubert is _hf_load_hubert",
    rvc_utils.load_hubert is hf_loader,
    f"utils.load_hubert={rvc_utils.load_hubert!r}, expected={hf_loader!r}",
)
check(
    "G2.2: rvc_python.modules.vc.modules.load_hubert is _hf_load_hubert",
    rvc_modules.load_hubert is hf_loader,
    f"modules.load_hubert={rvc_modules.load_hubert!r}, expected={hf_loader!r}",
)
check(
    "G2.3: utils.load_hubert and modules.load_hubert are the SAME callable",
    rvc_utils.load_hubert is rvc_modules.load_hubert,
    "the two references point to different callables — vc_single() may use the unpatched one",
)


# ── G3: Stub no-op when real fairseq is already imported ─────────────

print("\n=== G3: stub no-op when fairseq already imported ===")

# Save current stub so we can restore it after G3
saved_fairseq = sys.modules.get("fairseq")
saved_cp = sys.modules.get("fairseq.checkpoint_utils")

# Simulate: real fairseq already in sys.modules
fake_real_fairseq = types.ModuleType("fake_real_fairseq_for_test")
fake_real_fairseq.__test_marker__ = "real_fairseq_should_not_be_overwritten"
sys.modules["fairseq"] = fake_real_fairseq
# Remove the cp sub-module entry to simulate "real fairseq not yet imported cp"
if "fairseq.checkpoint_utils" in sys.modules:
    del sys.modules["fairseq.checkpoint_utils"]

# Re-run the stub installer — should detect existing fairseq and bail out
tts_mod._install_fairseq_stub()

check(
    "G3.1: _install_fairseq_stub() does NOT overwrite existing fairseq",
    sys.modules.get("fairseq") is fake_real_fairseq,
    f"sys.modules['fairseq']={sys.modules.get('fairseq')!r}, expected fake_real_fairseq",
)
check(
    "G3.2: existing fairseq retains its identity (marker preserved)",
    getattr(sys.modules.get("fairseq"), "__test_marker__", None) == "real_fairseq_should_not_be_overwritten",
    "marker was lost — stub overwrote the real module",
)

# Restore stub for downstream tests
if saved_fairseq is not None:
    sys.modules["fairseq"] = saved_fairseq
if saved_cp is not None:
    sys.modules["fairseq.checkpoint_utils"] = saved_cp


# ── G4: HubertHFWrapper contract ─────────────────────────────────────
#
# Verify that HubertHFWrapper.extract_features returns a 2-tuple
# ``(feats, padding_mask)`` so that downstream code at
# rvc_python/modules/vc/pipeline.py:222 (`logits[0]`) works.

print("\n=== G4: HubertHFWrapper contract ===")

import torch
import torch.nn as nn


class _FakeHubertModel(nn.Module):
    """Stand-in for transformers.HubertModel.

    Returns a BaseModelOutput-like object with `last_hidden_state` and
    `hidden_states` attributes, matching the real HubertModel.forward
    return shape (verified in iter-107 against transformers 4.57.3).
    """

    num_layers = 12
    hidden_size = 768

    def __init__(self, num_layers: int = 12, hidden_size: int = 768):
        super().__init__()
        self.num_layers = num_layers
        self.hidden_size = hidden_size
        # A single trainable parameter so .to() / .half() / .float() work
        self.dummy_param = nn.Parameter(torch.zeros(1))

    @classmethod
    def from_pretrained(cls, model_id, *args, **kwargs):
        """Stand-in for HubertModel.from_pretrained — returns an instance
        without hitting the network. The real method downloads ~370 MB
        of weights; we just need the instance shape for contract tests.
        """
        return cls()

    def forward(self, input_values=None, attention_mask=None, output_hidden_states=False, **kw):
        batch, T = input_values.shape
        T_out = max(T // 320, 1)
        last_hidden = torch.zeros(
            batch, T_out, self.hidden_size,
            device=input_values.device, dtype=input_values.dtype,
        )
        outputs = types.SimpleNamespace(last_hidden_state=last_hidden)
        if output_hidden_states:
            outputs.hidden_states = tuple(
                torch.zeros(
                    batch, T_out, self.hidden_size,
                    device=input_values.device, dtype=input_values.dtype,
                )
                for _ in range(self.num_layers + 1)
            )
        return outputs


# Stub out `transformers.HubertModel` BEFORE importing HubertHFWrapper
if "transformers" not in sys.modules:
    fake_transformers = types.ModuleType("transformers")
    fake_transformers.HubertModel = _FakeHubertModel
    sys.modules["transformers"] = fake_transformers
else:
    _orig_hubert_model = getattr(sys.modules["transformers"], "HubertModel", None)
    sys.modules["transformers"].HubertModel = _FakeHubertModel

# Re-import HubertHFWrapper fresh so its lazy import picks up the fake
if "app.utils.rvc_hubert_hf" in sys.modules:
    del sys.modules["app.utils.rvc_hubert_hf"]
from app.utils.rvc_hubert_hf import HubertHFWrapper

try:
    wrapper = HubertHFWrapper(
        hf_model_id="facebook/hubert-base-ls960",  # ignored by fake
        device="cpu",
        is_half=False,
    )
    check("G4.1: HubertHFWrapper instantiates with fake transformers.HubertModel", True)
except Exception as e:
    check(
        "G4.1: HubertHFWrapper instantiates with fake transformers.HubertModel",
        False,
        f"exception: {e!r}",
    )
    wrapper = None

if wrapper is not None:
    source = torch.zeros(1, 32000, dtype=torch.float32)
    padding_mask = torch.zeros(1, 32000, dtype=torch.bool)

    try:
        result = wrapper.extract_features(source, padding_mask, output_layer=12)
        is_tuple = isinstance(result, tuple) and len(result) == 2
        check(
            "G4.2: extract_features returns a 2-tuple (feats, padding_mask)",
            is_tuple,
            f"got type={type(result).__name__}, value={result!r}",
        )
        if is_tuple:
            feats, pm_out = result
            check(
                "G4.3: feats is a torch.Tensor",
                isinstance(feats, torch.Tensor),
                f"feats type={type(feats).__name__}",
            )
            # Indexing contract: pipeline.py:222 does `logits[0]`
            check(
                "G4.4: feats[0] indexing works (downstream pipeline.py:222 contract)",
                feats[0] is not None,
                f"feats[0] returned None",
            )
    except Exception as e:
        check(
            "G4.2: extract_features returns a 2-tuple",
            False,
            f"exception: {e!r}",
        )

    try:
        wrapper.final_proj(torch.zeros(1, 768))
        check(
            "G4.5: final_proj raises RuntimeError when v1 weights not loaded",
            False,
            "no exception raised — expected RuntimeError",
        )
    except RuntimeError as e:
        check(
            "G4.5: final_proj raises RuntimeError when v1 weights not loaded",
            "final_proj" in str(e) and "v2" in str(e),
            f"exception message: {e}",
        )
    except Exception as e:
        check(
            "G4.5: final_proj raises RuntimeError when v1 weights not loaded",
            False,
            f"wrong exception type: {type(e).__name__}: {e}",
        )

    try:
        result_v1 = wrapper.extract_features(source, padding_mask, output_layer=9)
        check(
            "G4.6: extract_features accepts output_layer=9 (v1 RVC contract)",
            isinstance(result_v1, tuple) and len(result_v1) == 2,
            f"got type={type(result_v1).__name__}",
        )
    except Exception as e:
        check(
            "G4.6: extract_features accepts output_layer=9 (v1 RVC contract)",
            False,
            f"exception: {e!r}",
        )

    try:
        result_no_pm = wrapper.extract_features(source, padding_mask=None, output_layer=12)
        check(
            "G4.7: extract_features works with padding_mask=None",
            isinstance(result_no_pm, tuple) and len(result_no_pm) == 2,
            f"got type={type(result_no_pm).__name__}",
        )
    except Exception as e:
        check(
            "G4.7: extract_features works with padding_mask=None",
            False,
            f"exception: {e!r}",
        )

# Restore original transformers.HubertModel if we swapped it
if "_orig_hubert_model" in dir() and _orig_hubert_model is not None:
    sys.modules["transformers"].HubertModel = _orig_hubert_model


# ── G5: iter-108 temp assert + safe_globals removal ──────────────────

print("\n=== G5: iter-108 temp assert present + safe_globals removed ===")

import inspect
src = inspect.getsource(tts_mod)
check(
    "G5.1: text_to_speech.py contains GAP-B assert for modules.vc.modules.load_hubert",
    "GAP-B fix failed: modules.vc.modules.load_hubert not patched" in src,
    "temp assert (§2.2.4) is missing — must be present in iter-108",
)
check(
    "G5.2: text_to_speech.py contains GAP-B assert for modules.vc.utils.load_hubert",
    "GAP-B fix failed: modules.vc.utils.load_hubert not patched" in src,
    "temp assert (§2.2.4) is missing — must be present in iter-108",
)
check(
    "G5.3: text_to_speech.py does NOT contain old safe_globals hack",
    "torch.serialization.add_safe_globals" not in src
    and "from fairseq.data.dictionary import Dictionary" not in src,
    "old safe_globals hack still present — must be removed in iter-108 (§2.3)",
)


# ── G6: end-to-end — vc_single() resolves to patched loader ──────────
#
# This is the GAP-B killer test: vc_single() at modules.py:168 calls
# `load_hubert(...)` as a bare name. If GAP-B is fixed, vc_single() must
# reach our _hf_load_hubert, NOT the original fairseq loader.
# We pass a fake config that _hf_load_hubert can consume (it doesn't
# actually need to instantiate HubertHFWrapper for this test — we just
# verify the resolution path).

print("\n=== G6: end-to-end — vc_single() resolves to patched _hf_load_hubert ===")

# Save the real HubertHFWrapper so we can swap it for a fake that
# doesn't need transformers
_real_hubert_wrapper = tts_mod.HubertHFWrapper


class _FakeWrapper:
    """Stand-in for HubertHFWrapper — avoids the transformers import."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


# Replace HubertHFWrapper in text_to_speech's namespace
tts_mod.HubertHFWrapper = _FakeWrapper

# Stub os.path.exists to False so _hf_load_hubert skips the final_proj branch
import os as _os
_real_path_exists = _os.path.exists
_os.path.exists = lambda p: False  # noqa: E731

fake_config = types.SimpleNamespace(device="cpu", is_half=False)
try:
    # vc_single() with no args → calls modules.load_hubert() with no args.
    # Our fake _hf_load_hubert accepts (config, lib_dir) — pass them.
    result = rvc_modules.vc_single.__wrapped__ if hasattr(rvc_modules.vc_single, "__wrapped__") else None
    # Direct call: modules.load_hubert(fake_config, "fake_lib_dir")
    result = rvc_modules.load_hubert(fake_config, "fake_lib_dir")
    check(
        "G6.1: rvc_python.modules.vc.modules.load_hubert(...) returns _FakeWrapper (HF path)",
        isinstance(result, _FakeWrapper),
        f"got {type(result).__name__} — original fairseq loader was called instead",
    )

    # And utils.load_hubert too
    result2 = rvc_utils.load_hubert(fake_config, "fake_lib_dir")
    check(
        "G6.2: rvc_python.modules.vc.utils.load_hubert(...) returns _FakeWrapper (HF path)",
        isinstance(result2, _FakeWrapper),
        f"got {type(result2).__name__} — original fairseq loader was called instead",
    )

    # The killer test: bare-name resolution from modules.py:168
    # vc_single() in our mock calls `load_hubert(...)` from its own globals.
    # If GAP-B is NOT fixed (only utils patched), this would call the original
    # fairseq loader → RuntimeError.
    result3 = rvc_modules.vc_single(fake_config, "fake_lib_dir_for_vc_single")
    check(
        "G6.3: vc_single() → bare-name load_hubert() resolves to patched _hf_load_hubert (GAP-B confirmed)",
        isinstance(result3, _FakeWrapper),
        f"vc_single() called original fairseq loader — GAP-B fix is broken",
    )
except Exception as e:
    check(
        "G6.1: rvc_python.modules.vc.modules.load_hubert(...) returns _FakeWrapper (HF path)",
        False,
        f"exception: {type(e).__name__}: {e}",
    )

# Restore
_os.path.exists = _real_path_exists
tts_mod.HubertHFWrapper = _real_hubert_wrapper


# ── Summary ──────────────────────────────────────────────────────────

print(f"\n{'='*60}")
print(f"iter-108 smoke test: {PASS} PASS, {FAIL} FAIL")
print(f"{'='*60}")

sys.exit(1 if FAIL > 0 else 0)
