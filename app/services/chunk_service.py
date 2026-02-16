from app.services.embedding_service import get_chroma_collection


MAX_CHARS = 800
OVERLAP_CHARS = 120


def _split_paragraphs(text: str):
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if paragraphs:
        return paragraphs
    return [p.strip() for p in text.split("\n") if p.strip()]


def _chunk_text(text: str):
    if len(text) <= MAX_CHARS:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + MAX_CHARS)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(0, end - OVERLAP_CHARS)
    return chunks


def chunk_sections(sections, document_id):
    chunks = []
    chunk_id = 0

    for section in sections:
        paragraphs = _split_paragraphs(section["content"])

        for para in paragraphs:
            if len(para) < 80:
                continue

            for chunk_text in _chunk_text(para):
                chunks.append({
                    "id": f"{document_id}_chunk_{chunk_id}",
                    "text": chunk_text,
                    "heading": section["heading"],
                    "document_id": document_id,
                    "page": section.get("page"),
                    "discourse_type": section.get("discourse_type", "unknown"),
                    "difficulty": section.get("difficulty", "unknown")
                })
                chunk_id += 1

    return chunks

def get_chunks_for_document(document_id: str):
    collection = get_chroma_collection()

    results = collection.get(
        where={
            "$and": [
                {"document_id": document_id},
                {"type": "text"}
            ]
        }
    )

    chunks = []

    for i in range(len(results["documents"])):
        chunks.append({
            "id": results["ids"][i],
            "text": results["documents"][i],
            "metadata": results["metadatas"][i]
        })

    # SORT BY PAGE
    chunks = sorted(
        chunks,
        key=lambda x: x["metadata"].get("page", 0)
    )

    return chunks