"""
ACP — Agent Commerce Protocol SDK
v0.1 — reference implementation

Core: 4 event types + 1 atomic transaction flow.
Nostr identity + Lightning hold-invoice atomic delivery.
"""

from .identity import AgentIdentity, generate_keypair
from .events import (
    Manifest, ServiceRequest, ServiceOffer, Receipt,
    Attestation, Dispute, Resolution,
    EventKind, parse_event,
)
from .crypto import (
    generate_preimage, hash_preimage,
    encrypt_result, decrypt_result,
    encrypt_result_b64, decrypt_result_b64,
    verify_preimage, verify_receipt,
)
from .protocol import ACPProtocol, MockLightning

__version__ = "0.1.0"
__all__ = [
    "AgentIdentity",
    "generate_keypair",
    "Manifest", "ServiceRequest", "ServiceOffer", "Receipt",
    "Attestation", "Dispute", "Resolution",
    "EventKind", "parse_event",
    "generate_preimage", "hash_preimage",
    "encrypt_result", "decrypt_result",
    "encrypt_result_b64", "decrypt_result_b64",
    "verify_preimage", "verify_receipt",
    "ACPProtocol", "MockLightning",
    "__version__",
]
