"""WebSocket 连接管理：区分电脑端和手机端"""
from typing import List
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.desktop: List[WebSocket] = []
        self.mobile: List[WebSocket] = []

    async def connect(self, ws: WebSocket, role: str):
        await ws.accept()
        target = self.desktop if role == "desktop" else self.mobile
        target.append(ws)

    def disconnect(self, ws: WebSocket, role: str):
        target = self.desktop if role == "desktop" else self.mobile
        if ws in target:
            target.remove(ws)

    async def send_to_desktop(self, msg: dict):
        await self._safe_send(self.desktop, msg)

    async def send_to_mobile(self, msg: dict):
        await self._safe_send(self.mobile, msg)

    async def broadcast(self, msg: dict):
        await self._safe_send(self.desktop, msg)
        await self._safe_send(self.mobile, msg)

    async def _safe_send(self, clients: List[WebSocket], msg: dict):
        for ws in clients[:]:
            try:
                await ws.send_json(msg)
            except Exception:
                if ws in clients:
                    clients.remove(ws)


manager = ConnectionManager()