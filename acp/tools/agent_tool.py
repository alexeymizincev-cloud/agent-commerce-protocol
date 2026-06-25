"""
ACP Agent Tool — plugin for agent frameworks (Claude Code, Hermes, Codex, LangChain).

Principle: user sees ONLY confirmation request + result.
Everything else (Nostr, Lightning, preimage, receipt) — backend.

Usage in any agent framework:
    tool = ACPBuyTool(wallet, relay_url)
    result = tool.discover("vpn", budget_sat=5000)
    # → "Found VPN Agent. Price: 5000 sats. Confirm?"
    # User: "Yes"
    result = tool.execute(provider, budget_sat=5000)
    # → "Bought. VPN key: xxxx. Spent: 5000 sats."

Or in one command (if auto_confirm=False):
    result = tool.buy("vpn", budget_sat=5000)
"""

import json
from typing import Optional
from dataclasses import dataclass

from ..identity import AgentIdentity
from ..events import Manifest, ServiceRequest, ServiceOffer, Receipt, EventKind, parse_event
from ..crypto import decrypt_result_b64, verify_preimage
from ..protocol import ACPProtocol, MockLightning


@dataclass
class ConfirmRequest:
    """What the agent shows the user before purchase."""
    service: str
    price_sat: int
    provider_name: str
    description: str
    provider_pubkey: str

    def __str__(self):
        return (f"Found: {self.service} from {self.provider_name}\n"
                f"Price: {self.price_sat} sats\n"
                f"Provider: {self.provider_pubkey[:24]}...\n"
                f"Buy? (yes/no)")


@dataclass
class PurchaseResult:
    """What the agent shows the user after purchase."""
    success: bool
    service: str
    provider_name: str
    price_sat: int
    result_data: Optional[bytes]
    error: Optional[str] = None
    receipt_id: Optional[str] = None

    def __str__(self):
        if not self.success:
            return f"Purchase failed: {self.error}"
        result_text = self.result_data.decode('utf-8', errors='replace') if self.result_data else ''
        return (f"Done. {self.service} bought from {self.provider_name}.\n"
                f"Spent: {self.price_sat} sats\n"
                f"Result: {result_text[:200]}")


class AgentWallet:
    """Prepaid agent wallet with limits.

    Principle: agent CANNOT physically spend beyond limit.
    Human loads N sats → agent is limited.
    """

    def __init__(self, balance_sat: int, max_per_purchase: int = None,
                 daily_limit: int = None):
        self.balance_sat = balance_sat
        self.max_per_purchase = max_per_purchase or balance_sat
        self.daily_limit = daily_limit or balance_sat
        self.spent_today = 0
        self.lightning = MockLightning()  # In production: real LNbits/LND

    def can_spend(self, amount_sat: int) -> tuple[bool, str]:
        """Check limits. Returns (allowed, reason)."""
        if amount_sat > self.balance_sat:
            return False, f"Insufficient balance ({self.balance_sat} sats)"
        if amount_sat > self.max_per_purchase:
            return False, f"Per-purchase limit exceeded ({self.max_per_purchase} sats)"
        if self.spent_today + amount_sat > self.daily_limit:
            remaining = self.daily_limit - self.spent_today
            return False, f"Daily limit exceeded (remaining: {remaining} sats)"
        return True, "OK"

    def spend(self, amount_sat: int):
        """Deduct funds. Raises if limit exceeded."""
        ok, reason = self.can_spend(amount_sat)
        if not ok:
            raise ValueError(reason)
        self.balance_sat -= amount_sat
        self.spent_today += amount_sat

    def get_balance(self) -> int:
        return self.balance_sat

    def top_up(self, amount_sat: int):
        """Human tops up agent wallet."""
        self.balance_sat += amount_sat


