"""
OBS / Bologna public — ``SEED_URLS`` içindeki her program için ayrı tarama + birleşik kuyruk (GET + BeautifulSoup).

* Her seed farklı ``curUnit`` / ``curSunit`` ile ``index.aspx`` girişidir; erişilemeyen seed ``errors`` listesine yazılır.
* Keşfedilen linkler öncelik sıralıdır; ``max_pages`` tüm seed’ler için global üst sınırdır; ``source_url`` tekil.
* Başlık formatı: ``<Program> - <Sayfa türü>`` (kısa, paragraf yok).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.db import transaction

from chat.models import UniversityContent
from scraper import utils

_OBS_HOST = "obs.acibadem.edu.tr"

# Her satır: (``index.aspx`` girişi, başlıkta kullanılacak program adı). ``curUnit`` / ``curSunit`` çiftleri OBS’te doğrulanmıştır.
# Psikoloji girişi: bölüm web sayfasındaki Bologna linki (curUnit=16, curSunit=6287).
SEED_URLS: tuple[tuple[str, str], ...] = (
    # Computer Engineering
    (
        "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=14&curSunit=6246",
        "Bilgisayar Mühendisliği",
    ),
    # Psychology
    (
        "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=16&curSunit=6287",
        "Psikoloji",
    ),
    # Nursing
    (
        "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=11&curSunit=6050",
        "Hemşirelik",
    ),
    # Nutrition and Dietetics
    (
        "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=11&curSunit=6051",
        "Beslenme ve Diyetetik",
    ),
    # Physiotherapy and Rehabilitation
    (
        "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=11&curSunit=6052",
        "Fizyoterapi ve Rehabilitasyon",
    ),
    # Molecular Biology and Genetics
    (
        "https://obs.acibadem.edu.tr/oibs/bologna/index.aspx?lang=tr&curOp=showPac&curUnit=14&curSunit=6248",
        "Moleküler Biyoloji ve Genetik",
    ),
)

# Geriye dönük uyumluluk (PDF canonical = ilk seed).
BOLOGNA_CANONICAL_URL = SEED_URLS[0][0]

TITLE_MAX_LEN = 120

# Kayıt eşiği (çok kısa/boş sayfaları yazma)
_SAVE_MIN_CHARS = 90
_SAVE_MIN_WORDS = 14

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
        "redirect.aspx",
        "student.aspx",
    )
)

_PRIORITY_KEYWORDS: tuple[tuple[str, int], ...] = (
    ("mufredat", 55),
    ("müfredat", 55),
    ("curriculum", 48),
    ("listcurricula", 50),
    ("catalog", 48),
    ("katalog", 48),
    ("showcoursecatalog", 52),
    ("ders", 40),
    ("course", 38),
    ("showcourse", 45),
    ("program", 35),
    ("showprogram", 42),
    ("showpac", 32),
    ("akts", 45),
    ("ects", 45),
    ("kredi", 40),
    ("ogrenme", 42),
    ("çıktı", 42),
    ("cikti", 42),
    ("yeterlilik", 44),
    ("learning", 40),
    ("outcome", 40),
    ("progabout", 28),
    ("bologna", 8),
    ("oibs/bologna", 6),
)

_DEPRIORITIZE_SUBSTR: tuple[str, ...] = (
    "akademik-kadro",
    "personel",
    "kadro",
    "photo",
    "image",
    "foto",
)


def _get_cur_sunit(url: str) -> str | None:
    qs = parse_qs(urlparse(url).query)
    vals = qs.get("curSunit") or qs.get("cursunit")
    if not vals or not vals[0]:
        return None
    return str(vals[0]).strip()


def _cursunit_to_program_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for seed_url, pname in SEED_URLS:
        nu = utils.normalize_obs_url(seed_url, allowed_host=_OBS_HOST)
        if not nu:
            continue
        su = _get_cur_sunit(nu)
        if su:
            m[su] = pname
    return m


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


def _link_priority(url: str) -> int:
    u = url.lower()
    score = 0
    for needle, pts in _PRIORITY_KEYWORDS:
        if needle in u:
            score += pts
    for bad in _DEPRIORITIZE_SUBSTR:
        if bad in u:
            score -= 35
    if u.endswith(".aspx") or ".aspx?" in u:
        score += 4
    return score


def _page_kind_tr(page_url: str) -> str:
    pl = urlparse(page_url).path.lower()
    ql = urlparse(page_url).query.lower()
    if "progabout" in pl:
        return "Program Bilgileri"
    if "progcourses" in pl:
        return "Dersler"
    if "progcoursematrix" in pl:
        return "Ders Planı / Matris"
    if "proglearnoutcomes" in pl:
        return "Öğrenme Çıktıları"
    if "progrecogpriorlearning" in pl:
        return "Önceki Öğrenmenin Tanınması"
    if "dynconpage" in pl:
        m = re.search(r"curpageid=(\d+)", ql, re.I)
        if m:
            return f"Metin Sayfası ({m.group(1)})"
        return "Bologna Metin Sayfası"
    if "showcoursecatalog" in ql or "coursecatalog" in ql:
        return "Ders Kataloğu"
    if "listcurricula" in ql:
        return "Müfredat"
    if "showcourse" in ql and "catalog" not in ql:
        return "Ders Bilgisi"
    if "showprogram" in ql:
        return "Program Yapısı"
    if "showpac" in ql:
        return "Program Girişi"
    if "yeterlilik" in ql or "qualification" in ql:
        return "Program Yeterlilikleri"
    if "ogrenme" in ql or "learning" in ql or "cikti" in ql or "çıktı" in ql:
        return "Öğrenme Çıktıları"
    if "akts" in ql or "ects" in ql or "kredi" in ql:
        return "AKTS / Kredi"
    if "index.aspx" in pl:
        return "Bologna Sayfası"
    return "Bologna İçeriği"


def _is_paragraph_like(text: str) -> bool:
    t = text.strip()
    if len(t) > 100:
        return True
    if len(t) > 55 and t.count(".") >= 2:
        return True
    if "\n" in t:
        return True
    return False


def _short_html_heading(soup: BeautifulSoup) -> str:
    raw = utils.extract_page_title(soup)
    t = utils.sanitize_display_title(raw).strip()
    if t and len(t) <= 72 and not _is_paragraph_like(t):
        return t[:72]
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        t = utils.sanitize_display_title(t).strip()
        if t and len(t) <= 72 and not _is_paragraph_like(t):
            return t[:72]
    return ""


def _compose_title(program_label: str, page_url: str, soup_for_hint: BeautifulSoup) -> str:
    prog = program_label.strip()
    if len(prog) > 52:
        prog = prog[:49].rstrip() + "…"
    kind = _page_kind_tr(page_url)
    base = f"{prog} - {kind}"
    hint = _short_html_heading(soup_for_hint)
    if hint and len(hint) >= 5:
        low = hint.lower()
        plow = program_label.lower()[:18]
        if plow not in low and not _is_paragraph_like(hint):
            cand = f"{prog} - {hint}"
            if len(cand) <= TITLE_MAX_LEN:
                return cand
    if len(base) > TITLE_MAX_LEN:
        return base[: TITLE_MAX_LEN - 1].rstrip() + "…"
    return base


def _light_strip(soup: BeautifulSoup) -> None:
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


def _div_span_dump(soup: BeautifulSoup, *, limit: int = 350) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for tag in soup.find_all(("div", "span"), limit=limit):
        t = tag.get_text(" ", strip=True)
        if not t or len(t) < 3:
            continue
        if len(t) > 700:
            t = t[:700] + "…"
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return "\n".join(out).strip()


def _structured_tag_walk(soup: BeautifulSoup) -> str:
    lines: list[str] = []
    for tag in soup.find_all(("table", "tr", "td", "th", "option", "label", "textarea")):
        t = tag.get_text(" ", strip=True)
        if t and len(t) < 3000:
            lines.append(t)
    return "\n".join(lines).strip()


def _collect_same_host_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    found: list[str] = []
    for tag in soup.find_all(("a", "area")):
        href = (tag.get("href") or "").strip()
        if not href or href.startswith("#") or "javascript:" in href.lower():
            continue
        full = urljoin(base_url, href.split("#", 1)[0])
        nu = utils.normalize_obs_url(full, allowed_host=_OBS_HOST)
        if nu and _is_allowed_obs_url(nu):
            found.append(nu)
    return found


def _collect_onclick_aspx_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    found: list[str] = []
    for tag in soup.find_all(True):
        for attr in ("onclick", "onmouseenter", "data-url", "data-href"):
            val = tag.get(attr) or ""
            if not val or ".aspx" not in val.lower():
                continue
            for m in re.finditer(r"([\w./-]+\.aspx(?:\?[^'\"\s)>]+)?)", val, re.I):
                path = m.group(1).strip()
                if "redirect" in path.lower():
                    continue
                full = urljoin(base_url, path)
                nu = utils.normalize_obs_url(full, allowed_host=_OBS_HOST)
                if nu and _is_allowed_obs_url(nu) and "/oibs/bologna/" in nu.lower():
                    found.append(nu)
    return found


def _iframe_src(soup: BeautifulSoup, page_url: str) -> str | None:
    iframe = soup.find("iframe", id="IFRAME1") or soup.find("iframe")
    if not iframe:
        return None
    src = (iframe.get("src") or "").strip()
    if not src:
        return None
    return urljoin(page_url, src)


def _combined_quality_text(
    parent_plain: str,
    child_plain: str,
    child_tables: str,
    child_options: str,
    child_struct: str,
    child_div_span: str,
) -> tuple[str, int]:
    combined = "\n\n".join(
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
    words = len(re.findall(r"\w+", combined, flags=re.UNICODE))
    return combined, words


def _build_raw_text(
    source_url: str,
    child_url: str | None,
    parent_plain: str,
    child_plain: str,
    child_tables: str,
    child_options: str,
    child_struct: str,
    child_div_span: str,
) -> str:
    raw_parts: list[str] = [f"Kaynak URL (source_url): {source_url}"]
    if child_url:
        raw_parts.append(f"İçerik iframe / alt sayfa: {child_url}")
    if parent_plain:
        raw_parts.append("---\nKabuk / menü metni\n---\n" + parent_plain.strip())
    if child_tables:
        raw_parts.append("---\nTablolar\n---\n" + child_tables)
    if child_options:
        raw_parts.append("---\nSelect / option\n---\n" + child_options)
    if child_struct:
        raw_parts.append("---\nYapısal etiket metni\n---\n" + child_struct)
    if child_div_span:
        raw_parts.append("---\nDiv / span özetleri\n---\n" + child_div_span)
    if child_plain:
        raw_parts.append("---\nDüz metin gövde\n---\n" + child_plain.strip())
    return "\n\n".join(raw_parts).strip()


def _ingest_single_or_iframe_shell(
    session: requests.Session,
    page_url: str,
    program_label: str,
    errors: list[Any],
    *,
    html_cache: dict[str, bytes],
) -> tuple[str, str, str] | None:
    nu = utils.normalize_obs_url(page_url, allowed_host=_OBS_HOST)
    if not nu or not _is_allowed_obs_url(nu):
        errors.append({"url": page_url, "error": "URL normalize / izin dışı"})
        return None

    if nu in html_cache:
        html = html_cache[nu]
    else:
        resp = utils.safe_get(session, nu)
        if resp.status_code != 200:
            errors.append({"url": nu, "error": f"HTTP {resp.status_code}"})
            return None
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            errors.append({"url": nu, "error": f"HTML değil: {ctype!r}"})
            return None
        html = resp.content
        html_cache[nu] = html

    soup = BeautifulSoup(html, "html.parser")
    parent_plain = _plain_after_light_strip(html)

    child_url = _iframe_src(soup, nu)
    child_plain = ""
    child_tables = ""
    child_options = ""
    child_struct = ""
    child_div_span = ""
    soup_for_title = soup

    child_norm = utils.normalize_obs_url(child_url, allowed_host=_OBS_HOST) if child_url else None
    if (
        child_norm
        and _is_allowed_obs_url(child_norm)
        and child_norm != nu
    ):
        if child_norm not in html_cache:
            utils.delay_between_requests()
        try:
            if child_norm in html_cache:
                chtml = html_cache[child_norm]
            else:
                r2 = utils.safe_get(session, child_norm)
                if r2.status_code != 200:
                    errors.append({"url": child_norm, "error": f"iframe HTTP {r2.status_code}"})
                    chtml = b""
                else:
                    chtml = r2.content
                    html_cache[child_norm] = chtml
            if chtml:
                csoup = BeautifulSoup(chtml, "html.parser")
                soup_for_title = csoup
                child_plain = _plain_after_light_strip(chtml)
                child_tables = _tables_to_text(BeautifulSoup(chtml, "html.parser"))
                child_options = _options_to_text(csoup)
                child_struct = _structured_tag_walk(csoup)
                child_div_span = _div_span_dump(csoup)
        except Exception as exc:
            errors.append({"url": child_norm, "error": f"{type(exc).__name__}: {exc}"})
    else:
        soup_for_title = soup

    su = _get_cur_sunit(nu) or _get_cur_sunit(child_norm or "")
    curs_map = _cursunit_to_program_map()
    effective_program = curs_map.get(su, program_label) if su else program_label

    title = _compose_title(effective_program, nu, soup_for_title)
    if len(title) > TITLE_MAX_LEN:
        title = title[: TITLE_MAX_LEN - 1].rstrip() + "…"

    combined, words = _combined_quality_text(
        parent_plain, child_plain, child_tables, child_options, child_struct, child_div_span
    )
    if len(combined) < _SAVE_MIN_CHARS or words < _SAVE_MIN_WORDS:
        errors.append(
            {
                "url": nu,
                "error": f"İçerik kısa veya yetersiz ({len(combined)} char, {words} kelime)",
            }
        )
        return None

    content_text = (child_plain or combined).strip()
    if parent_plain and len(parent_plain) > 40:
        content_text = (
            "Bologna menü / kabuk:\n"
            + parent_plain[:2200].strip()
            + "\n\n---\n\nProgram / detay:\n"
            + content_text
        )

    raw_text = _build_raw_text(
        nu,
        child_norm if child_norm and child_norm != nu else None,
        parent_plain,
        child_plain,
        child_tables,
        child_options,
        child_struct,
        child_div_span,
    )

    return title[:TITLE_MAX_LEN], content_text, raw_text


def _build_queue(
    session: requests.Session,
    canonical: str,
    max_pages: int,
    errors: list[Any],
    html_cache: dict[str, bytes],
) -> list[str]:
    """Tek seed: başarılı canonical yükleme sonrası iframe + keşfedilen linkler (öncelik sıralı)."""
    ordered: list[str] = []
    seen: set[str] = set()

    def push(u: str) -> None:
        nu = utils.normalize_obs_url(u, allowed_host=_OBS_HOST)
        if nu and _is_allowed_obs_url(nu) and nu not in seen:
            seen.add(nu)
            ordered.append(nu)

    try:
        if canonical in html_cache:
            r0_content = html_cache[canonical]
        else:
            r0 = utils.safe_get(session, canonical)
            if r0.status_code != 200:
                errors.append({"url": canonical, "error": f"HTTP {r0.status_code} (seed yüklenemedi)"})
                return []
            r0_content = r0.content
            html_cache[canonical] = r0_content
    except Exception as exc:
        errors.append({"url": canonical, "error": f"{type(exc).__name__}: {exc}"})
        return []

    push(canonical)

    s0 = BeautifulSoup(r0_content, "html.parser")
    discovered: list[str] = []
    for link in _collect_same_host_links(s0, canonical):
        discovered.append(link)
    for link in _collect_onclick_aspx_links(s0, canonical):
        discovered.append(link)

    child = _iframe_src(s0, canonical)
    child_nu = utils.normalize_obs_url(child, allowed_host=_OBS_HOST) if child else None
    if child_nu and _is_allowed_obs_url(child_nu) and child_nu != canonical:
        if child_nu not in html_cache:
            utils.delay_between_requests()
        try:
            if child_nu not in html_cache:
                r1 = utils.safe_get(session, child_nu)
                if r1.status_code == 200:
                    html_cache[child_nu] = r1.content
                else:
                    errors.append({"url": child_nu, "error": f"program sayfası HTTP {r1.status_code}"})
            if child_nu in html_cache:
                push(child_nu)
                s1 = BeautifulSoup(html_cache[child_nu], "html.parser")
                for link in _collect_same_host_links(s1, child_nu):
                    discovered.append(link)
                for link in _collect_onclick_aspx_links(s1, child_nu):
                    discovered.append(link)
        except Exception as exc:
            errors.append({"url": child_nu or "", "error": f"{type(exc).__name__}: {exc}"})

    extra_candidates = sorted(
        {u for u in discovered if u not in seen},
        key=lambda u: (-_link_priority(u), u),
    )

    for u in extra_candidates:
        if len(ordered) >= max_pages:
            break
        push(u)

    return ordered[:max_pages]


def _validate_seed_reachable(
    session: requests.Session,
    seed_url: str,
    errors: list[Any],
    html_cache: dict[str, bytes],
) -> str | None:
    """Seed için tek GET; başarısızsa ``errors`` ve ``None``."""
    nu = utils.normalize_obs_url(seed_url, allowed_host=_OBS_HOST)
    if not nu or not _is_allowed_obs_url(nu):
        errors.append({"url": seed_url, "error": "Seed URL normalize / izin dışı"})
        return None
    if nu in html_cache:
        return nu
    try:
        r = utils.safe_get(session, nu)
        if r.status_code != 200:
            errors.append({"url": nu, "error": f"Seed erişilemedi: HTTP {r.status_code}"})
            return None
        html_cache[nu] = r.content
        return nu
    except Exception as exc:
        errors.append({"url": nu, "error": f"{type(exc).__name__}: {exc}"})
        return None


def _merge_seed_queues_round_robin(
    session: requests.Session,
    max_pages: int,
    errors: list[Any],
    html_cache: dict[str, bytes],
) -> list[tuple[str, str]]:
    """
    Her seed için ayrı ``_build_queue``; round-robin ile URL alınır (aynı ``source_url`` yalnızca bir kez).

    Aynı derinlikte paylaşılan genel linkler (``curSunit`` yok) ilk ekleyen seed’in program etiketiyle
    kayda gider; ``curSunit`` taşıyan linklerde ``SEED_URLS`` eşlemesi önceliklidir.
    """
    curs_map = _cursunit_to_program_map()
    per_seed_cap = max(15, max_pages + 20)

    seed_queues: list[list[tuple[str, str]]] = []

    for si, (seed_url, pname) in enumerate(SEED_URLS):
        if si > 0:
            utils.delay_between_requests()
        nu = _validate_seed_reachable(session, seed_url, errors, html_cache)
        if not nu:
            seed_queues.append([])
            continue
        sub_urls = _build_queue(session, nu, per_seed_cap, errors, html_cache)
        seed_queues.append([(u, pname) for u in sub_urls])

    merged: list[tuple[str, str]] = []
    seen: set[str] = set()
    idxs = [0] * len(seed_queues)

    while len(merged) < max_pages:
        progressed = False
        for si, sub in enumerate(seed_queues):
            if len(merged) >= max_pages:
                break
            while idxs[si] < len(sub):
                u, default_label = sub[idxs[si]]
                idxs[si] += 1
                if u in seen:
                    continue
                seen.add(u)
                su = _get_cur_sunit(u)
                label = curs_map.get(su, default_label) if su else default_label
                merged.append((u, label))
                progressed = True
                break
        if not progressed:
            break

    return merged[:max_pages]


def run(max_pages: int = 20, reset: bool = False) -> dict[str, Any]:
    """
    ``SEED_URLS`` üzerinden her program için ayrı crawl başlatır; round-robin ile en fazla ``max_pages`` URL işlenir.

    ``reset=True``: yalnızca ``source=bologna`` kayıtlarını siler.
    """
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")

    stats: dict[str, Any] = utils.stats_dict("bologna")

    if reset:
        with transaction.atomic():
            UniversityContent.objects.filter(source=UniversityContent.Source.BOLOGNA).delete()

    session = requests.Session()
    session.headers.update(utils.DEFAULT_HEADERS)

    html_cache: dict[str, bytes] = {}
    queue = _merge_seed_queues_round_robin(session, max_pages, stats["errors"], html_cache)

    for idx, (page_url, program_label) in enumerate(queue):
        nu = utils.normalize_obs_url(page_url, allowed_host=_OBS_HOST)
        if not nu:
            stats["skipped"] += 1
            continue
        if idx > 0:
            utils.delay_between_requests()
        stats["urls"] += 1
        try:
            bundle = _ingest_single_or_iframe_shell(
                session, nu, program_label, stats["errors"], html_cache=html_cache
            )
            if bundle is None:
                stats["skipped"] += 1
                continue
            title, content_text, raw_text = bundle
            with transaction.atomic():
                UniversityContent.objects.update_or_create(
                    source_url=nu,
                    defaults={
                        "source": UniversityContent.Source.BOLOGNA,
                        "title": title[: min(TITLE_MAX_LEN, 512)],
                        "content_text": content_text,
                        "raw_text": raw_text,
                    },
                )
            stats["saved"] += 1
        except Exception as exc:
            stats["errors"].append({"url": nu, "error": f"{type(exc).__name__}: {exc}"})
            stats["skipped"] += 1

    return stats
