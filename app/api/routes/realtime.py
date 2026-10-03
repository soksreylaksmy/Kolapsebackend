from jose import JWTError, jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import User
from app.services.websocket_manager import manager

router = APIRouter(tags=["Realtime"])


def websocket_user(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        return None


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    user_id = websocket_user(token)
    if not user_id:
        await websocket.close(code=4401)
        return
    db: Session = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user or not user.is_active:
            await websocket.close(code=4401)
            return
    finally:
        db.close()

    await manager.connect(user_id, websocket)
    try:
        await websocket.send_json({"type": "connected", "message": "KOLAPSE realtime connected"})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
