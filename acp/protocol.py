"""
ACP Protocol — high-level transaction flow orchestration.

Implements the core atomic-delivery flow:
  Manifest → Request → Offer (hold invoice + enc result) → Payment → Settlement → Receipt

For testing without real Lightning: MockLightning simulates hold invoices.
"""

import time
import json
from typing import Optional

from .identity import AgentIdentity
from .events import (
    Manifest, ServiceRequest, ServiceOffer, Receipt, Attestation,
    EventKind,
)
from .crypto import (
    generate_preimage, hash_preimage,
    encrypt_result_b64, decrypt_result_b64,
    verify_preimage, verify_receipt,
)


class MockLightning:
    """Simulates Lightning hold invoice lifecycle for testing.

    States: CREATED → (consumer pays) → LOCKED → (provider settles) → SETTLED
                                 OR
                          (expires) → CANCELLED

    Real Lightning would use BOLT11 invoices over the Lightning Network.
    This mock simulates the exact same state machine.
    """

    def __init__(self):
        # invoice_hash → {state, preimage, amount_msat, consumer, provider, created_at}
        self.invoices = {}
        self.settled_payments = []  # log of settled payments

    def create_hold_invoice(self, amount_msat: int, preimage: bytes,
                             provider: str, consumer: str = None,
                             expiry_s: int = 60) -> dict:
        """Provider creates a hold invoice. Returns invoice dict."""
        h = hash_preimage(preimage)
        h_hex = h.hex()
        bolt11 = f"lnbcrt{amount_msat}m1mock_{h_hex}"  # fake BOLT11 for testing

        invoice_record = {
            "hash": h_hex,
            "preimage": preimage.hex() if preimage else None,
            "amount_msat": amount_msat,
            "state": "CREATED",
            "provider": provider,
            "consumer": consumer,
            "created_at": time.time(),
            "expiry_s": expiry_s,
            "bolt11": bolt11,
        }
        self.invoices[h_hex] = invoice_record
        return invoice_record["bolt11"]

    def pay_hold_invoice(self, invoice_hash_hex: str, consumer: str):
        """Consumer pays (locks funds). State: CREATED → LOCKED."""
        inv = self.invoices.get(invoice_hash_hex)
        if inv is None:
            raise ValueError(f"Unknown invoice: {invoice_hash_hex}")
        if inv["state"] != "CREATED":
            raise ValueError(f"Invoice not payable (state={inv['state']})")

        inv["consumer"] = consumer
        inv["state"] = "LOCKED"
        inv["locked_at"] = time.time()
        return True

    def settle_hold_invoice(self, invoice_hash_hex: str, preimage: bytes,
                             provider: str):
        """Provider settles (reveals preimage). State: LOCKED → SETTLED.

        Lightning network verifies: SHA256(preimage) == invoice_hash.
        If mismatch → rejection (settle fails).
        """
        inv = self.invoices.get(invoice_hash_hex)
        if inv is None:
            raise ValueError(f"Unknown invoice: {invoice_hash_hex}")
        if inv["state"] != "LOCKED":
            raise ValueError(f"Cannot settle (state={inv['state']})")
        if inv["provider"] != provider:
            raise ValueError("Only original provider can settle")

        # Lightning protocol verification: hash(preimage) must match hash
        h = hash_preimage(preimage)
        if h.hex() != invoice_hash_hex:
            raise ValueError("Preimage hash mismatch — Lightning would reject")

        inv["preimage"] = preimage.hex()
        inv["state"] = "SETTLED"
        inv["settled_at"] = time.time()
        self.settled_payments.append({
            "hash": invoice_hash_hex,
            "amount_msat": inv["amount_msat"],
            "preimage": preimage.hex(),
            "provider": provider,
            "consumer": inv["consumer"],
            "settled_at": inv["settled_at"],
        })
        return True

    def cancel_hold_invoice(self, invoice_hash_hex: str):
        """Hold invoice expires. State: LOCKED → CANCELLED (funds return).

        In real Lightning this happens automatically after expiry.
        """
        inv = self.invoices.get(invoice_hash_hex)
        if inv is None:
            raise ValueError(f"Unknown invoice: {invoice_hash_hex}")
        if inv["state"] == "LOCKED":
            inv["state"] = "CANCELLED"
            inv["cancelled_at"] = time.time()
        return True

    def get_preimage(self, invoice_hash_hex: str) -> Optional[bytes]:
        """Get preimage for a settled invoice.

        Consumer observes preimage through Lightning network after settlement.
        """
        inv = self.invoices.get(invoice_hash_hex)
        if inv is None or inv["state"] != "SETTLED":
            return None
        return bytes.fromhex(inv["preimage"])

    def get_invoice_state(self, invoice_hash_hex: str) -> str:
        inv = self.invoices.get(invoice_hash_hex)
        return inv["state"] if inv else "UNKNOWN"


