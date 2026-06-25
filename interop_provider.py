#!/usr/bin/env python3
"""
ACP Interop: Python provider + TS consumer across real relay.

Run this first, then in another terminal:
  cd acp-ts && npx tsx interop_consumer.ts
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from acp.relay import start_relay, _events
from acp.client import NostrClient
from acp import (
    AgentIdentity, ACPProtocol, MockLightning,
    ServiceRequest, ServiceOffer, Receipt,
)
from acp.events import EventKind


async def run_provider():
    print("=== PYTHON PROVIDER — Interop with TS Consumer ===")
    print()

    relay_task = asyncio.create_task(start_relay("127.0.0.1", 7777))
    await asyncio.sleep(0.3)
    print("[PY] Relay started on ws://127.0.0.1:7777")

    provider = AgentIdentity.generate()
    ln = MockLightning()
    p = ACPProtocol(lightning=ln)
    pc = NostrClient("ws://127.0.0.1:7777")
    await pc.connect()

    # Publish manifest
    manifest = p.create_manifest(
        identity=provider,
        name="Python Translation Agent",
        offers=[{
            "service": "translation",
            "content_type": "text/plain",
            "lang": ["ja", "en"],
            "pricing": {"model": "per_request", "amount_msat": 100000, "unit": "call"}
        }],
        pay_endpoint="lnurl://python_wallet",
        stake_msat=5000000,
    )
    await pc.publish_event(manifest)
    print(f"[PY] Manifest published: {manifest['id'][:24]}...")
    print(f"[PY] Provider pubkey: {provider.pubkey_hex}")
    print()

    # Wait for TS consumer request
    print("[PY] Waiting for TS consumer request (30s timeout)...")
    found_request = None
    for i in range(60):  # 60x2s = 120s timeout
        requests = await pc.get_events(
            [{"kinds": [EventKind.REQUEST], "#t": ["agent-commerce"]}],
            timeout=2.0
        )
        # Find one NOT from ourselves
        for r in requests:
            if r["pubkey"] != provider.pubkey_hex:
                found_request = r
                break
        if found_request:
            break
        await asyncio.sleep(1)

    if not found_request:
        print("[PY] No request from TS consumer (timeout)")
        await pc.close()
        relay_task.cancel()
        return

    req_data = ServiceRequest.from_event(found_request)
    consumer_pubkey = req_data["pubkey"]
    print(f"[PY] Received request from: {consumer_pubkey[:24]}...")
    print(f"[PY] Service: {req_data['need'].get('service')}")
    print()

    # Create offer with atomic delivery
    result_data = b"Hello TS Consumer! This is the English translation from Python Provider."
    offer, preimage = p.create_offer(
        provider_identity=provider,
        request_event=found_request,
        result_data=result_data,
        amount_msat=100000,
    )
    await pc.publish_event(offer)
    offer_data = ServiceOffer.from_event(offer)
    print(f"[PY] Offer published: {offer['id'][:24]}...")
    print(f"[PY] Preimage K: {preimage.hex()[:24]}...")
    print()

    # Wait and auto-pay (mock)
    print("[PY] Waiting 3s then auto-paying (mock)...")
    await asyncio.sleep(8)
    ln.pay_hold_invoice(
        invoice_hash_hex=offer_data["preimage_hash"],
        consumer=consumer_pubkey,
    )
    print(f"[PY] Invoice state: {ln.get_invoice_state(offer_data['preimage_hash'])}")
    print()

    # Settle + publish receipt
    receipt = p.settle_and_publish_receipt(
        provider_identity=provider,
        offer_event=offer,
        preimage=preimage,
        amount_msat=100000,
    )
    await pc.publish_event(receipt)
    print(f"[PY] Receipt published: {receipt['id'][:24]}...")
    print(f"[PY] Preimage K revealed")
    print()

    # Wait for TS consumer to decrypt
    print("[PY] Waiting 5s for TS consumer to decrypt...")
    await asyncio.sleep(15)

    print("[PY] Python provider done.")
    print("[PY] INTEROP TEST: if TS consumer printed success → v3 PASSED")
    await pc.close()
    relay_task.cancel()


if __name__ == "__main__":
    asyncio.run(run_provider())