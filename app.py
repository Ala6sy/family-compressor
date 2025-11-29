from flask import Flask, request, jsonify, Response
import io
import logging
import pikepdf
import requests  # لتحميل الملف من الرابط عند الحاجة

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def compress_pdf(pdf_bytes: bytes, target_kb: int | None = None):
    """
    ضغط PDF بسيط عن طريق إعادة حفظه عبر pikepdf.
    لا نستخدم optimize_streams لأن النسخة الحالية لا تدعمه.
    """

    orig_size = len(pdf_bytes)

    input_stream = io.BytesIO(pdf_bytes)
    output_stream = io.BytesIO()

    with pikepdf.open(input_stream) as pdf:
        # حفظ عادي (فيه بعض الضغط تلقائياً)
        pdf.save(output_stream)

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
    يحاول أولاً قراءة ملف مرفوع باسم 'file'.
    إذا لم يجده، يحاول قراءة 'fileUrl' (من form أو JSON) وتحميله بنفسه.
    """

    try:
        target_kb = None
        # حجم الهدف (اختياري)
        size_str = None

        pdf_bytes = None

        # --------- 1) حاول قراءة ملف مرفوع ---------
        if "file" in request.files and request.files["file"].filename:
            file_storage = request.files["file"]
            pdf_bytes = file_storage.read()
            logger.info(
                "Received upload '%s', size=%d KB",
                file_storage.filename,
                len(pdf_bytes) // 1024,
            )
            size_str = request.form.get("size")

        # --------- 2) إن لم يوجد ملف، جرّب fileUrl ---------
        if pdf_bytes is None:
            # من form (multipart أو x-www-form-urlencoded)
            file_url = request.form.get("fileUrl")

            # أو من JSON
            if not file_url and request.is_json:
                data = request.get_json(silent=True) or {}
                file_url = data.get("fileUrl")

            if not file_url:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "No file upload and no fileUrl provided",
                        }
                    ),
                    400,
                )

            logger.info("Downloading PDF from URL: %s", file_url)
            r = requests.get(file_url, timeout=60)
            if r.status_code != 200:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Failed to download file from URL, status={r.status_code}",
                        }
                    ),
                    400,
                )
            pdf_bytes = r.content

            # حجم الهدف من form أو JSON
            if not size_str:
                size_str = request.form.get("size")
            if not size_str and request.is_json:
                data = request.get_json(silent=True) or {}
                size_str = data.get("size")

        # --------- تجهيز target_kb ---------
        if size_str and str(size_str).isdigit():
            target_kb = int(size_str)

        compressed_bytes, orig_size, comp_size = compress_pdf(pdf_bytes, target_kb)

        response = Response(compressed_bytes, mimetype="application/pdf")
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
