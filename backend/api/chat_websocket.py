"""Bidirectional chat transport with authenticated steering and cancellation."""

from __future__ import annotations

import asyncio
import copy
from contextlib import suppress
import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from anyio import CancelScope
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from adapters.llm_adapter import is_provider_unavailable_error
from adapters.supabase_auth_adapter import get_current_user
from agent.deadlines import WorkflowDeadlineExceeded
from agent.graph import run_agent
from agent.activity import ActivityRecorder
from agent.graph_review_budget import GraphReviewBudget
from agent.graph_review_control import GraphReviewControl
from agent.state import AgentState
from analytics.events import enqueue_analytics_event
from api.chat_guards import (
    byte_len,
    check_prompt_injection,
    check_rate_limit,
    internal_test_stream_scope,
    graph_continuity_error,
    is_production_traffic,
    knowledge_base_ready,
    truncate_utf8,
)
from api.diagram_evaluation_channel import DiagramEvaluationChannel, DiagramWaiter
from api.sse_handler import (
    ChatRequest, MAX_CHAT_STEERS, _make_agent_tools, max_effective_message_bytes,
)
from config import settings
from observability import (
    change_active_chat_streams,
    record_agent_duration,
    record_cancel,
    record_timeout,
)
from storage import message_store, runtime_state_store, thread_store
from storage.errors import ThreadMessageLimitExceeded
from storage.profile_store import upsert_profile


router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

_AUTH_TIMEOUT_S = 8.0
_START_TIMEOUT_S = 20.0
_MAX_STEERS_PER_RUN = MAX_CHAT_STEERS
# JSON escapes can expand one content byte to six bytes; reserve room for request fields.
_MAX_WS_FRAME_BYTES = max(16_384, 6 * max_effective_message_bytes() + 4_096)


async def _run_blocking(
    operation: Callable[..., Any],
    *args: Any,
    stream_acquisition: bool = False,
    **kwargs: Any,
) -> Any:
    """Finish API storage work before cancellation can unwind held resources."""
    # Framework shutdown uses cancel scopes; direct Task.cancel is handled below.
    with CancelScope(shield=True):
        worker = asyncio.create_task(run_in_threadpool(operation, *args, **kwargs))
        cancelled = False
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        try:
            result = worker.result()
        except Exception as exc:
            if cancelled:
                logger.warning(
                    "Cancelled WebSocket worker failed (%s: %s)",
                    getattr(operation, "__name__", type(operation).__name__),
                    type(exc).__name__,
                )
                raise asyncio.CancelledError from exc
            raise
        if cancelled:
            if stream_acquisition and result is not None:
                # Assignment in the caller never happened, so its finally cannot
                # release this lease. Finish release even under repeated cancellation.
                try:
                    await _run_blocking(
                        runtime_state_store.release_active_stream, result
                    )
                except Exception as exc:
                    logger.warning(
                        "Cancelled WebSocket lease cleanup failed (release_active_stream: %s)",
                        type(exc).__name__,
                    )
                    raise asyncio.CancelledError from exc
            raise asyncio.CancelledError
        return result


class _SingleWaitDiagramEvaluationChannel(DiagramEvaluationChannel):
    """Correlate one candidate with one bounded browser-evaluation wait."""

    async def request(self, graph: dict[str, Any], send: Any) -> dict[str, Any]:
        evaluation_id = str(uuid.uuid4())
        graph_version_text = str(graph.get("version") or "").strip()
        graph_version = graph_version_text or None
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        waiter = DiagramWaiter(
            graph_version=graph_version,
            future=future,
        )
        self._waiters[evaluation_id] = waiter
        try:
            await send(
                self.graph_candidate_event(
                    evaluation_id=evaluation_id,
                    graph_version=graph_version,
                    graph=graph,
                    criteria=waiter.criteria,
                )
            )
            return await asyncio.wait_for(future, timeout=self._timeout_s)
        finally:
            self._waiters.pop(evaluation_id, None)
            self._uploads.pop(evaluation_id, None)
            if not future.done():
                future.cancel()


