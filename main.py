import os

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.services.pdf_service import (
    save_pdf,
    extract_text_from_pdf,
    extract_images_from_pdf,
    generate_document_id,
    record_last_uploaded,
    get_last_uploaded
)
from app.services.text_processing_service import clean_text, structure_pages
from app.services.discourse_service import classify_discourse
from app.services.chunk_service import chunk_sections, get_chunks_for_document
from app.services.embedding_service import (
    get_images_for_document,
    upsert_chunks,
    upsert_images,
    query_similar,
    query_images_for_document,
    get_text_for_page
)
from app.services.image_service import generate_caption, extract_text
from app.services.rag_service import generate_answer
from app.services.notes_service import generate_quick_notes
from app.services.summarizer_service import summarize_text_levels
from app.services.video_gen_service import generate_slide_plan, generate_voice, get_audio_duration, html_to_video, image_audio_to_video, normalize_chroma_images, render_slide_html, stitch_videos
from dotenv import load_dotenv
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.post("/upload_pdf")
async def upload_pdf(file: UploadFile = File(...)):
    path = await save_pdf(file)

    document_id = generate_document_id(path)
    full_text, pages_text = extract_text_from_pdf(path)
    cleaned = clean_text(full_text)
    sections = structure_pages(pages_text)
    sections = classify_discourse(sections)

    for section in sections:
        section["document_id"] = document_id

    chunks = chunk_sections(sections, document_id)
    upsert_chunks(chunks)

    images = extract_images_from_pdf(path, document_id)
    if images:
        image_chunks = []
        for image in images:
            try:
                caption = generate_caption(image["path"])
            except Exception:
                caption = "Image"
            try:
                ocr_text = extract_text(image["path"])
            except Exception:
                ocr_text = ""
            if ocr_text:
                ocr_snippet = ocr_text[:400]
                caption = f"{caption}. OCR: {ocr_snippet}"
            image_chunks.append({
                "id": image["id"],
                "caption": caption,
                "ocr": ocr_text,
                "page": image.get("page"),
                "document_id": image.get("document_id"),
                "path": image.get("path")
            })
        upsert_images(image_chunks)

    record_last_uploaded(path, document_id)

    return {
        "message": "PDF processed",
        "document_id": document_id,
        "characters_extracted": len(cleaned),
        "chunks": len(chunks),
        "images": len(images)
    }


@app.post("/rag")
async def rag_query(payload: dict):
    query = payload.get("query", "")
    context = query_similar(query, top_k=8)
    answer = generate_answer(query, context)
    images = []
    metadatas = (context.get("metadatas") or [[]])[0]
    document_ids = [m.get("document_id") for m in metadatas if m]
    if document_ids:
        image_context = query_images_for_document(query, document_ids[0], limit=5)
        image_docs = (image_context.get("documents") or [[]])[0]
        image_metas = (image_context.get("metadatas") or [[]])[0]
        for doc, meta in zip(image_docs, image_metas):
            meta = meta or {}
            context_snippet = ""
            page = meta.get("page")
            if page is not None:
                page_context = get_text_for_page(document_ids[0], page, limit=1)
                page_docs = page_context.get("documents") or []
                page_docs = page_docs[0] if page_docs and isinstance(page_docs[0], list) else page_docs
                if page_docs:
                    context_snippet = page_docs[0][:400]
            images.append({
                "path": meta.get("path"),
                "caption": meta.get("caption") or doc or "Image",
                "ocr": meta.get("ocr") or "",
                "context": context_snippet,
                "page": meta.get("page"),
                "document_id": meta.get("document_id")
            })
    return {"answer": answer, "context": context, "images": images}


@app.post("/notes")
async def notes_query(payload: dict):
    text = (payload.get("text") or "").strip()
    if not text:
        last_uploaded = get_last_uploaded()
        if not last_uploaded:
            raise HTTPException(status_code=400, detail="No text provided and no uploaded PDF found.")

        pdf_path = last_uploaded.get("path")
        if not pdf_path or not os.path.exists(pdf_path):
            raise HTTPException(status_code=400, detail="Last uploaded PDF not found.")

        full_text, _ = extract_text_from_pdf(pdf_path)
        text = clean_text(full_text)
    notes = generate_quick_notes(text)
    return notes


@app.post("/notes/summary")
async def notes_summary(payload: dict):
    text = (payload.get("text") or "").strip()
    if not text:
        last_uploaded = get_last_uploaded()
        if not last_uploaded:
            raise HTTPException(status_code=400, detail="No text provided and no uploaded PDF found.")

        pdf_path = last_uploaded.get("path")
        if not pdf_path or not os.path.exists(pdf_path):
            raise HTTPException(status_code=400, detail="Last uploaded PDF not found.")

        full_text, _ = extract_text_from_pdf(pdf_path)
        text = clean_text(full_text)
    return summarize_text_levels(text)

@app.post("/generate_video/{document_id}")
async def generate_video(document_id: str):

    text_chunks = get_chunks_for_document(document_id)
    raw_images = get_images_for_document(document_id)
    image_chunks = normalize_chroma_images(raw_images)


    if not text_chunks:
        return {"error": "No text chunks found for document"}

    slides = generate_slide_plan(text_chunks, image_chunks)

    # print(slides)

    if not slides:
        return {"error": "Slide generation failed"}

    video_paths = []

    for i, slide in enumerate(slides):
        print(f"Generating slide {i+1}/{len(slides)}")

        voice_text = slide.get("voiceover") or slide.get("explanation")

        if not voice_text:
            continue

        audio_path = generate_voice(voice_text, i)
        print(audio_path)
        duration = get_audio_duration(audio_path)

        # ⚠ IMPORTANT: pass image_chunks here
        html_path = render_slide_html(
            slide,
            duration=5,
            slide_id=i,
            all_images=image_chunks
        )

        webm_path = await html_to_video(html_path, i, duration)
        print("WEBM EXISTS:", os.path.exists(webm_path))
        print("AUDIO EXISTS:", os.path.exists(audio_path))
        video_path = image_audio_to_video(webm_path, audio_path, duration, i)
        video_paths.append(video_path)

    if not video_paths:
        return {"error": "Video generation failed"}

    final_video = stitch_videos(video_paths)

    return {
        "message": "Video generated successfully",
        "video_path": final_video
        # "slides": slides
    }
