"""
ACP Provider types — три типа провайдеров.

1. Native: принимает Lightning напрямую (LNURL/BOLT11)
2. Bridge: принимает Lightning, платит через сторонний API (Stripe, PayPal)
3. Adapter: обёртка над существующим сервисом (Bitrefill, CoinGate)

Все три = ACP-совместимые провайдеры. Разница — как они исполняют
обязательство после получения Lightning-платежа.

Протокол НЕ знает и НЕ заботится как провайдер исполняет.
Манифест = "я продаю X за N сатов". Как — не протокольная забота.
"""

from dataclasses import dataclass
from typing import Optional
from .identity import AgentIdentity
from .events import Manifest
from .crypto import encrypt_result_b64, generate_preimage, hash_preimage
from .protocol import MockLightning


@dataclass
class ProviderManifest:
    """Провайдер manifest + метаданные для routing."""
    service: str
    provider_type: str  # "native" | "bridge" | "adapter"
    name: str
    price_msat: int
    pay_endpoint: str
    description: str
    target: Optional[str] = None  # для bridge: "stripe", "paypal", etc.
    fee_pct: Optional[float] = None  # для bridge: комиссия


class NativeProvider:
    """Type 1: принимает Lightning напрямую.

    Пример: VPN провайдер с BTCPay Server, LNbits, или LND.
    Агент платит через LNURL → получает результат.

    Никакого Stripe, fiat, или браузера. Чистый Lightning.
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
        """Публикует manifest на Nostr relay."""
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
        """Создаёт offer с atomic delivery. Возвращает (offer_event, preimage)."""
        from .protocol import ACPProtocol
        p = ACPProtocol(lightning=self.lightning)
        return p.create_offer(
            provider_identity=self.identity,
            request_event=request_event,
            result_data=self.result_data,
            amount_msat=self.price_msat,
        )


class BridgeProvider:
    """Type 2: принимает Lightning, платит через сторонний API.

    Пример: Bridge-agent с Stripe API key.
    - Агент платит Lightning → Bridge-agent получает саты
    - Bridge-agent вызывает Stripe API (не сайт, API!) → оплачивает fiat-сервис
    - Bridge-agent публикует receipt с credentials

    Fee = markup за арбитраж (typical 3-10%).

    ВАЖНО: Bridge-agent вызывает API, НЕ открывает браузер.
    Stripe API = REST. PayPal API = REST. Всё через HTTP, не через формы.
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
        """Manifest с bridge-метаданными."""
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
        """Создаёт offer. В реальности: после settle вызывает Stripe API."""
        from .protocol import ACPProtocol
        p = ACPProtocol(lightning=self.lightning)
        return p.create_offer(
            provider_identity=self.identity,
            request_event=request_event,
            result_data=self.result_data,
            amount_msat=self.price_msat,
        )


class AdapterProvider:
    """Type 3: обёртка над существующим сервисом.

    Пример: Bitrefill adapter.
    - Bitrefill уже принимает Lightning и продаёт gift cards
    - Adapter = ACP-совместимый manifest поверх Bitrefill API
    - Агент находит adapter через Nostr, платит, получает gift card код

    Adapter = не новый сервис, а мост к существующему.
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
    """Agent routing: выбрать лучшего провайдера.

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