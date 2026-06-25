# ACP — Agent Commerce Protocol

> Open protocol: discovery + atomic delivery + receipt + reputation for AI agents.
> Payment = pluggable (L402, Lightning, Cashu). Not a competitor to L402 — a complement.
>
> **Status:** v0.3 DRAFT · **Interop:** Python ↔ TypeScript proven · **Tests:** 50/50 PASS

---

## What is ACP?

ACP gives AI agents the ability to **find, pay for, and receive services** on the
internet — without human intermediaries, API keys, or pre-existing relationships.

```
Human: "Buy me a VPN"
Agent: "Found VPN for 5000 sats. Buy?"
Human: "Yes"
Agent: "Done. VPN key: xxxx. Spent 5000 sats."
```

Everything else (discovery, payment, encryption, proof) happens under the hood.

## Why ACP?

**L402** solved agent **payment** (HTTP 402 → Lightning invoice → macaroon).
**A2A** solved agent **communication** (AgentCards, messaging).

**Nobody solved:**
- **Discovery** — how does an agent FIND a provider? (ACP: Nostr manifests)
- **Atomic delivery** — how does agent GUARANTEE receiving the result? (ACP: hold invoice + preimage = decryption key)
- **Receipt** — how does agent PROVE what it bought? (ACP: Nostr receipt events)
- **Reputation** — how does agent TRUST a provider? (ACP: attestations)

ACP = the missing layers. Payment = pluggable (use L402, Lightning, or Cashu).

## How it works

```
┌─────────────────────────────────────────────┐
│  Human gives agent a wallet (one line)      │
│  Human: "Buy X"                             │
├─────────────────────────────────────────────┤
│  Agent (Claude Code / any framework)         │
│  └─ ACP tool: discover → confirm → buy      │
├──────┬──────────┬───────────────────────────┤
│ Nostr│ Payment  │  (existing infrastructure) │
│disco │ L402/LN  │  pluggable payment rail    │
└──────┴──────────┴───────────────────────────┘
```

### Atomic Delivery (the key innovation)

1. Provider generates random key K
2. Encrypts result: `E = AES(result, K)`
3. Creates Lightning hold invoice: preimage = K, hash = SHA256(K)
4. Agent pays → funds locked → provider settles → K revealed
5. Agent decrypts result with K

**Provider cannot get paid without delivering. Agent cannot get result without paying.**
Atomic = guaranteed by cryptography, not trust.

## Protocol Events (4 core)

| Kind | Name | Who publishes | Purpose |
|---|---|---|---|
| 30000 | Agent Manifest | Provider | "I offer X for Y sats" |
| 30001 | Service Request | Consumer | "I need X, budget Y" |
| 30002 | Service Offer | Provider | "Here's invoice + encrypted result" |
| 30003 | Transaction Receipt | Provider | "Deal done, here's cryptographic proof" |

Extensions: 30004 (Attestation), 30005 (Dispute), 30006 (Resolution).

## Repository Structure

```
acp/
├── 00_START_HERE/          # Foundation, spec, suspects, threat model
│   ├── FOUNDATION.md
│   ├── ACPv0_SPEC.md
│   ├── SUSPECT_GENERATION.md
│   ├── HARNESS_DESIGN.md
│   └── THREAT_MODEL.md
├── acp/                    # Python SDK
│   ├── agent.py            # Zero-config ACPAgent
│   ├── identity.py         # Nostr keypair
│   ├── crypto.py           # Preimage = decryption key
│   ├── events.py           # 7 event types
│   ├── protocol.py         # Transaction flow + MockLightning
│   ├── providers.py        # Native/Bridge/Adapter providers
│   ├── relay.py            # Minimal Nostr relay
│   ├── client.py           # Nostr WebSocket client
│   ├── lnbits_wallet.py    # Real Lightning via LNbits API
│   └── tools/
│       └── agent_tool.py   # Plugin for agent frameworks
├── acp-ts/                 # TypeScript SDK (interop proof)
│   └── src/
│       ├── identity.ts
│       ├── crypto.ts
│       ├── events.ts
│       └── mock_lightning.ts
├── tests/                  # 50 tests (L0-L4)
│   ├── test_l0_format.py
│   ├── test_l1_flow.py
│   ├── test_l2_relay.py
│   ├── test_l3_adversarial.py
│   └── test_l4_agent_tool.py
├── demo.py                 # Quick demo
├── testnet.py              # Full flow via real relay
├── interop_provider.py     # Python provider for interop test
└── real_testnet_demo.py    # Real service demo (live data fetch)
```

## Quick Start

```bash
# Run tests
python3 -m pytest tests/ -v

# Run demo
python3 demo.py

# Run full testnet (real WebSocket relay)
python3 testnet.py

# Run real service demo (fetches live BTC price)
python3 real_testnet_demo.py

# Cross-language interop (Python provider + TS consumer)
python3 interop_provider.py  # terminal 1
cd acp-ts && npx tsx interop_consumer.ts  # terminal 2
```

## Zero-Config Agent

```python
from acp.agent import ACPAgent, WalletConfig

# User gives wallet — everything else is automatic
wallet = WalletConfig.nwc("nwc://user@wallet.relay")
# or
wallet = WalletConfig.lnbits("https://demo.lnbits.com", "invoice_key", "admin_key")
# or
wallet = WalletConfig.mock(balance_sat=10000)

agent = ACPAgent(wallet=wallet)
print(agent.status())
# → "ACP Agent ready. Wallet: mock. Balance: 10000 sats."

# Buy
confirm = agent.discover("vpn", budget_sat=5000)
# → "Found VPN for 5000 sats. Buy?"
result = agent.execute(confirm)
# → "Done. VPN key: xxxx. Spent 5000 sats."
```

## Provider Types

| Type | Payment | Example |
|---|---|---|
| **Native** | Lightning direct / L402 | VPN for sats |
| **Bridge** | Lightning → Stripe API | Notion via bridge-agent |
| **Adapter** | Existing service wrapper | Bitrefill gift cards |

## Test Results

```
50 passed in 1.45s

L0 Format:      17/17  (event types, tags, parseability)
L1 Flow:        10/10  (happy path + 7 edge cases)
L2 Relay:        3/3   (full transaction via WebSocket)
L3 Adversarial:  7/7   (Sybil, replay, false preimage, spam)
L4 Agent Tool:  13/13  (confirmation, limits, auto-confirm, receipts)

Cross-language: Python ↔ TypeScript interop PASS
Real service:   Live BTC price fetch PASS
```

## License

MIT

## Status

v0.3 DRAFT — ready for community review.