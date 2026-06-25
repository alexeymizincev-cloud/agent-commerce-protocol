"""
Agent identity = Nostr keypair (secp256k1).
Uses pynostr for proper Schnorr (BIP-340) signatures.
Falls back to coincurve + ECDSA for local testing if pynostr unavailable.
"""

import hashlib
import secrets
import json
from typing import Optional

try:
    from pynostr.key import PrivateKey
    HAS_PYNOSTR = True
except ImportError:
    HAS_PYNOSTR = False

try:
    import coincurve
    HAS_COINCURVE = True
except ImportError:
    HAS_COINCURVE = False


def generate_keypair() -> tuple[bytes, bytes]:
    """Generate a Nostr-compatible secp256k1 keypair.

    Returns:
        (private_key_32bytes, public_key_32bytes_xonly)
    """
    if HAS_PYNOSTR:
        pk = PrivateKey()
        return bytes.fromhex(pk.hex()), bytes.fromhex(pk.public_key.hex())
    
    # Fallback
    priv = secrets.token_bytes(32)
    pub = _privkey_to_pubkey(priv)
    return priv, pub


def _privkey_to_pubkey(priv: bytes) -> bytes:
    """Convert 32-byte private key to 32-byte X-only public key (Nostr format)."""
    if HAS_PYNOSTR:
        pk = PrivateKey(hex_string=priv.hex())
        return bytes.fromhex(pk.public_key.hex())
    
    if HAS_COINCURVE:
        pk = coincurve.PrivateKey(priv)
        return pk.public_key.format(compressed=True)[1:33]
    else:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        key = ec.derive_private_key(int.from_bytes(priv,'big'), ec.SECP256K1())
        pub_bytes = key.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        return pub_bytes[1:33]


def pubkey_to_hex(pub: bytes) -> str:
    """Convert 32-byte pubkey to hex string (Nostr format)."""
    return pub.hex()


def hex_to_pubkey(h: str) -> bytes:
    """Convert hex pubkey to 32 bytes."""
    return bytes.fromhex(h)


class NostrEventBuilder:
    """Build and sign Nostr events per NIP-01.

    Uses pynostr for proper Schnorr (BIP-340) signatures when available.
    Falls back to ECDSA for local testing only.
    """

    @staticmethod
    def build_event_dict(
        privkey: bytes,
        pubkey: bytes,
        kind: int,
        tags: list,
        content: str = "",
        created_at: int = None,
    ) -> dict:
        """Build a signed Nostr event dict."""
        import time as _time
        if created_at is None:
            created_at = int(_time.time())

        if HAS_PYNOSTR:
            # Use pynostr for proper Schnorr signatures
            from pynostr.event import Event
            pk = PrivateKey(bytes.fromhex(privkey.hex()))
            ev = Event(
                pubkey=pk.public_key.hex(),
                kind=kind,
                content=content,
                tags=tags,
                created_at=created_at,
            )
            ev.sign(pk.hex())
            return ev.to_dict()

        # Fallback: ECDSA (local testing only, public relays will reject)
        pubkey_hex = pubkey.hex()
        event_template = [0, pubkey_hex, created_at, kind, tags, content]
        serialized = json.dumps(event_template, separators=(',', ':'), ensure_ascii=False)
        msg = hashlib.sha256(serialized.encode('utf-8')).digest()
        sig = _sign_ecdsa(privkey, msg)

        return {
            "id": msg.hex(),
            "pubkey": pubkey_hex,
            "created_at": created_at,
            "kind": kind,
            "tags": tags,
            "content": content,
            "sig": sig.hex(),
        }

    @staticmethod
    def verify_event(event: dict) -> bool:
        """Verify a Nostr event signature."""
        if HAS_PYNOSTR:
            from pynostr.event import Event
            try:
                ev = Event.from_dict(event)
                return ev.verify()
            except Exception:
                return False

        # Fallback: check event ID matches (local testing)
        pubkey_hex = event["pubkey"]
        event_template = [
            0, pubkey_hex, event["created_at"],
            event["kind"], event["tags"], event["content"]
        ]
        serialized = json.dumps(event_template, separators=(',', ':'), ensure_ascii=False)
        msg = hashlib.sha256(serialized.encode('utf-8')).digest()
        return msg.hex() == event["id"]


def _sign_ecdsa(privkey: bytes, msg: bytes) -> bytes:
    """ECDSA sign (fallback for local testing only)."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes
    key = ec.derive_private_key(int.from_bytes(privkey, 'big'), ec.SECP256K1())
    der_sig = key.sign(msg, ec.ECDSA(hashes.SHA256()))
    r, s = _der_to_rs(der_sig)
    return r + s


def _der_to_rs(der_sig: bytes) -> tuple[bytes, bytes]:
    """Convert DER signature to raw r||s (64 bytes)."""
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    r, s = decode_dss_signature(der_sig)
    return r.to_bytes(32, 'big'), s.to_bytes(32, 'big')


class AgentIdentity:
    """An ACP agent identity backed by a Nostr keypair."""

    def __init__(self, privkey: bytes = None, pubkey: bytes = None):
        if privkey is None:
            privkey, pubkey = generate_keypair()
        self.privkey = privkey
        self.pubkey = pubkey
        self.pubkey_hex = pubkey_to_hex(pubkey)

    @classmethod
    def generate(cls) -> "AgentIdentity":
        """Create a new random agent identity."""
        return cls()

    @classmethod
    def from_private_key_hex(cls, hex_key: str) -> "AgentIdentity":
        """Load identity from hex private key."""
        priv = bytes.fromhex(hex_key)
        pub = _privkey_to_pubkey(priv)
        return cls(priv, pub)

    def sign_event(self, kind: int, tags: list, content: str = "",
                   created_at: int = None) -> dict:
        """Create a signed Nostr event."""
        return NostrEventBuilder.build_event_dict(
            self.privkey, self.pubkey, kind, tags, content, created_at
        )

    def verify_event(self, event: dict) -> bool:
        """Verify that an event was signed by this identity."""
        if event.get("pubkey") != self.pubkey_hex:
            return False
        return NostrEventBuilder.verify_event(event)

    def __repr__(self):
        return f"AgentIdentity(pubkey={self.pubkey_hex[:16]}...)"