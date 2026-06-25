/**
 * Mock Lightning — simulates hold invoice lifecycle for testing.
 *
 * States: CREATED → (pay) → LOCKED → (settle) → SETTLED
 *                     OR
 *               (cancel) → CANCELLED
 */

interface Invoice {
  hash: string;
  preimage: string | null;
  amountMsat: number;
  state: 'CREATED' | 'LOCKED' | 'SETTLED' | 'CANCELLED';
  provider: string;
  consumer: string | null;
  createdAt: number;
}

export class MockLightning {
  invoices: Map<string, Invoice> = new Map();
  settledPayments: any[] = [];

  createHoldInvoice(amountMsat: number, preimage: Buffer, provider: string): string {
    const crypto = require('crypto');
    const h = crypto.createHash('sha256').update(preimage).digest();
    const hHex = h.toString('hex');
    const bolt11 = `lnbcrt${amountMsat}m1mock_${hHex}`;

    this.invoices.set(hHex, {
      hash: hHex,
      preimage: null,
      amountMsat,
      state: 'CREATED',
      provider,
      consumer: null,
      createdAt: Date.now() / 1000,
    });

    return bolt11;
  }

  payHoldInvoice(hashHex: string, consumer: string): boolean {
    const inv = this.invoices.get(hashHex);
    if (!inv) throw new Error(`Unknown invoice: ${hashHex}`);
    if (inv.state !== 'CREATED') throw new Error(`Invoice not payable (state=${inv.state})`);

    inv.consumer = consumer;
    inv.state = 'LOCKED';
    return true;
  }

  settleHoldInvoice(hashHex: string, preimage: Buffer, provider: string): boolean {
    const inv = this.invoices.get(hashHex);
    if (!inv) throw new Error(`Unknown invoice: ${hashHex}`);
    if (inv.state !== 'LOCKED') throw new Error(`Cannot settle (state=${inv.state})`);
    if (inv.provider !== provider) throw new Error('Only original provider can settle');

    // Verify preimage hash matches
    const crypto = require('crypto');
    const h = crypto.createHash('sha256').update(preimage).digest();
    if (h.toString('hex') !== hashHex) {
      throw new Error('Preimage hash mismatch — Lightning would reject');
    }

    inv.preimage = preimage.toString('hex');
    inv.state = 'SETTLED';
    this.settledPayments.push({
      hash: hashHex,
      amountMsat: inv.amountMsat,
      preimage: preimage.toString('hex'),
      provider,
      consumer: inv.consumer,
    });
    return true;
  }

  cancelHoldInvoice(hashHex: string): boolean {
    const inv = this.invoices.get(hashHex);
    if (!inv) throw new Error(`Unknown invoice: ${hashHex}`);
    if (inv.state === 'LOCKED') {
      inv.state = 'CANCELLED';
    }
    return true;
  }

  getPreimage(hashHex: string): Buffer | null {
    const inv = this.invoices.get(hashHex);
    if (!inv || inv.state !== 'SETTLED') return null;
    return Buffer.from(inv.preimage!, 'hex');
  }

  getState(hashHex: string): string {
    const inv = this.invoices.get(hashHex);
    return inv ? inv.state : 'UNKNOWN';
  }
}