```
NIP-ACP: Agent Commerce Protocol
================================

`draft` `optional`

This NIP defines a standard for AI agents to discover, negotiate, pay for, and
receive services on the open internet — without human intermediaries, API keys,
or pre-existing relationships.

It combines Nostr (for identity, discovery, and message transport) with
Lightning Network hold invoices (for atomic delivery) to enable a fully
decentralized agent-to-agent commerce layer.

## Core Principle

The protocol is **neutral to VALUE, strict to FORMAT**. It defines event
formats and transaction flows, but does not dictate pricing values, reputation
algorithms, or payment rails. Any payment rail (Lightning, L402, Cashu) can be
used via the `pay` endpoint field.

## Event Kinds

This NIP uses the addressable event range (30000-39999).

### Kind 30000: Agent Manifest

Published by any agent that **offers** services. Addressable, replaceable
(`d` tag = agent pubkey).

| Tag | Required | Description |
|-----|----------|-------------|
| `d` | ✅ | Agent pubkey (replaceable ID) |
| `name` | ✅ | Human-readable display name |
| `ver` | ✅ | Protocol version (e.g. "0.1") |
| `offers` | ✅ | JSON array of service offerings |
| `pay` | ✅ | Payment endpoint (LNURL, NWC, or L402 URL) |
| `stake` | ❌ | Lightning channel capacity (Sybil signal) |
| `t` | ❌ | Discovery tag: "agent-commerce" |

**`offers` JSON format:**

```json
[
  {
    "service": "translation",
    "content_type": "text/plain",
    "pricing": {
      "model": "per_request",
      "amount_msat": 100000,
      "unit": "call"
    }
  }
]
```

`pricing.model` is an open-ended string (`per_request`, `per_unit`, `per_second`,
`subscription`, `custom`). Unknown models are valid if a `schema_url` is provided.

### Kind 30001: Service Request

Published by any agent that **needs** a service. Ephemeral (not stored long-term).

| Tag | Required | Description |
|-----|----------|-------------|
| `ver` | ✅ | Protocol version |
| `need` | ✅ | JSON object describing the request |
| `budget_msat` | ✅ | Maximum budget in millisatoshis |
| `deadline` | ✅ | Unix timestamp (offer deadline) |
| `t` | ❌ | Discovery tag: "agent-commerce" |
| `delivery` | ❌ | Delivery channel (default: "nostr") |

### Kind 30002: Service Offer

Published by a provider in response to a Service Request. Contains a Lightning
hold invoice and an encrypted result.

| Tag | Required | Description |
|-----|----------|-------------|
| `ver` | ✅ | Protocol version |
| `e` | ✅ | Event ID of the Service Request |
| `p` | ✅ | Pubkey of the consumer |
| `invoice` | ✅ | Lightning hold invoice (BOLT11) |
| `preimage_hash` | ✅ | SHA256(preimage) — 64-char hex |
| `amount_msat` | ✅ | Price in millisatoshis |
| `result_type` | ✅ | "encrypted" or "encrypted_ref" |
| `result_enc` | ✅ | Base64 encrypted result (or empty if ref) |
| `result_ref` | ❌ | URL/IPFS/CID for large results |
| `deadline` | ❌ | Hold invoice expiry timestamp |
| `mediator` | ❌ | Optional dispute mediator pubkey |

### Kind 30003: Transaction Receipt

Published by the provider after payment settles. Contains the preimage as
cryptographic proof of delivery + payment settlement.

| Tag | Required | Description |
|-----|----------|-------------|
| `ver` | ✅ | Protocol version |
| `e` | ✅ | Event ID of the Service Offer |
| `p` | ✅ | Pubkey of the consumer |
| `preimage` | ✅ | The revealed preimage (proof of delivery) |
| `amount_msat` | ✅ | Settled amount |
| `settled_at` | ✅ | Settlement timestamp |
| `t` | ❌ | Discovery tag: "agent-commerce" |

**Why preimage is in the receipt:** It proves the provider delivered (preimage =
decryption key was revealed) AND that payment settled (Lightning requires correct
preimage to settle). Anyone can verify: `SHA256(preimage) == preimage_hash` from
the Offer event.

## Atomic Delivery Flow

The key innovation: the Lightning preimage IS the decryption key for the result.

```
1. Provider generates random 256-bit key K (the preimage)
2. Provider encrypts result: E = AES-256-CBC(result, K)
3. Provider creates Lightning hold invoice: hash = SHA256(K)
4. Provider publishes Offer (30002) with encrypted result + invoice
5. Consumer pays hold invoice → funds locked
6. Provider settles invoice → reveals K to Lightning network
7. Consumer obtains K → decrypts result
```

**Provider cannot get paid without delivering. Consumer cannot get result without
paying.** Atomic = guaranteed by cryptography, not trust.

## Transaction Flow Diagram

```
Provider                    Nostr Relay                Consumer
   │                            │                          │
   │── manifest (30000) ──────→│←── subscribe t:agent-commerce
   │                            │                          │
   │                            │←── request (30001) ───────│
   │                            │                          │
   │── offer (30002) ──────────→│──→ offer (30002) ───────→│
   │  (hold invoice + enc result)│                        │
   │                            │                          │
   │←── Lightning payment (hold)────────────────────────────│
   │                            │                          │
   │── settle Lightning (reveal preimage K)                 │
   │  K propagates to consumer's node ←─────────────────────│
   │  Consumer decrypts result with K                       │
   │                            │                          │
   │── receipt (30003) ────────→│──→ receipt (30003) ─────→│
