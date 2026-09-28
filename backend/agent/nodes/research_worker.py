# ─────────────────────────────────────────────────────────────────────────────
# File: backend/agent/nodes/research_worker.py
# Purpose: Phase 1a research worker — queries web search through DDGS for real-world context
#          on the user's topic and returns a formatted bullet list.
#
#          Runs in parallel with rag_worker. Its output (research_context) is
#          injected into the graph_worker and orchestrator_synthesise prompts
#          to ground responses in current real-world practice.
#
#          DDGS is queried synchronously inside asyncio.to_thread() to
#          avoid blocking the event loop. An unavailable provider degrades to
#          book evidence with an explicit status instead of being presented as
#          successful current research.
# Language: Python
# Connects to: agent/state.py, config.py
# Inputs:  AgentState (user_message, send callback)
# Outputs: AgentState update: research_context (formatted bullet string)
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from agent.complexity import is_applied_system_design_request
from agent.state import AgentState
from config import settings


logger = logging.getLogger(__name__)

# Max characters for title and body in each bullet to keep prompts lean
_TITLE_MAX = 80
_BODY_MAX = 600
_TOPIC_MAX = 160
# Pinned DDGS 9.14.4 disables Bing and silently routes that backend to auto.
_SEARCH_BACKEND = "brave"
_SEARCH_FALLBACK = "duckduckgo"
_SEARCH_SAFESEARCH = "on"

_DESIGN_SCAFFOLD = re.compile(
    r"\b(?:multi[- ]agent|agentic|ai[- ]powered|artificial intelligence|ai|"
    r"architecture|system|platform|pipeline|workflow|chatbot|assistant)\b",
    re.IGNORECASE,
)


async def research_worker_node(state: AgentState) -> AgentState:
    """
    Search the requested topic in a background thread and format results
    as a compact bullet list for downstream workers.

    Returns state with research_context and research_status set. On failure,
    downstream nodes degrade explicitly to book-only evidence.
    """
    send = state["send"]
    await send(
        {"type": "worker_status", "worker": "research", "status": "Searching the web…"}
    )

    topic = _normalise_topic(state.get("design_query") or state["user_message"])
    queries = _build_queries(topic)
    # Keep the existing three-query result budget when one topic query suffices.
    result_limit = (
        min(6, settings.research_results_per_query * 3)
        if len(queries) == 1
        else settings.research_results_per_query
    )

    try:
        raw = await asyncio.to_thread(
            _run_ddgs_searches,
            queries,
            result_limit,
        )
    except Exception as exc:
        logger.warning("Web research failed: %s", type(exc).__name__)
        await _send_unavailable(send)
        return {**state, "research_context": "", "research_status": "unavailable"}

    context = _format_results(raw, settings.research_noise_domains)
    if not context:
        logger.warning("Web research returned no source snippets")
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
    return {**state, "research_context": context, "research_status": "ready"}


async def _send_unavailable(send) -> None:
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


def _build_queries(topic: str) -> list[str]:
    """Preserve the requested topic before researching its domain function.

    Terse design prompts otherwise produce three near-duplicate architecture
    searches. Removing only generic solution scaffolding gives the architect
    evidence about the domain's real workflow, decisions, measures, and failure
    modes without asking another model to expand the query.
    """
    if not is_applied_system_design_request(topic):
        return [topic]
    current_year = datetime.now(timezone.utc).year
    domain_topic = _domain_topic(topic)
    return [
        topic,
        f"{domain_topic} operating model workflow decision points KPIs",
        f"{domain_topic} best practices failure modes {current_year}",
    ]


def _domain_topic(topic: str) -> str:
    stripped = _DESIGN_SCAFFOLD.sub(" ", topic)
    stripped = re.sub(r"\s+", " ", stripped).strip(" -:;,.")
    stripped = re.sub(r"^(?:for|to)\s+", "", stripped, flags=re.IGNORECASE)
    return stripped if len(stripped) >= 3 else topic


def _run_ddgs_searches(queries: list[str], results_per_query: int) -> list[dict]:
    """
    Synchronous search through DDGS with one bounded alternate-provider attempt.
    Called inside asyncio.to_thread — must be thread-safe.
    Returns result dicts with their originating query and backend.
    """
    from ddgs import DDGS  # imported lazily — only if research is enabled

    results: list[dict] = []
    with DDGS(timeout=4) as ddg:
        for query in queries:
            try:
                hits = ddg.text(
                    query,
                    max_results=results_per_query,
                    backend=_SEARCH_BACKEND,
                    safesearch=_SEARCH_SAFESEARCH,
                )
                results.extend(
                    {**hit, "query": query, "backend": _SEARCH_BACKEND} for hit in hits
                )
            except Exception as exc:
                logger.warning(
                    "Web search query failed backend=%s error=%s",
                    _SEARCH_BACKEND,
                    type(exc).__name__,
                )
                continue
    if not queries or _format_results(results, settings.research_noise_domains):
        return results

    # Keep the existing query budget, but use another provider when the primary
    # returns no usable sources. Raw hits may all be filtered or lack snippets.
    logger.warning(
        "Web search fallback primary=%s fallback=%s raw_results=%d",
        _SEARCH_BACKEND,
        _SEARCH_FALLBACK,
        len(results),
    )
    try:
        with DDGS(timeout=4) as ddg:
            hits = ddg.text(
                queries[0],
                max_results=results_per_query,
                backend=_SEARCH_FALLBACK,
                safesearch=_SEARCH_SAFESEARCH,
            )
            results.extend(
                {**hit, "query": queries[0], "backend": _SEARCH_FALLBACK}
                for hit in hits
            )
    except Exception as exc:
        logger.warning(
            "Web search fallback failed backend=%s error=%s",
            _SEARCH_FALLBACK,
            type(exc).__name__,
        )
    return results


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

        parsed = urlparse(href)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
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
