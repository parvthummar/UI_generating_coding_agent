import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.agent import run_turn, sse
from app.sessions import Session
from app.workspace import apply_template_app, read_committed_files, snapshot_count, undo_committed

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173'],
    allow_methods=['*'],
    allow_headers=['*'],
)

turn_lock = threading.Lock()
session = Session()


class ChatRequest(BaseModel):
    message: str


@app.post('/api/chat')
def chat(body: ChatRequest):
    if not turn_lock.acquire(blocking=False):
        return JSONResponse({'error': 'A turn is already running'}, status_code=409)

    def stream():
        try:
            for event in run_turn(session, body.message):
                yield event
        except Exception as err:
            yield sse('error', {'message': str(err)})
        finally:
            turn_lock.release()

    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})


@app.get('/api/files')
def files():
    return read_committed_files()


@app.post('/api/reset')
def reset():
    if not turn_lock.acquire(blocking=False):
        return JSONResponse({'error': 'A turn is already running'}, status_code=409)
    try:
        apply_template_app()
        session.clear()
        return {'ok': True}
    finally:
        turn_lock.release()


@app.post('/api/undo')
def undo():
    if not turn_lock.acquire(blocking=False):
        return JSONResponse({'error': 'A turn is already running'}, status_code=409)
    try:
        files = undo_committed()
        if files is None:
            return JSONResponse({'error': 'Nothing to undo'}, status_code=400)
        session.add_turn(
            'Undo the last committed change.',
            'Restored the previous committed UI. The preview matches that snapshot.',
            [],
        )
        return {'files': files, 'remaining': snapshot_count()}
    finally:
        turn_lock.release()
