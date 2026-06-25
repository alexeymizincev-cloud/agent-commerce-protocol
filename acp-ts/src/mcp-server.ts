/**
 * ACP MCP Server — exposes ACP tools to Claude Code, Cursor, VS Code, and any
 * MCP-compatible client.
 *
 * Tools exposed:
 *   acp_status    — show wallet balance + agent status
 *   acp_discover  — find providers for a service
 *   acp_buy       — purchase a service (with user confirmation)
 *   acp_balance   — check wallet balance
 *
 * Setup (Claude Code / Cursor / VS Code):
 *   1. npm run build
 *   2. Add to MCP config:
 *      {
 *        "mcpServers": {
 *          "acp": {
 *            "command": "node",
 *            "args": ["./build/mcp-server.js"],
 *            "env": {
 *              "ACP_WALLET_TYPE": "mock",
 *              "ACP_BALANCE_SATS": "10000"
 *            }
 *          }
 *        }
 *      }
 *   3. Restart Claude Code / Cursor
 *   4. Ask: "Find me a VPN and buy it"
 */

import { McpServer } from '@modelcontextprotocol/server';
import { StdioServerTransport } from '@modelcontextprotocol/server';
import { z } from 'zod';
import * as crypto from 'crypto';
import WebSocket from 'ws';

// ─── ACP Core (inline for MCP server self-containment) ─────

function generatePreimage(): Buffer {
  return crypto.randomBytes(32);
}

function hashPreimage(preimage: Buffer): Buffer {
  return crypto.createHash('sha256').update(preimage).digest();
}

function encryptResult(result: Buffer, preimage: Buffer): Buffer {
  const key = preimage;
  const iv = crypto.createHash('sha256').update(Buffer.concat([preimage, Buffer.from('iv')])).digest().slice(0, 16);
  const cipher = crypto.createCipheriv('aes-256-cbc', key, iv);
  return Buffer.concat([iv, cipher.update(result), cipher.final()]);
}

function decryptResult(encrypted: Buffer, preimage: Buffer): Buffer {
  const key = preimage;
  const iv = encrypted.slice(0, 16);
  const ct = encrypted.slice(16);
  const decipher = crypto.createDecipheriv('aes-256-cbc', key, iv);
  return Buffer.concat([decipher.update(ct), decipher.final()]);
}

function encryptResultB64(result: Buffer, preimage: Buffer): string {
  return encryptResult(result, preimage).toString('base64');
}

function decryptResultB64(encryptedB64: string, preimage: Buffer): Buffer {
  return decryptResult(Buffer.from(encryptedB64, 'base64'), preimage);
}

// ─── Mock Lightning ────────────────────────────────────────

interface Invoice {
  hash: string;
  preimage: string | null;
  amountMsat: number;
  state: 'CREATED' | 'LOCKED' | 'SETTLED' | 'CANCELLED';
  provider: string;
  consumer: string | null;
}

class MockLightning {
  invoices: Map<string, Invoice> = new Map();

  createHoldInvoice(amountMsat: number, preimage: Buffer, provider: string): string {
    const h = crypto.createHash('sha256').update(preimage).digest();
    const hHex = h.toString('hex');
    this.invoices.set(hHex, {
      hash: hHex, preimage: null, amountMsat,
      state: 'CREATED', provider, consumer: null,
    });
    return `lnbcrt${amountMsat}m1mock_${hHex}`;
  }

  payHoldInvoice(hashHex: string, consumer: string): boolean {
    const inv = this.invoices.get(hashHex);
    if (!inv || inv.state !== 'CREATED') throw new Error('Cannot pay');
    inv.consumer = consumer;
    inv.state = 'LOCKED';
    return true;
  }

  settleHoldInvoice(hashHex: string, preimage: Buffer, provider: string): boolean {
    const inv = this.invoices.get(hashHex);
    if (!inv || inv.state !== 'LOCKED' || inv.provider !== provider) throw new Error('Cannot settle');
    const h = crypto.createHash('sha256').update(preimage).digest();
    if (h.toString('hex') !== hashHex) throw new Error('Preimage hash mismatch');
    inv.preimage = preimage.toString('hex');
    inv.state = 'SETTLED';
    return true;
  }

  getState(hashHex: string): string {
    return this.invoices.get(hashHex)?.state || 'UNKNOWN';
  }
}

// ─── Agent Wallet ──────────────────────────────────────────

class AgentWallet {
  balanceSat: number;
  maxPerPurchase: number;
  dailyLimit: number;
  spentToday: number = 0;
  lightning: MockLightning;

  constructor(balance: number, maxPer?: number, daily?: number) {
    this.balanceSat = balance;
    this.maxPerPurchase = maxPer || balance;
    this.dailyLimit = daily || balance;
    this.lightning = new MockLightning();
  }

  canSpend(amount: number): [boolean, string] {
    if (amount > this.balanceSat) return [false, `Insufficient balance (${this.balanceSat} sats)`];
    if (amount > this.maxPerPurchase) return [false, `Per-purchase limit exceeded (${this.maxPerPurchase} sats)`];
    if (this.spentToday + amount > this.dailyLimit) return [false, `Daily limit exceeded`];
    return [true, 'OK'];
  }

