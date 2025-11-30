import base64
import logging

from flask import Flask, request, jsonify
import fitz  # PyMuPDF

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# -------------------------
# بروفايلات الجودة والضغط
# -------------------------
PROFILES = {
    # جودة قليلة + ضغط قوي (أصغر حجم – تشويش أعلى)
    "low_q_high_c": {
        "zoom": 0.4,   # دقة الصورة
        "jpeg": 45     # جودة JPEG
    },
    # جودة متوسطة + ضغط قليل (ملف أصغر بقليل مع وضوح جيد)
    "med_q_low_c": {
        "zoom": 0.8,
        "jpeg": 80
    },
    # جودة متوسطة + ضغط قوي (توازن بين الحجم والوضوح)
    "med_q_high_c": {
        "zoom": 0.6,
        "jpeg": 60
    },
    # جودة عالية + ضغط قليل (أفضل وضوح – حجم قريب من الأصلي)
    "high_q_low_c": {
        "zoom": 1.0,
        "jpeg": 90
    },
    # جودة عالية + ضغط متوسط (توازن مقبول مع وضوح ممتاز)
    "high_q_med_c": {
        "zoom": 0.9,
        "jpeg": 80
    }
}

DEFAULT_PROFILE = "med_q_high_c"


def compress_pdf(pdf_bytes: bytes, profile_name: str):
    """
    ضغط PDF عن طريق تحويل الصفحات إلى صور JPEG
    حسب إعدادات البروفايل (zoom + jpeg quality).
    """
    original_size_kb = len(pdf_bytes) // 1024

    profile = PROFILES.get(profile_name, PROFILES[DEFAULT_PROFILE])
    zoom = profile["zoom"]
    jpeg_quality = profile["jpeg"]

    logger.info(
        "Compressing PDF: profile=%s, zoom=%.2f, jpeg_quality=%d, original=%d KB",
        profile_name, zoom, jpeg_quality, original_size_kb
    )

    # افتح الـ PDF من bytes
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out_doc = fitz.open()

    mat = fitz.Matrix(zoom, zoom)

    for page_index, page in enumerate(doc):
        # تحويل الصفحة إلى صورة
        pix = page.get_pixmap(matrix=mat, alpha=False)
        # انتبه: في PyMuPDF لا نستخدم keyword "quality"، فقط قيمة رقمية
        img_bytes = pix.tobytes("jpeg", jpeg_quality)

        # إنشاء صفحة جديدة بحجم الصورة
        rect = fitz.Rect(0, 0, pix.width, pix.height)
        new_page = out_doc.new_page(width=rect.width, height=rect.height)

        # إدراج الصورة داخل الصفحة
        new_page.insert_image(rect, stream=img_bytes)

    compressed_bytes = out_doc.tobytes()
    compressed_size_kb = len(compressed_bytes) // 1024

    logger.info(
        "Compressed size: %d KB (original %d KB)",
        compressed_size_kb, original_size_kb
    )

    return compressed_bytes, original_size_kb, compressed_size_kb


@app.route("/")
def index():
    return "Family PDF compressor is running."


@app.route("/compress", methods=["POST"])
def compress_endpoint():
    """
    يستقبل:
      - الملف في الحقل 'file'
      - البروفايل في الحقل 'profile'
    ويرجع:
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
        if profile == "":
            profile = DEFAULT_PROFILE

        pdf_bytes = file_storage.read()
        logger.info(
            "Received file '%s' (%d KB), profile=%s",
            file_storage.filename,
            len(pdf_bytes) // 1024,
            profile
        )

        compressed_bytes, orig_kb, comp_kb = compress_pdf(pdf_bytes, profile)

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
