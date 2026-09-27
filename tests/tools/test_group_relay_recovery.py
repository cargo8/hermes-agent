"""Recovery only reattaches delivery tracking, never re-executes user work."""
import concurrent.futures
import json

import pytest

from tools import group_relay as gr


def queued(root):
    return gr.enqueue(root, room_id="room", room_name="Council", text="once",
                      from_profile="default", label="test")


def test_live_owner_excludes_other_renderer_and_crash_lease_expires(tmp_path, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(gr.time, "time", lambda: now[0])
    env = queued(tmp_path)
    assert gr.drain_with_recovery(tmp_path, owner="one")["envelopes"] == [env]
    gr.append_reply_line(tmp_path, env["id"], {"kind": "accepted", "thread": "t",
                         "anchor_entry_id": "a", "epoch": 3}, owner="one")
    assert gr.drain_with_recovery(tmp_path, owner="two")["recoveries"] == []
    now[0] += 50
    assert gr.drain_with_recovery(tmp_path, owner="one", active=[env["id"]])["recoveries"] == []
    now[0] += 50
    assert gr.drain_with_recovery(tmp_path, owner="two")["recoveries"] == []
    now[0] += gr.CLAIM_LEASE_SECONDS + 1
    restored = gr.drain_with_recovery(tmp_path, owner="two")
    assert restored["envelopes"] == []  # cannot execute a prompt a second time
    assert restored["recoveries"][0]["accepted"]["anchor_entry_id"] == "a"
    with pytest.raises(gr.GroupRelayError, match="another renderer"):
        gr.append_reply_line(tmp_path, env["id"], {"kind": "done", "status": "settled"}, owner="one")
    gr.append_reply_line(tmp_path, env["id"], {"kind": "error", "reason": "desktop_restarted"}, owner="two")
    assert gr.drain_with_recovery(tmp_path, owner="two")["recoveries"] == []


def test_acked_entry_ids_recovered_and_retried_lines_deduplicated(tmp_path):
    env = queued(tmp_path)
    gr.drain_with_recovery(tmp_path, owner="one")
    accepted = {"kind": "accepted", "thread": "t", "anchor_entry_id": "a"}
    reply = {"kind": "reply", "entry_id": "r", "text": "result"}
    for line in [accepted, accepted, reply, reply]:
        gr.append_reply_line(tmp_path, env["id"], line, owner="one")
    recovered = gr.drain_with_recovery(tmp_path, owner="one")["recoveries"][0]
    assert recovered["reply_entry_ids"] == ["r"]
    assert [line["kind"] for line in gr.read_reply_lines(tmp_path, env["id"])[0]] == ["accepted", "reply"]
    for line in [{"kind": "done", "status": "settled"}, reply, {"kind": "done", "status": "timeout"}]:
        gr.append_reply_line(tmp_path, env["id"], line, owner="one")
    assert len(gr.read_reply_lines(tmp_path, env["id"])[0]) == 3


def test_unacknowledged_claim_is_reported_not_requeued(tmp_path):
    env = queued(tmp_path)
    gr.drain_with_recovery(tmp_path, owner="one")
    recovered = gr.drain_with_recovery(tmp_path, owner="one")
    assert recovered["envelopes"] == []
    assert recovered["recoveries"][0]["accepted"] is None
    assert recovered["recoveries"][0]["envelope"]["id"] == env["id"]


def test_legacy_replies_are_marked_unsafe_to_replay(tmp_path):
    env = queued(tmp_path)
    gr.drain_with_recovery(tmp_path, owner="one")
    gr.append_reply_line(tmp_path, env["id"], {"kind": "accepted", "thread": "t"}, owner="one")
    gr.append_reply_line(tmp_path, env["id"], {"kind": "reply", "text": "old renderer reply"}, owner="one")
    recovery = gr.drain_with_recovery(tmp_path, owner="one")["recoveries"][0]
    assert recovery["legacy_reply_count"] == 1
    assert recovery["reply_entry_ids"] == []


def test_partial_crash_record_is_repaired_before_ack(tmp_path):
    env = queued(tmp_path)
    path = gr.append_reply_line(tmp_path, env["id"], {"kind": "accepted", "thread": "t"})
    with path.open("ab") as handle:
        handle.write(b'{"kind": "reply", "text": "torn')
    gr.append_reply_line(tmp_path, env["id"], {"kind": "reply", "entry_id": "r", "text": "complete"})
    assert [line["kind"] for line in gr.read_reply_lines(tmp_path, env["id"])[0]] == ["accepted", "reply"]
    for line in path.read_text().splitlines():
        json.loads(line)


def test_parallel_retry_appends_one_long_record(tmp_path):
    env = queued(tmp_path)
    reply = {"kind": "reply", "entry_id": "r", "text": "long" * 10000}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: gr.append_reply_line(tmp_path, env["id"], reply), range(12)))
    lines, _ = gr.read_reply_lines(tmp_path, env["id"])
    assert len(lines) == 1 and lines[0]["text"] == reply["text"]
