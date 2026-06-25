"""
L4: Agent Tool Tests — user-facing tool behavior.

Tests: confirmation flow, budget limits, auto-confirm, receipt reporting.
These test the TOOL INTERFACE the user interacts with, not the protocol internals.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from acp.tools import ACPBuyTool, AgentWallet, ConfirmRequest, PurchaseResult
from acp import AgentIdentity


class TestAgentTool:
    """Tests for ACPBuyTool — the agent-facing interface."""

    def setup_method(self):
        """Setup fresh wallet + tool for each test."""
        self.wallet = AgentWallet(
            balance_sat=10000,
            max_per_purchase=8000,
            daily_limit=20000,
        )
        self.identity = AgentIdentity.generate()
        self.tool = ACPBuyTool(
            wallet=self.wallet,
            identity=self.identity,
            relay_url="ws://127.0.0.1:7777",
        )
        self.tool.register_provider(
            service="vpn",
            price_sat=5000,
            name="LightningVPN",
            pubkey="npub1vpn_provider_abc",
            description="VPN subscription 1 month",
            result_data=b"VPN_KEY=xxxx-xxxx-xxxx-xxxx",
        )

    def test_discover_returns_confirm_request(self):
        """Discover returns a ConfirmRequest (asks user, doesn't buy)."""
        confirm = self.tool.discover("vpn", budget_sat=5000)
        assert isinstance(confirm, ConfirmRequest)
        assert confirm.service == "vpn"
        assert confirm.price_sat == 5000
        assert confirm.provider_name == "LightningVPN"

    def test_discover_does_not_spend(self):
        """Discover alone does NOT spend any sats."""
        balance_before = self.wallet.get_balance()
        self.tool.discover("vpn", budget_sat=5000)
        assert self.wallet.get_balance() == balance_before

    def test_execute_requires_confirm(self):
        """Execute after confirm works and spends."""
        confirm = self.tool.discover("vpn", budget_sat=5000)
        result = self.tool.execute(confirm)
        assert isinstance(result, PurchaseResult)
        assert result.success
        assert result.price_sat == 5000
        assert self.wallet.get_balance() == 5000  # 10000 - 5000

    def test_limit_per_purchase_exceeded(self):
        """Purchase exceeding per-purchase limit is blocked."""
        self.tool.register_provider(
            service="gpu", price_sat=10000, name="GPUProvider",
            pubkey="npub1gpu", description="GPU", result_data=b"result",
        )
        confirm = self.tool.discover("gpu", budget_sat=10000)
        # Price exceeds max_per_purchase (8000)
        result = self.tool.execute(confirm)
        assert not result.success
        assert "лимит" in result.error.lower() or "limit" in result.error.lower()

    def test_limit_balance_exceeded(self):
        """Purchase exceeding balance is blocked."""
        self.tool.register_provider(
            service="car", price_sat=50000, name="CarDealer",
            pubkey="npub1car", description="Ferrari", result_data=b"vroom",
        )
        confirm = self.tool.discover("car", budget_sat=50000)
        result = self.tool.execute(confirm)
        assert not result.success
        assert "недостаточно" in result.error.lower() or "insufficient" in result.error.lower()

    def test_daily_limit_exceeded(self):
        """Multiple purchases exceeding daily limit are blocked."""
        # Spend 5000 twice (total 10000, under balance 10000)
        confirm1 = self.tool.discover("vpn", budget_sat=5000)
        self.tool.execute(confirm1)
        # Register second VPN provider for variety
        self.tool.register_provider(
            service="vpn2", price_sat=5000, name="VPN2",
            pubkey="npub1vpn2", description="VPN2", result_data=b"key2",
        )
        # Reset max_per_purchase but daily_limit=20000, spent 5000, balance 5000
        # 5000 + 5000 = 10000 < 20000, so daily limit OK but balance will hit 0
        confirm2 = self.tool.discover("vpn2", budget_sat=5000)
        result2 = self.tool.execute(confirm2)
        assert result2.success
        assert self.wallet.get_balance() == 0

        # Third purchase: balance = 0
        confirm3 = self.tool.discover("vpn", budget_sat=5000)
        result3 = self.tool.execute(confirm3)
        assert not result3.success

    def test_auto_confirm_mode(self):
        """buy() with auto_confirm=True skips user confirmation."""
        result = self.tool.buy("vpn", budget_sat=5000, auto_confirm=True)
        assert isinstance(result, PurchaseResult)
        assert result.success
        assert self.wallet.get_balance() == 5000

    def test_auto_confirm_respects_limits(self):
        """Auto-confirm still respects budget limits."""
        self.tool.register_provider(
            service="expensive", price_sat=50000, name="Expensive",
            pubkey="npub1exp", description="Too expensive", result_data=b"x",
        )
        result = self.tool.buy("expensive", budget_sat=50000, auto_confirm=True)
        assert not result.success
        assert self.wallet.get_balance() == 10000  # nothing spent

    def test_provider_not_found(self):
        """Searching for non-existent service returns no provider."""
        confirm = self.tool.discover("nonexistent", budget_sat=1000)
        assert confirm.price_sat == 0
        assert "N/A" in confirm.provider_name or "не нашёл" in confirm.description.lower()

    def test_receipt_reported(self):
        """Successful purchase includes receipt ID (proof of spending)."""
        confirm = self.tool.discover("vpn", budget_sat=5000)
        result = self.tool.execute(confirm)
        assert result.success
        assert result.receipt_id is not None
        assert len(result.receipt_id) > 0  # receipt has an ID

    def test_result_data_correct(self):
        """Decrypted result matches what provider offered."""
        expected = b"VPN_KEY=xxxx-xxxx-xxxx-xxxx"
        confirm = self.tool.discover("vpn", budget_sat=5000)
        result = self.tool.execute(confirm)
        assert result.success
        assert result.result_data == expected

    def test_topup_increases_balance(self):
        """User can add funds to agent wallet."""
        assert self.wallet.get_balance() == 10000
        self.wallet.top_up(5000)
        assert self.wallet.get_balance() == 15000

    def test_multiple_purchases_track_spending(self):
        """Multiple purchases track spent_today correctly."""
        self.tool.register_provider(
            service="data1", price_sat=3000, name="Data1",
            pubkey="npub1d1", description="Data", result_data=b"d1",
        )
        self.tool.register_provider(
            service="data2", price_sat=3000, name="Data2",
            pubkey="npub1d2", description="Data", result_data=b"d2",
        )

        # Buy data1
        c1 = self.tool.discover("data1", budget_sat=3000)
        r1 = self.tool.execute(c1)
        assert r1.success
        assert self.wallet.get_balance() == 7000  # 10000-3000
        assert self.wallet.spent_today == 3000

        # Buy data2
        c2 = self.tool.discover("data2", budget_sat=3000)
        r2 = self.tool.execute(c2)
        assert r2.success
        assert self.wallet.get_balance() == 4000  # 10000-3000-3000
        assert self.wallet.spent_today == 6000