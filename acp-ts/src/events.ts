/**
 * ACP Protocol Events — 4 core + 3 extension event types.
 *
 * Core (NIP-ACP-01):
 *   30000 — Agent Manifest
 *   30001 — Service Request
 *   30002 — Service Offer (hold invoice + encrypted result)
 *   30003 — Transaction Receipt
 *
 * Extensions:
 *   30004 — Attestation (NIP-ACP-02)
 *   30005 — Dispute (NIP-ACP-03)
 *   30006 — Resolution (NIP-ACP-03)
 */

import { AgentIdentity } from './identity.js';
import type { NostrEvent } from './identity.js';

export const EventKind = {
  MANIFEST: 30000,
  REQUEST: 30001,
  OFFER: 30002,
  RECEIPT: 30003,
  ATTESTATION: 30004,
  DISPUTE: 30005,
  RESOLUTION: 30006,
} as const;

/** Parse Nostr tags into a dict. Single values as string, repeatable (e,p,t) unwrapped. */
export function parseTags(tags: string[][]): Record<string, string> {
  const result: Record<string, string> = {};
  const repeatable = new Set(['e', 'p', 't']);
  const temp: Record<string, string[]> = {};

  for (const tag of tags) {
    const name = tag[0];
    const value = tag[1] || '';
    if (repeatable.has(name)) {
      if (!temp[name]) temp[name] = [];
      temp[name].push(value);
    } else {
      result[name] = value;
    }
  }

  // Unwrap single-element repeatable tags
  for (const name of repeatable) {
    if (temp[name] && temp[name].length === 1) {
      result[name] = temp[name][0];
    } else if (temp[name]) {
      result[name] = temp[name] as any;
    }
  }

  return result;
}

/** Add a required tag (throws if value is empty). */
function addRequired(tags: string[][], name: string, value: string | number): void {
  const v = String(value);
  if (!v) throw new Error(`Required tag '${name}' is missing`);
  tags.push([name, v]);
}

/** Add an optional tag (skip if value is null/empty). */
function addOptional(tags: string[][], name: string, value: string | number | undefined): void {
  const v = value !== undefined ? String(value) : '';
  if (v) tags.push([name, v]);
}

// ─── Manifest (30000) ─────────────────────────────────────

export interface ManifestData {
  pubkey: string;
  name: string;
  ver: string;
  offers: any[];
  pay: string;
  stake?: string;
  bio?: string;
}

export function createManifest(
  identity: AgentIdentity,
  name: string,
  offers: any[],
  payEndpoint: string,
  stakeMsat?: number,
): NostrEvent {
  const tags: string[][] = [];
  addRequired(tags, 'd', identity.pubkeyHex);
  addRequired(tags, 'name', name);
  addRequired(tags, 'ver', '0.1');
  addRequired(tags, 'offers', JSON.stringify(offers));
  addRequired(tags, 'pay', payEndpoint);
  addOptional(tags, 'stake', stakeMsat);
  addOptional(tags, 'bio', undefined);
  tags.push(['t', 'agent-commerce']);
  return identity.signEvent(EventKind.MANIFEST, tags, '');
}

export function parseManifest(event: NostrEvent): ManifestData {
  if (event.kind !== EventKind.MANIFEST) throw new Error(`Expected 30000, got ${event.kind}`);
  const tags = parseTags(event.tags);
  return {
    pubkey: event.pubkey,
    name: tags.name,
    ver: tags.ver,
    offers: tags.offers ? JSON.parse(tags.offers) : [],
    pay: tags.pay,
    stake: tags.stake,
  };
}

// ─── Service Request (30001) ──────────────────────────────

export interface RequestData {
  pubkey: string;
  need: any;
  budgetMsat: number;
  deadline: number;
  delivery: string;
}

export function createRequest(
  identity: AgentIdentity,
  need: any,
  budgetMsat: number,
  deadline: number,
): NostrEvent {
  const tags: string[][] = [];
  addRequired(tags, 'ver', '0.1');
  addRequired(tags, 'need', JSON.stringify(need));
  addRequired(tags, 'budget_msat', budgetMsat);
  addRequired(tags, 'deadline', deadline);
  tags.push(['t', 'agent-commerce']);
  return identity.signEvent(EventKind.REQUEST, tags, '');
}

