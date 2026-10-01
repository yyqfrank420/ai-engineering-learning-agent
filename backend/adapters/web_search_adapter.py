"""Authenticated Moonshot Basic search with one bounded provider request."""

from __future__ import annotations

import asyncio
import logging
import json
import time

import openai
import httpx

from adapters.llm_adapter import _get_kimi_client, _reserve_evaluation_provider_attempt
from analytics.events import enqueue_analytics_event
from config import settings
from observability import current_trace_context, record_llm_metrics
from storage.telemetry_store import record_llm_telemetry

logger = logging.getLogger(__name__)


class WebSearchUnavailable(RuntimeError):
    """The search provider did not return usable results."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class WebSearchProtocolError(WebSearchUnavailable):
    """The provider response did not match its documented result shape."""


async def search_sources(
    query: str,
    telemetry: dict | None = None,
) -> list[dict[str, str]]:
    if not isinstance(query, str):
        raise TypeError("Search query must be a string")
    normalized_query = " ".join(query.split())
    if not normalized_query:
        raise ValueError("Search query must not be empty")
    if not settings.moonshot_api_key:
        raise WebSearchUnavailable("Search provider is not configured")
    client = _get_kimi_client()
    if client is None:
        raise WebSearchUnavailable("Search provider is not configured")
    post = client.post
    if not callable(post):
        raise TypeError("Search client POST is not callable")
    # Set up the client before reserving; the reservation counts provider POSTs.
    _reserve_evaluation_provider_attempt()
    started_at = time.perf_counter()
    billable_requests: int | None = None
    status = "error"
    error_type: str | None = None
    try:
        response = await post(
            "/tools/search",
            cast_to=httpx.Response,
            body={
                "text_query": normalized_query,
                "limit": 6,
                "timeout_seconds": 20,
                "include_content": False,
            },
            options={"timeout": 30.0, "max_retries": 0, "follow_redirects": False},
        )
        if response.status_code != 200:
            billable_requests = 0
            raise WebSearchProtocolError(
                "Search provider returned an unexpected status",
                status_code=response.status_code,
            )
        response = response.json()
        if not isinstance(response, dict) or not isinstance(
            response.get("search_results"), list
        ):
            raise WebSearchProtocolError("Search response has invalid results")
        results = response["search_results"]
        # HTTP 200 plus a nonempty provider array is billed before local filtering.
        billable_requests = int(bool(results))
        projected: list[dict[str, str]] = []
        for result in results:
            if not isinstance(result, dict) or any(
                not isinstance(result.get(field), str)
                for field in ("title", "url", "snippet")
            ):
                raise WebSearchProtocolError("Search response has an invalid result")
            projected.append(
                {field: result[field] for field in ("title", "url", "snippet")}
            )
        status = "success"
        return projected
    except (json.JSONDecodeError, UnicodeDecodeError):
        error_type = "WebSearchProtocolError"
        raise WebSearchProtocolError("Search response has invalid JSON") from None
    except openai.APIStatusError as exc:
        billable_requests = 0 if exc.status_code != 200 else None
        error_type = "APIStatusError"
        raise WebSearchUnavailable(
            "Search provider request failed", status_code=exc.status_code
        ) from None
    except (openai.APIConnectionError, TimeoutError):
        error_type = "ProviderTransportError"
        raise WebSearchUnavailable("Search provider request failed") from None
    except asyncio.CancelledError:
        error_type = "CancelledError"
        raise
    except Exception as exc:
        error_type = type(exc).__name__
        raise
    finally:
        details = telemetry or {}
        raw_metadata = details.get("metadata")
        raw_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        trace_context = current_trace_context()
        duration_ms = max(1, int((time.perf_counter() - started_at) * 1000))
        complete = billable_requests is not None
        attempt = {
            "attempt": 1,
            "provider": "moonshot",
            "model": "moonshot-web-search-basic",
            "status": status,
            "duration_ms": duration_ms,
            "error_type": error_type,
            "input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 0,
            "usage_complete": complete,
            "web_search_requests": billable_requests,
            "web_search_usage_complete": complete,
        }
        metadata = {
            **{
                name: raw_metadata[name]
                for name in (
                    "request_id",
                    "client_request_id",
                    "search_api_version",
                )
                if name in raw_metadata
            },
            "trace_id": trace_context.get("trace_id"),
            "span_id": trace_context.get("span_id"),
            "provider_attempts": 1,
            "input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 0,
            "usage_complete": complete,
            "web_search": True,
            "web_search_requests": billable_requests,
            "web_search_usage_complete": complete,
            "attempts": [attempt],
        }
        try:
            record_llm_telemetry(
                operation="web_research",
                provider="moonshot",
                model="moonshot-web-search-basic",
                status=status,
                duration_ms=duration_ms,
                output_chars=0,
                used_fallback=False,
                user_id=details.get("user_id"),
                thread_id=details.get("thread_id"),
                error_type=error_type,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("Search telemetry write failed: %s", type(exc).__name__)
        enqueue_analytics_event(
            event_name="llm_call_completed",
            event_category="llm",
            user_id=details.get("user_id"),
            thread_id=details.get("thread_id"),
            session_id=details.get("thread_id"),
            request_id=metadata.get("request_id"),
            client_request_id=metadata.get("client_request_id"),
            trace_id=metadata["trace_id"],
            numeric_value=duration_ms,
            unit="ms",
            properties={
                "operation": "web_research",
                "provider": "moonshot",
                "model": "moonshot-web-search-basic",
                "status": status,
                "provider_attempts": 1,
                "duration_ms": duration_ms,
                "web_search_requests": billable_requests,
                "web_search_usage_complete": complete,
            },
        )
        record_llm_metrics(
            operation="web_research",
            provider="moonshot",
            model="moonshot-web-search-basic",
            duration_ms=duration_ms,
            used_fallback=False,
            status=status,
        )
