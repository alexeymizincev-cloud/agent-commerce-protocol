"""
ACP Provider types — three provider types.

1. Native: accepts Lightning directly (LNURL/BOLT11)
2. Bridge: accepts Lightning, pays via third-party API (Stripe, PayPal)
3. Adapter: wrapper over existing service (Bitrefill, CoinGate)

All three are ACP-compatible providers. The difference is how they fulfill
the obligation after receiving Lightning payment.

The protocol does NOT know or care how the provider fulfills.
Manifest = "I sell X for N sats". How — not the protocol concern.
"""

from dataclasses import dataclass
from typing import Optional
from .identity import AgentIdentity
from .events import Manifest
from .crypto import encrypt_result_b64, generate_preimage, hash_preimage
from .protocol import MockLightning


@dataclass
class ProviderManifest:
    """Provider manifest + routing metadata."""
    service: str
    provider_type: str  # "native" | "bridge" | "adapter"
    name: str
    price_msat: int
    pay_endpoint: str
    description: str
    target: Optional[str] = None  # for bridge: "stripe", "paypal", etc.
    fee_pct: Optional[float] = None  # for bridge: fee


class NativeProvider:
    """Type 1: accepts Lightning directly.

    Example: VPN provider with BTCPay Server, LNbits, or LND.
    Agent pays via LNURL → gets result.

    No Stripe, fiat, or browser. Pure Lightning.
    """

    def __init__(self, identity: AgentIdentity, service: str,
                 price_msat: int, result_data: bytes,
                 lightning: MockLightning = None):
        self.identity = identity
        self.service = service
        self.price_msat = price_msat
        self.result_data = result_data
        self.lightning = lightning or MockLightning()

    def get_manifest(self) -> dict:
        """Publishes manifest on Nostr relay."""
        from .protocol import ACPProtocol
        p = ACPProtocol(lightning=self.lightning)
        return p.create_manifest(
            identity=self.identity,
            name=f"Native {self.service}",
            offers=[{
                "service": self.service,
                "content_type": "text/plain",
                "pricing": {
                    "model": "per_request",
                    "amount_msat": self.price_msat,
                    "unit": "call"
                }
            }],
            pay_endpoint=f"lnurl://native_{self.service}",
        )

    def fulfill(self, request_event: dict) -> tuple[dict, bytes]:
        """Creates offer with atomic delivery. Returns (offer_event, preimage)."""
        from .protocol import ACPProtocol
        p = ACPProtocol(lightning=self.lightning)
        return p.create_offer(
            provider_identity=self.identity,
            request_event=request_event,
            result_data=self.result_data,
            amount_msat=self.price_msat,
        )


class BridgeProvider:
    """Type 2: accepts Lightning, pays via third-party API.

    Example: Bridge-agent with Stripe API key.
    - Agent pays Lightning → Bridge-agent receives sats
    - Bridge-agent calls Stripe API (not website, API!) → pays for fiat service
    - Bridge-agent publishes receipt with credentials

    Fee = arbitrage markup (typical 3-10%).

    IMPORTANT: Bridge-agent calls API, does NOT open browser.
    Stripe API = REST. PayPal API = REST. All via HTTP, not forms.
    """

    def __init__(self, identity: AgentIdentity, service: str,
                 price_msat: int, result_data: bytes,
                 target: str = "stripe",
                 fee_pct: float = 5.0,
                 lightning: MockLightning = None):
        self.identity = identity
        self.service = service
        self.price_msat = price_msat
        self.result_data = result_data
        self.target = target
        self.fee_pct = fee_pct
        self.lightning = lightning or MockLightning()

    def get_manifest(self) -> dict:
        """Manifest with bridge metadata."""
        from .protocol import ACPProtocol
        p = ACPProtocol(lightning=self.lightning)
        return p.create_manifest(
            identity=self.identity,
            name=f"Bridge: {self.service} via {self.target}",
            offers=[{
                "service": self.service,
                "content_type": "text/plain",
                "pricing": {
                    "model": "per_request",
                    "amount_msat": self.price_msat,
                    "unit": "call",
                    "fee_pct": self.fee_pct,
                    "target": self.target,
                }
            }],
            pay_endpoint=f"lnurl://bridge_{self.service}_{self.target}",
            stake_msat=10000000,  # bridge = higher stake (more trust needed)
        )

    def fulfill(self, request_event: dict) -> tuple[dict, bytes]:
        """Creates offer. In reality: after settle calls Stripe API."""
        from .protocol import ACPProtocol
        p = ACPProtocol(lightning=self.lightning)
        return p.create_offer(
            provider_identity=self.identity,
            request_event=request_event,
            result_data=self.result_data,
            amount_msat=self.price_msat,
        )


class AdapterProvider:
    """Type 3: wrapper over existing service.

    Example: Bitrefill adapter.
    - Bitrefill already accepts Lightning and sells gift cards
    - Adapter = ACP-compatible manifest over Bitrefill API
    - Agent finds adapter via Nostr, pays, gets gift card code

    Adapter = not a new service, but a bridge to existing one.
    """

    def __init__(self, identity: AgentIdentity, service: str,
                 price_msat: int, result_data: bytes,
                 source: str = "bitrefill",
                 lightning: MockLightning = None):
        self.identity = identity
        self.service = service
        self.price_msat = price_msat
        self.result_data = result_data
        self.source = source
        self.lightning = lightning or MockLightning()

    def get_manifest(self) -> dict:
        from .protocol import ACPProtocol
        p = ACPProtocol(lightning=self.lightning)
        return p.create_manifest(
            identity=self.identity,
            name=f"Adapter: {self.service} via {self.source}",
            offers=[{
                "service": self.service,
                "content_type": "text/plain",
                "pricing": {
                    "model": "per_request",
                    "amount_msat": self.price_msat,
                    "unit": "call",
                    "source": self.source,
                }
            }],
            pay_endpoint=f"lnurl://adapter_{self.source}",
        )

    def fulfill(self, request_event: dict) -> tuple[dict, bytes]:
        from .protocol import ACPProtocol
        p = ACPProtocol(lightning=self.lightning)
        return p.create_offer(
            provider_identity=self.identity,
            request_event=request_event,
            result_data=self.result_data,
            amount_msat=self.price_msat,
        )


# ─── Routing logic ──────────────────────────────────────

def route_purchase(query: str, budget_sat: int,
                   providers: list) -> Optional[object]:
    """Agent routing: select best provider.

    Priority:
    1. Native (cheapest, no fee)
    2. Adapter (existing service, low fee)
    3. Bridge (highest fee, but covers fiat)

    Returns best provider or None.
    """
    matching = [p for p in providers if p.service == query
                and p.price_msat <= budget_sat * 1000]

    if not matching:
        return None

    # Sort by type priority then price
    type_priority = {"native": 0, "adapter": 1, "bridge": 2}
    matching.sort(key=lambda p: (type_priority.get(
        getattr(p, 'provider_type', 'native'), 3), p.price_msat))

    return matching[0]