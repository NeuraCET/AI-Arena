"""Interactive and automated WebSocket test client for AI-Arena.

This script acts as a test client (simulating a display frontend, operator control panel,
or another agent) connecting to the WebSocket server (`ws://localhost:8765`).

Features:
1. Interactive CLI menu to send predefined test packets (`state`, `round`, `response`,
   `complete`, `error`, `custom control/start command`).
2. Concurrent listener thread printing any server broadcast messages in real-time.
3. Automated batch send mode (`--batch`).

Usage:
    uv run python test/test-client.py                 # Interactive terminal menu
    uv run python test/test-client.py --batch         # Fire sequence of sample packets
    uv run python test/test-client.py --url ws://localhost:8765
"""

import asyncio
import json
import sys
import threading
from typing import Any

from websockets.asyncio.client import ClientConnection, connect


# Sample packet templates matching packet.md schema
SAMPLE_PACKETS: dict[str, dict[str, Any]] = {
    "1": {
        "name": "State: Qwen Thinking",
        "packet": {
            "type": "state",
            "agent": "qwen",
            "data": {"status": "thinking"},
        },
    },
    "2": {
        "name": "State: Gemma Speaking",
        "packet": {
            "type": "state",
            "agent": "gemma",
            "data": {"status": "speaking"},
        },
    },
    "3": {
        "name": "Round: Round 1, Arg 1/4",
        "packet": {
            "type": "round",
            "agent": "moderator",
            "data": {
                "argument-count": {"current": 1, "total": 4},
                "round": {"current": 1, "total": 3},
            },
        },
    },
    "4": {
        "name": "Response: Qwen speech",
        "packet": {
            "type": "response",
            "agent": "qwen",
            "data": {"response": "Artificial intelligence will not replace humans, but empower them!"},
        },
    },
    "5": {
        "name": "Response: Gemma roast counter",
        "packet": {
            "type": "response",
            "agent": "gemma",
            "data": {"response": "That sounds like wishful thinking wrapped in a buzzword salad!"},
        },
    },
    "6": {
        "name": "Complete: Turn complete",
        "packet": {
            "type": "complete",
            "agent": "qwen",
            "data": {"complete": True},
        },
    },
    "7": {
        "name": "Error: Timeout warning",
        "packet": {
            "type": "error",
            "agent": "gemma",
            "data": {"error": "Model response took too long (>30s)"},
        },
    },
    "8": {
        "name": "Control: Start Debate",
        "packet": {
            "type": "control",
            "action": "start_debate",
            "topic": "Should AI have human rights?",
        },
    },
}


class TestClient:
    """Manages test client connection, sending packets, and printing incoming broadcasts."""

    def __init__(self, uri: str = "ws://127.0.0.1:8765") -> None:
        self.uri = uri
        self.ws: ClientConnection | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    async def _listen_loop(self) -> None:
        """Continuously print incoming broadcast messages from server."""
        try:
            assert self.ws is not None
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    print(f"\n[<-- RECV Broadcast] {json.dumps(data, indent=2)}")
                except json.JSONDecodeError:
                    print(f"\n[<-- RECV Raw] {message}")
                print("\nEnter choice (1-8, c, b, q) > ", end="", flush=True)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not self._stop_event.is_set():
                print(f"\n[Client Listener Error]: {e}")

    def start(self) -> bool:
        """Establish connection and start background listening thread."""
        self.loop = asyncio.new_event_loop()

        ready_event = threading.Event()
        connect_error: list[Exception] = []

        def _runner():
            assert self.loop is not None
            asyncio.set_event_loop(self.loop)

            async def _connect():
                try:
                    self.ws = await connect(self.uri)
                    ready_event.set()
                    await self._listen_loop()
                except Exception as ex:
                    connect_error.append(ex)
                    ready_event.set()

            self.loop.run_until_complete(_connect())

        self._thread = threading.Thread(target=_runner, daemon=True, name="WSClientThread")
        self._thread.start()

        ready_event.wait(timeout=5.0)

        if connect_error:
            print(f"[Error] Failed to connect to {self.uri}: {connect_error[0]}")
            return False

        if self.ws is None:
            print(f"[Error] Connection timed out to {self.uri}")
            return False

        print(f"[Client] Connected to {self.uri}")
        return True

    def send(self, packet: dict[str, Any]) -> None:
        """Send a packet synchronously to the connected server."""
        if self.ws is None or self.loop is None:
            print("[Error] Client is not connected.")
            return

        payload = json.dumps(packet)
        print(f"\n[--> SEND Packet]: {payload}")
        asyncio.run_coroutine_threadsafe(self.ws.send(payload), self.loop)

    def close(self) -> None:
        """Gracefully disconnect and terminate listening thread."""
        self._stop_event.set()
        if self.ws is not None and self.loop is not None:
            asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        print("[Client] Disconnected.")


def print_menu():
    print("\n" + "=" * 50)
    print("AI-Arena WebSocket Test Client Menu")
    print("=" * 50)
    for key, item in SAMPLE_PACKETS.items():
        print(f" [{key}] {item['name']}")
    print(" [c] Send Custom JSON packet")
    print(" [b] Send Batch sequence (1 through 8)")
    print(" [q] Quit")
    print("=" * 50)


def interactive_mode(client: TestClient):
    print_menu()
    while True:
        try:
            choice = input("\nEnter choice (1-8, c, b, q) > ").strip().lower()
            if choice == "q":
                break
            elif choice in SAMPLE_PACKETS:
                client.send(SAMPLE_PACKETS[choice]["packet"])
            elif choice == "b":
                print("\n[Batch] Sending all sample packets...")
                for key in sorted(SAMPLE_PACKETS.keys()):
                    client.send(SAMPLE_PACKETS[key]["packet"])
                    import time
                    time.sleep(0.3)
            elif choice == "c":
                raw = input("Enter raw JSON payload: ").strip()
                try:
                    custom_packet = json.loads(raw)
                    client.send(custom_packet)
                except json.JSONDecodeError as err:
                    print(f"[Invalid JSON]: {err}")
            else:
                print("Unknown option. Choose 1-8, c, b, or q.")
        except (KeyboardInterrupt, EOFError):
            break


def main():
    uri = "ws://127.0.0.1:8765"
    if "--url" in sys.argv:
        idx = sys.argv.index("--url")
        if idx + 1 < len(sys.argv):
            uri = sys.argv[idx + 1]

    batch_mode = "--batch" in sys.argv

    client = TestClient(uri=uri)
    if not client.start():
        sys.exit(1)

    try:
        if batch_mode:
            print("[Batch Mode] Sending all sample schema packets...")
            import time
            for key in sorted(SAMPLE_PACKETS.keys()):
                client.send(SAMPLE_PACKETS[key]["packet"])
                time.sleep(0.3)
            time.sleep(1.0)
        else:
            interactive_mode(client)
    finally:
        client.close()


if __name__ == "__main__":
    main()
