"""
L1: FLOW TESTS — end-to-end transaction scenarios.
Tests: happy path + edge cases (failures, timeouts, concurrency).
"""
import pytest
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from acp import (
    AgentIdentity, Manifest, ServiceRequest, ServiceOffer, Receipt,
    ACPProtocol, MockLightning,
    generate_preimage, hash_preimage,
    encrypt_result_b64, decrypt_result_b64,
    verify_preimage, verify_receipt,
)


class TestHappyPath:
    """Full successful transaction flow."""

    def test_happy_path_translation(self):
        """Provider offers translation, consumer buys, result correct."""
        provider = AgentIdentity.generate()
        consumer = AgentIdentity.generate()
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)

        # Manifest
        manifest = p.create_manifest(
            identity=provider, name='Translator',
            offers=[{'service':'translation','content_type':'text/plain',
                     'lang':['ja','en'],
                     'pricing':{'model':'per_request','amount_msat':100000,'unit':'call'}}],
            pay_endpoint='lnurl://wallet'
        )
        assert not ACPProtocol.validate_manifest(manifest)

        # Request
        request = p.create_request(
            identity=consumer,
            need={'service':'translation','content_type':'text/plain',
                  'constraints':{'lang':['ja','en']}},
            budget_msat=200000
        )

        # Offer with atomic delivery
        result = b'Hello World translated text'
        offer, preimage = p.create_offer(
            provider_identity=provider, request_event=request,
            result_data=result, amount_msat=100000
        )
        assert not ACPProtocol.validate_offer(offer, request)

        # Consumer pays
        p.accept_offer_and_pay(offer)

        # Provider settles
        receipt = p.settle_and_publish_receipt(
            provider_identity=provider, offer_event=offer,
            preimage=preimage, amount_msat=100000
        )
        assert not ACPProtocol.validate_receipt(receipt, offer)

        # Consumer decrypts
        decrypted = p.decrypt_result_from_receipt(receipt, offer)
        assert decrypted == result

    def test_happy_path_data_fetch(self):
        """Provider offers data fetch with larger result."""
        provider = AgentIdentity.generate()
        consumer = AgentIdentity.generate()
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)

        request = p.create_request(
            identity=consumer,
            need={'service':'data-fetch','content_type':'application/json',
                  'input_ref':'url:https://api.example.com/data'},
            budget_msat=50000
        )

        result = b'{"price": 42000, "volume": 1500000, "timestamp": 1719500000}'
        offer, preimage = p.create_offer(
            provider_identity=provider, request_event=request,
            result_data=result, amount_msat=50000
        )

        p.accept_offer_and_pay(offer)
        receipt = p.settle_and_publish_receipt(
            provider_identity=provider, offer_event=offer,
            preimage=preimage, amount_msat=50000
        )
        decrypted = p.decrypt_result_from_receipt(receipt, offer)
        assert decrypted == result

    def test_happy_path_computation(self):
        """Provider offers computation service."""
        provider = AgentIdentity.generate()
        consumer = AgentIdentity.generate()
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)

        request = p.create_request(
            identity=consumer,
            need={'service':'computation','content_type':'application/octet-stream',
                  'input_ref':'inline:base64data'},
            budget_msat=500000
        )

        result = b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f'
        offer, preimage = p.create_offer(
            provider_identity=provider, request_event=request,
            result_data=result, amount_msat=500000
        )

        p.accept_offer_and_pay(offer)
        receipt = p.settle_and_publish_receipt(
            provider_identity=provider, offer_event=offer,
            preimage=preimage, amount_msat=500000
        )
        decrypted = p.decrypt_result_from_receipt(receipt, offer)
        assert decrypted == result


