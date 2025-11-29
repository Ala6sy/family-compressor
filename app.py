import os
import io
import base64
import logging

import requests
from flask import Flask, request, jsonify
import pikepdf

app = Flask(__name__)

# إعداد اللوج
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# حد أقصى لحجم الملف اللي نسمح بتنزيله (ميغابايت)
MAX_DOWNLOAD_MB = 15


def download_file(url: str) -> bytes:
    """
    ينزّل الملف من رابط Google Drive (أو أي رابط مباشر)
    ويرجعه كـ bytes مع حد أقصى للحجم.
    """
    logger.info(f"Downloading file from: {url}")
    resp = requests.get(url, stream=True, timeout=25)
    resp.raise_for_status()

    buf = io.BytesIO()
    total = 0
    chunk_size = 64 * 1024  # 64 KB

    for chunk in resp.iter_content(chunk_size):
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_DOWNLOAD_MB * 1024 * 1024:
            raise ValueError(f"File too large (> {MAX_DOWNLOAD_MB} MB)")
        buf.write(chunk)

    logger.info(f"Downloaded {total} bytes")
    return buf.getvalue()


def compress_pdf(pdf_bytes: bytes, target_kb: int | float | None = None):
    """
    يضغط ملف PDF باستخدام pikepdf ويرجع:
    (الملف المضغوط, حجم الأصلي, حجم المضغوط) بالبايت.
    (الضغط هنا أساسي، بدون لعب مع الجودة كثيراً)
    """
    original_size = len(pdf_bytes)
    logger.info(f"Original PDF size: {original_size} bytes")

    input_stream = io.BytesIO(pdf_bytes)
    output_stream = io.BytesIO()

    # ضغط بسيط/قياسي
    with pikepdf.open(input_stream) as pdf:
        pdf.save(
            output_stream,
            optimize_streams=True,
            compress_streams=True
        )

    compressed_bytes = output_stream.getvalue()
    logger.info(f"Compressed PDF size: {len(compressed_bytes)} bytes")

    # ممكن لاحقاً نضيف منطق تكرار وتحقيق target_kb لو حابب
    return compressed_bytes, original_size, len(compressed_bytes)


@app.route("/", methods=["GET"])
def index():
    return "family-compressor is alive"


@app.route("/compress", methods=["POST"])
def compress_endpoint():
    """
    يستقبل JSON من Apps Script بالشكل:
    {
      "fileUrl": "https://drive.google.com/uc?export=download&id=...",
      "targetKB": 400   // اختياري
    }
    ويرجع:
    {
      "success": true,
      "originalSizeKB": ...,
      "compressedSizeKB": ...,
      "pdfBase64": "...."
    }
    """
    try:
        data = request.get_json(force=True, silent=False)
    except Exception as e:
        logger.exception("Invalid JSON body")
        return jsonify(success=False, error=f"Invalid JSON: {e}"), 400

    if not isinstance(data, dict):
        return jsonify(success=False, error="Body must be a JSON object"), 400

    file_url = data.get("fileUrl") or data.get("url")
    target_kb = data.get("targetKB") or data.get("target_kb") or 0

    if not file_url:
        return jsonify(success=False, error="fileUrl is required"), 400

    try:
        pdf_bytes = download_file(file_url)
    except Exception as e:
        logger.exception("Download failed")
        return jsonify(success=False, error=f"Download error: {e}"), 500

    try:
        compressed_bytes, orig_size, comp_size = compress_pdf(pdf_bytes, target_kb)
    except Exception as e:
        logger.exception("Compression failed")
        return jsonify(success=False, error=f"Compression error: {e}"), 500

    # تحويل النتيجة إلى base64 ليرجعها لـ Apps Script
    pdf_b64 = base64.b64encode(compressed_bytes).decode("ascii")

    resp = {
        "success": True,
        "originalSizeKB": round(orig_size / 1024),
        "compressedSizeKB": round(comp_size / 1024),
        "pdfBase64": pdf_b64,
    }
    return jsonify(resp)


if __name__ == "__main__":
    # Render يعطي PORT في متغير بيئة
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
