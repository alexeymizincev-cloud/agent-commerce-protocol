#!/usr/bin/env tsx
/**
 * TS Consumer — connects to Python relay, discovers provider,
 * pays, receives receipt, decrypts result.
 *
 * Proves Python↔TS interop on the ACP protocol level.
 */
import WebSocket from 'ws';
import { AgentIdentity } from './src/identity.js';
import { parseManifest, parseOffer, parseReceipt } from './src/events.js';
import { decryptResultB64, verifyPreimage } from './src/crypto.js';

const RELAY_URL = 'ws://127.0.0.1:7777';

async function sleep(ms: number): Promise<void> {
  return new Promise(r => setTimeout(r, ms));
}

async function connectWithRetry(url: string, maxAttempts = 10): Promise<WebSocket> {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const ws = new WebSocket(url);
      await new Promise<void>((resolve, reject) => {
        ws.once('open', resolve);
        ws.once('error', reject);
        setTimeout(() => reject(new Error('timeout')), 2000);
      });
      return ws;
    } catch (e) {
      if (i < maxAttempts - 1) {
        console.log(`Retry connecting (attempt ${i + 1})...`);
        await sleep(1000);
      }
    }
  }
  throw new Error('Failed to connect to relay');
}

async function relayRequest(ws: WebSocket, filters: any[], timeout = 2000): Promise<any[]> {
  return new Promise((resolve) => {
    const collected: any[] = [];
    const subId = 'ts_' + Math.random().toString(36).slice(2);
    let resolved = false;

    ws.send(JSON.stringify(['REQ', subId, ...filters]));

    const timer = setTimeout(() => {
      if (resolved) return;
      resolved = true;
      ws.send(JSON.stringify(['CLOSE', subId]));
      resolve(collected);
    }, timeout);

    const handler = (raw: any) => {
      const msg = JSON.parse(raw.toString());
      if (msg[0] === 'EVENT' && msg[1] === subId) {
        collected.push(msg[2]);
      } else if (msg[0] === 'EOSE' && msg[1] === subId) {
        if (resolved) return;
        resolved = true;
        clearTimeout(timer);
        ws.send(JSON.stringify(['CLOSE', subId]));
        ws.off('message', handler);
        resolve(collected);
      }
    };
    ws.on('message', handler);
  });
}

async function publishEvent(ws: WebSocket, event: any): Promise<boolean> {
  return new Promise((resolve) => {
    let resolved = false;
    const handler = (raw: any) => {
      const msg = JSON.parse(raw.toString());
      if (msg[0] === 'OK' && msg[1] === event.id) {
        if (resolved) return;
        resolved = true;
        ws.off('message', handler);
        resolve(msg[2]);
      }
    };
    ws.on('message', handler);
    ws.send(JSON.stringify(['EVENT', event]));
    setTimeout(() => { if (!resolved) { resolved = true; resolve(false); } }, 2000);
  });
}

async function main() {
  console.log();
  console.log('=== TS CONSUMER — Interop with Python Provider ===');
  console.log();

  const consumer = AgentIdentity.generate();
  console.log('TS Consumer:', consumer.toString());
  console.log();

  const ws = await connectWithRetry(RELAY_URL);
  console.log('Connected to Python relay');
  console.log();

  // 1. Discover provider manifests
  console.log('[TS] Discovering provider manifests...');
  const manifests = await relayRequest(ws, [{ kinds: [30000], '#t': ['agent-commerce'] }]);
  console.log(`[TS] Found ${manifests.length} manifest(s)`);
  if (manifests.length === 0) {
    console.log('[TS] No manifests found');
    process.exit(1);
  }

  const manifest = manifests[0];
  const mdata = parseManifest(manifest);
  console.log(`[TS] Provider: ${mdata.name}`);
  console.log(`[TS] Offer: ${mdata.offers[0].service} @ ${mdata.offers[0].pricing.amount_msat} msat`);
  console.log();

  // 2. Publish request
  console.log('[TS] Publishing request...');
  const requestEvent = consumer.signEvent(30001, [
    ['ver', '0.1'],
    ['need', JSON.stringify({
      service: 'translation',
      content_type: 'text/plain',
      constraints: { lang: ['ja', 'en'] },
      input_ref: 'inline:HelloFromTS',
    })],
    ['budget_msat', '200000'],
    ['deadline', String(Math.floor(Date.now() / 1000) + 60)],
    ['t', 'agent-commerce'],
  ], 'TS consumer needs translation');
  await publishEvent(ws, requestEvent);
  console.log(`[TS] Request published: ${requestEvent.id.slice(0, 24)}...`);
  console.log();

  // 3. Wait for provider's offer
  console.log('[TS] Waiting for provider offer...');
  let offers: any[] = [];
  for (let i = 0; i < 15; i++) {
    await sleep(2000);
    offers = await relayRequest(ws, [{ kinds: [30002], '#p': [consumer.pubkeyHex] }], 1500);
    if (offers.length > 0) break;
    process.stdout.write('.');
  }
  console.log();
  if (offers.length === 0) {
    console.log('[TS] No offer received from Python provider');
    process.exit(1);
  }

  const offer = offers[0];
  const odata = parseOffer(offer);
  console.log(`[TS] Received offer: ${offer.id.slice(0, 24)}...`);
  console.log(`[TS] Preimage hash: ${odata.preimageHash.slice(0, 24)}...`);
  console.log(`[TS] Amount: ${odata.amountMsat} msat`);
  console.log();

  // 4. Wait for receipt
  console.log('[TS] Waiting for receipt (provider settles)...');
  let receipts: any[] = [];
  for (let i = 0; i < 15; i++) {
    await sleep(2000);
    receipts = await relayRequest(ws, [{ kinds: [30003], '#p': [consumer.pubkeyHex] }], 1500);
    if (receipts.length > 0) break;
    process.stdout.write('.');
  }
  console.log();
  if (receipts.length === 0) {
    console.log('[TS] No receipt received');
    process.exit(1);
  }

  const receipt = receipts[0];
  const rdata = parseReceipt(receipt);
  console.log(`[TS] Received receipt: ${receipt.id.slice(0, 24)}...`);
  console.log(`[TS] Preimage: ${rdata.preimage.slice(0, 24)}...`);
  console.log();

  // 5. Decrypt result
  console.log('[TS] Decrypting result...');
  const preimage = Buffer.from(rdata.preimage, 'hex');
  const offerHash = Buffer.from(odata.preimageHash, 'hex');
  if (!verifyPreimage(preimage, offerHash)) {
    console.log('[TS] PREIMAGE VERIFICATION FAILED');
    process.exit(1);
  }
  console.log('[TS] Preimage verified OK');

  const decrypted = decryptResultB64(odata.resultEnc, preimage);
  console.log(`[TS] Decrypted: "${decrypted.toString('utf8')}"`);
  console.log();

  console.log('=== TS CONSUMER INTEROP SUCCESS ===');
  console.log('Python provider → TS consumer transaction complete via relay.');
  console.log();

  ws.close();
  process.exit(0);
}

main().catch((e) => { console.error(e); process.exit(1); });