"""
LNbits Wallet Adapter — real Lightning payments via LNbits REST API.

Works with any LNbits instance (self-hosted or public like testnet.lnbits.com).

Setup:
1. Go to https://testnet.lnbits.com (or your own LNbits)
2. Create a wallet
3. Get API keys (Wallet > API info):
   - Invoice key (for creating invoices)
   - Admin key (for paying invoices)
4. Get testnet sats from a faucet (lightningfaucet.com)
5. Set environment variables:
   export LNBITS_URL="https://testnet.lnbits.com"
   export LNBITS_INVOICE_KEY="your_invoice_key"
   export LNBITS_ADMIN_KEY="your_admin_key"
6. Run: python3 real_testnet_demo.py

This replaces MockLightning with REAL Lightning payments.
"""

import os
import json
import requests
from typing import Optional, Tuple
from .mock_lightning import MockLightning


class LNbitsWallet:
    """Real Lightning wallet via LNbits REST API.

    Replaces MockLightning for real testnet testing.
    API docs: https://docs.lnbits.com/api
    """

    def __init__(self, url: str = None, invoice_key: str = None,
                 admin_key: str = None):
        self.url = (url or os.environ.get("LNBITS_URL", "")).rstrip("/")
        self.invoice_key = invoice_key or os.environ.get("LNBITS_INVOICE_KEY", "")
        self.admin_key = admin_key or os.environ.get("LNBITS_ADMIN_KEY", "")

        if not self.url or not self.invoice_key:
            raise ValueError(
                "LNbits not configured. Set LNBITS_URL and LNBITS_INVOICE_KEY "
                "environment variables, or pass url + keys to constructor.\n"
                "Get free testnet keys at https://testnet.lnbits.com"
            )

    # ─── Balance ──────────────────────────────────────

    def get_balance(self) -> int:
        """Get wallet balance in millisatoshis."""
        resp = requests.get(
            f"{self.url}/api/v1/wallet",
            headers={"X-Api-Key": self.invoice_key}
        )
        data = resp.json()
        return data.get("balance", 0)  # msat

    # ─── Create Invoice (receive) ─────────────────────

    def create_invoice(self, amount_sat: int, memo: str = "ACP payment") -> str:
        """Create a Lightning invoice. Returns BOLT11 string.

        amount_sat: amount in satoshis (1 sat = 1000 msat)
        """
        resp = requests.post(
            f"{self.url}/api/v1/payments",
            headers={
                "X-Api-Key": self.invoice_key,
                "Content-Type": "application/json"
            },
            json={
                "out": False,
                "amount": amount_sat,  # LNbits uses sats, not msat
                "memo": memo,
            }
        )
        data = resp.json()
        return data.get("payment_hash", ""), data.get("payment_request", "")

    # ─── Pay Invoice (send) ───────────────────────────

    def pay_invoice(self, bolt11: str) -> bool:
        """Pay a Lightning invoice. Returns True if successful."""
        resp = requests.post(
            f"{self.url}/api/v1/payments",
            headers={
                "X-Api-Key": self.admin_key,
                "Content-Type": "application/json"
            },
            json={
                "out": True,
                "bolt11": bolt11,
            }
        )
        if resp.status_code == 201:
            return True
        # Check if already paid
        try:
            data = resp.json()
            if "already paid" in str(data).lower():
                return True
        except:
            pass
        return False

    # ─── Check Payment ────────────────────────────────

    def check_invoice_paid(self, payment_hash: str) -> bool:
        """Check if an invoice has been paid."""
        resp = requests.get(
            f"{self.url}/api/v1/payments/{payment_hash}",
            headers={"X-Api-Key": self.invoice_key}
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("paid", False)
        return False

    # ─── Hold Invoice Support ─────────────────────────
    # NOTE: LNbits standard API doesn't support hold invoices directly.
    # Hold invoices require LND backend with HoldInvoice RPC.
    # For testing: we simulate atomic delivery with regular invoices.
    # Production: use LND directly or LNbits with hold invoice extension.

    def is_configured(self) -> bool:
        """Check if wallet is properly configured."""
        try:
            balance = self.get_balance()
            return True
        except Exception:
            return False

    def status(self) -> str:
        """Human-readable status."""
        try:
            balance_msat = self.get_balance()
            balance_sat = balance_msat / 1000
            return f"LNbits wallet: {balance_sat:.0f} sats ({self.url})"
        except Exception as e:
            return f"LNbits error: {e}"


# ─── Fallback: Mock if no LNbits configured ─────────────

def get_lightning_backend() -> object:
    """Get Lightning backend: real LNbits if configured, Mock otherwise.

    This allows tests to run without LNbits setup,
    but real testnet test uses LNbits if keys are set.
    """
    if os.environ.get("LNBITS_URL") and os.environ.get("LNBITS_INVOICE_KEY"):
        try:
            wallet = LNbitsWallet()
            if wallet.is_configured():
                print(f"[ACP] Using real LNbits wallet: {wallet.status()}")
                return wallet
        except Exception as e:
            print(f"[ACP] LNbits config failed, falling back to Mock: {e}")

    print("[ACP] No LNbits configured, using MockLightning")
    return MockLightning()