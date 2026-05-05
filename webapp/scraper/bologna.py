"""
OBS / Bologna public — tek canonical ``index.aspx`` + program iframe (GET + BeautifulSoup).

Yalnızca elle ``run()`` çağrıldığında çalışır. İçerik ana sitede ``<iframe>`` ile geldiği için
iframe URL’si ayrıca çekilir; ``UniversityContent.source_url`` her zaman PDF’teki canonical URL’dir.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.db import transaction

from chat.models import UniversityContent
from scraper import utils

_OBS_HOST = "obs.acibadem.edu.tr"

# PDF: Bilgisayar Mühendisliği Bologna public (canonical ``source_url``).
BOLOGNA_CANONICAL_URL = (
    "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx"
    "?lang=tr&curOp=showPac&curUnit=14&curSunit=6246"
)

DEFAULT_PROGRAM_TITLE = "Computer Engineering Bologna Program"

# Bologna sayfaları kısa görünebilir veya CMS etiketleri farklıdır — ana siteden daha düşük eşik.
_MIN_COMBINED_CHARS = 35
_MIN_COMBINED_WORDS = 4
_MIN_CONTENT_TEXT_CHARS = 20

_OBS_BLOCKED_SNIPPETS: frozenset[str] = frozenset(
    (
        "/login",
        "login.aspx",
        "giris",
        "studentlogin",
        "password",
        "secure",
        "auth",
        "oauth",
    )
)


def _is_allowed_obs_url(url: str) -> bool:
    nu = utils.normalize_obs_url(url, allowed_host=_OBS_HOST)
    if not nu:
        return False
    if utils.is_blocked_file_extension(nu):
        return False
    pl = urlparse(nu).path.lower()
    ql = urlparse(nu).query.lower()
    if any(s in pl for s in _OBS_BLOCKED_SNIPPETS) or any(s in ql for s in ("returnurl=", "ticket=")):
        return False
    if "lang=en" in ql or "culture=en" in ql:
        return False
    return True


def _light_strip(soup: BeautifulSoup) -> None:
    """Sadece script/style/noscript — ``nav``/``header`` kaldırma iframe içeriğini silmesin."""
    for tag in soup.find_all(("script", "style", "noscript")):
        tag.decompose()


def _plain_after_light_strip(html: bytes) -> str:
    soup = BeautifulSoup(html, "html.parser")
    _light_strip(soup)
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _tables_to_text(soup: BeautifulSoup) -> str:
    blocks: list[str] = []
    for table in soup.find_all("table"):
        rows_out: list[str] = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                rows_out.append(" | ".join(cells))
        if rows_out:
            blocks.append("\n".join(rows_out))
    return "\n\n".join(blocks).strip()


def _options_to_text(soup: BeautifulSoup) -> str:
    lines: list[str] = []
    for sel in soup.find_all("select"):
        for opt in sel.find_all("option"):
            t = opt.get_text(strip=True)
            if t:
                lines.append(t)
    return "\n".join(lines).strip()


def _div_span_dump(soup: BeautifulSoup, *, limit: int = 400) -> str:
    """div/span iç metinleri (kısa bloklar) raw_text için — çok uzun tekrarları atla."""
    seen: set[str] = set()
    out: list[str] = []
    for tag in soup.find_all(("div", "span"), limit=limit):
        t = tag.get_text(" ", strip=True)
        if not t or len(t) < 3:
            continue
        if len(t) > 800:
            t = t[:800] + "…"
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return "\n".join(out).strip()


def _structured_tag_walk(soup: BeautifulSoup) -> str:
    """table / tr / td / th / option / label vb. metinleri satır satır (raw_text tamamlayıcı)."""
    lines: list[str] = []
    for tag in soup.find_all(("table", "tr", "td", "th", "option", "label", "textarea")):
        t = tag.get_text(" ", strip=True)
        if t and len(t) < 3000:
            lines.append(t)
    return "\n".join(lines).strip()


def _iframe_document_url(parent_soup: BeautifulSoup, base_url: str) -> str | None:
    iframe = parent_soup.find("iframe", id="IFRAME1") or parent_soup.find("iframe")
    if not iframe:
        return None
    src = (iframe.get("src") or "").strip()
    if not src:
        return None
    return urljoin(base_url, src)


def _resolve_program_title(soup: BeautifulSoup) -> str:
    raw = utils.sanitize_display_title(utils.extract_page_title(soup))
    if len(raw.strip()) >= 3:
        return raw[:512]
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if len(t.strip()) >= 3:
            return utils.sanitize_display_title(t)[:512]
    for tag in soup.find_all(["h2", "h3"]):
        t = tag.get_text(" ", strip=True)
        if len(t.strip()) >= 10:
            return t[:512]
    plain = soup.get_text("\n", strip=True)
    for line in plain.splitlines():
        line = line.strip()
        if 15 <= len(line) <= 240:
            return line[:512]
    return ""


def _ingest_canonical_page(
    session: requests.Session,
    canonical: str,
    errors: list[Any],
) -> tuple[str, str, str] | None:
    resp = utils.safe_get(session, canonical)
    if resp.status_code != 200:
        errors.append({"url": canonical, "error": f"HTTP {resp.status_code}: beklenen 200 değil"})
        return None

    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
        errors.append({"url": canonical, "error": f"Beklenmeyen Content-Type: {ctype!r}"})
        return None

    parent_html = resp.content
    parent_soup = BeautifulSoup(parent_html, "html.parser")
    parent_plain = _plain_after_light_strip(parent_html)

    child_url = _iframe_document_url(parent_soup, canonical)
    child_plain = ""
    child_tables = ""
    child_options = ""
    child_struct = ""
    child_div_span = ""
    title = ""

    if child_url and _is_allowed_obs_url(child_url):
        utils.delay_between_requests()
        try:
            r2 = utils.safe_get(session, child_url)
            if r2.status_code != 200:
                errors.append({"url": child_url, "error": f"iframe GET HTTP {r2.status_code}"})
            else:
                child_html = r2.content
                child_soup = BeautifulSoup(child_html, "html.parser")
                title = _resolve_program_title(child_soup)
                child_plain = _plain_after_light_strip(child_html)
                child_tables = _tables_to_text(BeautifulSoup(child_html, "html.parser"))
                child_options = _options_to_text(child_soup)
                child_struct = _structured_tag_walk(child_soup)
                child_div_span = _div_span_dump(child_soup)
        except Exception as exc:
            errors.append({"url": child_url, "error": f"{type(exc).__name__}: {exc}"})
    else:
        if not child_url:
            errors.append({"url": canonical, "error": "iframe src bulunamadı (IFRAME1)"})
        else:
            errors.append({"url": canonical, "error": f"iframe URL izin listesinde değil: {child_url}"})

    if not (title or "").strip():
        title = _resolve_program_title(parent_soup)
    if not (title or "").strip() or len((title or "").strip()) < 3:
        title = DEFAULT_PROGRAM_TITLE

    combined_for_quality = "\n\n".join(
        p
        for p in (
            parent_plain,
            child_plain,
            child_tables,
            child_options,
            child_struct,
            child_div_span,
        )
        if p
    ).strip()

    if len(combined_for_quality) < _MIN_COMBINED_CHARS:
        errors.append(
            {
                "url": canonical,
                "error": (
                    f"Birleşik metin kısa ({len(combined_for_quality)} karakter < {_MIN_COMBINED_CHARS}); "
                    "yine de kayda izin veriliyor olabilir"
                ),
            }
        )
    words = len(re.findall(r"\w+", combined_for_quality, flags=re.UNICODE))
    if words < _MIN_COMBINED_WORDS and combined_for_quality:
        errors.append(
            {
                "url": canonical,
                "error": f"Kelime sayısı düşük ({words} < {_MIN_COMBINED_WORDS})",
            }
        )

    # Çok kısa / boş: gerçekten kaydedilecek bir şey yoksa çık.
    if len(combined_for_quality.strip()) < 12 or words < 2:
        errors.append(
            {"url": canonical, "error": "Yetersiz içerik (iframe ve kabuk metni neredeyse boş)"}
        )
        return None

    content_text = (child_plain or combined_for_quality).strip()
    if parent_plain and len(parent_plain) > 40:
        header = "Bologna menü (index.aspx):\n" + parent_plain[:2000].strip()
        content_text = header + "\n\n---\n\nProgram / içerik:\n" + content_text

    if len(content_text) < _MIN_CONTENT_TEXT_CHARS:
        content_text = combined_for_quality or content_text

    raw_parts: list[str] = [
        f"Canonical URL (source_url): {canonical}",
    ]
    if child_url:
        raw_parts.append(f"Program iframe URL: {child_url}")
    if parent_plain:
        raw_parts.append("---\nKabuk / menü (index.aspx, hafif strip)\n---\n" + parent_plain.strip())
    if child_tables:
        raw_parts.append("---\nTablolar (iframe)\n---\n" + child_tables)
    if child_options:
        raw_parts.append("---\nSelect / option (iframe)\n---\n" + child_options)
    if child_struct:
        raw_parts.append("---\nYapısal etiket metni table/tr/td/th/option/label (iframe)\n---\n" + child_struct)
    if child_div_span:
        raw_parts.append("---\nDiv / span metin örnekleri (iframe)\n---\n" + child_div_span)
    if child_plain:
        raw_parts.append("---\nTam düz metin (iframe, hafif strip)\n---\n" + child_plain.strip())
    raw_text = "\n\n".join(raw_parts).strip()

    return title[:512], content_text, raw_text


def run(max_pages: int = 20, reset: bool = False) -> dict[str, Any]:
    """
    Tek canonical Bologna URL işlenir; ``max_pages`` API uyumluluğu için korunur (≥1).

    ``reset=True``: yalnızca ``source=bologna`` satırlarını siler.
    """
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")

    stats: dict[str, Any] = utils.stats_dict("bologna")

    if reset:
        with transaction.atomic():
            UniversityContent.objects.filter(source=UniversityContent.Source.BOLOGNA).delete()

    canonical = utils.normalize_obs_url(BOLOGNA_CANONICAL_URL, allowed_host=_OBS_HOST)
    if not canonical or not _is_allowed_obs_url(canonical):
        stats["errors"].append({"url": BOLOGNA_CANONICAL_URL, "error": "Canonical URL normalize / izin hatası"})
        return stats

    session = requests.Session()
    session.headers.update(utils.DEFAULT_HEADERS)

    # Tek hedef sayfa; ``urls`` işlenen canonical girişi (max_pages bütçesi ile aynı sayıda raporlanabilir).
    stats["urls"] = 1
    try:
        bundle = _ingest_canonical_page(session, canonical, stats["errors"])
        if bundle is None:
            stats["skipped"] = 1
            return stats
        title, content_text, raw_text = bundle
        with transaction.atomic():
            UniversityContent.objects.update_or_create(
                source_url=canonical,
                defaults={
                    "source": UniversityContent.Source.BOLOGNA,
                    "title": title[:512],
                    "content_text": content_text,
                    "raw_text": raw_text,
                },
            )
        stats["saved"] = 1
    except Exception as exc:
        stats["errors"].append({"url": canonical, "error": f"{type(exc).__name__}: {exc}"})
        stats["skipped"] = 1

    return stats
