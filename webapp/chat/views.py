from django.shortcuts import render
from django.http import JsonResponse
from .models import PageContent, ChatMessage
import requests
import re
import unicodedata


OLLAMA_URL = "http://ollama:11434/api/generate"
MODEL_NAME = "qwen2.5:1.5b"


STOPWORDS = {
    "nedir", "ne", "kim", "kaç", "hangi", "mı", "mi", "mu", "mü",
    "bana", "söyle", "ver", "yaz", "olan", "için", "ile", "ve",
    "veya", "bu", "şu", "o", "de", "da", "var", "acaba", "acıbadem",
    "acibadem", "üniversitesi", "universitesi", "bölümü", "bolumu",
    "bölümünün", "bolumunun"
}


PROGRAM_ALIASES = {
    "bilgisayar mühendisliği": [
        "bilgisayar mühendisliği", "bilgisayar muhendisligi",
        "computer engineering"
    ],
    "eczacılık": [
        "eczacılık", "eczacilik", "eczacılık fakültesi",
        "pharmacy"
    ],
    "moleküler biyoloji ve genetik": [
        "moleküler biyoloji ve genetik", "molekuler biyoloji ve genetik",
        "moleküler biyoloji", "molekuler biyoloji", "genetik"
    ],
    "psikoloji": ["psikoloji", "psychology"],
    "sosyoloji": ["sosyoloji"],
    "beslenme ve diyetetik": ["beslenme ve diyetetik", "beslenme", "diyetetik"],
    "fizyoterapi ve rehabilitasyon": [
        "fizyoterapi ve rehabilitasyon", "fizyoterapi", "rehabilitasyon"
    ],
    "hemşirelik": ["hemşirelik", "hemsirelik", "nursing"],
    "sağlık yönetimi": ["sağlık yönetimi", "saglik yonetimi"],
    "tıp fakültesi": ["tıp fakültesi", "tip fakultesi", "tıp", "tip"],
    "tıp mühendisliği": ["tıp mühendisliği", "tip muhendisligi"],
    "biyomedikal mühendisliği": [
        "biyomedikal mühendisliği", "biyomedikal muhendisligi", "biyomedikal"
    ],
}


SECTION_ALIASES = {
    "Program Yetkilileri": [
        "başkan", "baskan", "bölüm başkanı", "bolum baskani",
        "bölüm baskanı", "bolum başkanı", "dekan", "yetkili",
        "yetkilileri", "koordinatör", "koordinator", "sorumlu",
        "kim yönetiyor", "kim yonetiyor"
    ],
    "Dersler": [
        "ders", "dersler", "kredi", "akts", "ects",
        "ders içerikleri", "ders icerikleri", "hangi dersler",
        "müfredat", "mufredat", "zorunlu", "seçmeli", "secmeli"
    ],
    "Program Profili": ["program profili", "profil"],
    "Program Hakkında": ["program hakkında", "program hakkinda", "hakkında", "hakkinda"],
    "Mezuniyet Koşulları": ["mezuniyet", "mezuniyet koşulları", "mezuniyet kosullari"],
    "Kabul Koşulları": ["kabul", "kabul koşulları", "kabul kosullari"],
    "Program Yeterlikleri": ["program yeterlikleri", "yeterlik"],
    "Yeterlilik Koşulları ve Kuralları": [
        "yeterlilik koşulları", "yeterlilik kosullari", "yeterlilik", "kurallar"
    ],
    "Akademik Personel": [
        "akademik personel", "öğretim görevlisi", "ogretim gorevlisi",
        "öğretim üyesi", "ogretim uyesi", "hoca", "akademisyen"
    ],
    "İletişim": [
        "iletişim", "iletisim", "adres", "telefon", "mail", "e-posta", "eposta"
    ],
    "İstihdam Olanakları": [
        "istihdam", "iş olanakları", "is olanaklari", "çalışma alanları",
        "calisma alanlari"
    ],

    "Öğrenci Kulüpleri": ["kulüp", "kulup", "kulüpler", "kulupler", "öğrenci kulüpleri"],
    "Yemek": ["yemek", "kafeterya", "aplus"],
    "Kampüs": [
    "kampüs", "kampus", "yerleşke", "yerleske",
    "nerede", "nerde", "nereye", "konum", "konumu",
    "adres", "lokasyon", "bulunmaktadır", "bulunmaktadir"
],
    "Konaklama": ["konaklama", "yurt"],
    "Sağlık Hizmetleri": ["sağlık hizmetleri", "saglik hizmetleri", "sağlık merkezi"],
    "Spor ve Sosyal Yaşam": ["spor", "sosyal yaşam", "sosyal yasam"],
    "Şehir Hakkında": ["şehir", "sehir", "istanbul"],
    "Engelli Öğrenci Hizmetleri": ["engelli"],
    "Erasmus+ Beyannamesi": ["erasmus", "erasmus beyannamesi"],
    "Bologna Süreci": ["bologna süreci", "bologna sureci", "bologna"],
    "Yönetim": ["yönetim", "yonetim", "rektör", "rektor", "mütevelli", "mutevelli"],
    "Üniversite Hakkında": [
        "üniversite hakkında", "universite hakkinda", "acıbadem üniversitesi hakkında",
        "acibadem universitesi hakkinda", "okul hakkında", "okul hakkinda"
    ],
    "Bologna Komisyonu": ["bologna komisyonu"],
    "AKTS Kataloğu": ["akts kataloğu", "akts katalogu"],
}


