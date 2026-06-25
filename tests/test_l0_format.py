"""
L0: FORMAT TESTS — validate ACP event format contract.
Tests: required tags present, format correct, parseable.
"""
import pytest
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from acp import (
    AgentIdentity, Manifest, ServiceRequest, ServiceOffer, Receipt,
    Attestation, Dispute, Resolution, EventKind, parse_event,
    ACPProtocol, MockLightning,
)


class TestManifestFormat:
    """Tests for Kind 30000 — Agent Manifest."""

    def test_manifest_has_required_tags(self):
        a = AgentIdentity.generate()
        m = Manifest(
            identity=a, name='TestAgent',
            offers=[{'service':'x','content_type':'text/plain',
                     'pricing':{'model':'per_request','amount_msat':100,'unit':'call'}}],
            pay_endpoint='lnurl://test'
        )
        ev = m.to_nostr_event()
        tags = {t[0]: t[1] for t in ev['tags']}
        assert 'd' in tags
        assert 'name' in tags
        assert 'ver' in tags
        assert 'offers' in tags
        assert 'pay' in tags

    def test_manifest_kind_30000(self):
        a = AgentIdentity.generate()
        m = Manifest(identity=a, name='X',
                     offers=[{'service':'x','content_type':'t',
                              'pricing':{'model':'m','amount_msat':1,'unit':'u'}}],
                     pay_endpoint='lnurl://x')
        ev = m.to_nostr_event()
        assert ev['kind'] == 30000

    def test_manifest_offers_json_valid(self):
        a = AgentIdentity.generate()
        offers = [{'service':'translation','content_type':'text/plain',
                   'pricing':{'model':'per_request','amount_msat':100,'unit':'call'}}]
        m = Manifest(identity=a, name='X', offers=offers, pay_endpoint='lnurl://x')
        ev = m.to_nostr_event()
        tags = {t[0]: t[1] for t in ev['tags']}
        parsed = json.loads(tags['offers'])
        assert isinstance(parsed, list)
        assert parsed[0]['service'] == 'translation'

    def test_manifest_missing_name_raises(self):
        a = AgentIdentity.generate()
        with pytest.raises(ValueError, match="name"):
            Manifest(identity=a, name='', offers=[],
                     pay_endpoint='lnurl://x')

    def test_manifest_missing_pay_raises(self):
        a = AgentIdentity.generate()
        with pytest.raises(ValueError, match="pay"):
            Manifest(identity=a, name='X',
                     offers=[{'service':'x','content_type':'t',
                              'pricing':{'model':'m','amount_msat':1,'unit':'u'}}],
                     pay_endpoint='')

    def test_manifest_custom_pricing_model(self):
        """Custom pricing model with schema_url should be valid."""
        a = AgentIdentity.generate()
        offers = [{'service':'zk-proof','content_type':'application/vnd.zk-proof',
                   'pricing':{'model':'custom','amount_msat':5000,'unit':'proof',
                              'schema_url':'https://example.com/schema.json'}}]
        m = Manifest(identity=a, name='X', offers=offers, pay_endpoint='lnurl://x')
        ev = m.to_nostr_event()
        errors = ACPProtocol.validate_manifest(ev)
        assert not errors, f"Custom pricing should be valid: {errors}"

    def test_manifest_version_tag(self):
        a = AgentIdentity.generate()
        m = Manifest(identity=a, name='X',
                     offers=[{'service':'x','content_type':'t',
                              'pricing':{'model':'m','amount_msat':1,'unit':'u'}}],
                     pay_endpoint='lnurl://x')
        ev = m.to_nostr_event()
        tags = {t[0]: t[1] for t in ev['tags']}
        assert tags['ver'] == '0.1'


