#!/usr/bin/env python3
"""Debug testnet: find the hang point."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from acp.relay import start_relay, _events
from acp.client import NostrClient
from acp import (AgentIdentity, ACPProtocol, MockLightning, Manifest,
                 ServiceRequest, ServiceOffer, Receipt)
from acp.events import EventKind


async def test():
    relay_task = asyncio.create_task(start_relay('127.0.0.1', 7786))
    await asyncio.sleep(0.3)

    provider = AgentIdentity.generate()
    consumer = AgentIdentity.generate()
    ln = MockLightning()
    p = ACPProtocol(lightning=ln)

    pc = NostrClient('ws://127.0.0.1:7786')
    cc = NostrClient('ws://127.0.0.1:7786')
    await pc.connect()
    await cc.connect()
    print('1. Connected')

    manifest = p.create_manifest(
        identity=provider, name='Translator',
        offers=[{'service':'translation','content_type':'text/plain',
                 'lang':['ja','en'],
                 'pricing':{'model':'per_request','amount_msat':100000,'unit':'call'}}],
        pay_endpoint='lnurl://provider_wallet', stake_msat=5000000)
    await pc.publish_event(manifest)
    print('2. Manifest published')

    manifests = await cc.get_events([{'kinds':[EventKind.MANIFEST],'#t':['agent-commerce']}], timeout=2.0)
    print(f'3. Found manifests: {len(manifests)}')

    request = p.create_request(
        identity=consumer,
        need={'service':'translation','content_type':'text/plain',
              'constraints':{'lang':['ja','en']},'input_ref':'inline:Hello'},
        budget_msat=200000)
    await cc.publish_event(request)
    print('4. Request published')

    requests = await pc.get_events([{'kinds':[EventKind.REQUEST],'#t':['agent-commerce']}], timeout=2.0)
    print(f'5. Found requests: {len(requests)}')
    our_request = next(r for r in requests if r['id'] == request['id'])

    result_data = b'Hello World! Translation via ACP testnet.'
    offer, preimage = p.create_offer(
        provider_identity=provider, request_event=our_request,
        result_data=result_data, amount_msat=100000)
    await pc.publish_event(offer)
    print('6. Offer published')

    offers = await cc.get_events([{'kinds':[EventKind.OFFER],'#p':[consumer.pubkey_hex]}], timeout=2.0)
    print(f'7. Found offers: {len(offers)}')
    our_offer = next(o for o in offers if o['id'] == offer['id'])

    p.accept_offer_and_pay(our_offer)
    print('8. Paid (LOCKED)')

    receipt = p.settle_and_publish_receipt(
        provider_identity=provider, offer_event=our_offer,
        preimage=preimage, amount_msat=100000)
    await pc.publish_event(receipt)
    print('9. Receipt published')

    receipts = await cc.get_events([{'kinds':[EventKind.RECEIPT],'#p':[consumer.pubkey_hex]}], timeout=2.0)
    print(f'10. Found receipts: {len(receipts)}')

    our_receipt = next(r for r in receipts if r['id'] == receipt['id'])
    decrypted = p.decrypt_result_from_receipt(our_receipt, our_offer)
    print(f'11. Decrypted: {decrypted.decode()}')

    await pc.close()
    await cc.close()
    relay_task.cancel()
    print('ALL 11 STEPS PASSED!')


if __name__ == '__main__':
    asyncio.run(test())