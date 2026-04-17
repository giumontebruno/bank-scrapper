from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape

from bs4 import BeautifulSoup, Tag


@dataclass
class PromoBlock:
    title: str | None
    text: str
    source_type: str
    source_url: str


def html_promo_blocks(html: str, source_url: str, source_type: str) -> list[PromoBlock]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[Tag] = []
    selectors = [
        "article",
        "section",
        "li",
        "div.card",
        "div.promo",
        "div.item",
        "div.beneficio",
        "div[class*='promo']",
        "div[class*='benef']",
    ]
    for selector in selectors:
        candidates.extend(soup.select(selector))

    blocks: list[PromoBlock] = []
    seen_texts: set[str] = set()
    for candidate in candidates:
        text = candidate.get_text("\n", strip=True)
        if len(text) < 40:
            continue
        compact = _compact(text)
        if compact in seen_texts:
            continue
        seen_texts.add(compact)
        title = _extract_title(candidate, text)
        blocks.append(PromoBlock(title=title, text=text, source_type=source_type, source_url=source_url))

    if blocks:
        return blocks

    fallback_text = soup.get_text("\n", strip=True)
    return text_promo_blocks(fallback_text, source_url=source_url, source_type=source_type)


def text_promo_blocks(text: str, source_url: str, source_type: str) -> list[PromoBlock]:
    normalized = text.replace("\r\n", "\n")
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", normalized) if chunk.strip()]
    if len(chunks) == 1:
        chunks = _split_dense_text(chunks[0])

    blocks: list[PromoBlock] = []
    for chunk in chunks:
        if len(chunk) < 12:
            continue
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        title = lines[0] if lines else None
        blocks.append(PromoBlock(title=title, text=chunk, source_type=source_type, source_url=source_url))
    return blocks


def embedded_html_promo_blocks(page_html: str, source_url: str, source_type: str) -> list[PromoBlock]:
    fragments: list[str] = []
    patterns = [
        r'\\"html\\":\\"(.*?)\\",\\"identificadores',
        r'"html":"(.*?)","identificadores',
    ]
    for pattern in patterns:
        fragments.extend(re.findall(pattern, page_html, flags=re.DOTALL))

    blocks: list[PromoBlock] = []
    seen: set[str] = set()
    for fragment in fragments:
        decoded = _decode_embedded_fragment(fragment)
        if "<" not in decoded and ">" not in decoded:
            continue
        soup = BeautifulSoup(decoded, "html.parser")
        text = soup.get_text("\n", strip=True)
        compact = _compact(text)
        if len(text) < 30 or compact in seen:
            continue
        seen.add(compact)
        blocks.extend(text_promo_blocks(text, source_url=source_url, source_type=source_type))
    return blocks


def _extract_title(candidate: Tag, text: str) -> str | None:
    heading = candidate.find(["h1", "h2", "h3", "h4", "strong", "b"])
    if heading:
        heading_text = heading.get_text(" ", strip=True)
        if heading_text:
            return heading_text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0] if lines else None


def _split_dense_text(text: str) -> list[str]:
    markers = re.split(r"(?=(?:PROMOCI[ÓO]N|VIGENCIA|BENEFICIO|DISFRUTA|DISFRUTÁ|[A-Z][A-Z0-9&\-\s]{8,}))", text)
    pieces = [piece.strip() for piece in markers if piece and len(piece.strip()) > 30]
    return pieces or [text]


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _decode_embedded_fragment(fragment: str) -> str:
    try:
        decoded = json.loads(f'"{fragment}"')
    except json.JSONDecodeError:
        decoded = fragment.replace('\\"', '"')
    return unescape(decoded)