class TestRequestFormat:
    """Tests for Kind 30001 — Service Request."""

    def test_request_has_required_tags(self):
        a = AgentIdentity.generate()
        r = ServiceRequest(identity=a, need={'service':'x'},
                          budget_msat=100, deadline=9999999999)
        ev = r.to_nostr_event()
        tags = {t[0]: t[1] for t in ev['tags']}
        assert 'need' in tags
        assert 'budget_msat' in tags
        assert 'deadline' in tags
        assert 'ver' in tags

    def test_request_kind_30001(self):
        a = AgentIdentity.generate()
        r = ServiceRequest(identity=a, need={'service':'x'},
                          budget_msat=100, deadline=9999999999)
        ev = r.to_nostr_event()
        assert ev['kind'] == 30001

    def test_request_need_json_valid(self):
        a = AgentIdentity.generate()
        r = ServiceRequest(identity=a, need={'service':'translation',
                                              'content_type':'text/plain'},
                          budget_msat=100, deadline=9999999999)
        ev = r.to_nostr_event()
        tags = {t[0]: t[1] for t in ev['tags']}
        parsed = json.loads(tags['need'])
        assert parsed['service'] == 'translation'


class TestOfferFormat:
    """Tests for Kind 30002 — Service Offer."""

    def test_offer_has_required_tags(self):
        a = AgentIdentity.generate()
        o = ServiceOffer(
            identity=a, request_event_id='abc', consumer_pubkey='def',
            invoice='lnbc1000n1mock', preimage_hash_hex='a'*64,
            amount_msat=100, result_enc_b64='base64data'
        )
        ev = o.to_nostr_event()
        tags = {t[0]: t[1] for t in ev['tags']}
        assert 'e' in tags
        assert 'p' in tags
        assert 'invoice' in tags
        assert 'preimage_hash' in tags
        assert 'amount_msat' in tags
        assert 'result_enc' in tags

    def test_offer_kind_30002(self):
        a = AgentIdentity.generate()
        o = ServiceOffer(identity=a, request_event_id='x',
                         consumer_pubkey='y', invoice='i',
                         preimage_hash_hex='b'*64, amount_msat=1,
                         result_enc_b64='r')
        ev = o.to_nostr_event()
        assert ev['kind'] == 30002

    def test_offer_preimage_hash_64chars(self):
        """preimage_hash must be 64-char hex (SHA256 = 32 bytes = 64 hex chars)."""
        a = AgentIdentity.generate()
        o = ServiceOffer(identity=a, request_event_id='x',
                         consumer_pubkey='y', invoice='i',
                         preimage_hash_hex='abcd' * 16,  # 64 chars
                         amount_msat=1, result_enc_b64='r')
        ev = o.to_nostr_event()
        errors = ACPProtocol.validate_offer(ev)
        assert not errors


class TestReceiptFormat:
    """Tests for Kind 30003 — Receipt."""

    def test_receipt_has_required_tags(self):
        a = AgentIdentity.generate()
        r = Receipt(identity=a, offer_event_id='x', consumer_pubkey='y',
                    preimage_hex='a'*64, amount_msat=100, settled_at=1234567890)
        ev = r.to_nostr_event()
        tags = {t[0]: t[1] for t in ev['tags']}
        assert 'e' in tags
        assert 'p' in tags
        assert 'preimage' in tags
        assert 'amount_msat' in tags
        assert 'settled_at' in tags

    def test_receipt_kind_30003(self):
        a = AgentIdentity.generate()
        r = Receipt(identity=a, offer_event_id='x', consumer_pubkey='y',
                    preimage_hex='a'*64, amount_msat=1, settled_at=1)
        ev = r.to_nostr_event()
        assert ev['kind'] == 30003


class TestParseEvent:
    """Tests for parse_event dispatcher."""

    def test_parse_unknown_kind_returns_none(self):
        ev = {'kind': 99999, 'tags': [], 'content': '', 'pubkey': 'x', 'id': 'y',
              'created_at': 0, 'sig': ''}
        assert parse_event(ev) is None

    def test_parse_manifest(self):
        a = AgentIdentity.generate()
        m = Manifest(identity=a, name='X',
                     offers=[{'service':'x','content_type':'t',
                              'pricing':{'model':'m','amount_msat':1,'unit':'u'}}],
                     pay_endpoint='lnurl://x')
        ev = m.to_nostr_event()
        parsed = parse_event(ev)
        assert parsed is not None
        assert parsed['name'] == 'X'