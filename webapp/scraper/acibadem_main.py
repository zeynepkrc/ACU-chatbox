"""
Acıbadem ana web sitesi (https://www.acibadem.edu.tr) — yalnızca public HTML.

* Sadece elle ``run()`` çağrıldığında çalışır (Django AppConfig’te otomatik yok).
* Rastgele tüm site taraması yok; seçilmiş tohum URL listesi + sınırlı sayfa sayısı.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from django.db import transaction

from chat.models import UniversityContent
from scraper import utils

_MAIN_HOST = "www.acibadem.edu.tr"

# 3.2: üniversite, fakülteler, bölümler, kampüs, aday/kabul, duyurular, iletişim (Türkçe).
# Öncelik: fakülte / bölüm / program sayfaları. /en/ yok; haber/etkinlik listesi ağırlığı düşük (tek duyurular girişi).
MAIN_SEED_URLS: tuple[str, ...] = (
    # --- Üniversite & akademik genel ---
    "https://www.acibadem.edu.tr/",
    "https://www.acibadem.edu.tr/universite",
    "https://www.acibadem.edu.tr/universite/hakkinda",
    "https://www.acibadem.edu.tr/akademik",
    "https://www.acibadem.edu.tr/akademik/lisans",
    # --- Tıp Fakültesi ---
    "https://www.acibadem.edu.tr/tip-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/hakkinda",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/vizyon-misyon",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/egitim",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/egitim-alt-yapisi",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/temel-tip-bilimleri",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/bolumler/cerrahi-tip-bilimleri",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/bolumler/dahili-tip-bilimleri",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/mezuniyet-oncesi-tip-egitimi-mote",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/tip-fakultesi-akreditasyon",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/ogrencilerimiz",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/sikca-sorulan-sorular",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/arastirma",
    "https://www.acibadem.edu.tr/akademik/lisans/tip-fakultesi/tipta-uzmanlik-egitimi",
    # --- Eczacılık Fakültesi ---
    "https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/eczacilik-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/hakkinda",
    "https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/arastirma",
    "https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/yonetim",
    "https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/egitim-kurul-ve-komisyonlar",
    "https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/mezuniyet-projeleri",
    "https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/bolumler/temel-eczacilik-bilimleri/analitik-kimya-ad",
    "https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/bolumler/eczacilik-meslek-bilimleri/farmakognozi-ad",
    "https://www.acibadem.edu.tr/akademik/lisans/eczacilik-fakultesi/bolumler/eczacilik-teknolojisi/farmasotik-teknoloji-ad",
    # --- Sağlık Bilimleri Fakültesi & bölümler ---
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/fakulte-hakkinda",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/bolumler",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/bolumler/beslenme-ve-diyetetik",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/bolumler/beslenme-ve-diyetetik/hakkinda",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/bolumler/beslenme-ve-diyetetik/stratejik-plan",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/bolumler/hemsirelik",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/bolumler/hemsirelik/hakkinda",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/bolumler/hemsirelik/kalite-ve-akreditasyon",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/bolumler/saglik-yonetimi",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/bolumler/saglik-yonetimi/hakkinda",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/bolumler/saglik-yonetimi/mufredat",
    "https://www.acibadem.edu.tr/akademik/lisans/saglik-bilimleri-fakultesi/bolumler/fizyoterapi-ve-rehabilitasyon/fizyoterapi-ve-rehabilitasyon",
    # --- Mühendislik ve Doğa Bilimleri & bölümler ---
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/vizyon-misyon",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/dekanlik",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/egitim-kurulu-ve-komisyonlar",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/arastirma",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/bilgisayar-muhendisligi",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/bilgisayar-muhendisligi/hakkinda",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/bilgisayar-muhendisligi/bolum-baskaninin-mesaji",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/bilgisayar-muhendisligi/komisyonlar",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/molekuler-biyoloji-ve-genetik",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/molekuler-biyoloji-ve-genetik/bolum-baskaninin-mesaji",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/molekuler-biyoloji-ve-genetik/komisyonlar",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/biyomedikal-muhendisligi",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/biyomedikal-muhendisligi/vizyon-misyon",
    "https://www.acibadem.edu.tr/akademik/lisans/muhendislik-ve-doga-bilimleri-fakultesi/bolumler/biyomedikal-muhendisligi/ogretim-plani",
    # --- İnsan ve Toplum Bilimleri & bölümler ---
    "https://www.acibadem.edu.tr/insan-ve-toplum-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/fakulte-hakkinda",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/insan-ve-toplum-bilimleri-fakultesi",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/insan-ve-toplum-bilimleri-akreditasyon-belgeleri",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/bolumler/psikoloji",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/bolumler/psikoloji/bolum-baskaninin-mesaji",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/bolumler/psikoloji/akreditasyon-belgesi",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/bolumler/psikoloji/psikoloji-bolumu-ogrenci-sayfasi",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/bolumler/sosyoloji/sosyoloji",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/bolumler/sosyoloji/mufredat",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/bolumler/sosyoloji/ogrenme-hedefleri",
    "https://www.acibadem.edu.tr/akademik/lisans/insan-ve-toplum-bilimleri-fakultesi/bolumler/sosyoloji/bolum-baskaninin-mesaji",
    # --- Aday / öğrenci / kampüs (sınırlı) ---
    "https://www.acibadem.edu.tr/aday/ogrenci",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/lisans/lisans-kontenjan-ve-puan-tablosu",
    "https://www.acibadem.edu.tr/aday/ogrenci/egitim/burs/burs-olanaklari",
    "https://www.acibadem.edu.tr/ogrenci/acuda-yasam/ogrenci-kulupleri",
    "https://www.acibadem.edu.tr/ogrenci/acuda-yasam/spor-merkezi",
    "https://www.acibadem.edu.tr/ogrenci/ogrenci-isleri/akademik-takvim",
    # --- Duyuru girişi, iletişim, hizmetler ---
    "https://www.acibadem.edu.tr/duyurular",
    "https://www.acibadem.edu.tr/iletisim",
    "https://www.acibadem.edu.tr/kariyer-merkezi",
    "https://www.acibadem.edu.tr/merkezler/uzem",
)

_MAIN_BLOCKED_PATH_SNIPPETS: frozenset[str] = frozenset(
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
        "/sso",
        "/oauth",
        "/callback",
        "/arama",
        "/search",
        "/api/",
        "/ajax/",
    }
)


def _is_allowed_main_url(url: str) -> bool:
    nu = utils.normalize_main_site_url(url, allowed_host=_MAIN_HOST)
    if not nu:
        return False
    if not utils.is_turkish_public_path(nu):
        return False
    if utils.is_blocked_file_extension(nu):
        return False
    path = urlparse(nu).path.lower()
    if any(snippet in path for snippet in _MAIN_BLOCKED_PATH_SNIPPETS):
        return False
    q = urlparse(nu).query.lower()
    if any(snippet in q for snippet in ("search=", "q=", "utm_")):
        return False
    return True


def _dedupe_seeds(urls: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        nu = utils.normalize_main_site_url(raw, allowed_host=_MAIN_HOST)
        if nu and _is_allowed_main_url(nu) and nu not in seen:
            seen.add(nu)
            out.append(nu)
    return out


def run(max_pages: int = 30, reset: bool = False) -> dict[str, Any]:
    """
    Public ana site sayfalarını çeker, ``UniversityContent`` (``source=main``) yazar.

    ``reset=True``: yalnızca ``source=main`` satırlarını siler; ``bologna`` dokunulmaz.
    """
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")

    stats: dict[str, Any] = utils.stats_dict("main")

    if reset:
        with transaction.atomic():
            UniversityContent.objects.filter(source=UniversityContent.Source.MAIN).delete()

    session = requests.Session()
    session.headers.update(utils.DEFAULT_HEADERS)

    queue = _dedupe_seeds(MAIN_SEED_URLS)[:max_pages]
    visited: set[str] = set()

    for idx, url in enumerate(queue):
        nu = utils.normalize_main_site_url(url, allowed_host=_MAIN_HOST)
        if not nu or nu in visited:
            stats["skipped"] += 1
            continue
        visited.add(nu)
        if idx > 0:
            utils.delay_between_requests()
        stats["urls"] += 1
        try:
            resp = utils.safe_get(session, nu)
            resp.raise_for_status()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
                stats["skipped"] += 1
                continue
            soup = BeautifulSoup(resp.content, "html.parser")
            title_raw = utils.extract_page_title(soup)
            title = utils.sanitize_display_title(title_raw)
            body_soup = BeautifulSoup(resp.content, "html.parser")
            body_text = utils.html_to_plain_text(body_soup)
            if utils.should_skip_english_page_title(title_raw, nu):
                stats["skipped"] += 1
                continue
            if not utils.passes_content_quality(title, body_text):
                stats["skipped"] += 1
                continue
            with transaction.atomic():
                UniversityContent.objects.update_or_create(
                    source_url=nu,
                    defaults={
                        "source": UniversityContent.Source.MAIN,
                        "title": title,
                        "content_text": body_text,
                        "raw_text": body_text,
                    },
                )
            stats["saved"] += 1
        except Exception as exc:
            stats["errors"].append({"url": nu or url, "error": f"{type(exc).__name__}: {exc}"})

    return stats
