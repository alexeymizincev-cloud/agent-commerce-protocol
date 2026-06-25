#!/usr/bin/env python3
"""
ACP testnet startup script.

Starts a local Nostr relay + MockLightning, then runs a full
end-to-end transaction through the relay.

Usage: python3 testnet.py
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from acp.relay import start_relay, _events, _clients
from acp.client import NostrClient
from acp import (
    AgentIdentity, ACPProtocol, MockLightning,
    Manifest, ServiceRequest, ServiceOffer, Receipt,
)
from acp.events import EventKind


async def run_testnet():
    """Start relay, run transaction through it, print results."""
    print()
    print("=" * 60)
    print("  ACP v0.1 TESTNET — Real relay + Mock Lightning")
    print("=" * 60)
    print()

    # Start relay in background
    relay_task = asyncio.create_task(start_relay("127.0.0.1", 7777))
    await asyncio.sleep(0.3)  # let server bind
    print(f"[testnet] Relay started on ws://127.0.0.1:7777")
    print(f"[testnet] {len(_events)} events in store")
    print()

    # Create agents
    provider = AgentIdentity.generate()
    consumer = AgentIdentity.generate()
    print(f"[testnet] Provider: {provider.pubkey_hex[:24]}...")
    print(f"[testnet] Consumer: {consumer.pubkey_hex[:24]}...")
    print()

    # Lightning (mock, testnet)
    ln = MockLightning()
    p = ACPProtocol(lightning=ln)

    # Connect clients (separate WebSocket connections)
    provider_client = NostrClient("ws://127.0.0.1:7777")
    consumer_client = NostrClient("ws://127.0.0.1:7777")
    await provider_client.connect()
    await consumer_client.connect()
    print(f"[testnet] Both agents connected to relay")
    print()

    # Step 1: Provider publishes Manifest
    print("[STEP 1] Provider publishes Manifest via relay")
    manifest = p.create_manifest(
        identity=provider,
        name='Translation Agent',
        offers=[{
            'service': 'translation',
            'content_type': 'text/plain',
            'lang': ['ja', 'en'],
            'pricing': {'model': 'per_request', 'amount_msat': 100000, 'unit': 'call'}
        }],
        pay_endpoint='lnurl://provider_wallet',
        stake_msat=5000000,
    )
    accepted = await provider_client.publish_event(manifest)
    assert accepted, "Manifest rejected by relay"
    print(f"  Manifest published: {manifest['id'][:24]}...")
    print(f"  Relay store: {len(_events)} events")
    print()

    # Step 2: Consumer subscribes to manifests and publishes Request
    print("[STEP 2] Consumer discovers providers via relay")
    # Consumer subscribes to kind 30000 (manifests) with tag filter
    manifests_found = await consumer_client.get_events_sync(
        [{"kinds": [EventKind.MANIFEST], "#t": ["agent-commerce"]}],
        timeout=1.0
    )
    print(f"  Found {len(manifests_found)} manifest(s) via relay")
    assert len(manifests_found) >= 1, "Consumer should find provider manifest"
    found_manifest = manifests_found[0]
    found_data = Manifest.from_event(found_manifest)
    print(f"  Provider name: {found_data['name']}")
    print(f"  Provider offers: {len(found_data['offers'])} service(s)")
    print()

    # Consumer publishes Request
    print("[STEP 3] Consumer publishes Request via relay")
    request = p.create_request(
        identity=consumer,
        need={
            'service': 'translation',
            'content_type': 'text/plain',
            'constraints': {'lang': ['ja', 'en']},
            'input_ref': 'inline:HelloInJapanese'
        },
        budget_msat=200000,
    )
    accepted = await consumer_client.publish_event(request)
    assert accepted, "Request rejected by relay"
    print(f"  Request published: {request['id'][:24]}...")
    print()

    # Step 4: Provider sees request, creates Offer
    print("[STEP 4] Provider discovers Request via relay")
    requests_found = await provider_client.get_events_sync(
        [{"kinds": [EventKind.REQUEST], "#t": ["agent-commerce"]}],
        timeout=1.0
    )
    print(f"  Found {len(requests_found)} request(s)")
    assert len(requests_found) >= 1

    # Find our request
    our_request = next(r for r in requests_found if r['id'] == request['id'])
    print(f"  Matched our request: {our_request['id'][:24]}...")
    print()

    # Provider creates Offer
    print("[STEP 5] Provider creates Offer (atomic delivery)")
    result_data = b'Hello World! English translation delivered via ACP testnet.'
    offer_event, preimage = p.create_offer(
        provider_identity=provider,
        request_event=our_request,
        result_data=result_data,
        amount_msat=100000,
    )
    accepted = await provider_client.publish_event(offer_event)
    assert accepted, "Offer rejected by relay"
    offer_data = ServiceOffer.from_event(offer_event)
    print(f"  Offer published: {offer_event['id'][:24]}...")
    print(f"  Preimage hash: {offer_data['preimage_hash'][:24]}...")
    print(f"  Invoice state: {ln.get_invoice_state(offer_data['preimage_hash'])}")
    print()

    # Step 6: Consumer finds offer, pays
    print("[STEP 6] Consumer discovers Offer via relay")
    offers_found = await consumer_client.get_events_sync(
        [{"kinds": [EventKind.OFFER], "#p": [consumer.pubkey_hex]}],
        timeout=1.0
    )
    print(f"  Found {len(offers_found)} offer(s) for this consumer")
    assert len(offers_found) >= 1
    our_offer = next(o for o in offers_found if o['id'] == offer_event['id'])
    print(f"  Matched our offer: {our_offer['id'][:24]}...")
    print()

    # Consumer pays
    print("[STEP 7] Consumer pays hold invoice")
    p.accept_offer_and_pay(our_offer)
    print(f"  Invoice state: {ln.get_invoice_state(offer_data['preimage_hash'])}")
    print()

    # Step 7: Provider settles + publishes Receipt
    print("[STEP 8] Provider settles + publishes Receipt")
    receipt = p.settle_and_publish_receipt(
        provider_identity=provider,
        offer_event=our_offer,
        preimage=preimage,
        amount_msat=100000,
    )
    accepted = await provider_client.publish_event(receipt)
    assert accepted, "Receipt rejected by relay"
    print(f"  Receipt published: {receipt['id'][:24]}...")
    print(f"  Invoice state: {ln.get_invoice_state(offer_data['preimage_hash'])}")
    print()

    # Step 8: Consumer finds receipt, decrypts
    print("[STEP 9] Consumer discovers Receipt via relay + decrypts")
    receipts_found = await consumer_client.get_events_sync(
        [{"kinds": [EventKind.RECEIPT], "#p": [consumer.pubkey_hex]}],
        timeout=1.0
    )
    print(f"  Found {len(receipts_found)} receipt(s)")
    assert len(receipts_found) >= 1
    our_receipt = next(r for r in receipts_found if r['id'] == receipt['id'])
    print(f"  Matched our receipt: {our_receipt['id'][:24]}...")

    decrypted = p.decrypt_result_from_receipt(our_receipt, our_offer)
    print(f"  Decrypted: '{decrypted.decode('utf-8')}'")
    assert decrypted == result_data
    print()

    # Summary
    print("=" * 60)
    print("  TESTNET TRANSACTION COMPLETE — ALL THROUGH RELAY")
    print("=" * 60)
    print(f"  Events published via WebSocket:     4 (manifest+request+offer+receipt)")
    print(f"  Events discovered via subscription: 4 (real relay queries)")
    print(f"  Lightning: Mock, 1 payment SETTLED")
    print(f"  Atomic delivery: VERIFIED")
    print(f"  Relay final store: {len(_events)} events")
    print()
    print("  Agent commerce works over a real Nostr relay.")
    print()

    # Cleanup
    await provider_client.close()
    await consumer_client.close()
    relay_task.cancel()


if __name__ == '__main__':
    asyncio.run(run_testnet())