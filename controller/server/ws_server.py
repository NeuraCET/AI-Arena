"""Low-level WebSocket server module for AI-Arena controller.

This module provides `WebSocketServer`, a robust, asynchronous server implementation
wrapping Python's `websockets` library. It handles:
- Client connection lifecycle (connection tracking, ping/pong heartbeats, graceful closure).
- Safe JSON message serialization and concurrent broadcasting to multiple connected clients.
- Pruning dead/stale client sockets upon connection drop or send failure.
- Flexible event hook registration for incoming messages, connections, and disconnections.
- Operational runtime telemetry via the `ServerStats` dataclass.

Architecture:
-------------
- `WebSocketServer`: Manages network sockets, concurrent client dispatch, and event hooks.
- `ServerStats`: Immutable-friendly metrics snapshot (uptime, client count, throughput).
- For a higher-level facade with predefined AI-Arena packet schemas (`state`, `round`,
  `response`, etc.) and synchronous background thread support, see `server.server.Server`.

Example:
--------
```python
import asyncio
from server.ws_server import WebSocketServer

async def main():
    server = WebSocketServer(host="0.0.0.0", port=8765)

    @server.on_message
    async def handle_msg(ws, data):
        print("Received from", ws.remote_address, data)
        await server.send_to(ws, {"type": "ack"})

    await server.start()
    await server.broadcast({"type": "ping"})
    await server.wait_until_stopped()

if __name__ == "__main__":
    asyncio.run(main())
```
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Set

import websockets
from websockets.asyncio.server import ServerConnection, serve

# Configure module-level logger
logger = logging.getLogger(__name__)


@dataclass
class ServerStats:
    """Snapshot statistics for the WebSocket server."""

    started_at: Optional[datetime] = None
    is_running: bool = False
    active_connections: int = 0
    total_messages_sent: int = 0
    total_messages_received: int = 0
    total_connections_handled: int = 0
    client_addresses: list[str] = field(default_factory=list)


# Type aliases for event handlers
MessageHandler = Callable[[ServerConnection, dict[str, Any]], Awaitable[None]]
ConnectHandler = Callable[[ServerConnection], Awaitable[None]]
DisconnectHandler = Callable[[ServerConnection], Awaitable[None]]


class WebSocketServer:
    """Manages WebSocket server lifecycle, connections, and message dispatch.

    Attributes:
        host (str): Network interface to bind to (e.g., "0.0.0.0" or "localhost").
        port (int): Port number to listen on.
        clients (Set[ServerConnection]): Set of currently active client connections.
        is_running (bool): Flag indicating if the server is active.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        ping_interval: float = 20.0,
        ping_timeout: float = 20.0,
        close_timeout: float = 10.0,
    ) -> None:
        """Initialize the WebSocket server instance.

        Args:
            host: IP address/hostname to bind. Defaults to "0.0.0.0".
            port: Port to bind. Defaults to 8765.
            ping_interval: Interval in seconds between heartbeat pings sent to clients.
                           Set to None or 0 to disable.
            ping_timeout: Seconds to wait for pong response before timing out a connection.
            close_timeout: Seconds to wait for client to close gracefully during shutdown.
        """
        self.host = host
        self.port = port
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.close_timeout = close_timeout

        self._clients: Set[ServerConnection] = set()
        self._server: Optional[Any] = None
        self._stop_event = asyncio.Event()
        self._is_running = False

        # Metrics tracking
        self._started_at: Optional[datetime] = None
        self._total_sent = 0
        self._total_received = 0
        self._total_connections_handled = 0

        # Optional callbacks for event integration
        self._message_handlers: list[MessageHandler] = []
        self._connect_handlers: list[ConnectHandler] = []
        self._disconnect_handlers: list[DisconnectHandler] = []

    @property
    def is_running(self) -> bool:
        """Return True if the server is currently started and listening."""
        return self._is_running and self._server is not None

    @property
    def client_count(self) -> int:
        """Return the number of connected clients."""
        return len(self._clients)

    @property
    def clients(self) -> Set[ServerConnection]:
        """Return a copy of the active clients set."""
        return set(self._clients)

    def on_message(self, handler: MessageHandler) -> MessageHandler:
        """Decorator or method to register an asynchronous incoming message handler.

        Args:
            handler: Async function taking `(websocket, message_data)`.
        """
        self._message_handlers.append(handler)
        return handler

    def on_connect(self, handler: ConnectHandler) -> ConnectHandler:
        """Decorator or method to register an asynchronous client connection handler.

        Args:
            handler: Async function taking `(websocket)`.
        """
        self._connect_handlers.append(handler)
        return handler

    def on_disconnect(self, handler: DisconnectHandler) -> DisconnectHandler:
        """Decorator or method to register an asynchronous client disconnection handler.

        Args:
            handler: Async function taking `(websocket)`.
        """
        self._disconnect_handlers.append(handler)
        return handler

    def get_stats(self) -> ServerStats:
        """Return current server operational statistics."""
        return ServerStats(
            started_at=self._started_at,
            is_running=self.is_running,
            active_connections=len(self._clients),
            total_messages_sent=self._total_sent,
            total_messages_received=self._total_received,
            total_connections_handled=self._total_connections_handled,
            client_addresses=[
                f"{client.remote_address[0]}:{client.remote_address[1]}"
                for client in self._clients
                if client.remote_address
            ],
        )

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        """Internal connection handler maintaining client session and message loop.

        Args:
            websocket: Incoming WebSocket client connection.
        """
        self._clients.add(websocket)
        self._total_connections_handled += 1
        remote_addr = websocket.remote_address
        logger.info("Client connected from %s (Total active: %d)", remote_addr, len(self._clients))

        # Notify connect hooks
        for hook in self._connect_handlers:
            try:
                await hook(websocket)
            except Exception as e:
                logger.error("Error in connect hook: %s", e, exc_info=True)

        try:
            async for raw_message in websocket:
                self._total_received += 1
                logger.debug("Received raw message from %s: %s", remote_addr, raw_message)

                try:
                    data = (
                        json.loads(raw_message)
                        if isinstance(raw_message, str)
                        else json.loads(raw_message.decode("utf-8"))
                    )
                except json.JSONDecodeError:
                    logger.warning("Received invalid non-JSON payload from %s: %s", remote_addr, raw_message)
                    continue

                for handler in self._message_handlers:
                    try:
                        await handler(websocket, data)
                    except Exception as e:
                        logger.error("Error processing message handler for %s: %s", remote_addr, e, exc_info=True)

        except websockets.exceptions.ConnectionClosedOK:
            logger.debug("Client %s closed connection normally.", remote_addr)
        except websockets.exceptions.ConnectionClosedError as e:
            logger.warning("Client %s connection closed with error: %s", remote_addr, e)
        except Exception as e:
            logger.error("Unexpected error in client session for %s: %s", remote_addr, e, exc_info=True)
        finally:
            self._clients.discard(websocket)
            logger.info("Client disconnected: %s (Remaining active: %d)", remote_addr, len(self._clients))

            for hook in self._disconnect_handlers:
                try:
                    await hook(websocket)
                except Exception as e:
                    logger.error("Error in disconnect hook: %s", e, exc_info=True)

    async def start(self) -> None:
        """Start the WebSocket server and bind to configured host and port.

        Raises:
            RuntimeError: If server is already running.
        """
        if self._is_running:
            logger.warning("WebSocket server is already running on ws://%s:%d", self.host, self.port)
            return

        logger.info("Starting WebSocket server on ws://%s:%d ...", self.host, self.port)
        self._stop_event.clear()

        self._server = await serve(
            self._handle_connection,
            host=self.host,
            port=self.port,
            ping_interval=self.ping_interval,
            ping_timeout=self.ping_timeout,
            close_timeout=self.close_timeout,
        )

        self._is_running = True
        self._started_at = datetime.now(timezone.utc)
        logger.info("WebSocket server started and listening on ws://%s:%d", self.host, self.port)

    async def wait_until_stopped(self) -> None:
        """Maintain server execution by waiting on the stop signal."""
        if not self._is_running:
            return
        await self._stop_event.wait()

    async def run_forever(self) -> None:
        """Convenience method to start server and maintain it until stop() is invoked or cancelled."""
        await self.start()
        try:
            await self.wait_until_stopped()
        finally:
            await self.stop()

    async def broadcast(self, message: dict[str, Any] | str) -> int:
        """Broadcast a message to all currently connected clients.

        Args:
            message: Dictionary to serialize to JSON, or a pre-serialized JSON string.

        Returns:
            int: Number of clients to which the message was successfully dispatched.
        """
        if not self._clients:
            logger.debug("No connected clients to broadcast message.")
            return 0

        payload = message if isinstance(message, str) else json.dumps(message)
        dead_clients: Set[ServerConnection] = set()
        dispatched_count = 0

        # Send to all clients concurrently
        send_tasks = []
        clients_list = list(self._clients)

        for client in clients_list:
            send_tasks.append(client.send(payload))

        results = await asyncio.gather(*send_tasks, return_exceptions=True)

        for client, result in zip(clients_list, results):
            if isinstance(result, Exception):
                logger.warning("Failed to send message to %s: %s", client.remote_address, result)
                dead_clients.add(client)
            else:
                dispatched_count += 1
                self._total_sent += 1

        # Prune disconnected clients encountered during broadcast
        for dead in dead_clients:
            self._clients.discard(dead)

        return dispatched_count

    async def send_to(self, websocket: ServerConnection, message: dict[str, Any] | str) -> bool:
        """Send a message to a specific client.

        Args:
            websocket: Target client connection.
            message: Dictionary to serialize to JSON, or a pre-serialized JSON string.

        Returns:
            bool: True if sent successfully, False otherwise.
        """
        if websocket not in self._clients:
            logger.warning("Cannot send message: Client is not in active clients list.")
            return False

        payload = message if isinstance(message, str) else json.dumps(message)
        try:
            await websocket.send(payload)
            self._total_sent += 1
            return True
        except Exception as e:
            logger.warning("Failed to send message to client %s: %s", websocket.remote_address, e)
            self._clients.discard(websocket)
            return False

    async def stop(self) -> None:
        """Gracefully stop the server, disconnect all clients, and close the listening socket."""
        if not self._is_running:
            return

        logger.info("Shutting down WebSocket server...")
        self._stop_event.set()

        # Disconnect all active clients gracefully
        if self._clients:
            logger.info("Closing %d active client connection(s)...", len(self._clients))
            close_tasks = [
                client.close(code=1000, reason="Server shutting down")
                for client in list(self._clients)
            ]
            await asyncio.gather(*close_tasks, return_exceptions=True)
            self._clients.clear()

        # Close the server listening socket
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        self._is_running = False
        logger.info("WebSocket server stopped cleanly.")
