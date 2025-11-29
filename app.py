import io
import base64
import logging

from flask import Flask, request, jsonify
from werkzeug.exceptions import HTTPException

# نحاول استيراد pikepdf (لو مش موجود لن نفشل، فقط نرجع الملف الأصلي)
try:
    import pikepdf
except ImportError:
    pikepdf = None

app = Flask(__name__)

# إعداد لوج بسيط
logging.basicConfig(level=logging.INFO)
logger = app.logger


# =========================================================
# دالة ضغط PDF
# =========================================================
def compress_pdf(pdf_bytes: bytes, target_kb: int | None = None):
    """
    تحاول ضغط ملف PDF باستخدام pikepdf.
    لو pikepdf غير متوفر أو الناتج أكبر/مساوي للأصل، نرجع الملف الأصلي.
    target_kb حالياً لا يُستخدم بشكل قوي، لكن تركناه للمستقبل.
    """
    orig_kb = len(pdf_bytes) // 1024

    # لو لا يوجد pikepdf، نرجع الملف كما هو
    if pikepdf is None:
        logger.warning("pikepdf غير متوفر، سيتم إرجاع الملف الأصلي بدون ضغط.")
        return pdf_bytes, orig_kb, orig_kb

    try:
        logger.info(f"Original size: {orig_kb} KB, target: {target_kb}")

        # نفتح PDF من الميموري
        input_stream = io.BytesIO(pdf_bytes)
        with pikepdf.Pdf.open(input_stream) as pdf:
            output_stream = io.BytesIO()

            # حفظ مع ضغط للستريمات وتقليل الحجم قدر الإمكان
            pdf.save(
                output_stream,
                compress_streams=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
                linearize=True,   # مفيد للقراءة عبر الويب
                # minimize=True    # يمكن إضافته لو أردت مزيداً من التصغير (حسب إصدار pikepdf)
            )

            compressed_bytes = output_stream.getvalue()

        comp_kb = len(compressed_bytes) // 1024
        logger.info(f"Compressed size: {comp_kb} KB")

        # لو لم يتحسن الحجم، نرجع الأصلي
        if comp_kb == 0 or comp_kb >= orig_kb:
            logger.info("Compressed file not significantly smaller, returning original.")
            return pdf_bytes, orig_kb, orig_kb

        return compressed_bytes, orig_kb, comp_kb

    except Exception as e:
        logger.exception(f"Compression failed, returning original. Error: {e}")
        return pdf_bytes, orig_kb, orig_kb


# =========================================================
# مسار بسيط للفحص
# =========================================================
@app.route("/", methods=["GET"])
def index():
    return "Family PDF compressor is running 🚀", 200


# =========================================================
# مسار الضغط /compress
# يستقبل:
#   - ملف PDF في الحقل "file"
#   - اختيارياً size في الحقل "size" بالكيلوبايت
# ويرجع JSON يحتوي:
#   success, pdfBase64, originalSizeKB, compressedSizeKB
# =========================================================
@app.route("/compress", methods=["POST"])
def compress_endpoint():
    try:
        # الملف المرسل من Google Apps Script في حقل "file"
        file_storage = request.files.get("file")
        if file_storage is None:
            return (
                jsonify({
                    "success": False,
                    "error": "No file part in request (expected field name 'file')"
                }),
                400,
            )

        # الحجم الهدف (اختياري حالياً)
        size_raw = request.form.get("size", "")
        size_str = size_raw.strip() if size_raw else ""
        target_kb = int(size_str) if size_str.isdigit() else None

        # قراءة بايتات الملف
        pdf_bytes = file_storage.read()
        if not pdf_bytes:
            return (
                jsonify({
                    "success": False,
                    "error": "Uploaded file is empty"
                }),
                400,
            )

        logger.info(
            f"Received file '{file_storage.filename}' "
            f"({len(pdf_bytes)//1024} KB), target={target_kb}"
        )

        # استدعاء دالة الضغط
        compressed_bytes, orig_kb, comp_kb = compress_pdf(pdf_bytes, target_kb)

        # تحويل الناتج إلى base64 ليرسله Google Apps Script
        pdf_b64 = base64.b64encode(compressed_bytes).decode("ascii")

        return jsonify({
            "success": True,
            "pdfBase64": pdf_b64,
            "originalSizeKB": orig_kb,
            "compressedSizeKB": comp_kb,
        }), 200

    except Exception as e:
        logger.exception("Error in /compress")
        return jsonify({"success": False, "error": str(e)}), 500


# =========================================================
# هاندلر للأخطاء HTTPException (اختياري لكنه جميل)
# =========================================================
@app.errorhandler(HTTPException)
def handle_http_exception(e: HTTPException):
    response = e.get_response()
    response.data = jsonify({
        "success": False,
        "error": e.description,
    }).data
    response.content_type = "application/json"
    return response, e.code


# =========================================================
# نقطة البداية عند التشغيل المحلي
# في Render سيستخدمون gunicorn app:app
# =========================================================
if __name__ == "__main__":
    # للتجربة محلياً:
    app.run(host="0.0.0.0", port=10000, debug=True)