  spend(amount: number): void {
    const [ok, reason] = this.canSpend(amount);
    if (!ok) throw new Error(reason);
    this.balanceSat -= amount;
    this.spentToday += amount;
  }

  topUp(amount: number): void {
    this.balanceSat += amount;
  }
}

// ─── ACP Identity (simplified) ─────────────────────────────

class AgentIdentity {
  privkey: Buffer;
  pubkey: Buffer;
  pubkeyHex: string;

  constructor() {
    this.privkey = crypto.randomBytes(32);
    const ecdh = crypto.createECDH('secp256k1');
    ecdh.setPrivateKey(this.privkey);
    this.pubkey = ecdh.getPublicKey().slice(1, 33);
    this.pubkeyHex = this.pubkey.toString('hex');
  }

  signEvent(kind: number, tags: string[][], content: string = ''): any {
    const createdAt = Math.floor(Date.now() / 1000);
    const template = [0, this.pubkeyHex, createdAt, kind, tags, content];
    const serialized = JSON.stringify(template);
    const id = crypto.createHash('sha256').update(serialized).digest('hex');
    return { id, pubkey: this.pubkeyHex, created_at: createdAt, kind, tags, content, sig: '' };
  }
}

// ─── ACP Agent (MCP-facing) ────────────────────────────────

interface Provider {
  service: string;
  name: string;
  priceSat: number;
  description: string;
  resultData: string;
}

class ACPAgent {
  wallet: AgentWallet;
  identity: AgentIdentity;
  providers: Map<string, Provider> = new Map();
  pendingPurchase: any = null;

  constructor(walletConfig: any) {
    const balance = parseInt(walletConfig.balance || '10000');
    const maxPer = parseInt(walletConfig.maxPerPurchase || String(balance));
    const daily = parseInt(walletConfig.dailyLimit || String(balance * 2));
    this.wallet = new AgentWallet(balance, maxPer, daily);
    this.identity = new AgentIdentity();

    // Register default mock providers for demo
    this.registerMockProviders();
  }

  private registerMockProviders() {
    this.providers.set('vpn', {
      service: 'vpn',
      name: 'LightningVPN',
      priceSat: 5000,
      description: 'VPN subscription, 1 month, Lightning-native',
      resultData: 'VPN_KEY=xxxx-xxxx-xxxx-xxxx; SERVER=tokyo.vpn.example.com; PROTOCOL=wireguard',
    });
    this.providers.set('btc-price', {
      service: 'btc-price',
      name: 'BTC Price Fetcher',
      priceSat: 100,
      description: 'Fetch current BTC price from public API',
      resultData: 'BTC=$61213.50 source=CoinGecko ts=2026-06-25T12:00:00Z',
    });
    this.providers.set('data-fetch', {
      service: 'data-fetch',
      name: 'Data Fetch Agent',
      priceSat: 200,
      description: 'Fetch data from any public URL',
      resultData: 'DATA={"status":"ok","data":"sample response"}',
    });
  }

  status(): string {
    return `ACP Agent ready. Wallet: mock. Balance: ${this.wallet.balanceSat} sats. Per-purchase limit: ${this.wallet.maxPerPurchase} sats. Daily limit: ${this.wallet.dailyLimit} sats. Spent today: ${this.wallet.spentToday} sats.`;
  }

  balance(): string {
    return `${this.wallet.balanceSat} sats`;
  }

  discover(query: string, budgetSat: number): string {
    // Find matching provider
    const provider = this.providers.get(query.toLowerCase());
    if (!provider) {
      // Try partial match
      for (const [key, p] of this.providers) {
        if (key.includes(query.toLowerCase()) || query.toLowerCase().includes(key)) {
          return this.formatDiscovery(p, budgetSat);
        }
      }
      return `No providers found for: ${query}`;
    }
    return this.formatDiscovery(provider, budgetSat);
  }

  private formatDiscovery(provider: Provider, budgetSat: number): string {
    const [ok, reason] = this.wallet.canSpend(provider.priceSat);
    if (!ok) {
      return `Found: ${provider.name} (${provider.service}) — Price: ${provider.priceSat} sats — BUT: ${reason}`;
    }
    this.pendingPurchase = provider;
    return `Found: ${provider.name}\nService: ${provider.service}\nPrice: ${provider.priceSat} sats\nDescription: ${provider.description}\n\nTo buy, call acp_buy with service="${provider.service}" and confirm=true`;
  }

