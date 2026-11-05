"""POST SSE: stage events and one committed, validated result, never draft text."""
import asyncio
from hashlib import sha256
import json
from threading import Event
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from auth import AuthenticatedUser, get_authenticated_user
from rag.progress import ProgressContext, QuestionCancelled, current
from rag.router import QuestionRequest, answer_question_request

router = APIRouter()


class ProgressQuestionRequest(QuestionRequest):
    request_id: UUID


@router.post("/questions/stream")
async def stream_question(request: ProgressQuestionRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> StreamingResponse:
    payload = QuestionRequest.model_validate(request.model_dump(exclude={"request_id"}))
    fingerprint = sha256(payload.model_dump_json().encode()).hexdigest()

    async def events():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        cancelled = Event()

        def put(event: str, **data):
            if not cancelled.is_set() and not loop.is_closed():
                loop.call_soon_threadsafe(queue.put_nowait, (event, {"request_id": str(request.request_id), **data}))

        def worker():
            previous = None

            def stage(value):
                nonlocal previous
                if value != previous:
                    put("progress", stage=value)
                    previous = value

            token = current.set(ProgressContext(request.request_id, fingerprint, cancelled, stage))
            try:
                response = answer_question_request(payload, user)
                put("result", response=response.model_dump(mode="json"))
            except QuestionCancelled:
                pass
            except HTTPException as error:
                put("error", status=error.status_code, detail=error.detail)
            except Exception:
                put("error", status=503, detail="Question answering is unavailable")
            finally:
                current.reset(token)

        task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                if event in {"result", "error"}:
                    break
        finally:
            cancelled.set()
            task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
    })
