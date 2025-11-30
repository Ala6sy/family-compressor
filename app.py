import base64
import logging
import io

from flask import Flask, request, jsonify
import fitz  # PyMuPDF

# إعداد اللوج
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def get_mode_params(mode: str):
    """
    اختيار درجة الضغط حسب الـ mode القادم من Apps Script.
    """
    mode = (mode or "").strip().lower()

    if mode == "high_compression":
        # ضغط شديد – جودة أقل
        return 0.6, 45
    elif mode == "low_compression":
        # ضغط أقل – جودة أعلى
        return 1.0, 75
    else:
        # recommended (الافتراضي)
        return 0.8, 60


def compress_pdf(pdf_bytes: bytes, mode: str):
    """
    يأخذ PDF كـ bytes ويعيد:
      - pdf_bytes المضغوط
      - الحجم الأصلي و المضغوط بالكيلوبايت
    """
    zoom, jpeg_quality = get_mode_params(mode)
    logger.info(f"Compressing PDF with mode={mode}, zoom={zoom}, jpeg_quality={jpeg_quality}")

    original_size_kb = round(len(pdf_bytes) / 1024)

    # فتح الـ PDF الأصلي من الذاكرة
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    new_doc = fitz.open()

    for page_index in range(len(doc)):
        page = doc.load_page(page_index)

        # تكبير / تصغير الصفحة
        mat = fitz.Matrix(zoom, zoom)

        # تحويل الصفحة لصورة
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # هنا كان الخطأ: استخدمت quality بدل jpg_quality
        img_bytes = pix.tobytes("jpeg", jpg_quality=jpeg_quality)

        # فتح الصورة كملف PDF صفحة واحدة
        img_doc = fitz.open("jpeg", img_bytes)
        img_page = img_doc[0]

        # إنشاء صفحة جديدة في الملف الجديد
        new_page = new_doc.new_page(
            width=img_page.rect.width,
            height=img_page.rect.height
        )

        # إدراج الصورة في الصفحة الجديدة
        new_page.show_pdf_page(new_page.rect, img_doc, 0)
        img_doc.close()

    # كتابة الـ PDF الجديد في الذاكرة
    compressed_bytes = new_doc.write()
    new_doc.close()
    doc.close()

    compressed_size_kb = round(len(compressed_bytes) / 1024)

    return compressed_bytes, original_size_kb, compressed_size_kb


@app.route("/", methods=["GET"])
def health():
    return jsonify({"ok": True, "message": "Family compressor API is running"})


@app.route("/compress", methods=["POST"])
def compress_endpoint():
    """
    يستقبل:
      - file: ملف PDF (multipart/form-data)
      - mode: high_compression / recommended / low_compression
    ويرجع JSON يحتوي:
      success, pdfBase64, originalSizeKB, compressedSizeKB
    """
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file part in request"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "error": "Empty filename"}), 400

        mode = request.form.get("mode", "recommended")
        pdf_bytes = file.read()

        logger.info(
            f"Received file for compression, mode={mode}, size={len(pdf_bytes)} bytes"
        )

        compressed_bytes, original_kb, compressed_kb = compress_pdf(pdf_bytes, mode)

        pdf_base64 = base64.b64encode(compressed_bytes).decode("ascii")

        return jsonify(
            {
                "success": True,
                "pdfBase64": pdf_base64,
                "originalSizeKB": original_kb,
                "compressedSizeKB": compressed_kb,
            }
        )

    except Exception as e:
        logger.exception("Error while compressing PDF")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    # لتجربة محلية فقط، في Render سيتم تشغيله عبر gunicorn
    app.run(host="0.0.0.0", port=8000)
