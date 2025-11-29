import base64
import logging

from flask import Flask, request, jsonify
import fitz  # PyMuPDF

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def compress_pdf(pdf_bytes: bytes, target_kb: int | None = None):
    """
    ضغط PDF عن طريق:
      - تحويل كل صفحة لصورة (raster)
      - تقليل الدقة (zoom) + جودة JPEG

    target_kb: الحجم المطلوب تقريباً بالكيلوبايت (ليس دقيق 100% لكنه قريب).
    يرجع: (compressed_bytes, original_size_kb, compressed_size_kb)
    """
    # الحجم الأصلي
    original_size_kb = max(1, len(pdf_bytes) // 1024)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out_doc = fitz.open()

    # حساب zoom بناءً على النسبة المطلوبة في الحجم
    if target_kb is not None and target_kb > 0:
        # نسبة الحجم المطلوب إلى الحجم الأصلي (0–1)
        desired_ratio = min(1.0, target_kb / float(original_size_kb))

        # لأن الحجم يتناسب مع المساحة (≈ zoom^2)
        # نأخذ الجذر التربيعي حتى يكون تأثير zoom منطقي
        zoom = desired_ratio ** 0.5

        # لا نسمح أن يكون صغير جداً أو أكبر من 1
        zoom = max(0.35, min(1.0, zoom))
    else:
        # لو ما أُرسل هدف → ضغط متوسط
        zoom = 0.6

    # جودة JPEG تربط بالـ zoom (كلما كبر zoom نرفع الجودة)
    jpeg_quality = int(45 + 35 * zoom)  # تقريباً من 45 إلى 80
    jpeg_quality = max(40, min(90, jpeg_quality))

    logger.info(
        "Compressing PDF: original=%d KB, target=%s KB, zoom=%.2f, jpeg_quality=%d",
        original_size_kb,
        str(target_kb),
        zoom,
        jpeg_quality,
    )

    matrix = fitz.Matrix(zoom, zoom)

    for page_index, page in enumerate(doc):
        # تحويل الصفحة لصورة
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img_bytes = pix.tobytes("jpeg", quality=jpeg_quality)

        # صفحة جديدة بحجم الصورة
        rect = fitz.Rect(0, 0, pix.width, pix.height)
        new_page = out_doc.new_page(width=rect.width, height=rect.height)

        # إدراج الصورة داخل الصفحة
        new_page.insert_image(rect, stream=img_bytes)

    compressed_bytes = out_doc.tobytes()
    compressed_size_kb = max(1, len(compressed_bytes) // 1024)

    logger.info(
        "Compressed size: %d KB (original %d KB)",
        compressed_size_kb,
        original_size_kb,
    )

    return compressed_bytes, original_size_kb, compressed_size_kb


@app.route("/")
def index():
    return "Family PDF compressor is running."


@app.route("/compress", methods=["POST"])
def compress_endpoint():
    """
    يستقبل:
      - الملف في الحقل 'file' (multipart/form-data)
      - حقل اختياري 'size' للحجم المطلوب بالكيلوبايت

    ويرجع JSON يحتوي:
      - success
      - pdfBase64        : الملف المضغوط base64
      - originalSizeKB   : حجم الأصلي بالكيلوبايت
      - compressedSizeKB : حجم المضغوط بالكيلوبايت
    """
    try:
        file_storage = request.files.get("file")
        if file_storage is None:
            return jsonify({
                "success": False,
                "error": "No file part in request (expected field name 'file')"
            }), 400

        size_str = (request.form.get("size") or "").strip()
        target_kb = int(size_str) if size_str.isdigit() else None

        pdf_bytes = file_storage.read()
        logger.info(
            "Received file '%s' (%d KB), target=%s",
            file_storage.filename,
            len(pdf_bytes) // 1024,
            str(target_kb)
        )

        compressed_bytes, orig_kb, comp_kb = compress_pdf(pdf_bytes, target_kb)

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
    # للتجربة المحلية فقط
    app.run(host="0.0.0.0", port=10000, debug=True)