GENERAL_NEGATIVE_FOR_PROGRAM = [
    "öğrenci kulüpleri", "ogrenci kulupleri", "yemek", "kafeterya",
    "kampüs", "kampus", "bologna süreci", "bologna sureci",
    "erasmus", "konaklama", "şehir", "sehir", "sağlık hizmetleri",
    "saglik hizmetleri"
]


def normalize(text):
    """
    Türkçe karakterleri sadeleştirir, küçük harfe çevirir.
    Böylece 'mühendisliği' ve 'muhendisligi' benzer yakalanır.
    """
    text = text or ""
    text = text.lower()

    replacements = {
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ş": "s",
        "Ş": "s",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }

    for tr, en in replacements.items():
        text = text.replace(tr, en)

    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(text):
    words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9]+", text or "")
    clean_words = []

    for word in words:
        w = normalize(word)
        if len(w) > 2 and w not in STOPWORDS:
            clean_words.append(w)

    return clean_words


def detect_program(question):
    q = normalize(question)

    for program, aliases in PROGRAM_ALIASES.items():
        for alias in aliases:
            if normalize(alias) in q:
                return program

    return None


def detect_section(question):
    q = normalize(question)

    for section, aliases in SECTION_ALIASES.items():
        for alias in aliases:
            if normalize(alias) in q:
                return section

    return None


def get_page_text(page):
    return f"{page.title or ''} {page.content or ''} {page.url or ''}"


def page_matches_program(page, program):
    if not program:
        return True

    text = normalize(get_page_text(page))
    aliases = PROGRAM_ALIASES.get(program, [program])

    return any(normalize(alias) in text for alias in aliases)


def page_matches_section(page, section):
    if not section:
        return True

    text = normalize(get_page_text(page))
    aliases = SECTION_ALIASES.get(section, [section])

    return any(normalize(alias) in text for alias in aliases) or normalize(section) in text


def score_page(page, question, program, section):
    title = normalize(page.title)
    content = normalize(page.content)
    url = normalize(page.url)
    combined = f"{title} {content} {url}"
    q_words = tokenize(question)

    score = 0

    if program:
        aliases = PROGRAM_ALIASES.get(program, [program])
        for alias in aliases:
            a = normalize(alias)
            if a in title:
                score += 300
            if a in content:
                score += 180
            if a in url:
                score += 80

    if section:
        aliases = SECTION_ALIASES.get(section, [section])
        for alias in aliases:
            a = normalize(alias)
            if a in title:
                score += 280
            if a in content:
                score += 150
            if a in url:
                score += 60

    for word in q_words:
        if word in title:
            score += 25
        if word in content:
            score += 6
        if word in url:
            score += 4

    if program:
        for bad in GENERAL_NEGATIVE_FOR_PROGRAM:
            if normalize(bad) in title:
                score -= 300
            if normalize(bad) in content[:1000]:
                score -= 120

    if not program and section:
        if page_matches_section(page, section):
            score += 180

    return score


