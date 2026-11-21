"""WebSocket connection manager for real-time dashboard events and telemetry."""

import asyncio
import logging
from typing import Any, Dict, List
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts real-time system events."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept an incoming WebSocket connection and register it."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info("WebSocket client connected. Total active: %d", len(self.active_connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a disconnected WebSocket connection."""
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info("WebSocket client disconnected. Total active: %d", len(self.active_connections))

    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket) -> None:
        """Send a direct JSON message to a single connected client."""
        try:
            await websocket.send_json(message)
        except Exception as exc:
            logger.debug("Failed to send personal message to WebSocket client: %s", exc)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast a JSON event message to all currently connected clients."""
        async with self._lock:
            connections = list(self.active_connections)

        dead_connections: List[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except (WebSocketDisconnect, RuntimeError, Exception) as exc:
                logger.debug("Dropping dead WebSocket connection during broadcast: %s", exc)
                dead_connections.append(connection)

        if dead_connections:
            async with self._lock:
                for dead in dead_connections:
                    if dead in self.active_connections:
                        self.active_connections.remove(dead)
