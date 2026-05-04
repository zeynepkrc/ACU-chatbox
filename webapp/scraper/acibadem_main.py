"""
Bounded scraper for public HTML on https://www.acibadem.edu.tr

Curated category seeds are fetched first; each seed may enqueue **one hop** of
same-site HTML links (fakülte / bölüm / öğretim üyesi profilleri dahil) without
deeper recursion or open-ended crawling. Total HTTP attempts are capped by
``max_pages`` (default 30); non-HTML assets and high-risk paths are skipped.
"""

from __future__ import annotations

import random
import re
import time
from collections import deque
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from django.db import transaction

from chat.models import UniversityContent

# Curated seeds by theme (expand carefully). Order preserved when flattening.
CATEGORY_SEEDS: dict[str, tuple[str, ...]] = {
    "university_about": (
        "https://www.acibadem.edu.tr/",
        "https://www.acibadem.edu.tr/universite",
        "https://www.acibadem.edu.tr/universite/hakkinda",
        "https://www.acibadem.edu.tr/universite/hakkinda/kisisel-verilerin-korunmasi",
    ),
    "faculties_programs": (
        "https://www.acibadem.edu.tr/universite",
    ),
    "student_admission": (
        "https://www.acibadem.edu.tr/",
    ),
    "student_life_campus": (
        "https://www.acibadem.edu.tr/",
    ),
    "contact": (
        "https://www.acibadem.edu.tr/iletisim",
    ),
    "news": (
        "https://www.acibadem.edu.tr/haberler/times-higher-education-asya-universite-siralamasi-aciklandi",
        "https://www.acibadem.edu.tr/haberler/prof-dr-murat-bas-kronobeslenmede-saat-2200deki-ogun-saat-1800dekinden-ayni-degil",
        "https://www.acibadem.edu.tr/haberler/prof-dr-javad-parvizinin-phage4dair-projesi-avrupada-desteklendi",
        "https://www.acibadem.edu.tr/haberler/codehub-2026-ogrenci-teknoloji-zirvesi-universitemizde-gerceklestirildi",
        "https://www.acibadem.edu.tr/haberler/isik-sacan-bakterilerle-hizli-tani-hastaya-uygun-antibiyotik-dakikalar-icinde-saptaniyor",
        "https://www.acibadem.edu.tr/haberler/universitemizde-akademik-yazimda-yapay-zeka-kullanimi-paneli-duzenlendi",
        "https://www.acibadem.edu.tr/haberler/fizyoterapi-ve-rehabilitasyon-bolumumuz-5-yilligina-akredite-edildi",
        "https://www.acibadem.edu.tr/haberler/prof-dr-guralp-onur-ceyhan-cost-aksiyonu-calisma-grubu-uyeligine-atandi",
        "https://www.acibadem.edu.tr/haberler/dunya-daha-ofkeli-degil-kaygi-ve-uzuntu-artiyor",
        "https://www.acibadem.edu.tr/haberler/acibadem-universitesi-balkan-universiteler-birligi-uyeligini-resmen-imzaladi",
    ),
    "announcements": (
        "https://www.acibadem.edu.tr/duyurular/fen-bilimleri-enstitusu-tez-savunma-sinavina-girecek-ogrenciler-mayis",
        "https://www.acibadem.edu.tr/duyurular/saglik-bilimleri-enstitusu-tez-savunma-sinavina-girecek-ogrenciler-nisan/mayis",
        "https://www.acibadem.edu.tr/duyurular/acibadem-mehmet-ali-aydinlar-universitesi-rektorlugunden-22",
        "https://www.acibadem.edu.tr/duyurular/erasmus-bip-kisa-donem-hareketlilik-tip-fakultesi-0",
        "https://www.acibadem.edu.tr/duyurular/saglik-bilimleri-fakultesi-beslenme-ve-diyetetik-turkce-bolumu-arastirma-gorevlisi-kadrosuna-atanmaya-hak-kazanan-adaylarin-listesi",
    ),
    "events": (
        "https://www.acibadem.edu.tr/etkinlikler/eureka-programlari-ve-kademeli-cagrilar-bilgi-gunu",
        "https://www.acibadem.edu.tr/etkinlikler/zorunlu-saglamlik-sakatlik-ve-bakimin-politikasi",
        "https://www.acibadem.edu.tr/etkinlikler/sanal-kumarin-perde-arkasi",
        "https://www.acibadem.edu.tr/etkinlikler/neuropeptide-signaling-large-scale-cortical-dynamics-mouse-models-neurodevelopmental-disorders",
        "https://www.acibadem.edu.tr/etkinlikler/bilimsel-eczacilik-gunu-beyaz-onluk-toreni",
        "https://www.acibadem.edu.tr/etkinlikler/mezuniyet-projeleri-fuari-2026",
        "https://www.acibadem.edu.tr/etkinlikler/hemsirelik-egitiminde-simulasyon-uygulamalari-2026",
        "https://www.acibadem.edu.tr/etkinlikler/aegean-molecular-biology-symposium",
    ),
}

