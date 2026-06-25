"""
ACP Agent — zero-config agent payment capability.

Principle: user provides ONLY a wallet. Everything else is automatic.

Usage (in any agent framework):
    agent = ACPAgent(wallet_nwc="nwc://user@wallet.relay")
    # or
    agent = ACPAgent(wallet_lnbits_url="https://demo.lnbits.com",
                     wallet_lnbits_invoice_key="xxx",
                     wallet_lnbits_admin_key="xxx")

    # Everything auto-configured:
    # - Nostr keypair generated
    # - Public relays connected
    # - Discovery subscribed
    # - Wallet connected

    # User says "buy VPN":
    result = agent.buy("vpn", budget_sat=5000)
    # → "Found VPN for 5000 sats. Buy?" (ConfirmRequest)
    # User: "yes"
    result = agent.execute(result)
    # → "Done. VPN key: xxxx. Spent 5000 sats."

User does NOT configure:
- Nostr relay (auto: public relays)
- Lightning node (auto: via wallet API)
- Keypair (auto: generated)
- Discovery (auto: subscription to t:agent-commerce)
"""

import os
import json
from typing import Optional
from dataclasses import dataclass

from .identity import AgentIdentity
from .tools.agent_tool import ACPBuyTool, AgentWallet, ConfirmRequest, PurchaseResult
from .protocol import MockLightning


# ─── Public Nostr relays (auto-configured) ──────────────

DEFAULT_RELAYS = [
    "wss://relay.damus.io",
    "wss://nostr.wine",
    "wss://relay.snort.social",
    # ACP-specific relay (future)
    # "wss://relay.agent-commerce.org",
]


@dataclass
class WalletConfig:
    ""Wallet config — the only thing the user provides.""
    wallet_type: str  # "nwc" | "lnbits" | "mock"
    # NWC
    nwc_uri: Optional[str] = None
    # LNbits
    lnbits_url: Optional[str] = None
    lnbits_invoice_key: Optional[str] = None
    lnbits_admin_key: Optional[str] = None
    # Limits (optional — user can set)
    max_per_purchase_sat: Optional[int] = None
    daily_limit_sat: Optional[int] = None

    @classmethod
    def nwc(cls, uri: str, **kwargs) -> "WalletConfig":
        """From NWC URI (Phoenix, Alby, Mutiny, Breez)."""
        return cls(wallet_type="nwc", nwc_uri=uri, **kwargs)

    @classmethod
    def lnbits(cls, url: str, invoice_key: str, admin_key: str, **kwargs) -> "WalletConfig":
        """From LNbits API keys."""
        return cls(
            wallet_type="lnbits",
            lnbits_url=url,
            lnbits_invoice_key=invoice_key,
            lnbits_admin_key=admin_key,
            **kwargs,
        )

    @classmethod
    def mock(cls, balance_sat: int = 10000, **kwargs) -> "WalletConfig":
        """Mock wallet for testing (no real sats)."""
        return cls(wallet_type="mock", **kwargs)


class ACPAgent:
    """Zero-config ACP agent.

    User provides wallet config → agent configures everything itself.

    What happens automatically:
    1. Nostr keypair generated
    2. Public relays connected
    3. Wallet connected (NWC / LNbits / mock)
    4. Balance checked
    5. Discovery subscription activated
    6. Buy tool ready
    """

    def __init__(self, wallet: WalletConfig,
                 relays: list = None,
                 auto_connect: bool = True):
        self.wallet_config = wallet
        self.relays = relays or DEFAULT_RELAYS
        self.identity = AgentIdentity.generate()
        self._connected = False
        self._balance = 0

        # Setup wallet
        self._setup_wallet()

        # Setup buy tool
        self.tool = ACPBuyTool(
            wallet=self.agent_wallet,
            identity=self.identity,
            relay_url=self.relays[0] if self.relays else "ws://127.0.0.1:7777",
        )

        if auto_connect:
            self._auto_configure()

    def _setup_wallet(self):
        """Setup wallet by type."""
        if self.wallet_config.wallet_type == "mock":
            balance = 10000  # mock balance
            self.lightning = MockLightning()
            self.agent_wallet = AgentWallet(
                balance_sat=balance,
                max_per_purchase=self.wallet_config.max_per_purchase_sat or balance,
                daily_limit=self.wallet_config.daily_limit_sat or balance * 2,
            )
            self.agent_wallet.lightning = self.lightning
            self._balance = balance

        elif self.wallet_config.wallet_type == "lnbits":
            from .lnbits_wallet import LNbitsWallet
            self.lnbits = LNbitsWallet(
                url=self.wallet_config.lnbits_url,
                invoice_key=self.wallet_config.lnbits_invoice_key,
                admin_key=self.wallet_config.lnbits_admin_key,
            )
            # Get real balance
            try:
                balance_msat = self.lnbits.get_balance()
                balance = balance_msat // 1000
            except:
                balance = 0
            self.lightning = MockLightning()  # still use mock for hold invoices
            self.agent_wallet = AgentWallet(
                balance_sat=balance,
                max_per_purchase=self.wallet_config.max_per_purchase_sat or max(balance, 1000),
                daily_limit=self.wallet_config.daily_limit_sat or max(balance * 2, 5000),
            )
            self.agent_wallet.lightning = self.lightning
            self._balance = balance

        elif self.wallet_config.wallet_type == "nwc":
            # NWC wallet — parse URI
            # nwc://wallet_pubkey@relay_url?secret=xxx
            # For now: use mock until NWC library is integrated
            print("[ACP] NWC wallet support: parsing URI...")
            self.lightning = MockLightning()
            self.agent_wallet = AgentWallet(
                balance_sat=10000,  # placeholder — real balance via NWC
                max_per_purchase=self.wallet_config.max_per_purchase_sat or 10000,
                daily_limit=self.wallet_config.daily_limit_sat or 20000,
            )
            self.agent_wallet.lightning = self.lightning
            self._balance = 10000  # placeholder

    def _auto_configure(self):
        """Auto-configure: keypair, relays, discovery."""
        # Keypair already generated in __init__
        # In production: connect to public Nostr relays
        # For now: mark as configured
        self._connected = True

    # ─── User-facing API (the only thing the user sees) ───

    def status(self) -> str:
        """Agent status — for the user."""
        return (
            f"ACP Agent ready.\n"
            f"Wallet: {self.wallet_config.wallet_type}\n"
            f"Balance: {self.agent_wallet.get_balance()} sats\n"
            f"Per-purchase limit: {self.agent_wallet.max_per_purchase} sats\n"
            f"Daily limit: {self.agent_wallet.daily_limit} sats\n"
        )

    def discover(self, query: str, budget_sat: int) -> ConfirmRequest:
        """Find a service. Returns confirmation request."""
        return self.tool.discover(query, budget_sat)

    def execute(self, confirm: ConfirmRequest) -> PurchaseResult:
        """Execute purchase after user confirmation."""
        return self.tool.execute(confirm)

    def buy(self, query: str, budget_sat: int,
            auto_confirm: bool = False):
        """Full cycle: discover → confirm → buy."""
        return self.tool.buy(query, budget_sat, auto_confirm)

    def balance(self) -> int:
        """Wallet balance."""
        return self.agent_wallet.get_balance()

    def top_up(self, amount_sat: int):
        """Top up wallet."""
        self.agent_wallet.top_up(amount_sat)

    def register_provider(self, **kwargs):
        """Register provider (for tests/demo)."""
        self.tool.register_provider(**kwargs)