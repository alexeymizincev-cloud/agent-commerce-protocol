"""
Nostr client for ACP agents.

Connects to a relay, publishes events, subscribes to events.
Used by provider and consumer agents to communicate over the relay.
"""
import asyncio
import json
import websockets
from typing import Optional, Callable


class NostrClient:
    """Minimal Nostr WebSocket client for ACP agents."""

    def __init__(self, relay_url: str = "ws://127.0.0.1:7777"):
        self.relay_url = relay_url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.subscriptions = {}  # sub_id -> callback
        self._running = False

    async def connect(self):
        """Connect to the relay."""
        self.ws = await websockets.connect(self.relay_url)

    async def close(self):
        """Close the connection."""
        if self.ws:
            await self.ws.close()
        self.ws = None

    async def publish_event(self, event: dict) -> bool:
        """Publish an event to the relay. Returns True if accepted."""
        if not self.ws:
            await self.connect()
        await self.ws.send(json.dumps(["EVENT", event]))

        # Wait for OK response
        while True:
            raw = await self.ws.recv()
            msg = json.loads(raw)
            if msg[0] == "OK":
                return msg[2]  # True/False
            elif msg[0] == "NOTICE":
                print(f"[relay NOTICE] {msg[1]}")

    async def subscribe(self, sub_id: str, filters: list,
                         callback: Callable = None):
        """Subscribe to events matching filters. Callback called per event."""
        if not self.ws:
            await self.connect()
        self.subscriptions[sub_id] = callback

        for filt in filters:
            await self.ws.send(json.dumps(["REQ", sub_id, filt]))

    async def unsubscribe(self, sub_id: str):
        """Close a subscription."""
        if sub_id in self.subscriptions:
            await self.ws.send(json.dumps(["CLOSE", sub_id]))
            del self.subscriptions[sub_id]

    async def listen(self):
        """Listen for incoming messages and dispatch to callbacks."""
        if not self.ws:
            await self.connect()
        self._running = True

        while self._running:
            try:
                raw = await self.ws.recv()
                msg = json.loads(raw)

                if msg[0] == "EVENT":
                    sub_id = msg[1]
                    event = msg[2]
                    cb = self.subscriptions.get(sub_id)
                    if cb:
                        await cb(event) if asyncio.iscoroutinefunction(cb) else cb(event)
                elif msg[0] == "EOSE":
                    pass  # End of stored events
                elif msg[0] == "NOTICE":
                    print(f"[relay NOTICE] {msg[1]}")
            except websockets.exceptions.ConnectionClosed:
                print("[client] Connection closed")
                self._running = False
            except Exception as e:
                print(f"[client] Error: {e}")

    def stop(self):
        """Stop listening."""
        self._running = False

    # ─── SYNCHRONOUS WRAPPERS (for testing) ───────────────────

    def publish_event_sync(self, event: dict) -> bool:
        """Synchronous wrapper for publish_event."""
        return asyncio.get_event_loop().run_until_complete(
            self.publish_event(event)
        )

    async def get_events(self, filters: list, timeout: float = 2.0) -> list:
        """Async fetch of events matching filters. Returns list of events."""
        if not self.ws:
            await self.connect()
        collected = []
        sub_id = 'fetch_temp'
        
        for filt in filters:
            await self.ws.send(json.dumps(['REQ', sub_id, filt]))
        
        # Read until EOSE
        while True:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
                msg = json.loads(raw)
                if msg[0] == 'EVENT':
                    collected.append(msg[2])
                elif msg[0] == 'EOSE':
                    break
            except asyncio.TimeoutError:
                break
        
        await self.ws.send(json.dumps(['CLOSE', sub_id]))
        return collected