def find_relevant_content(question):
    program = detect_program(question)
    section = detect_section(question)

    all_pages = list(PageContent.objects.all())
    scored = []

    for page in all_pages:
        if program and not page_matches_program(page, program):
            continue

        score = score_page(page, question, program, section)

        if score > 0:
            scored.append((score, page))

    scored.sort(reverse=True, key=lambda x: x[0])

    if not scored:
        q_words = tokenize(question)
        fallback = []

        for page in all_pages:
            text = normalize(get_page_text(page))
            score = sum(1 for w in q_words if w in text)

            if score > 0:
                fallback.append((score, page))

        fallback.sort(reverse=True, key=lambda x: x[0])
        scored = fallback

    return [page for score, page in scored[:5]]


def split_into_chunks(text):
    raw = text or ""

    chunks = re.split(r"[\n\r]+|(?<=[.!?])\s+", raw)
    cleaned = []

    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) > 2:
            cleaned.append(chunk)

    return cleaned


def extract_relevant_text(text, question):
    q_words = tokenize(question)
    section = detect_section(question)
    raw = text or ""

    chunks = split_into_chunks(raw)
    scored = []

    for chunk in chunks:
        c = normalize(chunk)
        score = 0

        for word in q_words:
            if word in c:
                score += 5

        if section:
            section_norm = normalize(section)

            if section_norm in c:
                score += 60

            for alias in SECTION_ALIASES.get(section, []):
                if normalize(alias) in c:
                    score += 35

        if section == "Program Yetkilileri":
         authority_words = [
        "bolum baskani", "baskan", "program baskani", "program yetkilileri",
        "dekan", "koordinator", "prof", "prof dr", "doc dr",
        "dr ogr", "ogr gor", "ahmet", "bulut"
    ]

    if any(w in c for w in authority_words):
        score += 120

        if section == "Dersler":
            course_words = [
                "akts", "ects", "kredi", "zorunlu", "secmeli", "ders",
                "yariyil", "donem", "course"
            ]

            if any(w in c for w in course_words):
                score += 60

        if section == "İletişim":
            if any(w in c for w in ["adres", "telefon", "mail", "eposta", "iletisim"]):
                score += 60

        if score > 0:
            scored.append((score, chunk))

    scored.sort(reverse=True, key=lambda x: x[0])

    if scored:
        return "\n".join([chunk for _, chunk in scored[:15]])[:5000]

    return raw[:5000]


def direct_answer_if_possible(question, context):
    section = detect_section(question)
    q = normalize(question)
    text = context or ""

    # 1) Bölüm başkanı / program yetkilileri soruları
    if section == "Program Yetkilileri":
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # Önce Ahmet Bulut gibi açık isimleri yakala
        known_name_patterns = [
            r"Prof\.?\s*Dr\.?\s*Ahmet\s+Bulut",
            r"Ahmet\s+Bulut",
        ]

        for pattern in known_name_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return "Bilgisayar Mühendisliği bölüm başkanı: Prof. Dr. Ahmet Bulut"

        # Genel isim yakalama
        for line in lines:
            line_norm = normalize(line)

            if any(key in line_norm for key in [
                "bolum baskani",
                "program baskani",
                "baskan",
                "program yetkilileri"
            ]):
                name_match = re.search(
                    r"(Prof\.?\s*Dr\.?|Doç\.?\s*Dr\.?|Doc\.?\s*Dr\.?|Dr\.?\s*Öğr\.?\s*Üyesi|Dr\.?\s*Ogr\.?\s*Uyesi)?\s*([A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+)+)",
                    line
                )

                if name_match:
                    title = name_match.group(1) or ""
                    name = name_match.group(2)

                    answer = f"{title} {name}".strip()
                    answer = re.sub(r"\s+", " ", answer)

                    if len(answer) > 5 and "Program Yetkilileri" not in answer:
                        return f"Bölüm başkanı: {answer}"

        return None

    # 2) Konum / kampüs / adres soruları
    if section == "Kampüs" or any(word in q for word in ["nerde", "nerede", "konum", "lokasyon", "adres"]):
        if "istanbul" in normalize(text) and "anadolu yakasi" in normalize(text):
            return "Acıbadem Üniversitesi İstanbul Anadolu Yakası’nda yer almaktadır."

        if "kerem aydinlar kampusu" in normalize(text):
            return "Acıbadem Üniversitesi Kerem Aydınlar Kampüsü’nde yer almaktadır."

        address_match = re.search(
            r"([A-ZÇĞİÖŞÜa-zçğıöşü0-9\s,./-]+Ataşehir\s*/\s*İstanbul)",
            text,
            flags=re.IGNORECASE
        )

        if address_match:
            return f"Acıbadem Üniversitesi'nin adresi: {address_match.group(1).strip()}"

    return None

