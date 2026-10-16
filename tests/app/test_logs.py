"""Logs: one JSON object per line on stdout, secrets redacted, library warnings captured as JSON too."""

import json
import logging
import subprocess
import sys
from pathlib import Path

from app.logs import configure_logging, log_event, set_secrets

REPO = Path(__file__).resolve().parents[2]


def test_events_are_single_json_lines_with_secrets_redacted(capsys):
    configure_logging("INFO")
    set_secrets(["sk-test-1234567890", "0123456789abcdef"])
    log_event("ask", request_id="r1", note="key sk-test-1234567890 and canary 0123456789ABCDEF")
    logging.getLogger("some.lib").debug("hidden at INFO")
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "ask" and rec["request_id"] == "r1"
    assert "sk-test" not in lines[0] and "0123456789abcdef" not in lines[0].lower()
    set_secrets([])


def test_python_warnings_become_json_log_lines():
    # a subprocess, because pytest captures warnings itself inside the test process
    code = ("from app.logs import configure_logging; configure_logging('INFO'); import warnings; "
            "warnings.warn('model pooling changed', UserWarning)")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines and "model pooling changed" in json.loads(lines[-1])["msg"]
