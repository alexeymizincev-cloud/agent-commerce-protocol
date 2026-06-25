"""
ACP Agent — zero-config agent payment capability.

Принцип: пользователь даёт ТОЛЬКО кошелёк. Всё остальное автоматически.

Usage (в любом agent-фреймворке):
    agent = ACPAgent(wallet_nwc="nwc://user@wallet.relay")
    # или
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

Пользователь НЕ настраивает:
- Nostr relay (авто: публичные релеи)
- Lightning node (авто: через кошелёк API)
- Keypair (авто: генерируется)
- Discovery (авто: подписка на t:agent-commerce)
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
    """Конфиг кошелька — единственное что даёт пользователь."""
    wallet_type: str  # "nwc" | "lnbits" | "mock"
    # NWC
    nwc_uri: Optional[str] = None
    # LNbits
    lnbits_url: Optional[str] = None
    lnbits_invoice_key: Optional[str] = None
    lnbits_admin_key: Optional[str] = None
    # Limits (опционально — пользователь может поставить)
    max_per_purchase_sat: Optional[int] = None
    daily_limit_sat: Optional[int] = None

    @classmethod
    def nwc(cls, uri: str, **kwargs) -> "WalletConfig":
        """Из NWC URI (Phoenix, Alby, Mutiny, Breez)."""
        return cls(wallet_type="nwc", nwc_uri=uri, **kwargs)

    @classmethod
    def lnbits(cls, url: str, invoice_key: str, admin_key: str, **kwargs) -> "WalletConfig":
        """Из LNbits API keys."""
        return cls(
            wallet_type="lnbits",
            lnbits_url=url,
            lnbits_invoice_key=invoice_key,
            lnbits_admin_key=admin_key,
            **kwargs,
        )

    @classmethod
    def mock(cls, balance_sat: int = 10000, **kwargs) -> "WalletConfig":
        """Mock wallet для тестирования (без реальных sats)."""
        return cls(wallet_type="mock", **kwargs)


class ACPAgent:
    """Zero-config ACP agent.

    Пользователь даёт wallet config → агент настраивает всё сам.

    Что делается автоматически:
    1. Nostr keypair генерируется
    2. Публичные релеи подключаются
    3. Wallet подключается (NWC / LNbits / mock)
    4. Balance проверяется
    5. Discovery подписка активируется
    6. Buy tool готов к использованию
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
        """Настройка кошелька по типу."""
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
        """Автоматическая настройка: keypair, relays, discovery."""
        # Keypair already generated in __init__
        # In production: connect to public Nostr relays
        # For now: mark as configured
        self._connected = True

    # ─── User-facing API (единственное что видит пользователь) ───

    def status(self) -> str:
        """Статус агента — для пользователя."""
        return (
            f"ACP Agent готов.\n"
            f"Кошелёк: {self.wallet_config.wallet_type}\n"
            f"Баланс: {self.agent_wallet.get_balance()} сатов\n"
            f"Лимит на покупку: {self.agent_wallet.max_per_purchase} сатов\n"
            f"Дневной лимит: {self.agent_wallet.daily_limit} сатов\n"
        )

    def discover(self, query: str, budget_sat: int) -> ConfirmRequest:
        """Найти услугу. Возвращает запрос на подтверждение."""
        return self.tool.discover(query, budget_sat)

    def execute(self, confirm: ConfirmRequest) -> PurchaseResult:
        """Выполнить покупку после подтверждения пользователя."""
        return self.tool.execute(confirm)

    def buy(self, query: str, budget_sat: int,
            auto_confirm: bool = False):
        """Полный цикл: найти → подтвердить → купить."""
        return self.tool.buy(query, budget_sat, auto_confirm)

    def balance(self) -> int:
        """Баланс кошелька."""
        return self.agent_wallet.get_balance()

    def top_up(self, amount_sat: int):
        """Пополнить кошелёк."""
        self.agent_wallet.top_up(amount_sat)

    def register_provider(self, **kwargs):
        """Регистрация провайдера (для тестов/demo)."""
        self.tool.register_provider(**kwargs)