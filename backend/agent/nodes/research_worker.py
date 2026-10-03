"""Bounded authenticated research using actual Moonshot search results."""

import asyncio
import logging
from urllib.parse import urlparse

from adapters.llm_adapter import build_telemetry
from adapters.web_search_adapter import WebSearchUnavailable, search_sources
from agent.state import AgentState
from config import settings


logger = logging.getLogger(__name__)

# Max characters for title and body in each bullet to keep prompts lean
_TITLE_MAX = 80
_BODY_MAX = 600
_TOPIC_MAX = 160
_RESEARCH_API_VERSION = "web_research_v2"
_RESEARCH_TIMEOUT_S = 30.0


async def research_worker_node(state: AgentState) -> AgentState:
    """
    Search the requested topic asynchronously and format actual source snippets
    as a compact bullet list for downstream workers.

    Returns state with research_context and research_status set. On failure,
    downstream nodes degrade explicitly to book-only evidence.
    """
    send = state["send"]
    await send(
        {"type": "worker_status", "worker": "research", "status": "Searching the web…"}
    )

    await send(
        {
            "type": "workflow_progress",
            "phase": "web",
            "status": "active",
            "title": "Searching web",
            "detail": "",
        }
    )

    topic = _normalise_topic(state.get("design_query") or state["user_message"])
    try:
        async with asyncio.timeout(_RESEARCH_TIMEOUT_S):
            results = await search_sources(
                topic,
                telemetry=build_telemetry(
                    "web_research",
                    user_id=state.get("user_id"),
                    thread_id=state.get("session_id"),
                    is_production=state.get("is_production"),
                    metadata={
                        "request_id": state.get("request_id"),
                        "client_request_id": state.get("client_request_id"),
                        "search_api_version": _RESEARCH_API_VERSION,
                    },
                ),
            )
    except (WebSearchUnavailable, TimeoutError) as exc:
        logger.warning(
            "Web research unavailable provider=moonshot code=%s", type(exc).__name__
        )
        await _send_unavailable(send)
        return {**state, "research_context": "", "research_status": "unavailable"}

    raw = [
        {
            "url": result["url"],
            "title": result["title"],
            "body": result["snippet"],
            "query": topic,
            "backend": "moonshot_search",
        }
        for result in results
    ]
    context = _format_results(raw, settings.research_noise_domains)
    if not context:
        logger.warning(
            "Web research unavailable provider=moonshot code=no_usable_sources"
        )
        await _send_unavailable(send)
        return {**state, "research_context": "", "research_status": "unavailable"}
    sources = _source_urls(context)
    await send(
        {
            "type": "worker_status",
            "worker": "research",
            "status": "Web search results available.",
            "sources": sources,
        }
    )
    if _may_emit_eval_evidence(state):
        provenance = []
        for item in raw:
            url = str(item.get("href") or item.get("url", "")).strip()
            query, backend = item.get("query"), item.get("backend")
            if url in sources and isinstance(query, str) and isinstance(backend, str):
                source = {"url": url, "query": query, "backend": backend}
                if source not in provenance:
                    provenance.append(source)
        await send(
            {
                "type": "research_evidence",
                "query": topic,
                "results": context.splitlines(),
                "source_provenance": provenance,
            }
        )
    await send(
        {
            "type": "workflow_progress",
            "phase": "web",
            "status": "complete",
            "title": "Web sources found",
            "detail": "",
        }
    )
    return {**state, "research_context": context, "research_status": "ready"}


async def _send_unavailable(send) -> None:
    await send(
        {
            "type": "workflow_progress",
            "phase": "web",
            "status": "degraded",
            "title": "Web search unavailable",
            "detail": "Continuing with book sources.",
        }
    )
    await send(
        {
            "type": "worker_status",
            "worker": "research",
            "status": "Web research unavailable — continuing with book evidence only.",
        }
    )


def _may_emit_eval_evidence(state: AgentState) -> bool:
    """Expose bounded provenance only to the explicit internal test identity.

    This keeps production-candidate smoke evidence available without making
    external snippets visible to ordinary production users.
    """
    email = str(state.get("user_email") or "").strip().lower()
    return email in settings.internal_test_email_allowlist


def _normalise_topic(message: str) -> str:
    topic = " ".join(message.split())
    if len(topic) <= _TOPIC_MAX:
        return topic
    shortened = topic[:_TOPIC_MAX].rsplit(" ", 1)[0].strip()
    return shortened or topic[:_TOPIC_MAX]


def _source_urls(context: str) -> list[str]:
    """Return the exact links emitted by this worker for audit and evaluation."""
    return [
        segment.split(">", 1)[0]
        for segment in context.split("<")[1:]
        if segment.startswith(("http://", "https://")) and ">" in segment
    ]


def _format_results(raw: list[dict], noise_domains: list[str]) -> str:
    """
    Filter noise, deduplicate URLs, and format up to 6 bullets.
    Each bullet preserves the exact source URL for downstream citation.
    Returns an empty string if nothing useful was found.
    """
    seen_urls: set[str] = set()
    bullets: list[str] = []
    normalised_noise_domains = [
        noise.lower().removeprefix("www.") for noise in noise_domains
    ]

    for item in raw:
        href = str(item.get("href") or item.get("url", "")).strip()
        title = (item.get("title") or "").strip()
        body = (item.get("body") or "").strip()

        if not href or not body:
            continue

        try:
            parsed = urlparse(href)
        except ValueError:
            continue
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or len(href) > 500
            or any(character.isspace() or character in "<>" for character in href)
        ):
            continue

        # Deduplicate by URL
        if href in seen_urls:
            continue
        seen_urls.add(href)

        # Filter low-quality domains
        domain = (parsed.hostname or "").lower().removeprefix("www.")
        if any(
            domain == noise or domain.endswith(f".{noise}")
            for noise in normalised_noise_domains
        ):
            continue

        # Truncate for prompt economy
        safe_title = (
            " ".join(
                title.replace("[", "(")
                .replace("]", ")")
                .replace("<", "(")
                .replace(">", ")")
                .split()
            )
            or domain
        )
        safe_body = " ".join(body.replace("<", "(").replace(">", ")").split())
        title_trunc = safe_title[:_TITLE_MAX] + (
            "…" if len(safe_title) > _TITLE_MAX else ""
        )
        body_trunc = safe_body[:_BODY_MAX] + ("…" if len(safe_body) > _BODY_MAX else "")

        bullets.append(f"- {title_trunc} — <{href}>: {body_trunc}")

        if len(bullets) >= 6:
            break

    if not bullets:
        return ""

    return "\n".join(bullets)
