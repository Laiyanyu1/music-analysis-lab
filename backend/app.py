from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from score_form_analysis import analyze_musicxml, image_to_musicxml


app = FastAPI(title="Music Form Analysis Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "engines": ["librosa.segment", "Taking Form", "MSAF optional", "Audiveris optional"]}


@app.post("/api/analyze-form-score")
async def analyze_form_score(file: UploadFile = File(...)):
    filename = Path(file.filename or "upload.musicxml").name
    suffix = Path(filename).suffix.lower()
    allowed = {".xml", ".musicxml", ".mxl", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
    if suffix not in allowed:
        raise HTTPException(400, "请上传 MusicXML/MXL 或 JPG、PNG、WEBP、TIFF 乐谱图片")
    content = await file.read()
    if not content:
        raise HTTPException(400, "上传文件为空")
    if len(content) > 30 * 1024 * 1024:
        raise HTTPException(413, "文件超过 30MB")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / filename
            source.write_bytes(content)
            musicxml = source
            source_kind = "musicxml"
            if suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
                musicxml = image_to_musicxml(source, root / "omr")
                source_kind = "image→Audiveris→MusicXML"
            result = analyze_musicxml(musicxml)
            result["source"] = source_kind
            result["filename"] = filename
            return JSONResponse(result)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422, f"乐谱分析失败：{exc}") from exc
