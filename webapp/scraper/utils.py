"""
Ortak scraper yardımcıları: URL normalize, güvenli HTTP, HTML→düz metin.
"""

from __future__ import annotations

import random
import re
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

DEFAULT_HEADERS = {
    "User-Agent": (
        "ACU-chatbot/0.1 (university public content; contact: webmaster; "
        "+https://www.acibadem.edu.tr)"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.2",
}

_STRIP_QUERY_KEYS = frozenset(
    {"gclid", "fbclid", "mc_cid", "mc_eid", "ref", "_ga", "gid"}
)

_BLOCKED_SUFFIXES: tuple[str, ...] = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".css",
    ".js",
    ".mjs",
    ".zip",
    ".rar",
    ".doc",
    ".docx",
)


def delay_between_requests(min_s: float = 1.5, max_s: float = 2.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def safe_get(session: requests.Session, url: str, *, timeout: int = 45) -> requests.Response:
    """requests.get + timeout; çağıran delay uygular."""
    return session.get(url, timeout=timeout, allow_redirects=True)


def _strip_tracking_query(parsed) -> str:
    kept: list[tuple[str, str]] = []
    for key, val in parse_qsl(parsed.query, keep_blank_values=True):
        kl = key.lower()
        if kl.startswith("utm_") or kl in _STRIP_QUERY_KEYS:
            continue
        kept.append((key, val))
    return urlencode(kept) if kept else ""


def normalize_main_site_url(url: str | None, *, allowed_host: str) -> str | None:
    """www ana site: fragment yok, path slash, tracking query temiz."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.netloc or "").lower()
    if host in ("acibadem.edu.tr", "www.acibadem.edu.tr"):
        host = allowed_host
    if host != allowed_host:
        return None
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = _strip_tracking_query(parsed)
    return urlunparse(("https", allowed_host, path, "", query, ""))


def normalize_obs_url(url: str | None, *, allowed_host: str) -> str | None:
    if not url:
        return None
    joined = url if url.startswith("http") else urljoin(f"https://{allowed_host}/", url)
    parsed = urlparse(joined)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.netloc or "").lower()
    if host != allowed_host:
        return None
    path = parsed.path or "/"
    query = _strip_tracking_query(parsed)
    return urlunparse(("https", allowed_host, path, "", query, ""))


def is_turkish_public_path(url: str) -> bool:
    pl = (urlparse(url).path or "/").lower()
    if pl == "/en" or pl.startswith("/en/") or "/en/" in pl:
        return False
    ql = (urlparse(url).query or "").lower()
    for needle in ("lang=en", "culture=en", "locale=en", "dil=en"):
        if needle in ql:
            return False
    return True


def is_blocked_file_extension(url: str) -> bool:
    lower = url.lower().split("?", 1)[0]
    return any(lower.endswith(sfx) for sfx in _BLOCKED_SUFFIXES)


def strip_boilerplate_tags(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(("script", "style", "nav", "header", "footer", "noscript", "svg", "iframe")):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": "navigation"}):
        tag.decompose()


def html_to_plain_text(soup: BeautifulSoup) -> str:
    strip_boilerplate_tags(soup)
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def extract_page_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return soup.title.get_text(strip=True)
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return str(og["content"]).strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    return ""


def sanitize_display_title(title: str) -> str:
    """HTML başlığı; bilinen CMS kadro soneklerini kırp."""
    t = (title or "").strip()
    t = re.sub(
        r"(?i)[\s|—–-]*akademik\s+kadro\s+ve\s+öğretim\s+üyeleri\s*$",
        "",
        t,
    ).strip(" —-|–-")
    return t[:512]


def passes_content_quality(title: str, body: str, *, min_chars: int = 220, min_words: int = 32) -> bool:
    if len((title or "").strip()) < 3:
        return False
    stripped = body.strip()
    if len(stripped) < min_chars:
        return False
    words = len(re.findall(r"\w+", stripped, flags=re.UNICODE))
    return words >= min_words


def should_skip_english_page_title(title: str, url: str) -> bool:
    if not is_turkish_public_path(url):
        return True
    tf = title.lower()
    if "acibadem mehmet ali aydinlar university" in tf and "üniversitesi" not in title.lower():
        return True
    if "|" in title:
        right = title.split("|", 1)[-1].lower()
        if "acibadem university" in right and "üniversitesi" not in right:
            return True
    return False


def stats_dict(source: str) -> dict[str, Any]:
    return {"source": source, "urls": 0, "saved": 0, "skipped": 0, "errors": []}
