"""
AVESİS (https://avesis.acibadem.edu.tr) public araştırmacı profillerinden
öncelikli bölüm/fakülte akademik kadro özetleri üretir.

* Giriş yok; ``cvpages.xml`` site haritasından profil URL'leri okunur.
* ``source`` Django modelinde yalnızca ``main`` / ``bologna`` olduğu için ``main`` kullanılır.
* ``source_url``: sabit sentetik anahtarlar (duplicate yok, ``update_or_create``).
"""

from __future__ import annotations

import random
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.db import transaction

from chat.models import UniversityContent

_AVESIS_BASE = "https://avesis.acibadem.edu.tr"
_SITEMAP_CV = f"{_AVESIS_BASE}/cvpages.xml"

# Sentetik ama tek ve kararlı ``source_url`` (gerçek HTTP rotası olması gerekmez).
SOURCE_URL_CS = f"{_AVESIS_BASE}/ingestion/kadro/bilgisayar-muhendisligi"
SOURCE_URL_FENS = f"{_AVESIS_BASE}/ingestion/kadro/muhendislik-ve-doga-bilimleri-fakultesi"

_DEFAULT_HEADERS = {
    "User-Agent": (
        "ACU-chatbot/0.1 (+https://avesis.acibadem.edu.tr; public academic staff "
        "aggregation; contact: webmaster)"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

_FOLD_TR = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "Ç": "c",
        "Ğ": "g",
        "İ": "i",
        "Ö": "o",
        "Ş": "s",
        "Ü": "u",
    }
)


def _fold(s: str) -> str:
    return s.translate(_FOLD_TR).lower()


def _delay_between_requests() -> None:
    time.sleep(random.uniform(1.5, 2.0))


def _parse_profile(html: bytes, profile_url: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    name_line = h1.get_text(" ", strip=True) if h1 else ""
    if not name_line and soup.title and soup.title.string:
        name_line = soup.title.get_text(strip=True).split("|")[0].strip()
    text = soup.get_text("\n", strip=True)
    dept_line = ""
    for line in text.split("\n"):
        line = line.strip()
        if len(line) < 12 or len(line) > 320:
            continue
        lf = _fold(line)
        if ("fakulte" in lf or "faculty" in lf) and ("bolum" in lf or "department" in lf or "ana bilim" in lf):
            dept_line = line
            break
    if not dept_line:
        for line in text.split("\n"):
            line = line.strip()
            lf = _fold(line)
            if "fakulte" in lf or "faculty" in lf:
                if 15 < len(line) < 320:
                    dept_line = line
                    break
    return name_line, dept_line or ""


def _has_rank(name_line: str, full_fold: str) -> bool:
    blob = f"{name_line}\n{full_fold}"
    return any(
        m in blob
        for m in (
            "prof. dr.",
            "doc. dr.",
            "dr. ogr. uyesi",
            "ogr. gor.",
            "ars. gor.",
            "ogretim gorevlisi",
            "assoc. prof",
            "asst. prof",
            "prof.",
        )
    )


def _is_cs_department(full_fold: str) -> bool:
    return "bilgisayar muhendisligi" in full_fold or "computer engineering" in full_fold


def _is_fens_faculty(full_fold: str) -> bool:
    return (
        "muhendislik ve doga bilimleri fakultesi" in full_fold
        or "faculty of engineering and natural sciences" in full_fold
    )


@dataclass
class _Bucket:
    source_url: str
    title: str
    predicate: Callable[[str, str, str], bool]
    lines: list[str] = field(default_factory=list)


def _bucket_append(bucket: _Bucket, name_line: str, dept_line: str, profile_url: str) -> None:
    block = (
        f"{len(bucket.lines) + 1}) {name_line}\n"
        f"   Birim: {dept_line or '(birim metni yok)'}\n"
        f"   Profil: {profile_url}\n"
    )
    bucket.lines.append(block)


def _flush_bucket(bucket: _Bucket, stats: dict[str, Any]) -> None:
    if not bucket.lines:
        return
    raw = (
        "Kaynak: AVESİS (https://avesis.acibadem.edu.tr) — public araştırmacı profilleri.\n\n"
        + "\n".join(bucket.lines)
    )
    with transaction.atomic():
        UniversityContent.objects.update_or_create(
            source_url=bucket.source_url,
            defaults={
                "source": UniversityContent.Source.MAIN,
                "title": bucket.title,
                "content_text": raw,
                "raw_text": raw,
            },
        )
    stats["saved"] += 1
    stats["academic_staff_pages"] += 1


def ingest_avesis_academic_staff(
    session: requests.Session,
    stats: dict[str, Any],
    profile_budget: int,
) -> None:
    """
    ``stats`` içinde ``urls``, ``saved``, ``skipped``, ``academic_staff_pages``, ``errors``
    alanlarını günceller. ``profile_budget``: sitemap dışında çekilecek profil sayısı üst sınırı.
    """
    if profile_budget < 1:
        return

    buckets = (
        _Bucket(
            source_url=SOURCE_URL_CS,
            title="Akademik Kadro - Bilgisayar Mühendisliği",
            predicate=lambda nf, df, ff: _is_cs_department(ff) and _has_rank(nf, ff),
        ),
        _Bucket(
            source_url=SOURCE_URL_FENS,
            title="Akademik Kadro - Mühendislik ve Doğa Bilimleri Fakültesi",
            predicate=lambda nf, df, ff: _is_fens_faculty(ff) and _has_rank(nf, ff),
        ),
    )

    session.headers.update(_DEFAULT_HEADERS)

    try:
        if stats.get("urls", 0) > 0:
            _delay_between_requests()
        r = session.get(_SITEMAP_CV, timeout=60)
        r.raise_for_status()
        stats["urls"] = stats.get("urls", 0) + 1
        root = ET.fromstring(r.content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs: list[str] = []
        for url_el in root.findall("sm:url", ns):
            loc_el = url_el.find("sm:loc", ns)
            if loc_el is not None and (loc_el.text or "").strip():
                locs.append(loc_el.text.strip())
        rng = random.Random(42)
        rng.shuffle(locs)
    except Exception as exc:
        stats["errors"].append({"url": _SITEMAP_CV, "error": f"{type(exc).__name__}: {exc}"})
        return

    fetched = 0
    for loc in locs:
        if fetched >= profile_budget:
            break
        parsed = urlparse(loc)
        if parsed.netloc and "avesis.acibadem.edu.tr" not in parsed.netloc.lower():
            continue
        path = (parsed.path or "").strip("/")
        if not path or path in ("search", "home", "error", "proxy"):
            continue
        if stats.get("urls", 0) > 0:
            _delay_between_requests()
        try:
            pr = session.get(loc, timeout=45, allow_redirects=True)
            pr.raise_for_status()
            stats["urls"] = stats.get("urls", 0) + 1
            fetched += 1
            ctype = (pr.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
                stats["skipped"] += 1
                continue
            name_line, dept_line = _parse_profile(pr.content, loc)
            full_fold = _fold(pr.text or "")
            if not name_line or not _has_rank(name_line, full_fold):
                stats["skipped"] += 1
                continue
            for b in buckets:
                if b.predicate(name_line, dept_line, full_fold):
                    _bucket_append(b, name_line, dept_line, loc)
        except Exception as exc:
            stats["errors"].append({"url": loc, "error": f"{type(exc).__name__}: {exc}"})

    for b in buckets:
        _flush_bucket(b, stats)