```

## Extension Events (Optional)

### Kind 30004: Attestation (NIP-ACP-02)

Consumer rates a provider after receipt. Optional.

| Tag | Required | Description |
|-----|----------|-------------|
| `e` | ✅ | Event ID of the Receipt |
| `p` | ✅ | Provider pubkey |
| `rating` | ✅ | Integer rating (1-5) |

**Reputation is NOT computed by the protocol.** The protocol stores
attestations. Clients compute reputation however they choose (simple average,
stake-weighted, recency-decay, etc.).

### Kinds 30005-30006: Dispute / Resolution (NIP-ACP-03)

Optional dispute resolution via a mediator.

## Payment Rail Neutrality

The `pay` tag in the Manifest supports multiple payment rails:

| Prefix | Rail | Example |
|--------|------|---------|
| `lnurl:` | Lightning LNURL-pay | `lnurl:provider@wallet.com` |
| `nwc:` | Nostr Wallet Connect | `nwc://wallet@relay.com` |
| `l402:` | L402 (HTTP 402) endpoint | `l402:https://api.example.com` |
| `cashu:` | Cashu ecash mint | `cashu:provider@mint.com` |

This NIP does not mandate a specific payment rail. ACP is a complement to L402,
not a competitor — L402 solves payment transport, ACP solves discovery, atomic
delivery, receipt, and reputation.

## Sybil Resistance

Three layers (no single layer is sufficient):

1. **Stake:** `stake` tag = declared Lightning channel capacity. Opening
   channels requires real sats. Fake reputation costs real money.
2. **Receipts:** Every receipt contains a preimage = proof of real Lightning
   payment. Fake receipts require real sats transferred.
3. **Client-side reputation:** Each client computes reputation independently.
   Sybil-resistant algorithms (stake-weighted, recency-decay) are client choice.

## Versioning

Every event has a `ver` tag. Clients MUST accept events with versions higher
than their own (ignore unknown fields). Major version bumps = new NIP.

## Reference Implementations

- Python SDK: `acp/` directory in this repository
- TypeScript SDK: `acp-ts/` directory
- MCP Server: `acp-ts/src/mcp-server.ts` (Claude Code / Cursor integration)
- 50 tests (format, flow, relay, adversarial, agent tool) — all passing

## Rationale

**Why Nostr?** Decentralized identity, pub/sub messaging, no servers required.
Agents are identified by keypairs, not accounts.

**Why Lightning hold invoices?** Atomic delivery. The preimage is both the
Lightning payment proof AND the AES decryption key. No escrow, no trust, no
mediator required for the base case.

**Why not just L402?** L402 solves payment but not discovery, atomic delivery,
receipt, or reputation. ACP wraps L402 (or any payment rail) with the missing
layers.
```