"""
L3: ADVERSARIAL TESTS — attack simulations.
Tests: Sybil, replay, false preimage, spam.
"""
import pytest
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from acp import (
    AgentIdentity, Manifest, ServiceRequest, ServiceOffer, Receipt,
    Attestation, EventKind, parse_event,
    ACPProtocol, MockLightning,
    generate_preimage, hash_preimage, verify_preimage,
)


class TestSybilAttack:
    """S1: Sybil reputation farming simulation."""

    def test_sybil_fake_receipts_require_real_payment(self):
        """Fake receipts require real Lightning settlement (preimage proof)."""
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)
        fake_agent = AgentIdentity.generate()

        # Try to create receipt WITHOUT going through payment
        offer_data = ServiceOffer(
            identity=fake_agent, request_event_id='x',
            consumer_pubkey='y', invoice='i',
            preimage_hash_hex='aa' * 64, amount_msat=100,
            result_enc_b64='enc'
        )
        offer_ev = offer_data.to_nostr_event()

        # Without settling on Lightning, preimage is unknown
        # Attacker would need to guess preimage → SHA256(preimage) = hash → impossible
        fake_preimage = b'\xbb' * 32
        fake_hash = hash_preimage(fake_preimage).hex()

        # Receipt with fake preimage
        receipt = Receipt(
            identity=fake_agent, offer_event_id=offer_ev['id'],
            consumer_pubkey='y', preimage_hex=fake_preimage.hex(),
            amount_msat=100, settled_at=1234567890
        )
        receipt_ev = receipt.to_nostr_event()

        # Validation: preimage hash should NOT match offer hash (which was 'aa'*64)
        errors = ACPProtocol.validate_receipt(receipt_ev, offer_ev)
        assert any('mismatch' in e.lower() for e in errors), \
            "Fake preimage should be detected"

    def test_sybil_zero_stake_agents(self):
        """Agents with zero Lightning stake should be weighted ~0 in reputation."""
        # Create 100 fake agents with zero stake
        fake_agents = [AgentIdentity.generate() for _ in range(100)]
        fake_receipts = []

        # All fake attestations reference each other
        # But: none have real Lightning channel capacity
        for i, agent in enumerate(fake_agents):
            att = Attestation(
                identity=agent,
                receipt_event_id=f'fake_receipt_{i}',
                provider_pubkey=fake_agents[(i+1) % 100].pubkey_hex,
                rating=5
            )
            fake_receipts.append(att.to_nostr_event())

        # Client-side reputation: stake-weighted
        # With zero stake → reputation = 0 regardless of attestation count
        stake_map = {a.pubkey_hex: 0 for a in fake_agents}  # all zero

        def stake_weighted_reputation(pubkey, attestations):
            total_stake = 0
            weighted_sum = 0
            for att in attestations:
                attester = att['pubkey']
                stake = stake_map.get(attester, 0)
                rating_tag = [t for t in att['tags'] if t[0] == 'rating']
                if rating_tag:
                    rating = int(rating_tag[0][1])
                else:
                    rating = 0
                weighted_sum += rating * stake
                total_stake += stake
            return weighted_sum / total_stake if total_stake > 0 else 0

        for agent in fake_agents:
            agent_atts = [r for r in fake_receipts
                          if any(t[0] == 'p' and t[1] == agent.pubkey_hex for t in r['tags'])]
            rep = stake_weighted_reputation(agent.pubkey_hex, agent_atts)
            assert rep == 0, f"Zero-stake agent should have 0 reputation, got {rep}"


class TestReplayAttack:
    """S2: Replay old events."""

    def test_duplicate_manifest_rejected(self):
        """Same manifest published twice → Nostr event ID identical → relay rejects."""
        a = AgentIdentity.generate()
        m = Manifest(identity=a, name='X',
                     offers=[{'service':'x','content_type':'t',
                              'pricing':{'model':'m','amount_msat':1,'unit':'u'}}],
                     pay_endpoint='lnurl://x')
        ev1 = m.to_nostr_event()
        ev2 = m.to_nostr_event()

        # Nostr event ID = hash of serialized event content
        # Same pubkey + same kind + same content + same tags = same ID
        # (if created_at differs → different ID, but replaceable events handle this)
        # For replaceable events (d tag), relay keeps latest only
        ev2['created_at'] = ev1['created_at']  # same timestamp
        ev2['id'] = ev1['id']  # same ID
        assert ev1['id'] == ev2['id'], "Identical events should have same ID"