class ACPProtocol:
    """High-level ACP protocol orchestration.

    Provides helpers for the agent transaction flow:
    1. create_manifest (provider)
    2. create_request (consumer)
    3. create_offer (provider — includes atomic delivery setup)
    4. accept_offer_and_pay (consumer — via mock/real Lightning)
    5. settle_and_publish_receipt (provider)
    6. decrypt_result_from_receipt (consumer)
    """

    def __init__(self, lightning: MockLightning = None):
        self.lightning = lightning or MockLightning()

    # ═══════════════════════════════════════════════════════════
    # PROVIDER SIDE
    # ═══════════════════════════════════════════════════════════

    def create_manifest(self, identity: AgentIdentity, name: str,
                        offers: list, pay_endpoint: str,
                        stake_msat: int = None) -> dict:
        """Provider: publish manifest advertising services."""
        m = Manifest(
            identity=identity,
            name=name,
            offers=offers,
            pay_endpoint=pay_endpoint,
            stake_msat=stake_msat,
        )
        return m.to_nostr_event()

    def create_offer(self, provider_identity: AgentIdentity,
                     request_event: dict, result_data: bytes,
                     amount_msat: int) -> dict:
        """Provider: create offer with atomic delivery.

        1. Generate preimage K (32 bytes)
        2. Encrypt result with K
        3. Create hold invoice with hash H = SHA256(K)
        4. Publish offer event with encrypted result + invoice

        Returns (offer_event, preimage) tuple.
        """
        # Step 1: Generate preimage
        preimage = generate_preimage()
        h = hash_preimage(preimage)

        # Step 2: Encrypt result
        result_enc = encrypt_result_b64(result_data, preimage)

        # Step 3: Create hold invoice
        bolt11 = self.lightning.create_hold_invoice(
            amount_msat=amount_msat,
            preimage=preimage,
            provider=provider_identity.pubkey_hex,
        )

        # Step 4: Build offer event
        request_parsed = ServiceRequest.from_event(request_event)
        offer = ServiceOffer(
            identity=provider_identity,
            request_event_id=request_event["id"],
            consumer_pubkey=request_parsed["pubkey"],
            invoice=bolt11,
            preimage_hash_hex=h.hex(),
            amount_msat=amount_msat,
            result_enc_b64=result_enc,
        )
        return offer.to_nostr_event(), preimage

    def settle_and_publish_receipt(self, provider_identity: AgentIdentity,
                                   offer_event: dict, preimage: bytes,
                                   amount_msat: int) -> dict:
        """Provider: settle hold invoice + publish receipt.

        1. Settle Lightning hold invoice (reveals preimage K)
        2. Publish receipt event with preimage K as proof
        """
        # Extract invoice hash from offer
        offer_parsed = ServiceOffer.from_event(offer_event)
        invoice_hash = offer_parsed["preimage_hash"]

        # Settle on Lightning
        self.lightning.settle_hold_invoice(
            invoice_hash_hex=invoice_hash,
            preimage=preimage,
            provider=provider_identity.pubkey_hex,
        )

        # Publish receipt
        receipt = Receipt(
            identity=provider_identity,
            offer_event_id=offer_event["id"],
            consumer_pubkey=offer_parsed["consumer_pubkey"],
            preimage_hex=preimage.hex(),
            amount_msat=amount_msat,
            settled_at=int(time.time()),
        )
        return receipt.to_nostr_event()

    # ╁══════════════════════════════════════════════════════════
    # CONSUMER SIDE
    # ═══════════════════════════════════════════════════════════

    def create_request(self, identity: AgentIdentity, need: dict,
                       budget_msat: int, deadline_s: int = 60) -> dict:
        """Consumer: publish service request."""
        req = ServiceRequest(
            identity=identity,
            need=need,
            budget_msat=budget_msat,
            deadline=int(time.time()) + deadline_s,
        )
        return req.to_nostr_event()

    def accept_offer_and_pay(self, offer_event: dict) -> str:
        """Consumer: accept offer and pay hold invoice.

        Returns invoice_hash_hex (for tracking settlement).

        Consumer validates:
        - Invoice amount matches offer amount_msat
        - Price is within budget (checked by caller)

        In real implementation: consumer's Lightning node pays BOLT11.
        In mock: calls MockLightning.pay_hold_invoice.
        """
        offer_parsed = ServiceOffer.from_event(offer_event)
        invoice_hash = offer_parsed["preimage_hash"]  # hash identifying the invoice

        # Pay on Lightning (mock simulates real payment)
        self.lightning.pay_hold_invoice(
            invoice_hash_hex=invoice_hash,
            consumer=offer_parsed["consumer_pubkey"],
        )
        return invoice_hash

    def decrypt_result_from_receipt(self, receipt_event: dict,
                                     offer_event: dict) -> bytes:
        """Consumer: decrypt result using preimage from receipt.

        1. Extract preimage K from receipt
        2. Verify SHA256(K) == preimage_hash from offer
        3. Decrypt result_enc with K
        """
        receipt_parsed = Receipt.from_event(receipt_event)
        offer_parsed = ServiceOffer.from_event(offer_event)

        preimage = bytes.fromhex(receipt_parsed["preimage"])

        # Verify preimage matches offer's hash
        offer_hash = bytes.fromhex(offer_parsed["preimage_hash"])
        if not verify_preimage(preimage, offer_hash):
            raise ValueError("Preimage does not match offer hash — FRAUD detected")

        # Decrypt result
        return decrypt_result_b64(offer_parsed["result_enc"], preimage)

    # ═══════════════════════════════════════════════════════════
    # VALIDATION
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def validate_manifest(event: dict) -> list[str]:
        """Validate manifest format. Returns list of errors (empty = valid)."""
        errors = []
        try:
            data = Manifest.from_event(event)
        except Exception as e:
            return [f"Parse error: {e}"]

        if not data.get("name"):
            errors.append("Missing name")
        if not data.get("offers"):
            errors.append("Missing offers")
        if not data.get("pay"):
            errors.append("Missing pay endpoint")

        for i, offer in enumerate(data.get("offers", [])):
            if "service" not in offer:
                errors.append(f"Offer {i}: missing 'service'")
            if "content_type" not in offer:
                errors.append(f"Offer {i}: missing 'content_type'")
            p = offer.get("pricing", {})
            if "model" not in p:
                errors.append(f"Offer {i}: pricing missing 'model'")
            if "amount_msat" not in p and "amount_msat" != 0:
                errors.append(f"Offer {i}: pricing missing 'amount_msat'")
            if "unit" not in p:
                errors.append(f"Offer {i}: pricing missing 'unit'")
        return errors

    @staticmethod
    def validate_offer(event: dict, request_event: dict = None) -> list[str]:
        """Validate offer format."""
        errors = []
        try:
            data = ServiceOffer.from_event(event)
        except Exception as e:
            return [f"Parse error: {e}"]

        if not data.get("invoice"):
            errors.append("Missing invoice")
        if not data.get("preimage_hash"):
            errors.append("Missing preimage_hash")
        if not data.get("result_enc"):
            errors.append("Missing result_enc")
        if not data.get("amount_msat"):
            errors.append("Missing amount_msat")

        # Validate preimage_hash format (64-char hex = SHA256)
        h = data.get("preimage_hash")
        if h and len(h) != 64:
            errors.append(f"preimage_hash must be 64-char hex (got {len(h)})")

        # Cross-check: offer amount vs request budget
        if request_event:
            req = ServiceRequest.from_event(request_event)
            if data["amount_msat"] > req["budget_msat"]:
                errors.append(f"Offer {data['amount_msat']} > budget {req['budget_msat']}")

        return errors

    @staticmethod
    def validate_receipt(event: dict, offer_event: dict = None) -> list[str]:
        """Validate receipt format + preimage verification."""
        errors = []
        try:
            data = Receipt.from_event(event)
        except Exception as e:
            return [f"Parse error: {e}"]

        if not data.get("preimage"):
            errors.append("Missing preimage")

        # Cross-check: preimage hash matches offer
        if offer_event:
            offer = ServiceOffer.from_event(offer_event)
            offer_hash = bytes.fromhex(offer["preimage_hash"])
            receipt_preimage = bytes.fromhex(data["preimage"])
            if not verify_receipt(offer_hash, receipt_preimage):
                errors.append("Preimage hash mismatch — receipt does not match offer")
        return errors