  buy(service: string, confirm: boolean): string {
    const provider = this.providers.get(service.toLowerCase());
    if (!provider) return `Provider not found: ${service}`;
    if (!confirm) return `Purchase cancelled. No funds spent.`;

    // Check limits
    const [ok, reason] = this.wallet.canSpend(provider.priceSat);
    if (!ok) return `Cannot buy: ${reason}`;

    // Execute atomic delivery (all under the hood)
    const providerIdentity = new AgentIdentity();
    const request = this.identity.signEvent(30001, [
      ['ver', '0.1'],
      ['need', JSON.stringify({ service: provider.service, content_type: 'text/plain' })],
      ['budget_msat', String(provider.priceSat * 1000)],
      ['deadline', String(Math.floor(Date.now() / 1000) + 60)],
      ['t', 'agent-commerce'],
    ], 'MCP agent request');

    const resultData = Buffer.from(provider.resultData, 'utf-8');
    const preimage = generatePreimage();
    const hash = hashPreimage(preimage);
    const invoice = this.wallet.lightning.createHoldInvoice(
      provider.priceSat * 1000, preimage, providerIdentity.pubkeyHex
    );
    const encrypted = encryptResultB64(resultData, preimage);

    const offer = providerIdentity.signEvent(30002, [
      ['ver', '0.1'], ['e', request.id], ['p', this.identity.pubkeyHex],
      ['invoice', invoice], ['preimage_hash', hash.toString('hex')],
      ['amount_msat', String(provider.priceSat * 1000)],
      ['result_type', 'encrypted'], ['result_enc', encrypted],
    ], 'Offer');

    // Pay
    this.wallet.lightning.payHoldInvoice(hash.toString('hex'), this.identity.pubkeyHex);

    // Settle
    const receipt = providerIdentity.signEvent(30003, [
      ['ver', '0.1'], ['e', offer.id], ['p', this.identity.pubkeyHex],
      ['preimage', preimage.toString('hex')],
      ['amount_msat', String(provider.priceSat * 1000)],
      ['settled_at', String(Math.floor(Date.now() / 1000))],
      ['t', 'agent-commerce'],
    ], 'Receipt');

    this.wallet.lightning.settleHoldInvoice(hash.toString('hex'), preimage, providerIdentity.pubkeyHex);

    // Decrypt
    const decrypted = decryptResultB64(encrypted, preimage);

    // Deduct
    this.wallet.spend(provider.priceSat);

    return `✅ Purchase complete!\nService: ${provider.service}\nProvider: ${provider.name}\nSpent: ${provider.priceSat} sats\nResult: ${decrypted.toString('utf-8')}\nRemaining balance: ${this.wallet.balanceSat} sats`;
  }
}

// ─── MCP Server Setup ──────────────────────────────────────

const server = new McpServer({
  name: 'acp',
  version: '0.1.0',
});

// Wallet config from environment
const walletConfig = {
  type: process.env.ACP_WALLET_TYPE || 'mock',
  balance: process.env.ACP_BALANCE_SATS || '10000',
  maxPerPurchase: process.env.ACP_MAX_PER_PURCHASE,
  dailyLimit: process.env.ACP_DAILY_LIMIT,
};

const agent = new ACPAgent(walletConfig);

// ─── Tool: acp_status ──────────────────────────────────────

server.registerTool(
  'acp_status',
  {
    title: 'ACP Agent Status',
    description: 'Show ACP agent status: wallet balance, limits, and available services.',
    inputSchema: z.object({}),
  },
  async () => ({
    content: [{
      type: 'text' as const,
      text: agent.status(),
    }],
  })
);

// ─── Tool: acp_balance ─────────────────────────────────────

server.registerTool(
  'acp_balance',
  {
    title: 'ACP Wallet Balance',
    description: 'Check the agent wallet balance in sats.',
    inputSchema: z.object({}),
  },
  async () => ({
    content: [{
      type: 'text' as const,
      text: agent.balance(),
    }],
  })
);

// ─── Tool: acp_discover ────────────────────────────────────

server.registerTool(
  'acp_discover',
  {
    title: 'ACP Discover Providers',
    description: 'Find ACP providers for a service. Returns provider name, price, and description. Does NOT purchase — user must confirm with acp_buy.',
    inputSchema: z.object({
      service: z.string().describe('Service to find (e.g. "vpn", "btc-price", "data-fetch")'),
      budget_sat: z.number().optional().describe('Maximum budget in sats'),
    }),
  },
  async ({ service, budget_sat }) => {
    const budget = budget_sat || 10000;
    const result = agent.discover(service, budget);
    return {
      content: [{
        type: 'text' as const,
        text: result,
      }],
    };
  }
);

// ─── Tool: acp_buy ─────────────────────────────────────────

server.registerTool(
  'acp_buy',
  {
    title: 'ACP Buy Service',
    description: 'Purchase a service via ACP protocol. Requires user confirmation. Deducts sats from wallet. Returns the decrypted result.',
    inputSchema: z.object({
      service: z.string().describe('Service to buy (e.g. "vpn", "btc-price")'),
      confirm: z.boolean().describe('Must be true to confirm purchase. If false, cancels.'),
    }),
  },
  async ({ service, confirm }) => {
    if (!confirm) {
      return {
        content: [{
          type: 'text' as const,
          text: 'Purchase cancelled. No funds spent.',
        }],
      };
    }
    const result = agent.buy(service, confirm);
    return {
      content: [{
        type: 'text' as const,
        text: result,
      }],
    };
  }
);

// ─── Start Server ──────────────────────────────────────────

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(`ACP MCP Server running on stdio (wallet: ${walletConfig.type}, balance: ${agent.balance()})`);
}

main().catch((error) => {
  console.error('Fatal error:', error);
  process.exit(1);
});