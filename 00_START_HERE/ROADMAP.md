# ACP — Roadmap & Status

> Created: 2026-06-25 · Updated: 2026-06-25

## Stages

| Stage | Criteria | Status | Date |
|---|---|---|---|
| **v0** — Spec draft | Markdown spec written | ✅ DONE | 2026-06-25 |
| **v1** — Spec interop-readable | Separate AI implements from spec | ✅ DONE | 2026-06-25 |
| **v2** — Reference impl | Python SDK + 2 agents trade | ✅ DONE | 2026-06-25 |
| **v3** — Cross-lang interop | Python ↔ TypeScript agents trade | ✅ DONE | 2026-06-25 |
| **v4** — Published | GitHub + NIP proposal + docs | ⬜ NEXT | — |
| **v5** — First adoption | Stranger builds agent on ACP | ⬜ | — |
| **v6** — Self-sustaining | Author gone, agents trade | ⬜ | — |

## Deliverables

| # | Document/Code | Status |
|---|---|---|
| 1 | FOUNDATION.md | ✅ DONE |
| 2 | SUSPECT_GENERATION.md (12 suspects) | ✅ DONE |
| 3 | ACPv0_SPEC.md (protocol spec) | ✅ DONE |
| 4 | HARNESS_DESIGN.md (testing architecture) | ✅ DONE |
| 5 | THREAT_MODEL.md (attack vectors + defenses) | ✅ DONE |
| 6 | acp/ Python SDK (identity, events, crypto, protocol, relay, client) | ✅ DONE |
| 7 | demo.py (live demo, 2 agents trade) | ✅ DONE |
| 8 | tests/ (37 tests: L0+L1+L2+L3) | ✅ DONE (37/37 PASS) |
| 9 | testnet.py (full flow via real WebSocket relay) | ✅ DONE |
| 10 | acp-ts/ TypeScript SDK (identity, crypto, events, mock_lightning) | ✅ DONE |
| 11 | Interop: Python provider ↔ TS consumer via relay | ✅ DONE |
| 12 | GitHub repo + NIP proposal + docs site | ⬜ NEXT |
| 13 | Outreach: LangChain/crewAI/Nostr/Lightning | ⬜ |

## Test Results

```
Python tests: 37 passed in 1.42s
L0 Format:      17/17 PASS
L1 Flow:        10/10 PASS (happy path + 7 edge cases)
L2 Relay:        3/3 PASS (full transaction via WebSocket)
L3 Adversarial:  7/7 PASS (Sybil, replay, false preimage, spam)

TS interop: PASS
  TS crypto: encrypt/decrypt/verify ✅
  TS→Python decrypt: PASS ✅
  Python→TS decrypt: PASS ✅
  Python provider ↔ TS consumer via relay: FULL TRANSACTION PASS ✅
```

## v3 Interop Proof

**Python provider** publishes manifest, receives request from **TypeScript consumer**,
creates atomic offer, settles, publishes receipt. **TS consumer** discovers receipt
via relay, verifies preimage, decrypts result.

Result: "Hello TS Consumer! This is the English translation from Python Provider."

**Two independent implementations on different languages trade via relay.**
Protocol ≠ product — proven.

## Current Status

v3 PASSED — cross-language interop proven.
Next: GitHub repo + NIP proposal + documentation (v4 publication).