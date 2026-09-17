"""Server package for AI-Arena controller.

This package provides communication infrastructure between the AI-Arena controller
(Python backend) and the display/spectator web frontend (React / WebSockets).

Key Modules & Classes:
----------------------
- `Server`: High-level all-in-one controller server. Provides:
    - Dedicated schema methods (`send_state`, `send_round`, `send_response`, etc.)
    - Dual runtime modes: Synchronous background thread mode (for blocking scripts)
      and native Asynchronous mode (`async`/`await`).
    - Bidirectional messaging: Callbacks via `@server.on_message` and a thread-safe
      queue via `server.get_message(block=...)` and `server.has_messages()`.
- `WebSocketServer`: Lower-level asynchronous WebSocket server wrapping `websockets`.
- `ServerStats`: Dataclass containing operational server statistics and metrics.

Quick Example:
--------------
```python
from server import Server

server = Server(host="0.0.0.0", port=8765)
server.start_background()

# Send structured packet to frontend
server.send_state("qwen", "thinking")

# Read incoming commands if any
if server.has_messages():
    msg = server.get_message(block=False)
    print("Received:", msg)

server.stop_background()
```
"""

from server.server import Server
from server.ws_server import (
    ConnectHandler,
    DisconnectHandler,
    MessageHandler,
    ServerStats,
    WebSocketServer,
)

__all__ = [
    "Server",
    "WebSocketServer",
    "ServerStats",
    "MessageHandler",
    "ConnectHandler",
    "DisconnectHandler",
]

