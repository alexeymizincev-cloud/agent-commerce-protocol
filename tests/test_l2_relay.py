"""
L2: RELAY TESTS — full transaction through real WebSocket Nostr relay.
Tests publish, discovery via relay queries, end-to-end atomic delivery.
"""
import asyncio
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from acp.relay import start_relay, _events
from acp.client import NostrClient
from acp import (AgentIdentity, ACPProtocol, MockLightning, Manifest,
                 ServiceRequest, ServiceOffer, Receipt)
from acp.events import EventKind


@pytest.fixture
async def relay():
    """Start a test relay on a unique port with clean store."""
    from acp.relay import _events
    _events.clear()  # reset relay store between tests
    port = 7800 + int(os.getpid() % 100) + hash(id(_events)) % 50
    task = asyncio.create_task(start_relay('127.0.0.1', port))
    await asyncio.sleep(0.3)
    yield port, task
    task.cancel()
    _events.clear()


class TestRelayTransaction:
    """Full transaction through real WebSocket relay."""

    @pytest.mark.asyncio
    async def test_full_transaction_via_relay(self, relay):
        """Complete ACP transaction published and discovered via relay."""
        port, task = relay

        provider = AgentIdentity.generate()
        consumer = AgentIdentity.generate()
        ln = MockLightning()
        p = ACPProtocol(lightning=ln)

        pc = NostrClient(f'ws://127.0.0.1:{port}')
        cc = NostrClient(f'ws://127.0.0.1:{port}')
        await pc.connect()
        await cc.connect()

        # 1. Publish manifest
        manifest = p.create_manifest(
            identity=provider, name='TestService',
            offers=[{'service':'test','content_type':'text/plain',
                     'pricing':{'model':'per_request','amount_msat':100000,'unit':'call'}}],
            pay_endpoint='lnurl://test')
        ok = await pc.publish_event(manifest)
        assert ok

        # 2. Discover manifest
        found = await cc.get_events(
            [{'kinds': [EventKind.MANIFEST], '#t': ['agent-commerce']}],
            timeout=2.0
        )
        assert len(found) >= 1
        assert found[0]['id'] == manifest['id']

        # 3. Publish request
        request = p.create_request(
            identity=consumer,
            need={'service':'test','content_type':'text/plain'},
            budget_msat=200000)
        ok = await cc.publish_event(request)
        assert ok

        # 4. Discover request
        found = await pc.get_events(
            [{'kinds': [EventKind.REQUEST], '#t': ['agent-commerce']}],
            timeout=2.0
        )
        assert len(found) >= 1
        our_request = next(r for r in found if r['id'] == request['id'])

        # 5. Create offer
        result_data = b'Test result via relay'
        offer, preimage = p.create_offer(
            provider_identity=provider, request_event=our_request,
            result_data=result_data, amount_msat=100000)
        ok = await pc.publish_event(offer)
        assert ok

        # 6. Discover offer
        found = await cc.get_events(
            [{'kinds': [EventKind.OFFER], '#p': [consumer.pubkey_hex]}],
            timeout=2.0
        )
        assert len(found) >= 1
        our_offer = next(o for o in found if o['id'] == offer['id'])

        # 7. Pay + settle
        p.accept_offer_and_pay(our_offer)
        receipt = p.settle_and_publish_receipt(
            provider_identity=provider, offer_event=our_offer,
            preimage=preimage, amount_msat=100000)
        ok = await pc.publish_event(receipt)
        assert ok

        # 8. Discover receipt
        found = await cc.get_events(
            [{'kinds': [EventKind.RECEIPT], '#p': [consumer.pubkey_hex]}],
            timeout=2.0
        )
        assert len(found) >= 1
        our_receipt = next(r for r in found if r['id'] == receipt['id'])

        # 9. Decrypt
        decrypted = p.decrypt_result_from_receipt(our_receipt, our_offer)
        assert decrypted == result_data

        await pc.close()
        await cc.close()

    @pytest.mark.asyncio
    async def test_discovery_fail_empty_relay(self, relay):
        """Discovery on empty relay returns 0 events."""
        port, task = relay
        c = NostrClient(f'ws://127.0.0.1:{port}')
        await c.connect()

        found = await c.get_events([{'kinds': [30000]}], timeout=1.0)
        assert len(found) == 0

        await c.close()

    @pytest.mark.asyncio
    async def test_tag_filtering_via_relay(self, relay):
        """Tag-based discovery (t:agent-commerce) works through relay."""
        port, task = relay
        c = NostrClient(f'ws://127.0.0.1:{port}')
        await c.connect()

        # Publish event with tag
        ev1 = {'id':'ev1','pubkey':'a'*64,'created_at':1719500000,'kind':30000,
               'tags':[['t','agent-commerce'],['name','Test1']],'content':'','sig':''}
        await c.publish_event(ev1)

        # Publish event WITHOUT tag
        ev2 = {'id':'ev2','pubkey':'b'*64,'created_at':1719500001,'kind':30000,
               'tags':[['t','other-tag'],['name','Test2']],'content':'','sig':''}
        await c.publish_event(ev2)

        # Query with tag filter
        found = await c.get_events([{'kinds':[30000],'#t':['agent-commerce']}], timeout=1.0)
        assert len(found) == 1
        assert found[0]['id'] == 'ev1'

        await c.close()