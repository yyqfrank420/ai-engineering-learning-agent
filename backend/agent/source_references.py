"""Read source identities from Markdown evidence and explanation blocks."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from markdown_it import MarkdownIt


_MARKDOWN = MarkdownIt("commonmark")
_BARE_URL = re.compile(r"(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)
_BOOK_REFERENCE = re.compile(
    r"\bChapter\s+(?P<chapter>[^\s()\[\]{}]+)\s*,\s*p\.\s*(?P<page>[^\s()\[\]{}]+)"
    r"|\bBook\s*,\s*p\.\s*(?P<book_page>[^\s()\[\]{}]+)"
    r"|[\[(]\s*Chapter\s+(?P<chapter_only>[^\s()\[\]{}]+)\s*[\])]"
    r"|[\[(]\s*(?P<excerpt>Book\s+excerpt)\s*[\])]",
    re.IGNORECASE,
)


def format_book_reference(chapter: int | None, page_number: int | None) -> str:
    """Format only known source locations; missing dimensions have no placeholder."""
    for name, value in (("chapter", chapter), ("page_number", page_number)):
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError(f"{name} must be a positive integer or None")
    if chapter is not None and page_number is not None:
        return f"Chapter {chapter}, p.{page_number}"
    if page_number is not None:
        return f"Book, p.{page_number}"
    if chapter is not None:
        return f"Chapter {chapter}"
    return "Book excerpt"


def canonical_source_url(url: str) -> str | None:
    """Normalize a complete HTTP(S) destination without parsing Markdown fragments."""
    if not re.fullmatch(r'https?://[^\s<>"`]+', url, re.IGNORECASE):
        return None
    try:
        if not urlsplit(url).hostname:
            return None
    except ValueError:
        return None
    return _MARKDOWN.normalizeLink(url)


def source_urls(text: str, *, include_bare: bool = False) -> set[str]:
    """Read link destinations, optionally including bare answer URLs.

    Bare URLs in research snippets do not establish source identity. Code spans
    and code blocks are examples, so they are excluded from citation checks.
    """
    references: set[str] = set()
    for block in _MARKDOWN.parse(text):
        link_depth = 0
        for token in block.children or []:
            if token.type == "link_open":
                link_depth += 1
                href = token.attrGet("href")
                if href is not None and (
                    include_bare or href.lower().startswith(("http://", "https://"))
                ):
                    references.add(canonical_source_url(href) or href)
            elif token.type == "link_close":
                link_depth -= 1
            elif include_bare and token.type == "text" and not link_depth:
                for match in _BARE_URL.finditer(token.content):
                    url = match.group().rstrip(".,;:!?*'\"")
                    while (
                        url
                        and url[-1] in ")]}"
                        and url.count(url[-1])
                        > url.count({")": "(", "]": "[", "}": "{"}[url[-1]])
                    ):
                        url = url[:-1].rstrip(".,;:!?*'\"")
                    if url.lower().startswith("www."):
                        url = "http://" + url
                    references.add(canonical_source_url(url) or url)
    return references


def book_references(text: str, *, include_malformed: bool = True) -> set[str]:
    """Read supported chapter/page notation in visible prose, excluding code."""
    references: set[str] = set()
    for block in _MARKDOWN.parse(text):
        prose = "".join(
            token.content if token.type == "text" else "\n"
            for token in block.children or []
            if token.type in {"text", "code_inline", "softbreak", "hardbreak"}
        )
        for match in _BOOK_REFERENCE.finditer(prose):
            # Retain the whole location token: 299.5 must never match page 299.
            locations = {
                name: value.rstrip(".,;:!")
                for name, value in match.groupdict().items()
                if name != "excerpt" and value is not None
            }
            if not include_malformed and any(
                re.fullmatch(r"[1-9][0-9]*", value) is None
                for value in locations.values()
            ):
                continue
            if "chapter" in locations:
                reference = f"Chapter {locations['chapter']}, p.{locations['page']}"
            elif "book_page" in locations:
                reference = f"Book, p.{locations['book_page']}"
            elif "chapter_only" in locations:
                reference = f"Chapter {locations['chapter_only']}"
            else:
                reference = "Book excerpt"
            references.add(reference)
    return references
