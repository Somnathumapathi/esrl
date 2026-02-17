# API Reference

Base URL: http://127.0.0.1:8000
Content types:
- application/json for POST bodies
- multipart/form-data for file uploads
CORS: allow all origins

## GET /
Health check.

Response:
{
  "message": "Hello World"
}

## POST /upload_pdf
Upload and process a PDF (text, chunks, images).

Content type: multipart/form-data
Body:
- file: PDF file

Response:
{
  "message": "PDF processed",
  "document_id": "string",
  "characters_extracted": 12345,
  "chunks": 42,
  "images": 5
}

## POST /rag
Ask a question and get an answer plus relevant images.

Content type: application/json
Body:
{
  "query": "string"
}

Response:
{
  "answer": "string",
  "context": { },
  "images": [
    {
      "path": "string",
      "url": "http://127.0.0.1:8000/storage/images/...",
      "caption": "string",
      "ocr": "string",
      "context": "string",
      "page": 3,
      "document_id": "string"
    }
  ]
}

## POST /chat
Chat-style Q&A with conversation history.

Content type: application/json
Body (recommended):
{
  "messages": [
    { "role": "user", "content": "What is the key idea in the introduction?" },
    { "role": "assistant", "content": "..." },
    { "role": "user", "content": "Summarize it in 3 bullets." }
  ]
}

Body (fallback):
{
  "query": "string"
}

Response:
{
  "answer": "string",
  "context": { }
}

## POST /notes
Generate quick notes from provided text or last uploaded PDF.

Content type: application/json
Body:
{
  "text": "string (optional)"
}

If text is empty, the last uploaded PDF is used.

Response: notes object (shape depends on generate_quick_notes).

## POST /notes/summary
Generate summary at multiple levels from text or last uploaded PDF.

Content type: application/json
Body:
{
  "text": "string (optional)"
}

Response: summary object (shape depends on summarize_text_levels).

## POST /generate_video/{document_id}
Create a narrated video from a document.

Path param:
- document_id: from /upload_pdf

Response:
{
  "message": "Video generated successfully",
  "video_path": "string",
  "video_url": "http://127.0.0.1:8000/media/video/final.mp4"
}
