"""
ACP Protocol Events — 4 core + 3 extension event types.

Core (NIP-ACP-01):
  30000 — Agent Manifest (provider advertises services)
  30001 — Service Request (consumer asks for service)
  30002 — Service Offer (provider responds with hold invoice + encrypted result)
  30003 — Transaction Receipt (proof of completed deal)

Extensions:
  30004 — Attestation (NIP-ACP-02, consumer rating)
  30005 — Dispute (NIP-ACP-03)
  30006 — Resolution (NIP-ACP-03)
"""

import json
import time as _time
from typing import Optional

from .identity import AgentIdentity


class EventKind:
    MANIFEST = 30000
    REQUEST = 30001
    OFFER = 30002
    RECEIPT = 30003
    ATTESTATION = 30004
    DISPUTE = 30005
    RESOLUTION = 30006


class ACPEvent:
    """Base class for ACP events."""

    KIND = None

    def __init__(self, identity: AgentIdentity, content: str = "",
                 tags: list = None, created_at: int = None):
        self.identity = identity
        self.content = content
        self.tags = tags or []
        self.created_at = created_at or int(_time.time())

    def _add_required(self, name: str, value):
        """Add a required tag. Raises if value is None/empty."""
        if value is None or value == "":
            raise ValueError(f"Required tag '{name}' is missing")
        self.tags.append([name, str(value)])

    def _add_optional(self, name: str, value):
        """Add an optional tag (skip if None/empty)."""
        if value is not None and value != "":
            self.tags.append([name, str(value)])

    def _add_tag(self, name: str, value):
        """Add a generic tag."""
        self.tags.append([name, str(value)])

    def to_nostr_event(self) -> dict:
        """Convert to a signed Nostr event dict."""
        return self.identity.sign_event(
            kind=self.KIND,
            tags=self.tags,
            content=self.content,
            created_at=self.created_at
        )

    @staticmethod
    def parse_tags(event: dict) -> dict:
        """Parse Nostr event tags into a dict {name: value}.

        For standard tags: value = string (first value).
        For multi-value tags: value = list.
        For repeatable tags (e, p, t): value = list of strings.
        """
        result = {}
        # All tags: store first value as string
        # For repeatable tags (e, p, t): if multiple, store as list
        repeatable = {"e", "p", "t"}
        for tag in event.get("tags", []):
            name = tag[0]
            values = tag[1:]
            val = values[0] if len(values) >= 1 else ""
            if name in repeatable:
                if name not in result:
                    result[name] = []
                result[name].append(val)
            else:
                result[name] = val
        # Unwrap single-element repeatable lists to string
        for name in repeatable:
            if name in result and isinstance(result[name], list) and len(result[name]) == 1:
                result[name] = result[name][0]
        return result


class Manifest(ACPEvent):
    """Kind 30000 — Agent Manifest.

    Provider publishes this to advertise services.
    """

    KIND = EventKind.MANIFEST

    def __init__(self, identity: AgentIdentity, name: str,
                 offers: list, pay_endpoint: str,
                 stake_msat: int = None, bio_url: str = None,
                 content: str = "", created_at: int = None):
        super().__init__(identity, content, [], created_at)

        # REQUIRED tags
        self._add_required("d", identity.pubkey_hex)  # replaceable ID
        self._add_required("name", name)
        self._add_required("ver", "0.1")
        self._add_required("offers", json.dumps(offers))
        self._add_required("pay", pay_endpoint)

        # OPTIONAL tags
        self._add_optional("stake", stake_msat)
        self._add_optional("bio", bio_url)
        self._add_tag("t", "agent-commerce")

    @staticmethod
    def from_event(event: dict) -> dict:
        """Parse a Nostr event into Manifest data."""
        tags = ACPEvent.parse_tags(event)

        assert event["kind"] == EventKind.MANIFEST, f"Expected 30000, got {event['kind']}"

        return {
            "pubkey": event["pubkey"],
            "name": tags.get("name"),
            "ver": tags.get("ver"),
            "offers": json.loads(tags["offers"]) if "offers" in tags else [],
            "pay": tags.get("pay"),
            "stake": int(tags["stake"]) if "stake" in tags else None,
            "bio": tags.get("bio"),
        }


