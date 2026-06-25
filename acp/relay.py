"""
Minimal Nostr relay for ACP local testing.

Implements just enough of NIP-01 to test ACP:
- WebSocket server
- Event submission (EVENT)
- Event subscription (REQ with filters)
- In-memory event storage (no persistence needed for tests)
- Tag-based filtering (for t:agent-commerce discovery)

NOT a production relay. Just enough for local ACP testing.
"""
import asyncio
import json
import websockets
from typing import Set

# Events stored in memory: list of event dicts
_events: list = []
_clients: Set = set()


async def handle_connection(websocket, path=None):
    """Handle a single WebSocket client connection."""
    _clients.add(websocket)
    client_subs = {}  # sub_id -> filter
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send(json.dumps(["NOTICE", "Invalid JSON"]))
                continue

            if not isinstance(msg, list) or len(msg) < 2:
                continue

            msg_type = msg[0]

            if msg_type == "EVENT":
                event = msg[1]
                # Basic validation: has required fields
                if not all(k in event for k in ['id', 'pubkey', 'created_at',
                                                  'kind', 'tags', 'content', 'sig']):
                    await websocket.send(json.dumps(["NOTICE", "Invalid event"]))
                    continue

                # Store event
                _events.append(event)

                # Acknowledge
                await websocket.send(json.dumps(["OK", event["id"], True, ""]))

                # Broadcast to matching subscriptions
                for sub_id, filt in client_subs.items():
                    if event_matches_filter(event, filt):
                        await websocket.send(json.dumps(["EVENT", sub_id, event]))

            elif msg_type == "REQ":
                sub_id = msg[1]
                filt = msg[2] if len(msg) > 2 else {}
                client_subs[sub_id] = filt

                # Send matching stored events
                for event in _events:
                    if event_matches_filter(event, filt):
                        await websocket.send(json.dumps(["EVENT", sub_id, event]))

                # End of stored events
                await websocket.send(json.dumps(["EOSE", sub_id]))

            elif msg_type == "CLOSE":
                sub_id = msg[1]
                client_subs.pop(sub_id, None)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _clients.discard(websocket)


def event_matches_filter(event: dict, filt: dict) -> bool:
    """Check if event matches a Nostr subscription filter."""
    # kinds filter
    if 'kinds' in filt:
        if event['kind'] not in filt['kinds']:
            return False

    # since (created_at >=)
    if 'since' in filt:
        if event['created_at'] < filt['since']:
            return False

    # until (created_at <=)
    if 'until' in filt:
        if event['created_at'] > filt['until']:
            return False

    # #t tag filter (single-letter tags)
    for key in filt:
        if key.startswith('#') and len(key) == 2:
            tag_name = key[1]
            filter_values = filt[key] if isinstance(filt[key], list) else [filt[key]]
            event_values = [t[1] for t in event['tags'] if len(t) >= 2 and t[0] == tag_name]
            if not any(v in event_values for v in filter_values):
                return False

    # authors filter
    if 'authors' in filt:
        if event['pubkey'] not in filt['authors']:
            return False

    # ids filter
    if 'ids' in filt:
        if event['id'] not in filt['ids']:
            return False

    return True


async def start_relay(host="127.0.0.1", port=7777):
    """Start the relay server."""
    print(f"[relay] ACP test relay starting on ws://{host}:{port}")
    async with websockets.serve(handle_connection, host, port):
        await asyncio.Future()  # run forever


def run_relay(host="127.0.0.1", port=7777):
    """Start relay (blocking, for CLI use)."""
    asyncio.run(start_relay(host, port))


if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7777
    run_relay(port=port)