class ACPBuyTool:
    """ACP buy tool for agent frameworks.

    Two modes:
    1. discover() → confirm → execute() (explicit confirmation, default)
    2. buy() with auto_confirm=True (for automation)

    Principle: user sees only ConfirmRequest and PurchaseResult.
    """

    def __init__(self, wallet: AgentWallet, identity: AgentIdentity,
                 relay_url: str = "ws://127.0.0.1:7777"):
        self.wallet = wallet
        self.identity = identity
        self.relay_url = relay_url
        self.protocol = ACPProtocol(lightning=wallet.lightning)
        self._pending_providers = {}  # cached discover results

    def discover(self, query: str, budget_sat: int) -> ConfirmRequest:
        """Find a provider. Returns ConfirmRequest for the user.

        Agent does NOT buy. Only shows what it found and asks.
        """
        # In real implementation: query Nostr relay for manifests
        # For v0: use mock provider from _pending_providers
        # (in tests we add providers directly)
        provider = self._pending_providers.get(query)
        if provider:
            # Check limits BEFORE showing to user
            ok, reason = self.wallet.can_spend(provider["price_sat"])
            if not ok:
                return ConfirmRequest(
                    service=query, price_sat=0,
                    provider_name="N/A", description=reason,
                    provider_pubkey=""
                )
            return ConfirmRequest(
                service=provider["service"],
                price_sat=provider["price_sat"],
                provider_name=provider["name"],
                description=provider.get("description", ""),
                provider_pubkey=provider["pubkey"]
            )
        return ConfirmRequest(
            service=query, price_sat=0,
            provider_name="N/A",
            description=f"No provider found for: {query}",
            provider_pubkey=""
        )

    def register_provider(self, service: str, price_sat: int,
                          name: str, pubkey: str,
                          description: str = "",
                          manifest_event: dict = None,
                          result_data: bytes = None):
        """Register provider (for tests / demo).

        In production: providers publish manifests on Nostr relay.
        """
        self._pending_providers[service] = {
            "service": service,
            "price_sat": price_sat,
            "name": name,
            "pubkey": pubkey,
            "description": description,
            "manifest_event": manifest_event,
            "result_data": result_data,
        }

    def execute(self, confirm: ConfirmRequest) -> PurchaseResult:
        """Execute purchase AFTER user confirmation.

        Full cycle (all invisible to user):
        1. Check limits
        2. Create request (Nostr event)
        3. Provider creates offer (hold invoice + encrypted result)
        4. Agent pays (Lightning)
        5. Provider settles (reveals preimage)
        6. Agent decrypts result
        7. Deduct from wallet
        """
        if confirm.price_sat == 0:
            return PurchaseResult(
                success=False, service=confirm.service,
                provider_name=confirm.provider_name,
                price_sat=0, result_data=None,
                error=confirm.description
            )

        # Check limits
        ok, reason = self.wallet.can_spend(confirm.price_sat)
        if not ok:
            return PurchaseResult(
                success=False, service=confirm.service,
                provider_name=confirm.provider_name,
                price_sat=confirm.price_sat, result_data=None,
                error=reason
            )

        # Get provider from cache
        provider = self._pending_providers.get(confirm.service)
        if not provider:
            return PurchaseResult(
                success=False, service=confirm.service,
                provider_name=confirm.provider_name,
                price_sat=confirm.price_sat, result_data=None,
                error="Provider not found in cache"
            )

        # Create provider identity (for mock)
        provider_identity = AgentIdentity.generate()

        # Create request
        request = self.protocol.create_request(
            identity=self.identity,
            need={"service": confirm.service, "content_type": "text/plain"},
            budget_msat=confirm.price_sat * 1000,
        )

        # Provider creates offer with atomic delivery
        result_data = provider.get("result_data", b"Service delivered.")
        offer, preimage = self.protocol.create_offer(
            provider_identity, request, result_data,
            confirm.price_sat * 1000
        )

        # Agent pays
        self.protocol.accept_offer_and_pay(offer)

        # Provider settles
        receipt = self.protocol.settle_and_publish_receipt(
            provider_identity, offer, preimage, confirm.price_sat * 1000
        )

        # Agent decrypts
        decrypted = self.protocol.decrypt_result_from_receipt(receipt, offer)

        # Deduct from wallet
        self.wallet.spend(confirm.price_sat)

        return PurchaseResult(
            success=True,
            service=confirm.service,
            provider_name=confirm.provider_name,
            price_sat=confirm.price_sat,
            result_data=decrypted,
            receipt_id=receipt["id"],
        )

    def buy(self, query: str, budget_sat: int,
            auto_confirm: bool = False) -> PurchaseResult:
        """Full cycle in one command.

        If auto_confirm=True: does not ask user (for automation).
        If auto_confirm=False: returns ConfirmRequest (needs execute()).
        """
        confirm = self.discover(query, budget_sat)
        if confirm.price_sat == 0:
            return PurchaseResult(
                success=False, service=query,
                provider_name=confirm.provider_name,
                price_sat=0, result_data=None,
                error=confirm.description
            )
        if auto_confirm:
            return self.execute(confirm)
        return confirm  # Returns ConfirmRequest, waits for "yes"