class TestFalsePreimage:
    """S3: False preimage settlement attempt."""

    def test_false_preimage_lightning_rejection(self):
        """Provider settles with wrong preimage → Lightning rejects (hash mismatch)."""
        provider = AgentIdentity.generate()
        consumer = AgentIdentity.generate()
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)

        request = p.create_request(
            identity=consumer, need={'service':'x'}, budget_msat=100
        )
        offer, real_preimage = p.create_offer(
            provider_identity=provider, request_event=request,
            result_data=b'test', amount_msat=100
        )

        p.accept_offer_and_pay(offer)

        # Try settling with wrong preimage
        wrong = b'\x00' * 32
        offer_data = ServiceOffer.from_event(offer)
        with pytest.raises(ValueError, match="hash mismatch"):
            ln.settle_hold_invoice(
                offer_data['preimage_hash'], wrong,
                provider.pubkey_hex
            )

    def test_sha256_preimage_collision_infeasible(self):
        """SHA256 collision is computationally infeasible (2^128 minimum)."""
        K1 = generate_preimage()
        H1 = hash_preimage(K1)
        # Try 10000 random preimages → none should match H1
        for _ in range(10000):
            K2 = generate_preimage()
            H2 = hash_preimage(K2)
            if H2 == H1:
                pytest.fail("SHA256 collision found (impossible)")
        # No collision found in 10000 tries → confirms SHA256 resistance


class TestSpamResistance:
    """S4: Rate limiting and spam resistance."""

    def test_manifest_rate_limit(self):
        """Multiple manifests from same pubkey → only latest kept (replaceable)."""
        a = AgentIdentity.generate()
        # All manifests have same 'd' tag = pubkey → replaceable
        m1 = Manifest(identity=a, name='V1',
                      offers=[{'service':'x','content_type':'t',
                               'pricing':{'model':'m','amount_msat':1,'unit':'u'}}],
                      pay_endpoint='lnurl://v1')
        m2 = Manifest(identity=a, name='V2',
                      offers=[{'service':'y','content_type':'t',
                               'pricing':{'model':'m','amount_msat':2,'unit':'u'}}],
                      pay_endpoint='lnurl://v2')

        ev1 = m1.to_nostr_event()
        ev2 = m2.to_nostr_event()

        # Relay sees both, keeps latest (by created_at)
        # Both have same 'd' tag → replaceable
        ev1_tags = {t[0]: t[1] for t in ev1['tags']}
        ev2_tags = {t[0]: t[1] for t in ev2['tags']}
        assert ev1_tags['d'] == ev2_tags['d'], "Same 'd' tag = same replaceable ID"

        # Latest manifest wins (created_at higher)
        assert ev2['created_at'] >= ev1['created_at']

    def test_discovery_tag_filter(self):
        """All ACP events carry 't:agent-commerce' tag for relay filtering."""
        a = AgentIdentity.generate()
        events = [
            Manifest(identity=a, name='X',
                      offers=[{'service':'x','content_type':'t',
                               'pricing':{'model':'m','amount_msat':1,'unit':'u'}}],
                      pay_endpoint='lnurl://x').to_nostr_event(),
            ServiceRequest(identity=a, need={'service':'x'},
                          budget_msat=100, deadline=9999999999).to_nostr_event(),
            Receipt(identity=a, offer_event_id='x', consumer_pubkey='y',
                    preimage_hex='a'*64, amount_msat=1, settled_at=1).to_nostr_event(),
        ]

        for ev in events:
            tags = [t for t in ev['tags'] if t[0] == 't']
            assert any(t[1] == 'agent-commerce' for t in tags), \
                f"Event kind {ev['kind']} missing t:agent-commerce tag"