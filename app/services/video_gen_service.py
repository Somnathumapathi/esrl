from pydub import AudioSegment
from google import genai
from google.genai import types
import json
import os
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright
import wave

MODEL_NAME = "gemini-2.5-flash"

# =====================================================
# Utility
# =====================================================

def _ensure_dirs():
    dirs = [
        "media/audio",
        "media/html",
        "media/images",
        "media/video",
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)


def _get_client():
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=api_key)


def _clean_json_response(text: str):
    """Removes ```json markdown wrappers if Gemini adds them."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
    return text.strip()

def normalize_chroma_images(chroma_response):
    """
    Converts raw Chroma image response into clean list of image dicts.
    """
    if not chroma_response:
        return []

    # If already normalized, return directly
    if isinstance(chroma_response, list):
        return chroma_response

    images = []

    ids = chroma_response.get("ids", [])
    metadatas = chroma_response.get("metadatas", [])
    for i in range(len(ids)):
        metadata = metadatas[i]

        images.append({
            "id": ids[i],
            "caption": metadata.get("caption", ""),
            "path": metadata.get("path", ""),
            "page": metadata.get("page", 0),
            "ocr": metadata.get("ocr", "")
        })

    return images

def _save_pcm_as_wav(pcm_data: bytes, slide_id: int):
    output_path = f"media/audio/slide_{slide_id}.wav"

    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)          # mono
        wf.setsampwidth(2)          # 16-bit
        wf.setframerate(24000)      # Gemini default sample rate
        wf.writeframes(pcm_data)

    return output_path


# =====================================================
# STEP 1 — Slide Plan
# =====================================================

def generate_slide_plan(chunks, images):
    client = _get_client()
    _ensure_dirs()

    context_text = "\n".join([c["text"] for c in chunks[:20]])

    image_info = "\n".join([
        f"Image ID: {img['id']}, Caption: {img.get('caption','')}"
        for img in images
    ])

    # print(images)

    prompt = f"""
Create professional educational slides.

TEXT:
{context_text}

IMAGES:
{image_info}

Rules:
- Max slides: 7
- Each slide:
    - title
    - as many bullet points as required, including at least 3 or 4 points
    - keep the text in bullet points very minimal and can restrict each point to a few words
    - Ensure text and image fits within a 1280x720 slide
    - no need to select images for slides like table of contents
    - no need of images for slides with no relevant images
    - 60-80 word natural conversational explanation
    - relevant image ids (array)

Return JSON list with:
- title
- bullet_points
- explanation
- image_ids
"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config={
            "response_mime_type": "application/json"
        }
    )

    raw_text = response.text

    clean_text = _clean_json_response(raw_text)

    return json.loads(clean_text)


# =====================================================
# STEP 2 — Voice Generation
# =====================================================

def generate_voice(text: str, slide_id: int):
    client = _get_client()

    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="puck"  # achernar, achird, algenib, algieba, alnilam, aoede, autonoe, callirrhoe, charon, despina, enceladus, erinome, fenrir, gacrux, iapetus, kore, laomedeia, leda, orus, puck, pulcherrima, rasalgethi, sadachbia, sadaltager, schedar, sulafat, umbriel, vindemiatrix, zephyr, zubenelgenubi
                    )
                )
            ),
        ),
    )

    audio_bytes = response.candidates[0].content.parts[0].inline_data.data

    return _save_pcm_as_wav(audio_bytes, slide_id)




def get_audio_duration(audio_path: str) -> float:
    audio = AudioSegment.from_file(audio_path)
    return len(audio) / 1000


# =====================================================
# STEP 3 — Image Resolver
# =====================================================

def resolve_image_path(slide, all_images):
    if len(all_images) == 0:
        return ""

    if len(slide["image_ids"]) == 0:
        return ""
    
    image_id = slide["image_ids"][0]

    for img in all_images:
        if img["id"] == image_id:
            return img["path"]

    return ""


# =====================================================
# STEP 4 — HTML Slide Renderer
# =====================================================

import random
import os

