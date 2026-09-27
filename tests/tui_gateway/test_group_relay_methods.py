"""Tests: group_relay.* JSON-RPC handlers (tui_gateway/methods_group_relay.py)."""

from __future__ import annotations

import pytest

import tui_gateway.change_watcher as cw
import tui_gateway.server as srv
from tools import group_relay as gr


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / ".hermes"
    (h / "profiles" / "researcher").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(h))
    return h


def _result(envelope):
    assert "error" not in envelope, envelope
    return envelope["result"]


def test_drain_returns_each_envelope_once(home):
    env = gr.enqueue(home, room_id="rm", room_name="Launchpad", text="t", from_profile="researcher", label="L")
    first = _result(srv._methods["group_relay.outbox.drain"](1, {}))
    assert [e["id"] for e in first["envelopes"]] == [env["id"]]
    assert _result(srv._methods["group_relay.outbox.drain"](2, {}))["envelopes"] == []


def test_drain_uses_machine_root_from_profile_home(tmp_path, monkeypatch):
    root = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(root / "profiles" / "researcher"))
    env = gr.enqueue(root, room_id="rm", room_name="n", text="t", from_profile="researcher", label="L")
    got = _result(srv._methods["group_relay.outbox.drain"](1, {}))
    assert [e["id"] for e in got["envelopes"]] == [env["id"]]


def test_reply_appends_lines_and_rejects_bad_input(home):
    env = gr.enqueue(home, room_id="rm", room_name="n", text="t", from_profile="researcher", label="L")
    assert _result(srv._methods["group_relay.reply"](1, {"id": env["id"], "line": {"kind": "accepted", "thread": "x"}}))["ok"]
    assert _result(srv._methods["group_relay.reply"](2, {"id": env["id"], "line": {"kind": "reply", "member": "a", "text": "hi"}}))["ok"]
    lines, _ = gr.read_reply_lines(home, env["id"])
    assert [l["kind"] for l in lines] == ["accepted", "reply"]

    bad_id = srv._methods["group_relay.reply"](3, {"id": "../x", "line": {"kind": "accepted"}})
    assert bad_id["error"]["code"] == 4096
    not_obj = srv._methods["group_relay.reply"](4, {"id": env["id"], "line": "nope"})
    assert not_obj["error"]["code"] == 4095
    bad_kind = srv._methods["group_relay.reply"](5, {"id": env["id"], "line": {"kind": "zzz"}})
    assert bad_kind["error"]["code"] == 4096


def test_change_watch_registered():
    assert "group_relay.outbox.pending" in cw._CHANGE_WATCHES
    assert "group_relay.outbox.drain" in srv._methods and "group_relay.reply" in srv._methods


def test_recovery_roundtrip_through_real_dispatcher(home, monkeypatch):
    now = [2000.0]
    monkeypatch.setattr(gr.time, "time", lambda: now[0])
    env = gr.enqueue(home, room_id="room", room_name="Council", text="once", from_profile="default", label="test")

    def call(method, params):
        return srv.handle_request({"jsonrpc": "2.0", "id": 99, "method": method, "params": params})

    claimed = _result(call("group_relay.outbox.drain", {"owner": "first", "active": []}))
    assert claimed["envelopes"][0]["id"] == env["id"]
    assert _result(call("group_relay.reply", {"owner": "first", "id": env["id"],
        "line": {"kind": "accepted", "thread": "t", "anchor_entry_id": "a", "epoch": 1}}))["ok"]
    now[0] += gr.CLAIM_LEASE_SECONDS + 1
    recovered = _result(call("group_relay.outbox.drain", {"owner": "second", "active": []}))
    assert recovered["envelopes"] == []
    assert recovered["recoveries"][0]["accepted"]["anchor_entry_id"] == "a"


def test_outbox_signature_is_monotone(home, monkeypatch):
    monkeypatch.setattr(srv, "_watcher_home", lambda: home)
    monkeypatch.setattr(srv, "_group_relay_outbox_seen", 0)
    assert srv._group_relay_outbox_sig() is None
    gr.enqueue(home, room_id="rm", room_name="n", text="t", from_profile="researcher", label="L")
    first = srv._group_relay_outbox_sig()
    assert first
    gr.claim_pending(home)  # outbox now empty; signature must not regress
    assert srv._group_relay_outbox_sig() == first
