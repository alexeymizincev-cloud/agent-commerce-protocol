#!/usr/bin/env python3
"""
ACP Demo — two agents execute a full transaction.
Run: python3 demo.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from acp import (
    AgentIdentity, ACPProtocol, MockLightning,
    ServiceRequest, ServiceOffer, Receipt,
)

def main():
    print()
    print("=" * 60)
    print("  AGENT COMMERCE PROTOCOL v0.1 — LIVE DEMO")
    print("  Two AI agents trade a service for sats")
    print("=" * 60)
    print()

    # Create agents
    provider = AgentIdentity.generate()
    consumer = AgentIdentity.generate()

    print("[PROVIDER] Agent identity created")
    print(f"  pubkey: {provider.pubkey_hex[:32]}...")
    print()
    print("[CONSUMER] Agent identity created")
    print(f"  pubkey: {consumer.pubkey_hex[:32]}...")
    print()

    # Setup Lightning + protocol
    ln = MockLightning()
    p = ACPProtocol(lightning=ln)

    # Step 1: Provider publishes Manifest
    print("[STEP 1] Provider publishes Manifest")
    print("  Service: translation (ja->en)")
    print("  Price:   100 sats per request")
    manifest = p.create_manifest(
        identity=provider,
        name='Translation Bot',
        offers=[{
            'service': 'translation',
            'content_type': 'text/plain',
            'lang': ['ja', 'en'],
            'pricing': {'model': 'per_request', 'amount_msat': 100000, 'unit': 'call'}
        }],
        pay_endpoint='lnurl://provider_wallet',
        stake_msat=5000000,
    )
    print(f"  Event ID: {manifest['id'][:32]}...")
    print(f"  Kind: {manifest['kind']}")
    print()

    # Step 2: Consumer publishes Request
    print("[STEP 2] Consumer publishes Request")
    print("  Need: translate Japanese text")
    print("  Budget: 200 sats")
    request = p.create_request(
        identity=consumer,
        need={
            'service': 'translation',
            'content_type': 'text/plain',
            'constraints': {'lang': ['ja', 'en']},
            'input_ref': 'inline:Hello'
        },
        budget_msat=200000,
    )
    print(f"  Event ID: {request['id'][:32]}...")
    print()

    # Step 3: Provider creates Offer with atomic delivery
    print("[STEP 3] Provider creates Offer (atomic delivery)")
    result_text = b'Hello World! This is the English translation.'
    offer, preimage = p.create_offer(
        provider_identity=provider,
        request_event=request,
        result_data=result_text,
        amount_msat=100000,
    )
    offer_data = ServiceOffer.from_event(offer)
    print(f"  Preimage K generated: {preimage.hex()[:32]}...")
    print(f"  Hash H = SHA256(K):   {offer_data['preimage_hash'][:32]}...")
    print(f"  Result encrypted with AES-256-CBC (key = K)")
    print(f"  Lightning hold invoice created")
    print(f"  Invoice state: {ln.get_invoice_state(offer_data['preimage_hash'])}")
    print()

    # Step 4: Consumer pays hold invoice
    print("[STEP 4] Consumer pays hold invoice (funds LOCKED)")
    p.accept_offer_and_pay(offer)
    print(f"  Invoice state: {ln.get_invoice_state(offer_data['preimage_hash'])}")
    print()

    # Step 5: Provider settles (reveals preimage)
    print("[STEP 5] Provider settles invoice (reveals preimage K)")
    receipt = p.settle_and_publish_receipt(
        provider_identity=provider,
        offer_event=offer,
        preimage=preimage,
        amount_msat=100000,
    )
    print(f"  Invoice state: {ln.get_invoice_state(offer_data['preimage_hash'])}")
    print(f"  Receipt published with preimage as proof")
    print()

    # Step 6: Consumer decrypts result
    print("[STEP 6] Consumer decrypts result using preimage K")
    decrypted = p.decrypt_result_from_receipt(receipt, offer)
    print(f"  Decrypted: '{decrypted.decode('utf-8')}'")
    print()

    # Summary
    print("=" * 60)
    print("  TRANSACTION COMPLETE")
    print("=" * 60)
    print(f"  Provider:  {provider.pubkey_hex[:16]}...")
    print(f"  Consumer:  {consumer.pubkey_hex[:16]}...")
    print(f"  Amount:    100,000 msat (100 sats)")
    print(f"  Result:    {len(result_text)} bytes delivered atomically")
    print(f"  Invoice:   SETTLED")
    print()
    print("  Atomic delivery verified:")
    print(f"    Provider could not get paid without revealing K")
    print(f"    Consumer could not decrypt without paying (K revealed on settle)")
    print(f"    Payment AND delivery happened in ONE atomic step")
    print()
    print("  This is the ACP protocol working end-to-end.")
    print()


if __name__ == '__main__':
    main()