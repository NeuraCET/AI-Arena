"""All-in-one Server class for AI-Arena controller.

This module provides a unified `Server` class that wraps `WebSocketServer`
and exposes simple, high-level methods tailored to the AI-Arena packet schema
(`state`, `round`, `response`, `complete`, `error`).

It supports both:
1. **Synchronous Mode** (Background thread): Ideal for blocking controller loops
   such as `prototype.py` without requiring async refactoring.
2. **Asynchronous Mode** (`async`/`await`): For modern async pipelines and event loops.

Usage Examples:
---------------
### Example 1: Synchronous Controller / Debate Loop (Recommended for prototype.py)
```python
import time
from server import Server

server = Server(host="0.0.0.0", port=8765)

# Optional: Receive messages from frontend using callback
@server.on_message
def handle_incoming(ws, data):
    print("Frontend sent:", data)

# 1. Start server in a background thread
server.start_background()

try:
    # 2. Check for incoming messages in your loop (queue-based)
    if server.has_messages():
        command = server.get_message(block=False)
        print("Processing queued command:", command)

    # 3. Broadcast high-level schema packets
    server.send_state("qwen", "thinking")

    server.send_round(
        agent="moderator",
        current_round=1,
        total_rounds=3,
        current_argument=1,
        total_arguments=4,
    )

    server.send_response("qwen", "Your logic is flawed!")
    server.send_state("qwen", "speaking")
    time.sleep(2)

    server.send_complete("qwen", True)

finally:
    # 4. Graceful shutdown
    server.stop_background()
```

### Example 2: Asynchronous Controller Loop
```python
import asyncio
from server import Server

async def main():
    server = Server(host="0.0.0.0", port=8765)

    @server.on_message
    async def handle_incoming(ws, data):
        print("Frontend sent:", data)

    # 1. Start server
    await server.start()

    try:
        # 2. Emit packets
        server.send_state("gemma", "thinking")
        server.send_response("gemma", "I disagree completely!")

        # 3. Keep running
        await server.wait_until_stopped()
    finally:
        await server.stop()

if __name__ == "__main__":
    asyncio.run(main())
```
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from typing import Any, Callable, Optional

from server.ws_server import MessageHandler, ServerStats, WebSocketServer

logger = logging.getLogger(__name__)


class Server:
    """All-in-one controller server for AI-Arena.

    Abstracts low-level WebSocket connection management and provides clean,
    expressive methods to broadcast structured packets to frontend displays
    and receive incoming control commands.

    Attributes:
        host (str): Bound host interface.
        port (int): Bound port number.

    Quick Start (Synchronous):
        >>> server = Server()
        >>> server.start_background()
        >>> server.send_state("qwen", "thinking")
        >>> server.send_response("qwen", "Hello Arena!")
        >>> server.stop_background()

    Quick Start (Asynchronous):
        >>> async def run():
        ...     server = Server()
        ...     await server.start()
        ...     server.send_state("gemma", "thinking")
        ...     await server.stop()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        ping_interval: float = 20.0,
        ping_timeout: float = 20.0,
    ) -> None:
        """Initialize the all-in-one Server instance.

        Args:
            host: Interface IP or hostname to bind. Defaults to "0.0.0.0".
            port: Port number to bind. Defaults to 8765.
            ping_interval: Heartbeat interval in seconds. Defaults to 20.0.
            ping_timeout: Heartbeat timeout in seconds. Defaults to 20.0.
        """
        self.host = host
        self.port = port
        self._ws_server = WebSocketServer(
            host=host,
            port=port,
            ping_interval=ping_interval,
            ping_timeout=ping_timeout,
        )

        # Threading support for synchronous controller scripts
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        # Thread-safe queue for synchronous message consumption
        self._sync_queue: queue.Queue[dict[str, Any]] = queue.Queue()

        # Connect low-level receiver to queue and handlers
        self._ws_server.on_message(self._internal_on_message)
        self._custom_message_handlers: list[Callable[..., Any]] = []

    async def _internal_on_message(self, websocket: Any, data: dict[str, Any]) -> None:
        """Internal router pushing to the sync queue and notifying user callbacks."""
        self._sync_queue.put(data)

        for handler in self._custom_message_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(websocket, data)
                else:
                    handler(websocket, data)
            except Exception as e:
                logger.error("Error in message handler: %s", e, exc_info=True)

    # -------------------------------------------------------------------------
    # Properties & Status
    # -------------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Return True if the server is actively running and accepting connections."""
        return self._ws_server.is_running

    @property
    def client_count(self) -> int:
        """Return the count of currently connected WebSocket clients."""
        return self._ws_server.client_count

    def get_stats(self) -> ServerStats:
        """Return snapshot statistics of the server."""
        return self._ws_server.get_stats()

    # -------------------------------------------------------------------------
    # Message Receiving & Event Listeners
    # -------------------------------------------------------------------------

    def on_message(self, handler: Callable[..., Any]) -> Callable[..., Any]:
        """Register a callback for incoming messages.

        Supports BOTH:
          - async callbacks: `async def handle(ws, data)`
          - sync callbacks:  `def handle(ws, data)`

        Args:
            handler: Callable taking `(websocket, message_data)`.
        """
        self._custom_message_handlers.append(handler)
        return handler

    def get_message(self, block: bool = True, timeout: Optional[float] = None) -> Optional[dict[str, Any]]:
        """Retrieve the next received message from the queue in synchronous code.

        Args:
            block: Whether to wait for a message if queue is empty.
            timeout: Maximum seconds to wait if blocking.

        Returns:
            dict with parsed message data, or None if queue is empty / timed out.
        """
        try:
            return self._sync_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None

    def has_messages(self) -> bool:
        """Check if there are unread received messages in the queue."""
        return not self._sync_queue.empty()

    def on_connect(self, handler: Callable[..., Any]) -> Callable[..., Any]:
        """Register a callback `(websocket)` when a client connects."""
        return self._ws_server.on_connect(handler)

    def on_disconnect(self, handler: Callable[..., Any]) -> Callable[..., Any]:
        """Register a callback `(websocket)` when a client disconnects."""
        return self._ws_server.on_disconnect(handler)

    # -------------------------------------------------------------------------
    # Async Lifecycle Methods
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the server asynchronously."""
        await self._ws_server.start()

    async def stop(self) -> None:
        """Stop the server and disconnect all clients asynchronously."""
        await self._ws_server.stop()

    async def wait_until_stopped(self) -> None:
        """Wait until the server stop event is triggered."""
        await self._ws_server.wait_until_stopped()

    async def run_forever(self) -> None:
        """Start server and keep running until explicitly stopped or cancelled."""
        await self._ws_server.run_forever()

    # -------------------------------------------------------------------------
    # Sync / Background Thread Lifecycle (for synchronous scripts like prototype.py)
    # -------------------------------------------------------------------------

    def start_background(self) -> None:
        """Start the server in a managed background thread with its own event loop.

        This allows synchronous scripts to broadcast packets without needing
        to convert their entire pipeline to `async def`.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Server is already running in background thread.")
            return

        self._loop = asyncio.new_event_loop()

        def _runner():
            assert self._loop is not None
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._ws_server.start())
            try:
                self._loop.run_forever()
            finally:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                self._loop.close()

        self._thread = threading.Thread(target=_runner, name="AIServerThread", daemon=True)
        self._thread.start()

        # Wait until server is up and running
        while not self._ws_server.is_running:
            threading.Event().wait(0.02)

        logger.info("Server started in background thread on ws://%s:%d", self.host, self.port)

    def stop_background(self) -> None:
        """Gracefully stop the background server thread."""
        if self._loop is not None and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._ws_server.stop(), self._loop)
            try:
                future.result(timeout=5.0)
            except Exception as e:
                logger.error("Error waiting for background server stop: %s", e)
            finally:
                self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
            self._loop = None

        logger.info("Background server stopped.")

    # -------------------------------------------------------------------------
    # Core Dispatch Helpers
    # -------------------------------------------------------------------------

    async def send_packet(self, packet: dict[str, Any]) -> int:
        """Broadcast a raw packet dictionary to all connected clients asynchronously."""
        return await self._ws_server.broadcast(packet)

    def emit(self, packet: dict[str, Any]) -> int:
        """Send a packet synchronously or asynchronously depending on caller context.

        If running inside an active asyncio event loop, schedules the coroutine.
        If running in synchronous mode with `start_background()`, executes safely via threadsafe call.
        """
        if self._loop is not None and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._ws_server.broadcast(packet), self._loop)
            return future.result()

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._ws_server.broadcast(packet))
            return len(self._ws_server.clients)
        except RuntimeError:
            return asyncio.run(self._ws_server.broadcast(packet))

    # -------------------------------------------------------------------------
    # High-Level Packet Methods (matching packet.md schema)
    # -------------------------------------------------------------------------

    def send_state(self, agent: str, status: str) -> int:
        """Broadcast an agent state update packet.

        Schema:
        {
            "type": "state",
            "agent": "<agent>",
            "data": {
                "status": "<status>"
            }
        }

        Args:
            agent: Agent name (e.g., "qwen", "gemma", "moderator").
            status: Status message/state (e.g., "thinking", "speaking", "idle").
        """
        packet = {
            "type": "state",
            "agent": agent,
            "data": {
                "status": status,
            },
        }
        return self.emit(packet)

    def send_round(
        self,
        agent: str,
        current_round: int,
        total_rounds: int,
        current_argument: int,
        total_arguments: int,
    ) -> int:
        """Broadcast a debate round progress packet.

        Schema:
        {
            "type": "round",
            "agent": "<agent>",
            "data": {
                "argument-count": {
                    "current": <current_argument>,
                    "total": <total_arguments>
                },
                "round": {
                    "current": <current_round>,
                    "total": <total_rounds>
                }
            }
        }

        Args:
            agent: Agent identifier.
            current_round: Current round number.
            total_rounds: Total rounds configured.
            current_argument: Current argument index within the round.
            total_arguments: Total arguments expected per round.
        """
        packet = {
            "type": "round",
            "agent": agent,
            "data": {
                "argument-count": {
                    "current": current_argument,
                    "total": total_arguments,
                },
                "round": {
                    "current": current_round,
                    "total": total_rounds,
                },
            },
        }
        return self.emit(packet)

    def send_response(self, agent: str, response: str) -> int:
        """Broadcast an agent's speech / text response packet.

        Schema:
        {
            "type": "response",
            "agent": "<agent>",
            "data": {
                "response": "<response>"
            }
        }

        Args:
            agent: Agent emitting the response (e.g. "qwen", "gemma").
            response: The generated textual response.
        """
        packet = {
            "type": "response",
            "agent": agent,
            "data": {
                "response": response,
            },
        }
        return self.emit(packet)

    def send_error(self, agent: str, error: str) -> int:
        """Broadcast an error packet to clients.

        Schema:
        {
            "type": "error",
            "agent": "<agent>",
            "data": {
                "error": "<error>"
            }
        }

        Args:
            agent: Source agent or subsystem triggering the error.
            error: Descriptive error message.
        """
        packet = {
            "type": "error",
            "agent": agent,
            "data": {
                "error": error,
            },
        }
        return self.emit(packet)

    def send_complete(self, agent: str, complete: bool | str = True) -> int:
        """Broadcast a completion packet.

        Schema:
        {
            "type": "complete",
            "agent": "<agent>",
            "data": {
                "complete": <complete>
            }
        }

        Args:
            agent: Agent that completed its turn, or "debate" for session end.
            complete: True, or a completion message string.
        """
        packet = {
            "type": "complete",
            "agent": agent,
            "data": {
                "complete": complete,
            },
        }
        return self.emit(packet)
