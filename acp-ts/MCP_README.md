## ACP MCP Server

ACP tools for Claude Code, Cursor, VS Code, and any MCP-compatible client.

### Quick Start (Claude Code)

1. Build the server:
```bash
cd acp-ts
npm install
npm run build
```

2. Add to Claude Code config (`.claude/settings.json` or `~/.claude.json`):
```json
{
  "mcpServers": {
    "acp": {
      "command": "node",
      "args": ["/path/to/acp-ts/build/mcp-server.js"],
      "env": {
        "ACP_WALLET_TYPE": "mock",
        "ACP_BALANCE_SATS": "10000"
      }
    }
  }
}
```

3. Restart Claude Code

4. Try:
```
You: "Check my ACP balance"
Claude: [calls acp_balance] → "10000 sats"

You: "Find me a VPN"
Claude: [calls acp_discover] → "Found LightningVPN for 5000 sats"

You: "Buy it"
Claude: [calls acp_buy] → "✅ Purchase complete! VPN key: xxxx"
```

### Tools

| Tool | Description |
|---|---|
| `acp_status` | Show agent status: balance, limits, spent today |
| `acp_balance` | Check wallet balance in sats |
| `acp_discover` | Find providers for a service (no purchase) |
| `acp_buy` | Purchase a service (requires confirm=true) |

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ACP_WALLET_TYPE` | `mock` | Wallet type (`mock` for demo, `lnbits` for real) |
| `ACP_BALANCE_SATS` | `10000` | Initial wallet balance (mock mode) |
| `ACP_MAX_PER_PURCHASE` | balance | Max sats per single purchase |
| `ACP_DAILY_LIMIT` | balance×2 | Max sats per day |

### Mock Providers (built-in for demo)

| Service | Price | Description |
|---|---|---|
| `vpn` | 5000 sats | VPN subscription, 1 month |
| `btc-price` | 100 sats | Fetch current BTC price |
| `data-fetch` | 200 sats | Fetch data from any URL |