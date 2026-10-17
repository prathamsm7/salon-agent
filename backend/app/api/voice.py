import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.voice.deepgram_session import DeepgramSalonSession

router = APIRouter()


@router.websocket("/voice")
async def voice(websocket: WebSocket) -> None:
    await websocket.accept()
    loop = asyncio.get_running_loop()
    outgoing: asyncio.Queue = asyncio.Queue()
    session = DeepgramSalonSession(loop, outgoing)

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