# Legacy default used when explicit ``urls=`` is passed (no discovery).
DEFAULT_SEED_URLS: tuple[str, ...] = tuple(
    dict.fromkeys(
        url
        for group in CATEGORY_SEEDS.values()
        for url in group
    )
)

_ALLOWED_HOST = "www.acibadem.edu.tr"

_BLOCKED_PATH_SNIPPETS: frozenset[str] = frozenset(
    {
        "/wp-admin",
        "/wp-login",
        "/admin",
        "/login",
        "/logout",
        "/signin",
        "/signup",
        "/register",
        "/kayit",
        "/hesabim",
        "/account",
        "/cart",
        "/checkout",
        "/payment",
        "/odeme",
        "/sso",
        "/oauth",
        "/callback",
        "/arama",
        "/search",
        "/api/",
        "/ajax/",
        "/.well-known/",
    }
)

_BLOCKED_QUERY_SNIPPETS: frozenset[str] = frozenset(
    ("search=", "q=", "query=", "filter=", "sort=", "utm_")
)

_BLOCKED_SUFFIXES: tuple[str, ...] = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".mjs",
    ".zip",
    ".rar",
    ".7z",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".mp4",
    ".mp3",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)

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

_MIN_TEXT_CHARS = 220
_MIN_WORDS = 32


def _canonical_acu_url(raw: str, base: str = "https://www.acibadem.edu.tr/") -> str | None:
    joined = urljoin(base, raw)
    parsed = urlparse(joined)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.netloc or "").lower()
    if host == "acibadem.edu.tr":
        host = _ALLOWED_HOST
    elif host.startswith("www."):
        host = host[4:]
        if host == "acibadem.edu.tr":
            host = _ALLOWED_HOST
    if host != _ALLOWED_HOST:
        return None
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse(("https", _ALLOWED_HOST, path, "", parsed.query, ""))


def _is_fetchable_html_url(url: str) -> bool:
    lower = url.lower()
    path = urlparse(url).path.lower()
    if any(lower.endswith(sfx) for sfx in _BLOCKED_SUFFIXES):
        return False
    if any(snippet in path for snippet in _BLOCKED_PATH_SNIPPETS):
        return False
    query = urlparse(url).query.lower()
    if any(snippet in query for snippet in _BLOCKED_QUERY_SNIPPETS):
        return False
    return True


