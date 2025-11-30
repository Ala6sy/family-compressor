import base64
import io
import logging

from flask import Flask, request, jsonify
import fitz  # PyMuPDF

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MODES = {
    "high_compression": {
        "zoom": 0.6,
        "jpeg_quality": 45,
    },
    "recommended": {
        "zoom": 0.8,
        "jpeg_quality": 60,
    },
    "low_compression": {
        "zoom": 1.0,
        "jpeg_quality": 75,
    },
}


def compress_pdf(pdf_bytes: bytes, mode: str) -> dict:
    """
    يضغط ملف PDF باستخدام PyMuPDF عن طريق تحويل الصفحات إلى صور ثم بناء PDF جديد.
    """
    if mode not in MODES:
        mode = "recommended"

    zoom = MODES[mode]["zoom"]
    jpeg_quality = MODES[mode]["jpeg_quality"]

    original_size_kb = len(pdf_bytes) // 1024

    # افتح الملف الأصلي من الـ bytes
    src_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    dst_doc = fitz.open()

    matrix = fitz.Matrix(zoom, zoom)

    for page_index in range(len(src_doc)):
        page = src_doc.load_page(page_index)

        # تحويل الصفحة إلى صورة
        pix = page.get_pixmap(matrix=matrix)

        # تحويل الصورة إلى JPEG مضغوط
        img_bytes = pix.tobytes("jpeg", quality=jpeg_quality)

        # تحويل JPEG إلى PDF صفحة واحدة
        img_doc = fitz.open("jpeg", img_bytes)
        img_pdf = fitz.open("pdf", img_doc.convert_to_pdf())
        dst_doc.insert_pdf(img_pdf)

        img_doc.close()
        img_pdf.close()

    compressed_bytes = dst_doc.tobytes()
    dst_doc.close()
    src_doc.close()

    compressed_size_kb = len(compressed_bytes) // 1024

    pdf_base64 = base64.b64encode(compressed_bytes).decode("ascii")

    return {
        "success": True,
        "pdfBase64": pdf_base64,
        "originalSizeKB": original_size_kb,
        "compressedSizeKB": compressed_size_kb,
    }


@app.route("/compress", methods=["POST"])
def compress_endpoint():
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file field in request"}), 400

        file_storage = request.files["file"]
        mode = request.form.get("mode", "recommended")

        pdf_bytes = file_storage.read()

        logger.info("Received file for compression, mode=%s, size=%d bytes",
                    mode, len(pdf_bytes))

        result = compress_pdf(pdf_bytes, mode)

        return jsonify(result)

    except Exception as e:
        logger.exception("Error while compressing PDF")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    return "Family PDF Compressor API is running."


if __name__ == "__main__":
    # للتجربة المحلية فقط – في Render سيتم استخدام gunicorn
    app.run(host="0.0.0.0", port=8000, debug=True)
