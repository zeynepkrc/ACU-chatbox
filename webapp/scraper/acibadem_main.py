"""
Responsible, bounded scraper for public pages on https://www.acibadem.edu.tr

Fetches only an explicit allow-listed set of URLs (no recursive crawling).
"""

from __future__ import annotations

import random
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.db import transaction

from chat.models import UniversityContent

# Small, explicit seed list of public pages (expand over time as needed).
DEFAULT_SEED_URLS: tuple[str, ...] = (
    "https://www.acibadem.edu.tr/",
    "https://www.acibadem.edu.tr/haberler/times-higher-education-asya-universite-siralamasi-aciklandi",
    "https://www.acibadem.edu.tr/duyurular/acibadem-mehmet-ali-aydinlar-universitesi-rektorlugunden-22",
)

_ALLOWED_HOST_SUFFIXES = ("acibadem.edu.tr",)

_REMOVE_TAGS = frozenset(
    {
        "script",
        "style",
        "nav",
        "header",
        "footer",
        "noscript",
        "svg",
        "iframe",
        "template",
        "form",
    }
)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "ACU-chatbot/0.1 (+https://www.acibadem.edu.tr; university content ingestion; "
        "contact: webmaster)"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


def _is_allowed_acibadem_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return any(host == s or host.endswith("." + s) for s in _ALLOWED_HOST_SUFFIXES)


def _delay_between_requests() -> None:
    time.sleep(random.uniform(1.0, 2.0))


def _extract_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return soup.title.get_text(strip=True)
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return str(og["content"]).strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    return ""


def _strip_noise(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": "navigation"}):
        tag.decompose()


def _html_to_clean_text(soup: BeautifulSoup) -> str:
    _strip_noise(soup)
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _fetch_page(session: requests.Session, url: str) -> tuple[str, str, str]:
    if not _is_allowed_acibadem_url(url):
        raise ValueError(f"Refusing to fetch non-Acıbadem URL: {url}")
    response = session.get(url, timeout=45, allow_redirects=True)
    response.raise_for_status()
    final_url = response.url
    if not _is_allowed_acibadem_url(final_url):
        raise ValueError(f"Redirected outside allowed host: {final_url}")
    soup = BeautifulSoup(response.content, "html.parser")
    title = _extract_title(soup)[:512]
    body_text = _html_to_clean_text(soup)
    return final_url, title, body_text


def run(urls: list[str] | None = None) -> dict[str, Any]:
    """
    Fetch allow-listed public pages and upsert into UniversityContent (source=main).

    Intended for manual invocation from ``manage.py shell`` until the Z7 command exists.
    """
    targets = list(urls) if urls is not None else list(DEFAULT_SEED_URLS)
    for u in targets:
        if not _is_allowed_acibadem_url(u):
            raise ValueError(f"URL not on allowed Acıbadem hosts: {u}")

    session = requests.Session()
    session.headers.update(_DEFAULT_HEADERS)

    stats: dict[str, Any] = {
        "urls": len(targets),
        "saved": 0,
        "errors": [],
    }

    for index, url in enumerate(targets):
        if index > 0:
            _delay_between_requests()
        try:
            final_url, title, body_text = _fetch_page(session, url)
            with transaction.atomic():
                UniversityContent.objects.update_or_create(
                    source_url=final_url,
                    defaults={
                        "source": UniversityContent.Source.MAIN,
                        "title": title,
                        "content_text": body_text,
                    },
                )
            stats["saved"] += 1
        except Exception as exc:
            stats["errors"].append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    return stats
