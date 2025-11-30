import base64
import logging
import io

from flask import Flask, request, jsonify
import fitz  # PyMuPDF

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_compression_params(mode: str):
    """
    ثلاثة مستويات مثل iLovePDF تقريباً:

    - extreme  : ضغط شديد (جودة أقل، حجم أصغر)
    - recommended : موصى به (توازن بين الجودة والحجم)
    - low : ضغط أقل (جودة أعلى، ملف أكبر قليلاً)
    """
    mode = (mode or "recommended").lower()

    if mode == "extreme":
        # جودة أقل، ضغط أعلى
        zoom = 0.55         # تصغير الأبعاد
        jpeg_quality = 45   # جودة JPEG
    elif mode == "low":
        # جودة عالية تقريباً، ضغط خفيف
        zoom = 0.95
        jpeg_quality = 80
    else:
        # recommended
        zoom = 0.75
        jpeg_quality = 60

    return zoom, jpeg_quality


def compress_pdf(pdf_bytes: bytes, mode: str = "recommended"):
    """
    ضغط PDF بتحويل الصفحات إلى صور مع التحكم في:
    - zoom (الدقة)
    - jpeg_quality (جودة الصورة)
    """
    original_size_kb = len(pdf_bytes) // 1024

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out_doc = fitz.open()

    zoom, jpeg_quality = get_compression_params(mode)

    logger.info(
        "Compressing PDF: original=%d KB, mode=%s, zoom=%.2f, jpeg_quality=%d",
        original_size_kb, mode, zoom, jpeg_quality
    )

    mat = fitz.Matrix(zoom, zoom)

    for page_index, page in enumerate(doc):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("jpeg", quality=jpeg_quality)

        rect = fitz.Rect(0, 0, pix.width, pix.height)
        new_page = out_doc.new_page(width=rect.width, height=rect.height)
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
    - الملف تحت اسم الحقل 'file' (multipart/form-data)
    - حقل 'mode' قيمته: extreme / recommended / low
    ويرجع JSON يحتوي:
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

        mode = request.form.get("mode", "recommended")

        pdf_bytes = file_storage.read()
        logger.info(
            "Received file '%s' (%d KB), mode=%s",
            file_storage.filename,
            len(pdf_bytes) // 1024,
            mode
        )

        compressed_bytes, orig_kb, comp_kb = compress_pdf(pdf_bytes, mode)

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
