# Salon Agent (Deepgram Voice)

Voice receptionist for salon bookings. Customers talk or type with Tara over a WebSocket; Deepgram handles listen / think / speak, and the FastAPI backend runs the booking tools.

## Stack

- **Backend:** FastAPI + Deepgram Voice Agent + Upstash Vector
- **Frontend:** Next.js chat UI with live mic and text input

## Project layout

```
backend/
  app/api/voice.py          # WebSocket /api/voice
  app/voice/                # Deepgram session + salon tools
  data/                     # services, staff, slots
frontend/
  app/                      # Next.js pages
  components/chat/          # reception UI
  lib/voice.ts              # browser mic + websocket client
```

## Setup

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `DEEPGRAM_API_KEY`, `UPSTASH_VECTOR_REST_URL`, and `UPSTASH_VECTOR_REST_TOKEN`.

```bash
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## API

| Endpoint | Description |
| --- | --- |
| `GET /health` | Health check |
| `WS /api/voice` | Deepgram-backed voice session |

## Notes

- Do not commit `.env` or `.env.local`. Use the `.env.example` files.
- Catalog search uses Upstash Vector; slots are stored in `backend/data/slots.json`.
