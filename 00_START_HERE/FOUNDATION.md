# ACP — Agent Commerce Protocol

> Foundation document. Required reading in any ACP session.
> v0.3 — 2026-06-25 — final framing: tool-not-product, L402 complement, zero-config

---

## §0. PROJECT NATURE

ACP is **NOT** a product, **NOT** a company, **NOT** a token.
ACP is an **open protocol**: discovery + atomic delivery + receipt + reputation
for AI agents. Payment = pluggable (L402, Lightning, Cashu).

### Analogy

| Layer | Internet | Agent commerce |
|---|---|---|
| Discovery | DNS | **ACP (Nostr manifests)** |
| Payment | TCP | L402 / Lightning / Cashu |
| Atomic delivery | TLS | **ACP (hold invoice + preimage)** |
| Proof | Server logs | **ACP (Nostr receipts)** |
| Trust | CA system | **ACP (attestations)** |

L402 = payment transport. ACP = everything else. Not a competitor — a complement.

---

## §1. WHY THIS IS NEEDED

### Problem

Models solve 90% of tasks themselves. But a model **physically cannot BUY**.
L402 solves payment. But L402 lacks: discovery, atomic delivery, receipt, reputation.

### Solution

ACP = **a tool in the agent's toolbelt.** A plugin for any framework (Claude Code,
Codex, LangChain, or any custom agent). Gives the agent the ability to: discover → pay → receive
with guarantee → prove the purchase.

### Three Roles

```
HUMAN
  │ gives wallet (one line) + purchase confirmation
  ▼
AGENT (any framework + ACP tool)
  │ discovery (Nostr) + payment (L402/LN/Cashu) + atomic delivery + receipt
  ▼
PROVIDER (native / bridge / adapter)
```

### Provider Types

| Type | Payment rail | Example |
|---|---|---|
| Native | Lightning direct / L402 | VPN for sats |
| Bridge | Lightning ← → Stripe API | Notion via bridge-agent |
| Adapter | Existing service | Bitrefill gift cards |

**The protocol is neutral to the payment rail and how the provider fulfills.**

---

## §2. PRINCIPLES

### 2.1 User sees results, not mechanism
ACP = under the hood. User gives wallet → says "buy" → gets result.

### 2.2 Zero-config
The only thing the user provides is a **wallet** (NWC URI or API key).
Everything else (keypair, relays, discovery) is automatic.

### 2.3 Agent = cashier
Agent shows price → waits for confirmation → executes. Does not spend autonomously.

### 2.4 Wallet = prepaid with limits
Human loads N sats. Agent CANNOT spend more. No fraud risk.

### 2.5 Protocol is neutral to VALUE, strict to FORMAT
Pricing format is in the protocol. Values are not. Event format is in the protocol.
Reputation algorithm is not.

### 2.6 Payment = pluggable
ACP is not tied to Lightning. L402, Cashu, Solana Pay — any rail via
the `pay_endpoint` format field.

### 2.7 Not a competitor to L402 — a complement
L402 = "how to pay". ACP = "how to find, trust, guarantee, prove".

---

## §3. WHAT IS IN THE PROTOCOL, WHAT IS NOT

| In protocol | NOT in protocol |
|---|---|
| Event format (tags, kinds) | Price values |
| Discovery (Nostr relay query) | Which relays |
| Payment endpoint format | Choice of payment rail |
| Atomic delivery (preimage = key) | How provider fulfills |
| Receipt (preimage proof) | Reputation algorithm |
| Confirmation flow (tool interface) | Agent UI |
| Budget limits (wallet interface) | Specific limits |
| Provider types (native/bridge/adapter) | Specific bridge providers |

---

## §4. STAGES

| Stage | Criteria | Status |
|---|---|---|
| v0 — Spec draft | Spec written | ✅ |
| v1 — Spec interop-readable | AI implements from spec | ✅ |
| v2 — Reference impl | Python SDK + tests | ✅ |
| v3 — Cross-lang interop | Python ↔ TS via relay | ✅ |
| v4 — Published | GitHub + NIP + docs | ⬜ NEXT |
| v5 — First adoption | Stranger builds on ACP | ⬜ |
| v6 — Self-sustaining | Author gone, agents trade | ⬜ |

---

## §5. DIVISION OF LABOR

| Who | What | What they DON'T do |
|---|---|---|
| AI agent | Spec, SDK, harness, tests, code | Outreach, binary decisions |
| Human | Quality control, veto, decisions, outreach | Code, architecture |

WHY — human. HOW — AI. WHAT — jointly.