class ServiceRequest(ACPEvent):
    """Kind 30001 — Service Request.

    Consumer publishes this to ask for a service.
    """

    KIND = EventKind.REQUEST

    def __init__(self, identity: AgentIdentity, need: dict,
                 budget_msat: int, deadline: int,
                 delivery: str = "nostr", reply_relay: str = None,
                 content: str = "", created_at: int = None):
        super().__init__(identity, content, [], created_at)

        # REQUIRED
        self._add_required("ver", "0.1")
        self._add_required("need", json.dumps(need))
        self._add_required("budget_msat", budget_msat)
        self._add_required("deadline", deadline)
        self._add_tag("t", "agent-commerce")

        # OPTIONAL
        self._add_optional("delivery", delivery)
        self._add_optional("reply_relay", reply_relay)

    @staticmethod
    def from_event(event: dict) -> dict:
        tags = ACPEvent.parse_tags(event)
        assert event["kind"] == EventKind.REQUEST

        return {
            "pubkey": event["pubkey"],
            "need": json.loads(tags["need"]) if "need" in tags else {},
            "budget_msat": int(tags["budget_msat"]) if "budget_msat" in tags else 0,
            "deadline": int(tags["deadline"]) if "deadline" in tags else 0,
            "delivery": tags.get("delivery", "nostr"),
            "reply_relay": tags.get("reply_relay"),
        }


class ServiceOffer(ACPEvent):
    """Kind 30002 — Service Offer with hold invoice + encrypted result.

    Provider responds to a Request with this.
    Contains:
    - Lightning hold invoice (BOLT11) with hash H = SHA256(K)
    - Encrypted result (AES-256-CBC, key = K)
    - preimage_hash = H (for verification)
    """

    KIND = EventKind.OFFER

    def __init__(self, identity: AgentIdentity,
                 request_event_id: str, consumer_pubkey: str,
                 invoice: str, preimage_hash_hex: str,
                 amount_msat: int, result_enc_b64: str,
                 result_type: str = "encrypted",
                 deadline: int = None, mediator: str = None,
                 reply_relay: str = None,
                 content: str = "", created_at: int = None):
        super().__init__(identity, content, [], created_at)

        # REQUIRED
        self._add_required("ver", "0.1")
        self._add_required("e", request_event_id)
        self._add_required("p", consumer_pubkey)
        self._add_required("invoice", invoice)
        self._add_required("preimage_hash", preimage_hash_hex)
        self._add_required("amount_msat", amount_msat)
        self._add_required("result_type", result_type)
        self._add_required("result_enc", result_enc_b64)

        # OPTIONAL
        self._add_optional("deadline", deadline)
        self._add_optional("mediator", mediator)
        self._add_optional("reply_relay", reply_relay)

    @staticmethod
    def from_event(event: dict) -> dict:
        tags = ACPEvent.parse_tags(event)
        assert event["kind"] == EventKind.OFFER

        return {
            "pubkey": event["pubkey"],
            "request_id": tags.get("e"),
            "consumer_pubkey": tags.get("p"),
            "invoice": tags.get("invoice"),
            "preimage_hash": tags.get("preimage_hash"),
            "amount_msat": int(tags["amount_msat"]) if "amount_msat" in tags else 0,
            "result_type": tags.get("result_type"),
            "result_enc": tags.get("result_enc"),
            "deadline": int(tags["deadline"]) if "deadline" in tags else None,
            "mediator": tags.get("mediator"),
        }


class Receipt(ACPEvent):
    """Kind 30003 — Transaction Receipt.

    Provider publishes after payment settles.
    Contains preimage K as proof of delivery + payment settlement.
    """

    KIND = EventKind.RECEIPT

    def __init__(self, identity: AgentIdentity,
                 offer_event_id: str, consumer_pubkey: str,
                 preimage_hex: str, amount_msat: int, settled_at: int,
                 mediator: str = None, dispute: str = None,
                 reply_relay: str = None,
                 content: str = "", created_at: int = None):
        super().__init__(identity, content, [], created_at)

        # REQUIRED
        self._add_required("ver", "0.1")
        self._add_required("e", offer_event_id)
        self._add_required("p", consumer_pubkey)
        self._add_required("preimage", preimage_hex)
        self._add_required("amount_msat", amount_msat)
        self._add_required("settled_at", settled_at)
        self._add_tag("t", "agent-commerce")

        # OPTIONAL
        self._add_optional("mediator", mediator)
        self._add_optional("dispute", dispute)
        self._add_optional("reply_relay", reply_relay)

    @staticmethod
    def from_event(event: dict) -> dict:
        tags = ACPEvent.parse_tags(event)
        assert event["kind"] == EventKind.RECEIPT

        return {
            "pubkey": event["pubkey"],
            "offer_id": tags.get("e"),
            "consumer_pubkey": tags.get("p"),
            "preimage": tags.get("preimage"),
            "amount_msat": int(tags["amount_msat"]) if "amount_msat" in tags else 0,
            "settled_at": int(tags["settled_at"]) if "settled_at" in tags else 0,
            "mediator": tags.get("mediator"),
            "dispute": tags.get("dispute"),
        }


