"""iter-31 smoke test: verify KI#45 fix (deferred `import main` re-import guard).

Simulates the bug scenario from iter-31 user report:
  1. main.py runs as `__main__` (entry point) — first legitimate import.
  2. prompt_engine.py later does `from main import privacy_filter_enabled`
     (or main.py:934 does `import main as main_module`) — triggers re-import.

Pre-fix symptom: 2 sow_<ts>.log + 2 llama_server_<ts>.log files from 1 launch.
Post-fix expected: 1 sow_<ts>.log + 1 llama_server_<ts>.log file.

This test extracts the logging-setup block from main.py (with the KI#45 guard)
and runs it twice to simulate the re-import. Verifies:
  - Only 1 sow_*.log file created (not 2).
  - Only 1 llama_server_*.log file created (not 2).
  - llama_logger has exactly 1 handler (not 2).
  - root logger has exactly 2 handlers (file + error), not 4.
  - "Logging started" message appears in ONLY 1 file (not 2).

Run: python scripts/iter31_smoke_test.py
"""
import os
import sys
import shutil
import tempfile
import logging
import importlib.util
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _build_main_module_source(log_dir: str) -> str:
    """Return main.py logging-setup source code (extracted from main.py iter-31)."""
    return f'''
import os
import time
import logging
import threading
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

LOG_DIR = {log_dir!r}
os.makedirs(LOG_DIR, exist_ok=True)

privacy_filter_enabled = True  # module-level global (canonical home is app.utils.logging_state)

def _cleanup_old_logs(log_dir, retention_days=14):
    cutoff = time.time() - retention_days * 86400
    for pattern in ["sow_*.log*", "sow_*.jsonl*", "llama_server_*.log*", "*_errors.log*"]:
        for f in Path(log_dir).glob(pattern):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass

# logger + formatter defined OUTSIDE guard
logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] - %(name)s: %(message)s")

# KI#45 (iter-31): defensive guard against re-import side effects.
if not getattr(logger, "_sow_logging_initialized", False):
    logger._sow_logging_initialized = True

    _cleanup_old_logs(LOG_DIR)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(LOG_DIR, f"sow_{{timestamp}}.log")

    logger.handlers.clear()

    file_handler = RotatingFileHandler(log_file, maxBytes=20*1024*1024, backupCount=10, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    error_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, f"sow_{{timestamp}}_errors.log"),
        maxBytes=5*1024*1024, backupCount=5, encoding="utf-8", delay=True,
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    llama_log_file = os.path.join(LOG_DIR, f"llama_server_{{timestamp}}.log")
    llama_handler = RotatingFileHandler(
        llama_log_file, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8", delay=True,
    )
    llama_handler.setFormatter(formatter)
    llama_logger = logging.getLogger("Llama Server Stream")
    llama_logger.handlers.clear()  # KI#45: clear stale handlers before adding new
    llama_logger.addHandler(llama_handler)
    llama_logger.setLevel(logging.INFO)
    llama_logger.propagate = False

    logger.info("========================================")
    logger.info(f"Logging started. Output will be written to: {{log_file}}")
    logger.info(f"All logs will be saved in 'logs' folder")
    logger.info("========================================")

logging.root = logger
logging.root.setLevel(logging.INFO)
logger.propagate = False
'''


def _load_module(source: str, module_name: str):
    """Load Python source as a named module (simulating import)."""
    import types
    mod = types.ModuleType(module_name)
    mod.__file__ = f"<{module_name}>"
    exec(compile(source, mod.__file__, "exec"), mod.__dict__)
    return mod


def _count_files(log_dir: str, pattern: str) -> int:
    return len(list(Path(log_dir).glob(pattern)))


def _read_all_logs(log_dir: str) -> dict:
    """Return {filename: content} for all .log files in dir."""
    out = {}
    for f in sorted(Path(log_dir).glob("*.log")):
        out[f.name] = f.read_text(encoding="utf-8")
    return out


