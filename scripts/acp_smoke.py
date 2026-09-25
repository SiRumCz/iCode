#!/usr/bin/env python3
# coding: utf-8
"""ACP stdio handshake smoke (Phase 0 / CI)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "openjiuwen_icode",
            "acp",
            "--demo",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert proc.stdin and proc.stdout
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/new",
            "params": {"cwd": str(ROOT)},
        },
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
    ]
    for msg in reqs:
        proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.close()
    out = proc.stdout.read()
    err = proc.stderr.read() if proc.stderr else ""
    proc.wait(timeout=60)
    if err.strip():
        print(err, file=sys.stderr)
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    by_id = {m.get("id"): m for m in lines if "id" in m}
    init = by_id.get(1, {})
    result = init.get("result") or {}
    agent = result.get("agentInfo") or {}
    assert result.get("protocolVersion") == 1, init
    assert agent.get("name"), init
    assert agent.get("version"), init
    assert by_id.get(2, {}).get("result", {}).get("sessionId"), by_id.get(2)
    print(
        "acp-smoke OK",
        agent.get("name"),
        agent.get("version"),
        by_id[2]["result"]["sessionId"],
    )
    return 0 if proc.returncode == 0 else proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