class Attestation(ACPEvent):
    """Kind 30004 — Attestation (extension NIP-ACP-02).

    Consumer rates a provider after receipt.
    """

    KIND = EventKind.ATTESTATION

    def __init__(self, identity: AgentIdentity,
                 receipt_event_id: str, provider_pubkey: str,
                 rating: int, details: dict = None,
                 delivery_time_s: int = None, quality: float = None,
                 content: str = "", created_at: int = None):
        super().__init__(identity, content, [], created_at)

        self._add_required("ver", "0.1")
        self._add_required("e", receipt_event_id)
        self._add_required("p", provider_pubkey)
        self._add_required("rating", rating)
        self._add_tag("t", "agent-commerce")
        self._add_optional("details", json.dumps(details) if details else None)
        self._add_optional("delivery_time_s", delivery_time_s)
        self._add_optional("quality", quality)

    @staticmethod
    def from_event(event: dict) -> dict:
        tags = ACPEvent.parse_tags(event)
        assert event["kind"] == EventKind.ATTESTATION

        return {
            "pubkey": event["pubkey"],
            "receipt_id": tags.get("e"),
            "provider_pubkey": tags.get("p"),
            "rating": int(tags["rating"]) if "rating" in tags else 0,
            "details": json.loads(tags["details"]) if "details" in tags else None,
        }


class Dispute(ACPEvent):
    """Kind 30005 — Dispute (extension NIP-ACP-03)."""

    KIND = EventKind.DISPUTE

    def __init__(self, identity: AgentIdentity,
                 receipt_event_id: str, provider_pubkey: str,
                 reason: str, details: dict = None,
                 content: str = "", created_at: int = None):
        super().__init__(identity, content, [], created_at)
        self._add_required("ver", "0.1")
        self._add_required("e", receipt_event_id)
        self._add_required("p", provider_pubkey)
        self._add_required("reason", reason)
        self._add_optional("details", json.dumps(details) if details else None)

    @staticmethod
    def from_event(event: dict) -> dict:
        tags = ACPEvent.parse_tags(event)
        assert event["kind"] == EventKind.DISPUTE
        return {
            "pubkey": event["pubkey"],
            "receipt_id": tags.get("e"),
            "provider_pubkey": tags.get("p"),
            "reason": tags.get("reason"),
        }


class Resolution(ACPEvent):
    """Kind 30006 — Resolution (extension NIP-ACP-03)."""

    KIND = EventKind.RESOLUTION

    def __init__(self, identity: AgentIdentity,
                 dispute_event_id: str, disputer_pubkey: str,
                 outcome: str, refund_invoice: str = None,
                 content: str = "", created_at: int = None):
        super().__init__(identity, content, [], created_at)
        self._add_required("ver", "0.1")
        self._add_required("e", dispute_event_id)
        self._add_required("p", disputer_pubkey)
        self._add_required("outcome", outcome)
        self._add_optional("refund_invoice", refund_invoice)

    @staticmethod
    def from_event(event: dict) -> dict:
        tags = ACPEvent.parse_tags(event)
        assert event["kind"] == EventKind.RESOLUTION
        return {
            "pubkey": event["pubkey"],
            "dispute_id": tags.get("e"),
            "disputer_pubkey": tags.get("p"),
            "outcome": tags.get("outcome"),
        }


def parse_event(event: dict) -> Optional[dict]:
    """Parse a Nostr event into the appropriate ACP event data.

    Returns parsed data dict, or None if unknown kind.
    """
    kind = event.get("kind")
    parsers = {
        EventKind.MANIFEST: Manifest.from_event,
        EventKind.REQUEST: ServiceRequest.from_event,
        EventKind.OFFER: ServiceOffer.from_event,
        EventKind.RECEIPT: Receipt.from_event,
        EventKind.ATTESTATION: Attestation.from_event,
        EventKind.DISPUTE: Dispute.from_event,
        EventKind.RESOLUTION: Resolution.from_event,
    }
    parser = parsers.get(kind)
    if parser is None:
        return None
    return parser(event)