@router.websocket("/chat/ws")
async def chat_websocket(websocket: WebSocket) -> None:
    """Run one steerable agent turn over one short-lived WebSocket.

    Protocol (client -> server): ``auth``, ``start``, then zero or more ``steer``
    commands or one ``stop`` command. Agent events use the existing ServerEvent
    JSON shapes, with ``ready``, ``response_reset``, and ``steer_applied`` added.
    """

    if not _origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    await websocket.accept()
    stream_id: str | None = None
    thread_stream_id: str | None = None
    receiver_task: asyncio.Task | None = None
    agent_task: asyncio.Task | None = None
    active_metric_counted = False
    session_started_at = time.perf_counter()

    try:
        auth_message = await asyncio.wait_for(
            _receive_object(websocket), timeout=_AUTH_TIMEOUT_S
        )
        if auth_message.get("type") != "auth":
            await _send_error(websocket, "Authentication must be the first message")
            await websocket.close(code=1008)
            return
        token = str(auth_message.get("access_token") or "")
        try:
            user = await _run_blocking(
                get_current_user, authorization=f"Bearer {token}"
            )
        except HTTPException:
            await _send_error(websocket, "Authentication failed")
            await websocket.close(code=1008)
            return

        await websocket.send_json(
            {
                "type": "ready",
                "turn_timeout_ms": int((settings.agent_timeout_s + 60) * 1000),
            }
        )
        start_message = await asyncio.wait_for(
            _receive_object(websocket), timeout=_START_TIMEOUT_S
        )
        if start_message.get("type") != "start":
            await _send_error(websocket, "Expected a start message")
            await websocket.close(code=1008)
            return
        try:
            body = ChatRequest.model_validate(
                {key: value for key, value in start_message.items() if key != "type"}
            )
        except ValidationError:
            await _send_error(websocket, "Invalid chat request")
            await websocket.close(code=1008)
            return

        user_id = user["id"]
        user_email = user.get("email") or f"{user_id}@unknown.local"
        await _run_blocking(upsert_profile, user_id, user_email)
        thread = await _run_blocking(thread_store.get_thread, user_id, body.thread_id)
        request_error = _request_error(body, thread)
        if request_error:
            await _send_error(websocket, request_error)
            await websocket.send_json({"type": "done"})
            return

        try:
            body, original_request = await _run_blocking(
                body.resolve_retry_source, user_id
            )
        except ValueError:
            await _send_error(websocket, "Retry request is unavailable")
            await websocket.send_json({"type": "done"})
            return

        request_id = str(uuid.uuid4())

        async def replay_completed_turn() -> bool:
            try:
                completed_turn = await _run_blocking(
                    thread_store.get_completed_turn,
                    user_id,
                    body.thread_id,
                    body.client_request_id,
                )
            except RuntimeError:
                logger.exception("Stored idempotent turn is incomplete")
                await _send_error(
                    websocket, "Previous request is incomplete — start a new request"
                )
                await websocket.send_json({"type": "done"})
                return True
            if completed_turn is not None:
                enqueue_analytics_event(
                    event_name="stream_replayed",
                    event_category="stream",
                    user_id=user_id,
                    thread_id=body.thread_id,
                    request_id=request_id,
                    client_request_id=body.client_request_id,
                    properties={"stream_type": "websocket"},
                )
                await websocket.send_json(
                    {
                        "type": "response_delta",
                        "content": completed_turn["assistant_content"],
                    }
                )
                await websocket.send_json(
                    {
                        "type": "graph_data",
                        "data": await _run_blocking(
                            thread_store.get_graph, user_id, body.thread_id
                        ),
                    }
                )
                if completed_turn.get("retry_request") is not None:
                    await websocket.send_json({"type": "generation_failed"})
                await websocket.send_json({"type": "done", **({"activity": completed_turn["activity"]} if completed_turn.get("activity") is not None else {})})
                return True
            return False

        if await replay_completed_turn():
            return

        preflight_error = await _run_blocking(
            _new_turn_preflight_error, websocket, user_id, body
        )
        if preflight_error:
            await _send_error(websocket, preflight_error)
            await websocket.send_json({"type": "done"})
            return

        stream_id = await _run_blocking(
            runtime_state_store.try_acquire_active_stream,
            user_id,
            "chat",
            limit=settings.max_active_chat_streams_per_user,
            ttl_s=settings.agent_timeout_s + 30,
            scope_id=internal_test_stream_scope(user, body.thread_id),
            stream_acquisition=True,
        )
        if stream_id is None:
            await _send_error(
                websocket,
                "Another response is already running. Stop it or wait for it to finish.",
            )
            await websocket.send_json({"type": "done"})
            return

        thread_stream_id = await _run_blocking(
            runtime_state_store.try_acquire_active_stream,
            user_id,
            "chat-thread",
            limit=1,
            ttl_s=settings.agent_timeout_s + 30,
            scope_id=body.thread_id,
            stream_acquisition=True,
        )
        if thread_stream_id is None:
            await _send_error(
                websocket,
                "Another response is already running. Stop it or wait for it to finish.",
            )
            await websocket.send_json({"type": "done"})
            return
        thread = await _run_blocking(thread_store.get_thread, user_id, body.thread_id)
        if thread is None:
            await _send_error(websocket, "Thread not found")
            await websocket.send_json({"type": "done"})
            return
        # A competing instance may have committed after the early replay check.
        if await replay_completed_turn():
            return

        rag_tools, graph_tools, node_detail_tools = _make_agent_tools(websocket)
        history = await _run_blocking(
            message_store.get_history,
            user_id,
            body.thread_id,
            limit=settings.max_messages_per_thread,
        )
        base_graph, base_graph_contract = await _run_blocking(
            thread_store.get_graph_artifact, user_id, body.thread_id
        )
        continuity_error = graph_continuity_error(
            graph_action=body.graph_action,
            expected_graph_version=body.expected_graph_version,
            current_graph=base_graph,
            content=body.content,
            diagram_requested=body.diagram_requested,
        )
        if continuity_error:
            await _send_error(websocket, continuity_error)
            await websocket.send_json({"type": "done"})
            return
        approved_graph_at_request_start = copy.deepcopy(base_graph)
        approved_graph_contract_at_request_start = copy.deepcopy(base_graph_contract)
        content = body.content
        latest_graph = base_graph
        graph_preview_sent = False
        command_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
        send_lock = asyncio.Lock()
        diagram_channel = _SingleWaitDiagramEvaluationChannel(
            timeout_s=settings.diagram_evaluation_timeout_s,
            max_screenshot_bytes=settings.max_diagram_screenshot_bytes,
        )
        steer_count = len(body.steering_updates)
        graph_review_budget = GraphReviewBudget()
        graph_review_control = GraphReviewControl()
        started_at = session_started_at
        activity = ActivityRecorder()
        saved_activity = None

        async def send(event: dict) -> None:
            nonlocal graph_preview_sent
            # ``done`` belongs to the transport: it is sent only after durable
            # persistence. This also prevents a cancelled draft from ending the UI.
            if event.get("type") in {"done", "thinking_delta", "activity_step"}:
                return
            if event.get("type") in {"graph_preview", "graph_data"}:
                graph_preview_sent = True
                event = {"type": "graph_preview", "data": event.get("data")}
            async with send_lock:
                await websocket.send_json(event)
                try:
                    step = activity.record(event, int((time.perf_counter() - started_at) * 1000))
                    if step is not None:
                        await websocket.send_json(step)
                except Exception as exc:
                    logger.info("Optional activity delivery failed (%s)", type(exc).__name__)

        async def send_authoritative_graph(graph: dict | None) -> None:
            nonlocal latest_graph
            latest_graph = copy.deepcopy(graph)
            async with send_lock:
                await websocket.send_json({"type": "graph_data", "data": latest_graph})

        async def restore_graph_preview() -> None:
            nonlocal graph_preview_sent
            if not graph_preview_sent:
                return
            await send_authoritative_graph(approved_graph_at_request_start)
            graph_preview_sent = False

        async def send_done() -> None:
            canonical_turn = await _run_blocking(
                thread_store.get_completed_turn,
                user_id,
                body.thread_id,
                body.client_request_id,
            )
            canonical_activity = canonical_turn.get("activity") if canonical_turn is not None else None
            if canonical_turn is None and body.client_request_id is None:
                canonical_activity = saved_activity
            async with send_lock:
                await websocket.send_json({"type": "done", **({"activity": canonical_activity} if canonical_activity is not None else {})})

        async def await_search_tool_request(
            search_request_id: str, timeout_s: float
        ) -> bool:
            expires_at = time.time() + timeout_s
            await _run_blocking(
                runtime_state_store.prune_search_tool_requests,
                older_than_epoch=time.time(),
            )
            try:
                await _run_blocking(
                    runtime_state_store.create_search_tool_request,
                    search_request_id,
                    user_id,
                    body.thread_id,
                    expires_at_epoch=expires_at,
                )
                deadline = asyncio.get_running_loop().time() + timeout_s
                while asyncio.get_running_loop().time() < deadline:
                    if await _run_blocking(
                        runtime_state_store.is_search_tool_requested,
                        search_request_id,
                        user_id,
                        body.thread_id,
                    ):
                        return True
                    await asyncio.sleep(0.1)
                return False
            finally:
                await _run_blocking(
                    runtime_state_store.delete_search_tool_request, search_request_id
                )

        async def receive_commands() -> None:
            def enqueue_disconnect() -> None:
                # Disconnect supersedes queued steering commands; otherwise a
                # full queue could leave paid work running until the timeout.
                while True:
                    try:
                        command_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                command_queue.put_nowait({"type": "disconnect"})

            try:
                while True:
                    command = await _receive_object(websocket)
                    if str(command.get("type") or "").startswith("diagram_evaluation_"):
                        diagram_channel.accept(command)
                    elif command.get("type") in {"steer", "stop", "accept_preview"}:
                        if command.get("client_request_id") != body.client_request_id:
                            await send(
                                {
                                    "type": "command_rejected",
                                    "reason": "Command does not match the active request",
                                    **({"command_type": "accept_preview"} if command.get("type") == "accept_preview" else {}),
                                }
                            )
                            continue
                        await command_queue.put(command)
                    else:
                        await send(
                            {"type": "command_rejected", "reason": "Unknown command"}
                        )
            except WebSocketDisconnect:
                enqueue_disconnect()
            except Exception as exc:
                logger.info("WebSocket command receiver ended: %s", type(exc).__name__)
                enqueue_disconnect()

        def make_state() -> AgentState:
            return {
                "session_id": body.thread_id,
                "user_id": user_id,
                "user_email": user_email,
                "is_production": is_production_traffic(user),
                "request_id": request_id,
                "client_request_id": body.client_request_id,
                "user_message": content,
                "history": history,
                "complexity": body.complexity,
                "graph_mode": body.graph_mode,
                "diagram_requested": body.diagram_requested,
                "graph_action": body.graph_action,
                "research_enabled": body.research_enabled,
                "route": "",
                "rag_chunks": [],
                "retrieval_relevance": "strong",
                "retrieval_notice": "",
                "graph_data": latest_graph,
                "approved_graph_data": copy.deepcopy(approved_graph_at_request_start),
                "graph_contract": copy.deepcopy(
                    approved_graph_contract_at_request_start
                ),
                "approved_graph_contract": copy.deepcopy(
                    approved_graph_contract_at_request_start
                ),
                "graph_changed": False,
                "graph_notice_sent": False,
                "graph_revision_count": 0,
                "_graph_review_budget": graph_review_budget,
                "_graph_review_control": graph_review_control,
                "research_context": "",
                "response_text": "",
                "send": send,
                "await_search_tool_request": await_search_tool_request,
                "await_diagram_evaluation": lambda graph: diagram_channel.request(
                    graph, send
                ),
                "workflow_started_at_s": workflow_started_at,
                "terminal_deadline_s": terminal_deadline,
                "graph_preview_deadline_s": (
                    min(
                        asyncio.get_running_loop().time()
                        + settings.graph_preview_timeout_s,
                        terminal_deadline,
                    )
                ),
            }

        enqueue_analytics_event(
            event_name="stream_started",
            event_category="stream",
            user_id=user_id,
            thread_id=body.thread_id,
            request_id=request_id,
            client_request_id=body.client_request_id,
            properties={"stream_type": "websocket", "steerable": True},
        )
        await send(
            {
                "type": "worker_status",
                "worker": "orchestrator",
                "status": "Question received — preparing the steerable workflow…",
            }
        )
        receiver_task = asyncio.create_task(receive_commands())
        change_active_chat_streams(1)
        active_metric_counted = True
        workflow_started_at = asyncio.get_running_loop().time()
        outer_deadline = workflow_started_at + settings.agent_timeout_s
        terminal_deadline = outer_deadline - settings.agent_terminal_headroom_s

        while True:
            if asyncio.get_running_loop().time() >= terminal_deadline:
                await restore_graph_preview()
                await send(
                    {
                        "type": "error",
                        "content": "Response timed out — please try again",
                    }
                )
                record_timeout()
                break

            agent_task = asyncio.create_task(
                run_agent(make_state(), rag_tools, graph_tools, node_detail_tools)
            )
            restart_requested = False
            final_state: AgentState | None = None

            while True:
                command_task = asyncio.create_task(command_queue.get())
                timeout_task = asyncio.create_task(
                    asyncio.sleep(
                        max(0.0, terminal_deadline - asyncio.get_running_loop().time())
                    )
                )
                done, pending = await asyncio.wait(
                    {agent_task, command_task, timeout_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                cancelled_tasks = [task for task in pending if task is not agent_task]
                for task in cancelled_tasks:
                    task.cancel()
                if cancelled_tasks:
                    await asyncio.gather(*cancelled_tasks, return_exceptions=True)

                if timeout_task in done:
                    agent_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await agent_task
                    await restore_graph_preview()
                    await send(
                        {
                            "type": "error",
                            "content": "Response timed out — please try again",
                        }
                    )
                    record_timeout()
                    break

                # Commands win a tie with completion. That makes a steer sent at
                # the final boundary deterministic instead of timing-dependent.
                if command_task in done:
                    command = command_task.result()
                    command_type = command.get("type")
                    if command_type == "accept_preview":
                        version = command.get("graph_version")
                        if not isinstance(version, str) or not graph_review_control.accept(version):
                            await send({
                                "type": "command_rejected",
                                "command_type": "accept_preview",
                                "reason": "This diagram is no longer available to accept. Please try again.",
                            })
                        continue
                    if command_type in {"stop", "disconnect"}:
                        agent_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await agent_task
                        enqueue_analytics_event(
                            event_name="stream_cancelled",
                            event_category="stream",
                            user_id=user_id,
                            thread_id=body.thread_id,
                            request_id=request_id,
                            properties={
                                "stream_type": "websocket",
                                "reason": command_type,
                            },
                        )
                        record_cancel()
                        if command_type == "stop":
                            await restore_graph_preview()
                            await send({"type": "stopped"})
                        return

                    if graph_review_control.accepted_version is not None:
                        await send({
                            "type": "command_rejected",
                            "reason": "The accepted diagram is finishing. Send your follow-up after the answer completes.",
                        })
                        continue
                    steering = " ".join(str(command.get("content") or "").split())
                    steered_content = (
                        f"{content}\n\nUser steering update {steer_count + 1}:\n{steering}"
                    )
                    if (
                        not steering
                        or byte_len(steering) > settings.max_message_bytes
                        or byte_len(steered_content) > max_effective_message_bytes()
                        or not check_prompt_injection(steering)
                        or steer_count >= _MAX_STEERS_PER_RUN
                    ):
                        await send(
                            {
                                "type": "command_rejected",
                                "reason": "Steering command was empty, unsafe, too large, or over the limit",
                            }
                        )
                        # Invalid commands do not disturb the active model call.
                        continue

                    agent_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await agent_task
                    graph_review_control = GraphReviewControl()
                    steer_count += 1
                    content = steered_content
                    await restore_graph_preview()
                    await send({"type": "response_reset"})
                    await send(
                        {
                            "type": "steer_applied",
                            "content": steering,
                            "steer_count": steer_count,
                        }
                    )
                    await send(
                        {
                            "type": "worker_status",
                            "worker": "orchestrator",
                            "status": "Steering received — rebuilding the answer around your correction…",
                        }
                    )
                    enqueue_analytics_event(
                        event_name="chat_steered",
                        event_category="stream",
                        user_id=user_id,
                        thread_id=body.thread_id,
                        request_id=request_id,
                        properties={"steer_count": steer_count},
                    )
                    restart_requested = True
                    break

                try:
                    final_state = agent_task.result()
                except WorkflowDeadlineExceeded:
                    await restore_graph_preview()
                    await send(
                        {
                            "type": "error",
                            "content": "Response timed out — please try again",
                        }
                    )
                    record_timeout()
                    final_state = None
                break

            if restart_requested:
                continue
            if final_state is None:
                break

            final_graph = final_state.get("graph_data")
            has_new_graph = (
                final_state.get("graph_publication") in {"approved", "user_accepted"}
                and bool(final_graph and final_graph.get("nodes"))
                and final_graph != approved_graph_at_request_start
            )
            if (
                not (final_state.get("response_text") or "").strip()
                and not has_new_graph
            ):
                await restore_graph_preview()
                await send(
                    {
                        "type": "error",
                        "content": "No response was returned. Please try again.",
                    }
                )
                break

            try:
                title = thread["title"]
                if title == "New chat":
                    title = truncate_utf8(
                        body.content, min(60, settings.max_thread_title_bytes)
                    )
                turn_activity = activity.snapshot(int((time.perf_counter() - started_at) * 1000))
                graph_saved = await _run_blocking(
                    thread_store.persist_turn,
                    user_id,
                    body.thread_id,
                    title=title,
                    user_content=content,
                    assistant_content=final_state["response_text"],
                    graph_data=final_state.get("graph_data"),
                    graph_contract=final_state.get("graph_contract"),
                    client_request_id=body.client_request_id,
                    retry_request=body.failed_generation_retry_request(
                        final_state, original_request
                    ),
                    activity=turn_activity,
                )
                saved_activity = turn_activity
                if not graph_saved:
                    await restore_graph_preview()
                    await send(
                        {
                            "type": "error",
                            "content": "Graph is displayed but was too large to save.",
                        }
                    )
                else:
                    persisted_graph = await _run_blocking(
                        thread_store.get_graph, user_id, body.thread_id
                    )
                    await send_authoritative_graph(persisted_graph)
                    graph_preview_sent = False
            except ThreadMessageLimitExceeded:
                await restore_graph_preview()
                await send(
                    {
                        "type": "error",
                        "content": "Thread message limit reached. Start a new chat to continue.",
                    }
                )
                break
            except Exception:
                logger.exception("WebSocket chat persistence failed")
                await restore_graph_preview()
                await send(
                    {
                        "type": "error",
                        "content": "Response could not be saved — please try again",
                    }
                )
                break

            enqueue_analytics_event(
                event_name="stream_completed",
                event_category="stream",
                user_id=user_id,
                thread_id=body.thread_id,
                request_id=request_id,
                client_request_id=body.client_request_id,
                numeric_value=max(1, int((time.perf_counter() - started_at) * 1000)),
                unit="ms",
                properties={"stream_type": "websocket", "steer_count": steer_count},
            )
            await send_done()
            return

        await send_done()
    except WebSocketDisconnect:
        return
    except Exception as exc:
        if isinstance(exc, asyncio.TimeoutError) and agent_task is None:
            return
        logger.error("WebSocket chat failed: %s", type(exc).__name__)
        with suppress(Exception):
            await _send_error(
                websocket,
                "The external API service is unavailable. Please try again."
                if is_provider_unavailable_error(exc)
                else "Response failed — please try again",
            )
            await websocket.send_json({"type": "done"})
    finally:
        try:
            try:
                if agent_task and not agent_task.done():
                    agent_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await agent_task
            finally:
                if receiver_task and not receiver_task.done():
                    receiver_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await receiver_task
        except Exception as exc:
            logger.error("WebSocket task cleanup failed: %s", type(exc).__name__)
            raise
        finally:
            try:
                try:
                    if thread_stream_id is not None:
                        await _run_blocking(
                            runtime_state_store.release_active_stream, thread_stream_id
                        )
                finally:
                    if stream_id is not None:
                        await _run_blocking(
                            runtime_state_store.release_active_stream, stream_id
                        )
            finally:
                if active_metric_counted:
                    change_active_chat_streams(-1)
                    record_agent_duration(
                        max(1, int((time.perf_counter() - session_started_at) * 1000)),
                        route="/api/chat/ws",
                    )
                with suppress(Exception):
                    await websocket.close()


def _request_error(body: ChatRequest, thread: dict | None) -> str | None:
    if thread is None:
        return "Thread not found"
    if not body.content:
        return "Empty message"
    if byte_len(body.content) > settings.max_message_bytes:
        return f"Message too large (max {settings.max_message_bytes} bytes)"


def _new_turn_preflight_error(
    websocket: WebSocket, user_id: str, body: ChatRequest
) -> str | None:
    if (
        message_store.count_messages(user_id, body.thread_id) + 2
        > settings.max_messages_per_thread
    ):
        return "Thread message limit reached. Start a new chat to continue."
    limit_error = check_rate_limit(user_id)
    if limit_error:
        return limit_error
    if not knowledge_base_ready(websocket):
        return "Knowledge base is still loading. Please try again in a moment."
    if not check_prompt_injection(body.content):
        return "Message blocked by security filter"
    return None


async def _receive_object(websocket: WebSocket) -> dict[str, Any]:
    raw = await websocket.receive_text()
    if byte_len(raw) > _MAX_WS_FRAME_BYTES:
        raise ValueError("WebSocket frame too large")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("WebSocket message must be an object")
    return payload


def _origin_allowed(origin: str | None) -> bool:
    # Non-browser clients may omit Origin; authentication is still mandatory.
    if not origin:
        return True
    if origin in settings.cors_allowed_origins:
        return True
    try:
        return re.fullmatch(settings.vercel_origin_regex, origin) is not None
    except re.error:
        return False


async def _send_error(websocket: WebSocket, message: str) -> None:
    await websocket.send_json({"type": "error", "content": message})