class TestEdgeCases:
    """Edge cases and failure scenarios."""

    def test_provider_does_not_settle(self):
        """Provider creates offer but doesn't settle → hold expires, consumer gets refund."""
        provider = AgentIdentity.generate()
        consumer = AgentIdentity.generate()
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)

        request = p.create_request(
            identity=consumer, need={'service':'x'}, budget_msat=100
        )
        offer, preimage = p.create_offer(
            provider_identity=provider, request_event=request,
            result_data=b'test', amount_msat=100
        )

        # Consumer pays
        p.accept_offer_and_pay(offer)

        # Provider does NOT settle → expire
        offer_data = ServiceOffer.from_event(offer)
        ln.cancel_hold_invoice(offer_data['preimage_hash'])

        inv_state = ln.get_invoice_state(offer_data['preimage_hash'])
        assert inv_state == 'CANCELLED'
        # Consumer lost nothing — funds returned

    def test_consumer_does_not_pay(self):
        """Consumer doesn't pay → provider never settles → encrypted result useless."""
        provider = AgentIdentity.generate()
        consumer = AgentIdentity.generate()
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)

        request = p.create_request(
            identity=consumer, need={'service':'x'}, budget_msat=100
        )
        offer, preimage = p.create_offer(
            provider_identity=provider, request_event=request,
            result_data=b'secret result', amount_msat=100
        )

        # Consumer does NOT pay
        offer_data = ServiceOffer.from_event(offer)
        inv_state = ln.get_invoice_state(offer_data['preimage_hash'])
        assert inv_state == 'CREATED'
        # Result is encrypted, consumer has no preimage → cannot decrypt

    def test_wrong_preimage_settle_fails(self):
        """Provider tries to settle with wrong preimage → Lightning rejects."""
        provider = AgentIdentity.generate()
        consumer = AgentIdentity.generate()
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)

        request = p.create_request(
            identity=consumer, need={'service':'x'}, budget_msat=100
        )
        offer, preimage = p.create_offer(
            provider_identity=provider, request_event=request,
            result_data=b'test', amount_msat=100
        )

        p.accept_offer_and_pay(offer)

        # Provider tries to settle with WRONG preimage
        wrong_preimage = b'\xff' * 32
        with pytest.raises(ValueError, match="Preimage hash mismatch"):
            offer_data = ServiceOffer.from_event(offer)
            ln.settle_hold_invoice(
                offer_data['preimage_hash'], wrong_preimage,
                provider.pubkey_hex
            )

    def test_offer_exceeds_budget(self):
        """Offer price > request budget → consumer should reject."""
        provider = AgentIdentity.generate()
        consumer = AgentIdentity.generate()
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)

        request = p.create_request(
            identity=consumer, need={'service':'x'}, budget_msat=100
        )
        # Provider offers at 200, budget is 100
        offer, _ = p.create_offer(
            provider_identity=provider, request_event=request,
            result_data=b'test', amount_msat=200
        )

        errors = ACPProtocol.validate_offer(offer, request)
        assert any('budget' in e for e in errors)

    def test_concurrent_buyers(self):
        """Two consumers pay same provider for different offers."""
        provider = AgentIdentity.generate()
        consumer1 = AgentIdentity.generate()
        consumer2 = AgentIdentity.generate()
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)

        # Two separate requests
        req1 = p.create_request(identity=consumer1, need={'service':'x'}, budget_msat=100)
        req2 = p.create_request(identity=consumer2, need={'service':'y'}, budget_msat=200)

        # Provider responds to both
        offer1, preimage1 = p.create_offer(
            provider_identity=provider, request_event=req1,
            result_data=b'result1', amount_msat=100
        )
        offer2, preimage2 = p.create_offer(
            provider_identity=provider, request_event=req2,
            result_data=b'result2', amount_msat=200
        )

        # Both consumers pay
        p.accept_offer_and_pay(offer1)
        p.accept_offer_and_pay(offer2)

        # Both settle
        r1 = p.settle_and_publish_receipt(provider, offer1, preimage1, 100)
        r2 = p.settle_and_publish_receipt(provider, offer2, preimage2, 200)

        # Both decrypt correctly
        d1 = p.decrypt_result_from_receipt(r1, offer1)
        d2 = p.decrypt_result_from_receipt(r2, offer2)
        assert d1 == b'result1'
        assert d2 == b'result2'

    def test_receipt_preimage_mismatch_detected(self):
        """Receipt with wrong preimage → validation fails."""
        provider = AgentIdentity.generate()
        consumer = AgentIdentity.generate()
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)

        request = p.create_request(
            identity=consumer, need={'service':'x'}, budget_msat=100
        )
        offer, preimage = p.create_offer(
            provider_identity=provider, request_event=request,
            result_data=b'test', amount_msat=100
        )

        p.accept_offer_and_pay(offer)
        receipt = p.settle_and_publish_receipt(
            provider, offer, preimage, 100
        )

        # Tamper with receipt preimage
        receipt['tags'] = [[k, v] if k != 'preimage' else [k, 'ff'*32]
                          for k, v in (t[:1] + t[1:] for t in receipt['tags'])]

        errors = ACPProtocol.validate_receipt(receipt, offer)
        assert any('mismatch' in e.lower() for e in errors)

    def test_decrypt_with_wrong_key_fails(self):
        """Decrypting result with wrong preimage produces garbage or fails."""
        from Crypto.Util.Padding import unpad
        from Crypto.Cipher import AES
        import base64

        result = b'secret data'
        K = generate_preimage()
        enc = encrypt_result_b64(result, K)

        wrong_K = b'\x00' * 32
        with pytest.raises(Exception):
            decrypt_result_b64(enc, wrong_K)  # should fail (padding error)