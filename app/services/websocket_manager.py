from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.connections: dict[int, list[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.connections.setdefault(user_id, []).append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        sockets = self.connections.get(user_id, [])
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets:
            self.connections.pop(user_id, None)

    async def send_user(self, user_id: int, payload: dict):
        dead: list[WebSocket] = []
        for websocket in self.connections.get(user_id, []):
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(user_id, websocket)


manager = ConnectionManager()
