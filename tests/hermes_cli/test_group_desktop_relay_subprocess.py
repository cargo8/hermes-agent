"""Isolated adoption smoke for cargo8's Desktop group relay.

Real CLI subprocesses, RPC dispatcher and filesystem receipts. Member replies
are synthetic fixtures: this is NOT a live Desktop, model or Discord test.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tui_gateway import server

REPO = Path(__file__).resolve().parents[2]
MEMBERS = ("market", "product", "architecture", "finance", "operations")


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    projection = {"ui_meta": {"hermes-bots-groups": {"version": 3, "rooms": {
        "id:rm-pilot": {"roomId": "rm-pilot", "name": "Pilot", "log": [],
                        "members": [{"name": name} for name in MEMBERS]}
    }}}}
    (home / "profile.yaml").write_text(json.dumps(projection), encoding="utf-8")
    env = {
        "HOME": str(tmp_path),
        "PATH": os.defpath,
        "HERMES_HOME": str(home),
        "HERMES_TEST_ISOLATION": str(home),
        "HERMES_GATEWAY_LOCK_DIR": str(tmp_path / "gateway-locks"),
        "LANG": "C.UTF-8",
        "TZ": "UTC",
    }
    return env


def rpc(method, params=None):
    response = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert response is not None and "error" not in response, response
    return response["result"]


def command(env, session, text, event):
    return subprocess.Popen(
        [sys.executable, "-m", "hermes_cli.main", "group", "send", "Pilot", text,
         "--kind", "desktop", "--session", session, "--event-id", event,
         "--as", "isolated Discord-shaped fixture", "--wait", "--json",
         "--poll", "0.02", "--timeout", "15"],
        cwd=REPO, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def exchange(env, session, text, event, expected_thread, assigned_thread):
    process = command(env, session, text, event)
    try:
        deadline = time.monotonic() + 10
        envelopes = []
        while not envelopes and process.poll() is None and time.monotonic() < deadline:
            envelopes = rpc("group_relay.outbox.drain")["envelopes"]
            if not envelopes:
                time.sleep(0.02)
        assert len(envelopes) == 1, (envelopes, process.poll())
        envelope = envelopes[0]
        assert envelope["text"] == text and envelope["thread"] == expected_thread
        assert envelope["room_id"] == "rm-pilot"
        lines = [{"kind": "accepted", "thread": assigned_thread, "group": "Pilot"}]
        lines.extend({"kind": "reply", "member": name, "text": f"synthetic {name}: {text}",
                      "thread": assigned_thread} for name in MEMBERS)
        lines.append({"kind": "done", "status": "settled", "replies": len(MEMBERS)})
        for line in lines:
            assert rpc("group_relay.reply", {"id": envelope["id"], "line": line})["ok"]
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
        summary = json.loads(stdout)
        assert summary["status"] == "settled" and summary["thread"] == assigned_thread
        assert len(summary["replies"]) == len(MEMBERS)
        assert all(f"synthetic {name}: {text}" in stdout for name in MEMBERS)
        return summary
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)


def test_cli_rpc_roundtrip_preserves_followup_and_separates_other_session(isolated):
    exchange(isolated, "fixture-discord-A", "first", "event-A1", None, "thread-A")
    # A fresh CLI process must recover the binding learned by --wait.
    exchange(isolated, "fixture-discord-A", "followup", "event-A2", "thread-A", "thread-A")
    exchange(isolated, "fixture-discord-B", "other topic", "event-B1", None, "thread-B")
    assert rpc("group_relay.outbox.drain")["envelopes"] == []
