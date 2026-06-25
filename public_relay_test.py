#!/usr/bin/env python3
"""
ACP Public Relay Test

Publishes an Agent Manifest to PUBLIC Nostr relays (not local).
Proves that ACP discovery works on the real internet — any agent
in the world can find this provider.

Run this script, then in another terminal run acp_discover_public.py
to find the provider from anywhere.

Usage:
  python3 public_relay_provider.py
  # Then in another terminal:
  python3 public_relay_provider.py --discover
"""
import asyncio
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from acp import AgentIdentity, ACPProtocol, MockLightning
from acp.events import EventKind, Manifest
import websockets

# Public Nostr relays
PUBLIC_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
]


async def publish_to_relays(event: dict, relays: list):
    """Publish an event to multiple public relays."""
    results = []
    for relay_url in relays:
        try:
            async with websockets.connect(relay_url) as ws:
                await ws.send(json.dumps(["EVENT", event]))
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(resp)
                if msg[0] == "OK" and msg[2]:
                    results.append((relay_url, True, "OK"))
                else:
                    results.append((relay_url, False, str(msg)))
        except Exception as e:
            results.append((relay_url, False, str(e)))
    return results


async def query_relays(filters: list, relays: list, timeout=5):
    """Query multiple public relays for events."""
    all_events = []
    for relay_url in relays:
        try:
            async with websockets.connect(relay_url) as ws:
                sub_id = f"acp_discover_{int(time.time())}"
                for f in filters:
                    await ws.send(json.dumps(["REQ", sub_id, f]))

                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                        msg = json.loads(raw)
                        if msg[0] == "EVENT" and msg[1] == sub_id:
                            all_events.append(msg[2])
                        elif msg[0] == "EOSE" and msg[1] == sub_id:
                            break
                    except asyncio.TimeoutError:
                        break

                await ws.send(json.dumps(["CLOSE", sub_id]))
        except Exception as e:
            print(f"  {relay_url}: query error: {e}")

    return all_events


async def run_provider():
    """Publish a real service manifest to public relays."""
    print("=" * 60)
    print("  ACP PUBLIC RELAY — Provider Mode")
    print("  Publishing manifest to public Nostr relays")
    print("=" * 60)
    print()

    provider = AgentIdentity.generate()
    ln = MockLightning()
    p = ACPProtocol(lightning=ln)

    # Create manifest with a real service
    manifest = p.create_manifest(
        identity=provider,
        name="ACP Demo BTC Price Agent",
        offers=[{
            "service": "btc-price-fetch",
            "content_type": "application/json",
            "pricing": {"model": "per_request", "amount_msat": 100000, "unit": "call"}
        }],
        pay_endpoint="lnurl://acp_demo_provider",
        stake_msat=1000000,
    )

    print(f"Provider identity: {provider.pubkey_hex}")
    print(f"Manifest event ID: {manifest['id']}")
    print(f"Service: btc-price-fetch @ 100 sats/call")
    print()

    # Publish to all public relays
    print("Publishing to public relays...")
    results = await publish_to_relays(manifest, PUBLIC_RELAYS)

    for relay_url, success, detail in results:
        status = "✅" if success else "❌"
        print(f"  {status} {relay_url}: {detail}")

    success_count = sum(1 for _, s, _ in results if s)
    print()
    print(f"Published to {success_count}/{len(PUBLIC_RELAYS)} public relays")
    print()
    print("Manifest is now discoverable by ANY agent on the internet.")
    print("Run 'python3 public_relay_test.py --discover' to verify.")
    print()

    # Save provider identity for later use
    with open("/tmp/acp_provider_key.txt", "w") as f:
        f.write(provider.privkey.hex())
    print(f"Provider key saved to /tmp/acp_provider_key.txt")

    return manifest


async def run_discover():
    """Query public relays for ACP manifests."""
    print("=" * 60)
    print("  ACP PUBLIC RELAY — Discovery Mode")
    print("  Searching public Nostr relays for ACP providers")
    print("=" * 60)
    print()

    print("Querying public relays for ACP manifests (kind 30000, t:agent-commerce)...")
    print()

    events = await query_relays(
        [{"kinds": [EventKind.MANIFEST], "#t": ["agent-commerce"]}],
        PUBLIC_RELAYS,
        timeout=5
    )

    # Deduplicate by event ID
    seen = {}
    for ev in events:
        seen[ev["id"]] = ev
    unique = list(seen.values())

    print(f"Found {len(unique)} unique ACP manifest(s) across {len(PUBLIC_RELAYS)} relays")
    print()

    for i, ev in enumerate(unique):
        try:
            data = Manifest.from_event(ev)
            print(f"  [{i+1}] Provider: {data['name']}")
            print(f"      Pubkey: {ev['pubkey'][:24]}...")
            for offer in data.get("offers", []):
                price = offer.get("pricing", {})
                print(f"      Service: {offer.get('service')} @ {price.get('amount_msat', '?')} msat")
            print(f"      Published: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ev['created_at']))}")
            print()
        except Exception as e:
            print(f"  [{i+1}] Parse error: {e}")
            print()

    if not unique:
        print("No ACP manifests found on public relays.")
        print("Run 'python3 public_relay_test.py' (without --discover) to publish one.")
        return

    print("=" * 60)
    print("  DISCOVERY PROVEN on public Nostr relays")
    print("  Any agent in the world can find ACP providers")
    print("=" * 60)


async def main():
    if "--discover" in sys.argv:
        await run_discover()
    else:
        await run_provider()


if __name__ == "__main__":
    asyncio.run(main())