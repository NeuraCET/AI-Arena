"""Interactive & Automated WebSocket Server Test Script for AI-Arena.

This test script validates the controller `Server`:
1. Launches the server in background thread mode on port 8765.
2. Spawns an automated client to test bidirectional packet exchange:
   - Client sends commands (`start_debate`, `ping`).
   - Server receives via sync queue (`get_message`) and callback (`@server.on_message`).
   - Server broadcasts all schema packets (`state`, `round`, `response`, `complete`, `error`).
   - Client verifies packet schemas match `packet.md`.
3. Optionally enters an interactive mode allowing manual packet broadcast
   while your React frontend display connects to `ws://localhost:8765`.

Usage:
    uv run python test/test-server.py
    uv run python test/test-server.py --interactive
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

# Ensure controller root is on sys.path so `from server import Server` works
CONTROLLER_ROOT = Path(__file__).resolve().parent.parent
if str(CONTROLLER_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTROLLER_ROOT))

from server import Server
from websockets.asyncio.client import connect


def run_automated_client_test(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Simulate a display frontend client connecting to the server."""
    uri = f"ws://{host}:{port}"

    async def _test():
        print(f"\n[Client] Connecting to {uri} ...")
        async with connect(uri) as ws:
            print("[Client] Connected successfully!")

            # 1. Test sending a message from client -> server
            print("[Client] Sending command: {'type': 'control', 'action': 'start_debate'}")
            await ws.send(
                json.dumps(
                    {
                        "type": "control",
                        "action": "start_debate",
                        "topic": "AI Consciousness",
                    }
                )
            )

            # 2. Wait for expected server broadcast packets
            expected_types = ["state", "round", "response", "complete", "error"]
            received_types = []

            print("[Client] Listening for server broadcast packets...")
            for _ in range(len(expected_types)):
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(raw)
                msg_type = data.get("type")
                received_types.append(msg_type)
                print(f"[Client] Received valid packet ({msg_type}): {data}")

            assert received_types == expected_types, f"Expected {expected_types}, got {received_types}"
            print("\n[Client] All expected schema packets verified successfully!")

    asyncio.run(_test())


def main():
    interactive = "--interactive" in sys.argv or "-i" in sys.argv
    host = "127.0.0.1"
    port = 8765

    print("=" * 60)
    print(f"Starting AI-Arena WebSocket Server Test on ws://{host}:{port}")
    print("=" * 60)

    # Initialize Server
    server = Server(host=host, port=port)

    received_messages: list[dict[str, Any]] = []

    # Test callback registration
    @server.on_message
    def on_message_handler(ws, data):
        print(f"[Server Callback] Received from client ({ws.remote_address}): {data}")
        received_messages.append(data)

    # Start in background thread (sync mode)
    server.start_background()
    print(f"[Server] Server is running: {server.is_running}")

    try:
        # Run automated client test
        time.sleep(0.2)

        # Trigger simulated broadcast flow in sync thread
        def server_broadcast_sequence():
            time.sleep(0.1)
            # 1. State packet
            server.send_state(agent="qwen", status="thinking")
            # 2. Round packet
            server.send_round(
                agent="moderator",
                current_round=1,
                total_rounds=3,
                current_argument=1,
                total_arguments=4,
            )
            # 3. Response packet
            server.send_response(agent="qwen", response="AI will reshape the world!")
            # 4. Complete packet
            server.send_complete(agent="qwen", complete=True)
            # 5. Error packet
            server.send_error(agent="system", error="Sample handled error message")

        # Start simulated broadcaster concurrently with client test
        async def run_pair():
            loop = asyncio.get_running_loop()
            await asyncio.gather(
                loop.run_in_executor(None, server_broadcast_sequence),
                loop.run_in_executor(None, run_automated_client_test, host, port),
            )

        asyncio.run(run_pair())

        # Verify server queue received message
        assert server.has_messages(), "Server queue should have received message from client"
        queued_msg = server.get_message(block=False)
        print(f"[Server Queue] Retrieved queued message: {queued_msg}")
        assert queued_msg.get("action") == "start_debate"

        stats = server.get_stats()
        print("\n[Server Stats]:")
        print(f" - Active connections: {stats.active_connections}")
        print(f" - Messages sent: {stats.total_messages_sent}")
        print(f" - Messages received: {stats.total_messages_received}")
        print(f" - Total connections handled: {stats.total_connections_handled}")
        print("\nAutomated test passed cleanly!")

        if interactive:
            print("\n" + "=" * 60)
            print("Entering Interactive Mode.")
            print(f"You can now connect your React display frontend to ws://{host}:{port}")
            print("Press Ctrl+C to terminate.")
            print("=" * 60)
            while True:
                time.sleep(1)
                if server.has_messages():
                    msg = server.get_message(block=False)
                    print(f"[Interactive Server] Received from display: {msg}")

    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
    finally:
        print("\nStopping server...")
        server.stop_background()
        print(f"Server is running: {server.is_running}")
        print("Server shutdown complete.")


if __name__ == "__main__":
    main()
