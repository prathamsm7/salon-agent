"""Voice socket. The caller must already be signed in."""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import user_from_token
from app.db.session import SessionLocal
from app.db.store import VoiceDenied, prepare_voice
from app.voice.deepgram_session import DeepgramSalonSession

router = APIRouter()


@router.websocket("/voice")
async def voice(websocket: WebSocket) -> None:
    await websocket.accept()
    token = websocket.query_params.get("token") or ""
    raw_conversation = websocket.query_params.get("conversation_id")
    with SessionLocal() as db:
        user = user_from_token(token, db) if token else None
        user_id = user.id if user else None
        user_name = user.name if user else ""
    if user_id is None:
        await websocket.send_json({"type": "error", "message": "Sign in again to talk with Tara."})
        await websocket.close(code=4401)
        return

    conversation_id = int(raw_conversation) if raw_conversation and raw_conversation.isdigit() else None
    try:
        opened = prepare_voice(user_id, user_name, conversation_id)
    except VoiceDenied as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return

    await websocket.send_json({"type": "conversation", "id": opened["conversation_id"]})
    loop = asyncio.get_running_loop()
    outgoing: asyncio.Queue = asyncio.Queue()
    session = DeepgramSalonSession(
        loop,
        outgoing,
        user_id=user_id,
        user_name=user_name,
        conversation_id=opened["conversation_id"],
        recap=opened["recap"],
        greeting=opened["greeting"],
        booking=opened["booking"],
    )

    await websocket.send_json({"type": "status", "state": "connecting"})
    try:
        await asyncio.to_thread(session.start)
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        session.close()
        return

    pump_task = asyncio.create_task(_pump(websocket, outgoing))
    try:
        while True:
            incoming = await websocket.receive()
            if incoming["type"] == "websocket.disconnect":
                break
            audio = incoming.get("bytes")
            text = incoming.get("text")
            if audio:
                await asyncio.to_thread(session.send_audio, audio)
            elif text:
                await _handle_text(session, text)
    except WebSocketDisconnect:
        pass
    finally:
        await asyncio.to_thread(session.close)
        try:
            await asyncio.wait_for(pump_task, timeout=2)
        except (asyncio.TimeoutError, Exception):
            pump_task.cancel()


async def _handle_text(session: DeepgramSalonSession, text: str) -> None:
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return
    if message.get("type") != "text":
        return
    content = str(message.get("content") or "").strip()
    if content:
        await asyncio.to_thread(session.send_text, content)


async def _pump(websocket: WebSocket, outgoing: asyncio.Queue) -> None:
    while True:
        kind, payload = await outgoing.get()
        if kind == "closed":
            return
        if kind == "json":
            await websocket.send_json(payload)
        elif kind == "audio" and payload:
            await websocket.send_bytes(payload)
