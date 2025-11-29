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
    - تحويل كل صفحة إلى صورة (raster)
    - تخفيض الدقة (zoom) وجودة JPEG
    مناسب جداً لملفات الجواز / السكانر.

    :param pdf_bytes: محتوى الـ PDF الأصلي
    :param target_kb: الحجم المطلوب تقريباً بالكيلوبايت (يمكن تركه None)
    :return: (compressed_bytes, original_size_kb, compressed_size_kb)
    """
    original_size_kb = len(pdf_bytes) // 1024

    # افتح الـ PDF من الـ bytes
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out_doc = fitz.open()

    # حساب نسبة التصغير حسب الهدف
    if target_kb and target_kb > 0 and target_kb < original_size_kb:
        ratio = target_kb / original_size_kb
        # نحدها بين 0.3 و 1.0 حتى ما نصغر بشكل مبالغ
        ratio = max(0.3, min(1.0, ratio))
    else:
        # قيمة افتراضية (تخفيض متوسط)
        ratio = 0.7

    # الـ zoom يتحكم بالدقة (resolution)
    zoom = ratio
    # جودة JPEG بين 35 و 85
    jpeg_quality = int(40 + 40 * ratio)
    jpeg_quality = max(35, min(85, jpeg_quality))

    logger.info(
        "Compressing PDF: original=%d KB, target=%s, ratio=%.2f, zoom=%.2f, jpeg_quality=%d",
        original_size_kb, str(target_kb), ratio, zoom, jpeg_quality
    )

    mat = fitz.Matrix(zoom, zoom)

    for page_index, page in enumerate(doc):
        # حوّل الصفحة إلى صورة
        pix = page.get_pixmap(matrix=mat, alpha=False)
        # هنا كان الخطأ: الكلمة الصحيحة jpg_quality
        img_bytes = pix.tobytes("jpeg", jpg_quality=jpeg_quality)

        # أنشئ صفحة جديدة بالحجم المناسب
        rect = fitz.Rect(0, 0, pix.width, pix.height)
        new_page = out_doc.new_page(width=rect.width, height=rect.height)

        # أدخل الصورة في الصفحة
        new_page.insert_image(rect, stream=img_bytes)

    # حول الناتج إلى bytes
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
    - الملف تحت اسم الحقل 'file' (multipart/form-data)
    - حقل اختياري 'size' للحجم المطلوب بالكيلوبايت

    ويرجع JSON يحتوي:
    - success
    - pdfBase64 : الملف المضغوط base64
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

        size_str = (request.form.get("size") or "").strip()
        target_kb = int(size_str) if size_str.isdigit() else None

        # اقرأ الـ PDF
        pdf_bytes = file_storage.read()
        logger.info(
            "Received file '%s' (%d KB), target=%s",
            file_storage.filename,
            len(pdf_bytes) // 1024,
            str(target_kb)
        )

        # نضغط
        compressed_bytes, orig_kb, comp_kb = compress_pdf(pdf_bytes, target_kb)

        # رجّع النتيجة
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
    # للتجريب المحلي فقط
    app.run(host="0.0.0.0", port=10000, debug=True)
