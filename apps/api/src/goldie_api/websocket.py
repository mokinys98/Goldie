import asyncio
from collections.abc import Mapping

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: Mapping) -> None:
        failed: list[WebSocket] = []
        for connection in list(self._connections):
            try:
                await connection.send_json(dict(message))
            except Exception:
                failed.append(connection)
        for connection in failed:
            await self.disconnect(connection)


manager = ConnectionManager()
