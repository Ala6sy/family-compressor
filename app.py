import base64
import logging

from flask import Flask, request, jsonify
import fitz  # PyMuPDF

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================
# بروفايلات الجودة / الضغط
# ============================
PROFILES = {
    # جودة قليلة + ضغط كبير
    "low_q_high_c":  {"zoom": 0.5, "quality": 55},

    # جودة متوسطة + ضغط قليل
    "med_q_low_c":   {"zoom": 0.9, "quality": 80},

    # جودة متوسطة + ضغط كبير
    "med_q_high_c":  {"zoom": 0.7, "quality": 65},

    # جودة عالية + ضغط قليل
    "high_q_low_c":  {"zoom": 1.0, "quality": 90},

    # جودة عالية + ضغط متوسط
    "high_q_med_c":  {"zoom": 0.9, "quality": 85},
}


def render_pdf_with_params(pdf_bytes: bytes, zoom: float, jpg_quality: int):
    """
    يرندر كل صفحة في الـ PDF كصورة JPEG حسب zoom و jpg_quality
    ثم يعيد تجميعها في PDF جديد.
    """
    src_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out_doc = fitz.open()

    mat = fitz.Matrix(zoom, zoom)

    for page in src_doc:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        # انتبه: في PyMuPDF الكلمة المفتاحية هي jpg_quality
        img_bytes = pix.tobytes("jpeg", jpg_quality=jpg_quality)

        rect = fitz.Rect(0, 0, pix.width, pix.height)
        new_page = out_doc.new_page(width=rect.width, height=rect.height)
        new_page.insert_image(rect, stream=img_bytes)

    out_bytes = out_doc.tobytes()
    return out_bytes, len(out_bytes) // 1024


def compress_pdf_with_profile(pdf_bytes: bytes, profile_code: str):
    """
    يضغط الـ PDF باستخدام بروفايل جاهز من PROFILES.
    """
    original_size_kb = len(pdf_bytes) // 1024
    if profile_code not in PROFILES:
        # لو بروفايل غير معروف → نرجع الأصلي
        logger.warning("Unknown profile '%s', returning original.", profile_code)
        return pdf_bytes, original_size_kb, original_size_kb

    params = PROFILES[profile_code]
    zoom = params["zoom"]
    jpg_quality = params["quality"]

    logger.info(
        "Using profile %s -> zoom=%.2f, quality=%d (original=%d KB)",
        profile_code, zoom, jpg_quality, original_size_kb
    )

    compressed_bytes, compressed_kb = render_pdf_with_params(
        pdf_bytes, zoom=zoom, jpg_quality=jpg_quality
    )

    logger.info(
        "Compressed size: %d KB (original %d KB)",
        compressed_kb, original_size_kb
    )

    return compressed_bytes, original_size_kb, compressed_kb


@app.route("/")
def index():
    return "Family PDF compressor with profiles is running."


@app.route("/compress", methods=["POST"])
def compress_endpoint():
    """
    يستقبل:
    - الملف في حقل 'file'
    - حقل اختياري 'profile' يساوي أحد القيم:
      low_q_high_c, med_q_low_c, med_q_high_c, high_q_low_c, high_q_med_c

    يرجع JSON فيه:
    - success
    - pdfBase64
    - originalSizeKB
    - compressedSizeKB
    """
    try:
        file_storage = request.files.get("file")
        if file_storage is None:
            return jsonify({
                "success": False,
                "error": "No file part in request (expected field name 'file')"
            }), 400

        profile = (request.form.get("profile") or "").strip()

        pdf_bytes = file_storage.read()
        logger.info(
            "Received file '%s' (%d KB), profile=%s",
            file_storage.filename,
            len(pdf_bytes) // 1024,
            profile or "NONE"
        )

        compressed_bytes, orig_kb, comp_kb = compress_pdf_with_profile(
            pdf_bytes, profile
        )

        return jsonify({
            "success": True,
            "pdfBase64": base64.b64encode(compressed_bytes).decode("ascii"),
            "originalSizeKB": orig_kb,
            "compressedSizeKB": comp_kb,
        })

    except Exception as e:
        logger.exception("Compression error")
        return jsonify({
            "success": False,
            "error": f"Compression error: {e}"
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