def render_slide_html(slide, duration, slide_id, all_images):
    _ensure_dirs()

    image_path = resolve_image_path(slide, all_images)
    abs_image_path = f"file:///{os.path.abspath(image_path)}" if image_path else ""

    # ---------- Dynamic Themes ----------
    themes = [
        # {
        #     "name": "Aurora Mist",
        #     "bg": "linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 100%)",
        #     "accent": "#4834d4"
        # },
        # {
        #     "name": "Midnight Emerald",
        #     "bg": "linear-gradient(135deg, #09203f 0%, #537895 100%)",
        #     "accent": "#50fa7b"
        # },
        # {
        #     "name": "Sunset Grain",
        #     "bg": "linear-gradient(135deg, #fbab7e 0%, #f7ce68 100%)",
        #     "accent": "#333333"
        # },
        {
            "name": "Deep Obsidian",
            "bg": "linear-gradient(135deg, #16161d 0%, #1f1f2e 100%)",
            "accent": "#ff0055"
        }
    ]

    theme = themes[slide_id % len(themes)]

    # ---------- Dynamic Layout ----------
    layout_type = slide_id % 3

    if layout_type == 0:
        layout_class = "row-layout"
    elif layout_type == 1:
        layout_class = "column-layout"
    else:
        layout_class = "center-layout"

    text_length = len(" ".join(slide["bullet_points"]))

    if text_length > 220:
        image_width = 420
        image_height = 300
    else:
        image_width = 520
        image_height = 360

    # ---------- Dynamic Animation ----------
    animation_type = slide_id % 3

    if animation_type == 0:
        animation_css = "fadeUp"
    elif animation_type == 1:
        animation_css = "slideIn"
    else:
        animation_css = "zoomIn"

    bullets_html = "".join(
        [f"<li style='animation-delay:{1.5 + i*1.5}s'>{b}</li>"
         for i, b in enumerate(slide["bullet_points"])]
    )

    html = f"""
<html>
<head>
<meta charset="UTF-8">
<style>

body {{
    margin:0;
    font-family: 'Segoe UI', sans-serif;
    background: {theme['bg']};
    color:white;
    height:100vh;
    display:flex;
    align-items:center;
    justify-content:center;
    overflow:hidden;
}}

.container {{
    width:95%;
    height:90%;
    display:flex;
    gap:40px;
}}

.row-layout {{
    flex-direction:row;
}}

.column-layout {{
    flex-direction:column;
    text-align:center;
}}

.center-layout {{
    flex-direction:column;
    justify-content:center;
    align-items:center;
    text-align:center;
}}

.text {{
    flex:1;
}}

.image {{
    width: {image_width}px;
    height: {image_height}px;
    display: flex;
    align-items: center;
    justify-content: center;
}}

.image img {{
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: 20px;
}}


h1 {{
    font-size:48px;
    margin-bottom:20px;
    color:{theme['accent']};
    animation:{animation_css} 1s ease forwards;
}}

ul {{
    list-style:none;
    padding:0;
    font-size:22px;
}}

li {{
    opacity:0;
    margin-bottom:15px;
    animation:{animation_css} 0.8s ease forwards;
}}

@keyframes fadeUp {{
    from {{opacity:0; transform:translateY(20px);}}
    to {{opacity:1; transform:translateY(0);}}
}}

@keyframes slideIn {{
    from {{opacity:0; transform:translateX(-40px);}}
    to {{opacity:1; transform:translateX(0);}}
}}

@keyframes zoomIn {{
    from {{opacity:0; transform:scale(0.8);}}
    to {{opacity:1; transform:scale(1);}}
}}

@keyframes floatAnim {{
    from {{ transform:translateY(0px); }}
    to {{ transform:translateY(-10px); }}
}}

</style>
</head>

<body>
<div class="container {layout_class}">

    <div class="text">
        <h1>{slide['title']}</h1>
        <ul>
            {bullets_html}
        </ul>
    </div>

    {"<div class='image'><img src='" + abs_image_path + "'></div>" if image_path else ""}

</div>
</body>
</html>
"""

    path = f"media/html/slide_{slide_id}.html"
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    return path

# =====================================================
# STEP 5 — HTML → PNG (Playwright Proper Way)
# =====================================================

async def html_to_video(html_path, slide_id, duration):
    _ensure_dirs()

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir="media/video/",
            record_video_size={"width": 1280, "height": 720}
        )

        page = await context.new_page()
        abs_path = os.path.abspath(html_path)

        await page.goto(f"file:///{abs_path}")
        await page.wait_for_timeout(int(duration * 1000))

        video = page.video

        await context.close()
        await browser.close()

    return await video.path()


# =====================================================
# STEP 6 — Image + Audio → Video
# =====================================================

def image_audio_to_video(webm_path, audio_path, duration, slide_id):
    output = f"media/video/slide_{slide_id}.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", webm_path,
        "-i", audio_path,
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",
        "-shortest",
        output
    ]

    subprocess.run(cmd, check=True)

    return output



# =====================================================
# STEP 7 — Stitch Videos
# =====================================================

def stitch_videos(video_paths):
    _ensure_dirs()

    concat_file = "media/video/concat.txt"

    with open(concat_file, "w") as f:
        for v in video_paths:
            f.write(f"file '{os.path.abspath(v)}'\n")

    final_path = "media/video/final.mp4"

    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        "-y",
        final_path
    ]

    subprocess.run(cmd, check=True)

    return final_path