def main():
    print("=" * 70)
    print("iter-31 smoke test: KI#45 fix (deferred `import main` re-import guard)")
    print("=" * 70)

    tmpdir = tempfile.mkdtemp(prefix="iter31_test_")
    try:
        # --- Simulate FIRST import (python main.py as __main__) ---
        print("\n[1] Simulating FIRST import (python main.py → __main__)...")
        source = _build_main_module_source(tmpdir)
        mod_main = _load_module(source, "__main__")
        print(f"    root logger handlers: {len(mod_main.logger.handlers)}")
        print(f"    llama logger handlers: {len(logging.getLogger('Llama Server Stream').handlers)}")
        print(f"    sow_*.log files: {_count_files(tmpdir, 'sow_*.log')}")
        print(f"    llama_server_*.log files: {_count_files(tmpdir, 'llama_server_*.log')}")

        # Simulate a llama-server log line being emitted (creates the lazy llama file)
        logging.getLogger("Llama Server Stream").info("0.00.000.001 I srv  llama_server: server is listening")

        # --- Simulate chat message → triggers `from main import privacy_filter_enabled` ---
        # In the real app this would re-execute main.py module body as `main`.
        # With the KI#45 fix, the guard skips all side effects.
        print("\n[2] Simulating SECOND import (deferred `from main import X`)...")
        mod_main_reimport = _load_module(source, "main")
        print(f"    root logger handlers: {len(logging.getLogger().handlers)}")
        print(f"    llama logger handlers: {len(logging.getLogger('Llama Server Stream').handlers)}")
        print(f"    sow_*.log files: {_count_files(tmpdir, 'sow_*.log')}")
        print(f"    llama_server_*.log files: {_count_files(tmpdir, 'llama_server_*.log')}")

        # --- Emit another llama line AFTER the second import ---
        # Pre-fix: this line would be written to BOTH llama_server_*.log files
        # Post-fix: this line is written to ONLY the original llama_server_*.log file
        print("\n[3] Emitting a post-reimport llama line (would duplicate pre-fix)...")
        logging.getLogger("Llama Server Stream").info("1.17.189.277 I srv  params_from_: Chat format: peg-native")

        # --- Verify ---
        print("\n" + "=" * 70)
        print("VERIFICATION")
        print("=" * 70)

        all_logs = _read_all_logs(tmpdir)

        failures = []

        # Test 1: only 1 sow_*.log file
        sow_files = sorted(Path(tmpdir).glob("sow_*.log"))
        # Filter out _errors.log (delay=True, no errors emitted, so file should not exist anyway)
        sow_main = [f for f in sow_files if "_errors" not in f.name]
        if len(sow_main) == 1:
            print(f"PASS  Test 1: exactly 1 sow_*.log file  ({sow_main[0].name})")
        else:
            failures.append(f"Test 1: expected 1 sow_*.log, got {len(sow_main)}: {[f.name for f in sow_main]}")
            print(f"FAIL  Test 1: expected 1 sow_*.log, got {len(sow_main)}: {[f.name for f in sow_main]}")

        # Test 2: only 1 llama_server_*.log file
        llama_files = sorted(Path(tmpdir).glob("llama_server_*.log"))
        if len(llama_files) == 1:
            print(f"PASS  Test 2: exactly 1 llama_server_*.log file  ({llama_files[0].name})")
        else:
            failures.append(f"Test 2: expected 1 llama_server_*.log, got {len(llama_files)}: {[f.name for f in llama_files]}")
            print(f"FAIL  Test 2: expected 1 llama_server_*.log, got {len(llama_files)}: {[f.name for f in llama_files]}")

        # Test 3: root logger has exactly 2 handlers (file + error)
        root_handlers = logging.getLogger().handlers
        if len(root_handlers) == 2:
            print(f"PASS  Test 3: root logger has 2 handlers (file + error)")
        else:
            failures.append(f"Test 3: expected 2 root handlers, got {len(root_handlers)}")
            print(f"FAIL  Test 3: expected 2 root handlers, got {len(root_handlers)}")

        # Test 4: llama_logger has exactly 1 handler
        llama_handlers = logging.getLogger("Llama Server Stream").handlers
        if len(llama_handlers) == 1:
            print(f"PASS  Test 4: llama_logger has 1 handler (not duplicated)")
        else:
            failures.append(f"Test 4: expected 1 llama handler, got {len(llama_handlers)}")
            print(f"FAIL  Test 4: expected 1 llama handler, got {len(llama_handlers)}")

        # Test 5: "Logging started" appears in exactly 1 file
        started_count = sum(1 for content in all_logs.values() if "Logging started" in content)
        if started_count == 1:
            print(f"PASS  Test 5: 'Logging started' appears in exactly 1 file")
        else:
            failures.append(f"Test 5: expected 'Logging started' in 1 file, got {started_count}")
            print(f"FAIL  Test 5: expected 'Logging started' in 1 file, got {started_count}")

        # Test 6: post-reimport llama line ("Chat format: peg-native") appears in exactly 1 file
        peg_count = sum(1 for content in all_logs.values() if "Chat format: peg-native" in content)
        if peg_count == 1:
            print(f"PASS  Test 6: post-reimport llama line appears in exactly 1 file (not duplicated)")
        else:
            failures.append(f"Test 6: expected 'Chat format: peg-native' in 1 file, got {peg_count}")
            print(f"FAIL  Test 6: expected 'Chat format: peg-native' in 1 file, got {peg_count}")

        # Test 7: no _errors.log file created (delay=True, no errors emitted)
        errors_files = list(Path(tmpdir).glob("*_errors.log"))
        if len(errors_files) == 0:
            print(f"PASS  Test 7: no _errors.log file (delay=True held, no errors emitted)")
        else:
            failures.append(f"Test 7: expected 0 _errors.log, got {len(errors_files)}")
            print(f"FAIL  Test 7: expected 0 _errors.log, got {len(errors_files)}")

        # Test 8: privacy_filter_enabled global is accessible from the re-imported module
        # (proves the import doesn't fail; in the real app, prompt_engine.py reads this)
        try:
            _ = mod_main_reimport.privacy_filter_enabled
            print(f"PASS  Test 8: privacy_filter_enabled accessible from re-imported module (= {_})")
        except AttributeError as e:
            failures.append(f"Test 8: privacy_filter_enabled not accessible: {e}")
            print(f"FAIL  Test 8: privacy_filter_enabled not accessible: {e}")

        print("\n" + "=" * 70)
        if failures:
            print(f"RESULT: FAIL ({len(failures)} test(s) failed)")
            for f in failures:
                print(f"  - {f}")
            ret = 1
        else:
            print("RESULT: ALL 8 TESTS PASS")
            ret = 0
        print("=" * 70)

        # Print the actual log file contents for visual inspection
        print("\n--- log file contents ---")
        for name, content in all_logs.items():
            print(f"\n[{name}]")
            for line in content.splitlines():
                print(f"  {line}")

        return ret
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