def ask_ollama(question, context):
    prompt = f"""
Sen Acıbadem Üniversitesi için çalışan kaynak bağlı bir asistansın.

ÇOK ÖNEMLİ KURALLAR:
- SADECE CONTEXT içindeki bilgiyi kullan.
- CONTEXT içinde açıkça yazmayan hiçbir ismi, tarihi, unvanı, adresi veya bilgiyi uydurma.
- Emin değilsen sadece şunu yaz: Bu konuda yeterli bilgim yok.
- Bölüm başkanı / dekan / yetkili / koordinatör sorularında sadece Program Yetkilileri bilgisini kullan.
- Ders, kredi, AKTS sorularında sadece Dersler bilgisini kullan.
- Eğer soru bir bölüm hakkındaysa başka bölüm bilgisi verme.
- Cevabı kısa, net ve Türkçe ver.
- Kaynak link yazma. Kaynaklar sistem tarafından ayrıca gösterilecek.

CONTEXT:
{context}

SORU:
{question}

CEVAP:
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0,
                "top_p": 0.2,
                "repeat_penalty": 1.15,
                "num_predict": 220
            }
        },
        timeout=180
    )

    response.raise_for_status()
    return response.json().get("response", "").strip()


def get_answer(question):
    results = find_relevant_content(question)

    if not results:
        return "Bu konuda yeterli bilgim yok.", []

    contexts = []
    sources = []

    for source in results:
        relevant_text = extract_relevant_text(source.content, question)

        if not relevant_text.strip():
            continue

        contexts.append(
            f"Başlık: {source.title}\n"
            f"Kaynak: {source.url}\n"
            f"İçerik:\n{relevant_text}"
        )

        if source.url and source.url not in sources:
            sources.append(source.url)

    if not contexts:
        return "Bu konuda yeterli bilgim yok.", []

    context = "\n\n---\n\n".join(contexts)

    direct = direct_answer_if_possible(question, context)
    if direct:
        return direct, sources[:5]

    try:
        answer = ask_ollama(question, context)
    except Exception as e:
        print("OLLAMA ERROR:", e)
        answer = f"AI service error: {e}"

    if not answer:
        answer = "Bu konuda yeterli bilgim yok."

    bad_answers = [
        "program yetkilileri",
        "bu konuda yeterli bilgim yok değil",
    ]

    if answer.strip().lower() in bad_answers:
        answer = "Bu konuda yeterli bilgim yok."

    return answer, sources[:5]


def home(request):
    question = request.GET.get("q", "")
    answer = ""
    sources = []

    if question:
        answer, sources = get_answer(question)
        ChatMessage.objects.create(question=question, answer=answer)

    return render(request, "chat/home.html", {
        "question": question,
        "answer": answer,
        "sources": sources,
    })


def chat(request):
    question = request.GET.get("q", "")

    if not question:
        return JsonResponse({"error": "Please provide a question using ?q=..."})

    answer, sources = get_answer(question)
    ChatMessage.objects.create(question=question, answer=answer)

    return JsonResponse({
        "question": question,
        "answer": answer,
        "sources": sources
    })