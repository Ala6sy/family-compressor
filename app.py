from flask import Flask, request, jsonify, Response
import io
import logging
import pikepdf

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def compress_pdf(pdf_bytes: bytes, target_kb: int | None = None):
    """
    يقوم بضغط ملف PDF ببساطة عن طريق إعادة حفظه عبر pikepdf.
    حالياً لا نستخدم optimize_streams لأن النسخة المثبتة لا تدعمه.
    """

    orig_size = len(pdf_bytes)

    input_stream = io.BytesIO(pdf_bytes)
    output_stream = io.BytesIO()

    # نفتح الـ PDF عبر pikepdf ونحفظه من جديد
    with pikepdf.open(input_stream) as pdf:
        # في بعض نسخ pikepdf يوجد compress_streams، لكن لتفادي أي مشاكل
        # سنستخدم الحفظ العادي فقط (ما زال فيه قدر من الضغط).
        pdf.save(output_stream)  # لا نستخدم optimize_streams هنا

    compressed_bytes = output_stream.getvalue()
    comp_size = len(compressed_bytes)

    logger.info(
        "Compression done: original=%d KB, compressed=%d KB",
        orig_size // 1024,
        comp_size // 1024,
    )

    return compressed_bytes, orig_size, comp_size


@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "message": "Family compressor is running"})


@app.route("/compress", methods=["POST"])
def compress_route():
    """
    يستقبل:
      - file: ملف PDF القادم من Google Apps Script (UrlFetchApp)
      - size (اختياري): الحجم المطلوب تقريباً بالكيلوبايت، حالياً فقط للمستقبل

    ويرجع:
      - PDF مضغوط مباشرة (binary) مع Content-Type = application/pdf
      - في حالة الخطأ يرجع JSON مع status 500
    """
    try:
        if "file" not in request.files:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "No file part in request (expected field name 'file')",
                    }
                ),
                400,
            )

        file_storage = request.files["file"]
        pdf_bytes = file_storage.read()

        if not pdf_bytes:
            return jsonify({"success": False, "error": "Empty file"}), 400

        # الحجم المطلوب (حالياً غير مستخدم بقوة، لكن نمرره للدالة لو احتجناه لاحقاً)
        size_str = request.form.get("size")
        target_kb = int(size_str) if size_str and size_str.isdigit() else None

        logger.info(
            "Received file '%s', size=%d KB, target_kb=%s",
            file_storage.filename,
            len(pdf_bytes) // 1024,
            target_kb,
        )

        compressed_bytes, orig_size, comp_size = compress_pdf(pdf_bytes, target_kb)

        # نرجع الـ PDF المضغوط مباشرة كـ binary response
        response = Response(compressed_bytes, mimetype="application/pdf")
        # ممكن نضيف بعض الهيدرز للمعلومية فقط
        response.headers["X-Original-Size-KB"] = str(orig_size // 1024)
        response.headers["X-Compressed-Size-KB"] = str(comp_size // 1024)

        return response

    except Exception as e:
        logger.exception("Error while compressing PDF")
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Compression error: {str(e)}",
                }
            ),
            500,
        )


if __name__ == "__main__":
    # للتجربة المحلية فقط
    app.run(host="0.0.0.0", port=5000, debug=True)
