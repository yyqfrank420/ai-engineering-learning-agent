from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from adapters.supabase_auth_adapter import get_current_user
from agent.complexity import diagram_submission_action
from api.chat_guards import byte_len
from config import settings
from graph.content_edit import (
    GraphContentEditRequest,
    GraphEditConflict,
    GraphEditInvalid,
    GraphEditNotFound,
    GraphEditTooLarge,
)
from storage.message_store import get_messages
from storage.profile_store import upsert_profile
from storage import runtime_state_store
from storage.thread_store import (
    create_thread,
    delete_thread,
    edit_graph_content,
    get_latest_thread,
    get_thread,
    list_threads,
    save_graph,
)

router = APIRouter(prefix="/api/threads", tags=["threads"])


class CreateThreadRequest(BaseModel):
    title: str = "New chat"


class UpdateGraphRequest(BaseModel):
    graph_data: dict[str, Any]


class DiagramIntentRequest(BaseModel):
    message: str


@router.post("/{thread_id}/diagram-intent")
async def diagram_intent_endpoint(
    thread_id: str, body: DiagramIntentRequest, user=Depends(get_current_user)
):
    thread = get_thread(user["id"], thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="Message is empty")
    if byte_len(body.message) > settings.max_message_bytes:
        raise HTTPException(status_code=413, detail="Message too large")
    return {"action": diagram_submission_action(body.message, thread.get("graph_data"))}


@router.get("")
async def list_threads_endpoint(user=Depends(get_current_user)):
    upsert_profile(user["id"], user["email"] or f"{user['id']}@unknown.local")
    return {"threads": list_threads(user["id"])}


@router.post("")
async def create_thread_endpoint(
    body: CreateThreadRequest, user=Depends(get_current_user)
):
    upsert_profile(user["id"], user["email"] or f"{user['id']}@unknown.local")
    title = body.title.strip() or "New chat"
    if byte_len(title) > settings.max_thread_title_bytes:
        raise HTTPException(status_code=413, detail="Thread title too large")
    thread = create_thread(user["id"], title)
    return {"thread": thread, "messages": []}


@router.get("/latest")
async def latest_thread_endpoint(user=Depends(get_current_user)):
    upsert_profile(user["id"], user["email"] or f"{user['id']}@unknown.local")
    thread = get_latest_thread(user["id"])
    if thread is None:
        thread = create_thread(user["id"])
    return {
        "thread": thread,
        "messages": get_messages(user["id"], thread["id"]),
    }


@router.delete("/{thread_id}", status_code=204)
async def delete_thread_endpoint(thread_id: str, user=Depends(get_current_user)):
    thread = get_thread(user["id"], thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    delete_thread(user["id"], thread_id)


@router.put("/{thread_id}/graph", status_code=204)
async def update_thread_graph_endpoint(
    thread_id: str,
    body: UpdateGraphRequest,
    user=Depends(get_current_user),
):
    thread = get_thread(user["id"], thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if not save_graph(user["id"], thread_id, body.graph_data):
        raise HTTPException(status_code=413, detail="Graph data too large")


@router.patch("/{thread_id}/graph")
async def edit_thread_graph_endpoint(
    thread_id: str,
    body: GraphContentEditRequest,
    user=Depends(get_current_user),
):
    thread = get_thread(user["id"], thread_id)
    if thread is None or thread.get("graph_data") is None:
        raise HTTPException(status_code=404, detail="Thread graph not found")
    stream_id = runtime_state_store.try_acquire_active_stream(
        user["id"],
        "chat-thread",
        limit=1,
        ttl_s=settings.agent_timeout_s + 30,
        scope_id=thread_id,
    )
    if stream_id is None:
        raise HTTPException(status_code=409, detail="A response is already running")
    try:
        try:
            graph = edit_graph_content(user["id"], thread_id, body)
        except GraphEditNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GraphEditConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except GraphEditInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except GraphEditTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
    finally:
        runtime_state_store.release_active_stream(stream_id)
    return {"graph_data": graph}


@router.get("/{thread_id}")
async def get_thread_endpoint(thread_id: str, user=Depends(get_current_user)):
    upsert_profile(user["id"], user["email"] or f"{user['id']}@unknown.local")
    thread = get_thread(user["id"], thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {
        "thread": thread,
        "messages": get_messages(user["id"], thread_id),
    }
