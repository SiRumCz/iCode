# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""ACP stdio smoke for editors (no LLM)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.cli.e2e.conftest import PROJECT_ROOT

pytestmark = pytest.mark.smoke


def _read_until_id(stdout, req_id: int) -> dict:
    while True:
        line = stdout.readline()
        assert line, f"ACP stdout closed before id={req_id}"
        data = json.loads(line)
        if data.get("id") == req_id:
            return data


def test_acp_demo_initialize_and_session() -> None:
    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT),
        "ICODE_HOME": str(Path("/tmp") / "icode_acp_smoke_home"),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "openjiuwen_icode", "acp", "--demo"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    assert proc.stdin and proc.stdout

    def send(msg: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    init = _read_until_id(proc.stdout, 1)
    assert init["result"]["agentInfo"]["version"]

    send(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/new",
            "params": {"cwd": str(PROJECT_ROOT)},
        }
    )
    created = _read_until_id(proc.stdout, 2)
    sid = created["result"]["sessionId"]

    send(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/prompt",
            "params": {
                "sessionId": sid,
                "prompt": [{"type": "text", "text": "ping"}],
            },
        }
    )
    prompted = _read_until_id(proc.stdout, 3)
    assert prompted["result"].get("ok") is True

    send({"jsonrpc": "2.0", "id": 4, "method": "session/diff", "params": {"sessionId": sid}})
    diffed = _read_until_id(proc.stdout, 4)
    assert "files" in diffed["result"]

    send({"jsonrpc": "2.0", "id": 5, "method": "shutdown", "params": {}})
    assert proc.stdin is not None
    proc.stdin.close()
    err = ""
    if proc.stderr is not None:
        err = proc.stderr.read()
    proc.wait(timeout=60)
    assert proc.returncode == 0
    assert "Traceback" not in (err or "")
