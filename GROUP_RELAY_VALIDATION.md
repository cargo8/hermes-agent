# Desktop group relay recovery validation

Validation date: 2026-09-27. Contribution base: cargo8's
`feature/group-cli-desktop-relay` at `9f242bc34bfbe4a97ae008c2b41f825a90425f28`
([upstream PR #102638](https://github.com/NousResearch/hermes-agent/pull/102638)).
This is a focused follow-up, not a replacement for the author's relay design.

## Reproduced defects and repair

- Add missing wire contracts for `group_relay.outbox.drain`,
  `group_relay.reply`, and `group_relay.outbox.pending`. Dispatcher calls already
  worked; this repairs contract coverage, not a total-connectivity failure.
- Fail closed when an explicitly identified room is gone. Preserve name fallback
  for legacy envelopes with no ID. The original test deliberately allowed
  fallback; this policy difference needs the author's review.
- Retain reply tracking through relay stop/start. Persist the accepted anchor and
  acknowledged reply IDs, use renderer leases, replay committed replies after
  hydration, and advance cursors only after acknowledgment.
- On renderer restart, report interruption rather than re-running possible
  side effects. An untrusted/missing original delivery anchor yields
  `delivery_unknown`. Preserve partial replies and accepted thread binding in
  CLI recovery output, including readable non-JSON errors.

## Exact contribution-branch checks

Environment: macOS arm64, Python 3.11.15 / pytest 9.0.2, Node 26.5.1 /
Vitest 4.1.10. Tests use isolated homes and synthetic model/transport fixtures.
No production credentials or conversation fixtures are committed.

- Canonical Python runner: **96 passed** across the seven files below.
- Desktop: **205 passed** across the six suites below.
- Renderer TypeScript check passed.
- Targeted ESLint passed after formatting corrections.
- Earlier pre-fix checks failed on missing wire contracts, explicit-ID fallback,
  and lost reply tracking; the corrected checks pass. CLI subprocess tests use
  the real dispatcher and filesystem, with explicitly synthetic replies.

```sh
scripts/run_tests.sh \
  tests/hermes_cli/test_group_cli.py \
  tests/hermes_cli/test_group_cli_desktop.py \
  tests/hermes_cli/test_group_desktop_relay_subprocess.py \
  tests/tools/test_group_relay.py \
  tests/tools/test_group_relay_recovery.py \
  tests/tui_gateway/test_group_relay_methods.py \
  tests/tui_gateway/contracts/test_generated.py -j 2 -q

cd apps/desktop
npx vitest run \
  src/plugins/hermes-bots/group-relay.test.ts \
  src/plugins/hermes-bots/group-rounds.test.ts \
  src/plugins/hermes-bots/group-turns.test.ts \
  src/plugins/hermes-bots/group-chat.test.ts \
  src/plugins/hermes-bots/relay.test.ts \
  src/plugins/hermes-bots/group-external-writes.test.ts
npx tsc -p tsconfig.json --noEmit
npx eslint src/plugins/hermes-bots/group-relay.ts \
  src/plugins/hermes-bots/group-relay.test.ts \
  src/plugins/hermes-bots/plugin.tsx
```

## Separate live integration evidence

The same functional fixes were ported to a newer local production base and
packaged there. That port also needs its base's `hermes_yaml` loader; that
unavailable-on-author-base import is deliberately excluded from this PR.
The newer port passed 102 Python and 216 Desktop tests, typecheck, packaging,
and strict local codesign checks. These counts are not the author-base counts.

Live tests used five actual configured native profiles, an open Desktop app,
and an existing Discord gateway:

| Probe | Observed outcome |
| --- | --- |
| CLI first question | Five distinct profile replies; settled |
| Fresh Discord question | Five initial replies returned; CLI waiter timed out; native round later capped at ten messages |
| Same-conversation follow-up | Changed-condition answer from the requested profile; same native thread; settled; returned to Discord |
| Normal Desktop and gateway restart | Process exits and relaunch verified; subsequent question retained source session/native thread; settled; returned to Discord |
| Exact forwarding after guidance update | Question and constraints preserved in one observed round; same-thread answer; settled; returned to Discord |

Receipts had one accepted record and one terminal record per envelope, without
duplicate reply entry IDs. Delivery was separately observed in Discord and
gateway logs. Raw operational receipts remain private.

## Limits and known integration issues

- Normal restart continuity is not forced-crash, interrupted-tool, sleep/wake,
  concurrency, or long-soak validation. Desktop must remain open as coordinator.
- The gateway model dropped a no-tools constraint in an earlier question, and
  a profile made read-only searches. Prompt guidance is not hard tool isolation.
- The representative inserted an answer hint in one probe and later falsely
  summarized every round as settled. Receipts contradicted that summary; it was
  corrected. The later exact-forwarding probe reused the already-hinted history,
  so independent unhinted-memory quality is not established.
- Existing gateway sessions keep their frozen prompt after skill/SOUL updates;
  a fresh native session boundary was needed for the new routing guidance.
- No standalone CLI wait/poll exists after timeout. Retrying the same event can
  conflict after the session learns a minted thread (`None` versus bound ID).
  Do not resubmit uncertain work to obtain a status update.
- Local tests are not GitHub CI approval, merge, or release evidence.
