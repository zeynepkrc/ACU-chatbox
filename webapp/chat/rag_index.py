"""
RAG / vektör indeks hazırlığı.

Şu an: PostgreSQL üzerinde ek şema yok; ``services.retrieve_relevant_university_content``
``raw_text`` dahil arama yapar. Bu modül veri tutarlılığı ve ileride pgvector / harici
embedding deposu için güvenli kancalar sağlar (scraper koduna dokunulmaz).
"""

from __future__ import annotations

from typing import Any, Iterator

from django.db.models import F

from chat.models import UniversityContent


def backfill_raw_text_from_content_text() -> int:
    """
    ``raw_text`` boş veya yalnızca boşluk olan satırlarda ``content_text`` kopyalanır.

    Mevcut satırları silmez; yalnızca eksik arama gövdesini doldurur (veri kaybı yok).
    """
    qs = UniversityContent.objects.filter(raw_text="").exclude(content_text="")
    return qs.update(raw_text=F("content_text"))


def embedding_source_text(row: UniversityContent) -> str:
    """İleride embedding / vektör indeksi için birleşik metin (tek kayıt)."""
    chunks = [
        (row.title or "").strip(),
        (row.raw_text or "").strip(),
        (row.content_text or "").strip(),
    ]
    return "\n\n".join(c for c in chunks if c)


def iter_embedding_documents(
    *,
    batch_size: int = 100,
) -> Iterator[list[dict[str, Any]]]:
    """
    Gelecekteki vektör pipeline'ı için batch'ler halinde ``{"id", "url", "text"}``.

    Şimdilik Ollama/embeddings çağrısı yok; sadece veri şekillendirme.
    """
    batch: list[dict[str, Any]] = []
    qs = UniversityContent.objects.order_by("pk").iterator(chunk_size=batch_size)
    for row in qs:
        text = embedding_source_text(row)
        if not text:
            continue
        batch.append({"id": row.pk, "url": row.source_url, "text": text})
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def planned_vector_index_spec() -> dict[str, Any]:
    """İleride uygulanacak vektör katmanı için sözleşme özeti (kod dışı dokümantasyon)."""
    return {
        "engine": "placeholder_pgvector_or_external",
        "source_model": "chat.UniversityContent",
        "text_fn": "chat.rag_index.embedding_source_text",
        "dimensions": "TBD (ör. 768 / 1024 modele göre)",
        "note": "PostgreSQL pgvector uzantısı veya ayrı vektör DB; migration ayrı PR'da.",
    }