export function parseRequest(event: NostrEvent): RequestData {
  if (event.kind !== EventKind.REQUEST) throw new Error(`Expected 30001, got ${event.kind}`);
  const tags = parseTags(event.tags);
  return {
    pubkey: event.pubkey,
    need: tags.need ? JSON.parse(tags.need) : {},
    budgetMsat: tags.budget_msat ? parseInt(tags.budget_msat) : 0,
    deadline: tags.deadline ? parseInt(tags.deadline) : 0,
    delivery: tags.delivery || 'nostr',
  };
}

// ─── Service Offer (30002) ────────────────────────────────

export interface OfferData {
  pubkey: string;
  requestId: string;
  consumerPubkey: string;
  invoice: string;
  preimageHash: string;
  amountMsat: number;
  resultType: string;
  resultEnc: string;
  deadline?: string;
  mediator?: string;
}

export function createOffer(
  identity: AgentIdentity,
  requestEventId: string,
  consumerPubkey: string,
  invoice: string,
  preimageHashHex: string,
  amountMsat: number,
  resultEncB64: string,
  resultType: string = 'encrypted',
): NostrEvent {
  const tags: string[][] = [];
  addRequired(tags, 'ver', '0.1');
  addRequired(tags, 'e', requestEventId);
  addRequired(tags, 'p', consumerPubkey);
  addRequired(tags, 'invoice', invoice);
  addRequired(tags, 'preimage_hash', preimageHashHex);
  addRequired(tags, 'amount_msat', amountMsat);
  addRequired(tags, 'result_type', resultType);
  addRequired(tags, 'result_enc', resultEncB64);
  return identity.signEvent(EventKind.OFFER, tags, '');
}

export function parseOffer(event: NostrEvent): OfferData {
  if (event.kind !== EventKind.OFFER) throw new Error(`Expected 30002, got ${event.kind}`);
  const tags = parseTags(event.tags);
  return {
    pubkey: event.pubkey,
    requestId: tags.e,
    consumerPubkey: tags.p,
    invoice: tags.invoice,
    preimageHash: tags.preimage_hash,
    amountMsat: tags.amount_msat ? parseInt(tags.amount_msat) : 0,
    resultType: tags.result_type,
    resultEnc: tags.result_enc,
    deadline: tags.deadline,
    mediator: tags.mediator,
  };
}

// ─── Receipt (30003) ──────────────────────────────────────

export interface ReceiptData {
  pubkey: string;
  offerId: string;
  consumerPubkey: string;
  preimage: string;
  amountMsat: number;
  settledAt: number;
}

export function createReceipt(
  identity: AgentIdentity,
  offerEventId: string,
  consumerPubkey: string,
  preimageHex: string,
  amountMsat: number,
  settledAt: number,
): NostrEvent {
  const tags: string[][] = [];
  addRequired(tags, 'ver', '0.1');
  addRequired(tags, 'e', offerEventId);
  addRequired(tags, 'p', consumerPubkey);
  addRequired(tags, 'preimage', preimageHex);
  addRequired(tags, 'amount_msat', amountMsat);
  addRequired(tags, 'settled_at', settledAt);
  tags.push(['t', 'agent-commerce']);
  return identity.signEvent(EventKind.RECEIPT, tags, '');
}

export function parseReceipt(event: NostrEvent): ReceiptData {
  if (event.kind !== EventKind.RECEIPT) throw new Error(`Expected 30003, got ${event.kind}`);
  const tags = parseTags(event.tags);
  return {
    pubkey: event.pubkey,
    offerId: tags.e,
    consumerPubkey: tags.p,
    preimage: tags.preimage,
    amountMsat: tags.amount_msat ? parseInt(tags.amount_msat) : 0,
    settledAt: tags.settled_at ? parseInt(tags.settled_at) : 0,
  };
}