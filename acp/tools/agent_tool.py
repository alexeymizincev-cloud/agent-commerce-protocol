"""
ACP Agent Tool — плагин для agent-фреймворков (Claude Code, Hermes, Codex, LangChain).

Принцип: пользователь видит ТОЛЬКО запрос подтверждения + результат.
Всё остальное (Nostr, Lightning, preimage, receipt) — бэкенд.

Usage в любом agent-фреймворке:
    tool = ACPBuyTool(wallet, relay_url)
    result = tool.discover("vpn", budget_sat=5000)
    # → "Found VPN Agent. Price: 5000 sats. Confirm?"
    # User: "Yes"
    result = tool.execute(provider, budget_sat=5000)
    # → "Bought. VPN key: xxxx. Spent: 5000 sats."

Или одной командой (если auto_confirm=False):
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
    """Что агент показывает пользователю перед покупкой."""
    service: str
    price_sat: int
    provider_name: str
    description: str
    provider_pubkey: str

    def __str__(self):
        return (f"Найдено: {self.service} от {self.provider_name}\n"
                f"Цена: {self.price_sat} сатов\n"
                f"Провайдер: {self.provider_pubkey[:24]}...\n"
                f"Купить? (да/нет)")


@dataclass
class PurchaseResult:
    """Что агент показывает пользователю после покупки."""
    success: bool
    service: str
    provider_name: str
    price_sat: int
    result_data: Optional[bytes]
    error: Optional[str] = None
    receipt_id: Optional[str] = None

    def __str__(self):
        if not self.success:
            return f"Не удалось купить: {self.error}"
        result_text = self.result_data.decode('utf-8', errors='replace') if self.result_data else ''
        return (f"Готово. {self.service} куплен у {self.provider_name}.\n"
                f"Потрачено: {self.price_sat} сатов\n"
                f"Результат: {result_text[:200]}")


class AgentWallet:
    """Prepaid кошелёк агента с лимитами.

    Принцип: агент ФИЗИЧЕСКИ не может потратить больше лимита.
    Человек грузит N сатов → агент ограничен.
    """

    def __init__(self, balance_sat: int, max_per_purchase: int = None,
                 daily_limit: int = None):
        self.balance_sat = balance_sat
        self.max_per_purchase = max_per_purchase or balance_sat
        self.daily_limit = daily_limit or balance_sat
        self.spent_today = 0
        self.lightning = MockLightning()  # В проде: real LNbits/LND

    def can_spend(self, amount_sat: int) -> tuple[bool, str]:
        """Проверка лимитов. Возвращает (можно, причина)."""
        if amount_sat > self.balance_sat:
            return False, f"Недостаточно средств (баланс: {self.balance_sat} сат)"
        if amount_sat > self.max_per_purchase:
            return False, f"Превышен лимит на покупку ({self.max_per_purchase} сат)"
        if self.spent_today + amount_sat > self.daily_limit:
            remaining = self.daily_limit - self.spent_today
            return False, f"Превышен дневной лимит (осталось: {remaining} сат)"
        return True, "OK"

    def spend(self, amount_sat: int):
        """Списать средства. Бросает исключение если лимит превышен."""
        ok, reason = self.can_spend(amount_sat)
        if not ok:
            raise ValueError(reason)
        self.balance_sat -= amount_sat
        self.spent_today += amount_sat

    def get_balance(self) -> int:
        return self.balance_sat

    def top_up(self, amount_sat: int):
        """Человек пополняет кошелёк агента."""
        self.balance_sat += amount_sat


class ACPBuyTool:
    """ACP buy tool для agent-фреймворков.

    Два режима:
    1. discover() → confirm → execute() (явное подтверждение, по умолчанию)
    2. buy() с auto_confirm=True (для automation)

    Принцип: пользователь видит только ConfirmRequest и PurchaseResult.
    """

    def __init__(self, wallet: AgentWallet, identity: AgentIdentity,
                 relay_url: str = "ws://127.0.0.1:7777"):
        self.wallet = wallet
        self.identity = identity
        self.relay_url = relay_url
        self.protocol = ACPProtocol(lightning=wallet.lightning)
        self._pending_providers = {}  # cached discover results

    def discover(self, query: str, budget_sat: int) -> ConfirmRequest:
        """Найти провайдера. Возвращает ConfirmRequest для пользователя.

        Агент НЕ покупает. Только показывает что нашёл и спрашивает.
        """
        # В реальной реализации: query Nostr relay for manifests
        # Для v0: используем mock provider из _pending_providers
        # (в tests мы добавляем провайдеров напрямую)
        provider = self._pending_providers.get(query)
        if provider:
            # Проверяем лимиты ДО показа пользователю
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
            description=f"Не нашёл провайдера для: {query}",
            provider_pubkey=""
        )

    def register_provider(self, service: str, price_sat: int,
                          name: str, pubkey: str,
                          description: str = "",
                          manifest_event: dict = None,
                          result_data: bytes = None):
        """Регистрация провайдера (для тестов / demo).

        В проде: провайдеры сами публикуют manifest на Nostr relay.
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
        """Выполнить покупку ПОСЛЕ подтверждения пользователя.

        Полный цикл (всё невидимо для пользователя):
        1. Проверка лимитов
        2. Создание request (Nostr event)
        3. Провайдер создаёт offer (hold invoice + encrypted result)
        4. Агент платит (Lightning)
        5. Провайдер settle (reveals preimage)
        6. Агент decrypts result
        7. Списание с кошелька
        """
        if confirm.price_sat == 0:
            return PurchaseResult(
                success=False, service=confirm.service,
                provider_name=confirm.provider_name,
                price_sat=0, result_data=None,
                error=confirm.description
            )

        # Проверка лимитов
        ok, reason = self.wallet.can_spend(confirm.price_sat)
        if not ok:
            return PurchaseResult(
                success=False, service=confirm.service,
                provider_name=confirm.provider_name,
                price_sat=confirm.price_sat, result_data=None,
                error=reason
            )

        # Получаем провайдера из кэша
        provider = self._pending_providers.get(confirm.service)
        if not provider:
            return PurchaseResult(
                success=False, service=confirm.service,
                provider_name=confirm.provider_name,
                price_sat=confirm.price_sat, result_data=None,
                error="Провайдер не найден в кэше"
            )

        # Создаём provider identity (для mock)
        provider_identity = AgentIdentity.generate()

        # Создаём request
        request = self.protocol.create_request(
            identity=self.identity,
            need={"service": confirm.service, "content_type": "text/plain"},
            budget_msat=confirm.price_sat * 1000,
        )

        # Провайдер создаёт offer с atomic delivery
        result_data = provider.get("result_data", b"Service delivered.")
        offer, preimage = self.protocol.create_offer(
            provider_identity, request, result_data,
            confirm.price_sat * 1000
        )

        # Агент платит
        self.protocol.accept_offer_and_pay(offer)

        # Провайдер settle
        receipt = self.protocol.settle_and_publish_receipt(
            provider_identity, offer, preimage, confirm.price_sat * 1000
        )

        # Агент decrypts
        decrypted = self.protocol.decrypt_result_from_receipt(receipt, offer)

        # Списываем с кошелька
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
        """Полный цикл одной командой.

        Если auto_confirm=True: не спрашивает пользователя (для automation).
        Если auto_confirm=False: возвращает ConfirmRequest (нужен execute()).
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
        return confirm  # Возвращает ConfirmRequest, ждёт "да"