def _delay_between_requests() -> None:
    time.sleep(random.uniform(1.5, 2.0))


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


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def _is_insufficient_content(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < _MIN_TEXT_CHARS:
        return True
    return _word_count(stripped) < _MIN_WORDS


def _collect_same_site_links(soup: BeautifulSoup, page_url: str) -> list[str]:
    found: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = str(tag.get("href", "")).strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        if href.lower().startswith("mailto:") or href.lower().startswith("tel:"):
            continue
        canon = _canonical_acu_url(href, base=page_url)
        if not canon or not _is_fetchable_html_url(canon):
            continue
        found.add(canon)
    return sorted(found)


def _fetch_page(session: requests.Session, url: str) -> tuple[str, str, str, list[str]]:
    canon = _canonical_acu_url(url)
    if not canon:
        raise ValueError(f"URL not allowed (off-site or invalid): {url}")
    if not _is_fetchable_html_url(canon):
        raise ValueError(f"URL blocked by fetch policy: {canon}")
    response = session.get(canon, timeout=45, allow_redirects=True)
    response.raise_for_status()
    final = _canonical_acu_url(response.url)
    if not final:
        raise ValueError(f"Redirected off allowed host: {response.url}")
    ctype = (response.headers.get("Content-Type") or "").lower()
    if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
        raise ValueError(f"Non-HTML content ({ctype or 'unknown'})")
    soup = BeautifulSoup(response.content, "html.parser")
    title = _extract_title(soup)[:512]
    # Collect links before stripping structural tags so faculty/program links remain.
    discovered = _collect_same_site_links(soup, final)
    body_text = _html_to_clean_text(soup)
    return final, title, body_text, discovered


def _ordered_seed_urls() -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for urls in CATEGORY_SEEDS.values():
        for u in urls:
            c = _canonical_acu_url(u)
            if not c or c in seen:
                continue
            seen.add(c)
            ordered.append(c)
    return ordered


def run(max_pages: int = 30, urls: list[str] | None = None) -> dict[str, Any]:
    """
    Fetch public Acıbadem pages and upsert ``UniversityContent`` rows (``source=main``).

    * Default: curated seeds + one-hop same-site links from **seed** pages only,
      bounded by ``max_pages`` total HTTP attempts.
    * ``urls`` optional: explicit list only (no discovery), still bounded by ``max_pages``.

    Returns ``{"urls": attempted, "saved": saved_or_updated, "errors": [...]}``.
    """
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")

    session = requests.Session()
    session.headers.update(_DEFAULT_HEADERS)

    stats: dict[str, Any] = {"urls": 0, "saved": 0, "errors": []}

    if urls is not None:
        explicit: list[str] = []
        seen_explicit: set[str] = set()
        for u in urls:
            c = _canonical_acu_url(u)
            if c and c not in seen_explicit:
                seen_explicit.add(c)
                explicit.append(c)
        queue: deque[str] = deque(explicit)
        visited: set[str] = set()
        index = 0
        while queue and stats["urls"] < max_pages:
            if index > 0:
                _delay_between_requests()
            index += 1
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)
            stats["urls"] += 1
            try:
                final_url, title, body_text, _ = _fetch_page(session, url)
                if _is_insufficient_content(body_text):
                    stats["errors"].append(
                        {"url": final_url, "error": "Skipped: content too short after cleaning"}
                    )
                    continue
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

    ordered_seeds = _ordered_seed_urls()
    scheduled: set[str] = set(ordered_seeds)
    seed_queue: deque[str] = deque(ordered_seeds)
    tier1_queue: deque[str] = deque()
    attempted_urls: set[str] = set()
    request_index = 0

    def _schedule_tier1(link: str) -> None:
        if link in scheduled:
            return
        if not _is_fetchable_html_url(link):
            return
        scheduled.add(link)
        tier1_queue.append(link)

    def _run_attempt(url: str, allow_discovery: bool) -> None:
        nonlocal request_index
        if stats["urls"] >= max_pages:
            return
        if url in attempted_urls:
            return
        if request_index > 0:
            _delay_between_requests()
        request_index += 1
        attempted_urls.add(url)
        stats["urls"] += 1
        try:
            final_url, title, body_text, discovered = _fetch_page(session, url)
            if allow_discovery:
                for link in discovered:
                    _schedule_tier1(link)
            if _is_insufficient_content(body_text):
                stats["errors"].append(
                    {"url": final_url, "error": "Skipped: content too short after cleaning"}
                )
                return
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

    while stats["urls"] < max_pages:
        if seed_queue:
            _run_attempt(seed_queue.popleft(), allow_discovery=True)
            continue
        if tier1_queue:
            _run_attempt(tier1_queue.popleft(), allow_discovery=False)
            continue
        break

    return stats
