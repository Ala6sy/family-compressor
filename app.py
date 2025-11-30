import base64
import io
import logging
import os

from flask import Flask, request, jsonify
import fitz  # PyMuPDF
from PIL import Image

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_mode_settings(mode: str):
    """
    تحويل اسم النمط إلى إعدادات التكبير وجودة JPEG.

    المبدأ الجديد:
    1) high_compression    → ما زال قوي لكن مقروء
    2) recommended         → توازن جيد (مقترح للاستخدام العادي)
    3) low_compression     → جودة عالية، ضغط خفيف
    """
    mode = (mode or "recommended").strip()

    if mode == "high_compression":
        # ضغط قوي لكن ليس قاتلاً جداً للجودة
        zoom = 0.9      # تقريبًا نفس حجم الصفحة الأصلي
        jpeg_quality = 65
        return zoom, jpeg_quality

    if mode == "low_compression":
        # أفضل جودة – مفيد للجوازات والوثائق المهمة
        zoom = 1.2      # دقة أعلى قليلاً
        jpeg_quality = 90
        return zoom, jpeg_quality

    # default = recommended
    zoom = 1.0          # نفس الدقة تقريباً
    jpeg_quality = 80   # جودة جيدة جداً
    return zoom, jpeg_quality



def compress_bytes(file_bytes: bytes, file_type: str, mode: str):
    """
    تضغط PDF أو صورة (JPG/PNG) حسب نوع الملف.
    ترجع: (out_bytes, original_kb, compressed_kb, output_mime, output_ext)
    """
    zoom, jpeg_quality = get_mode_settings(mode)
    original_kb = max(1, len(file_bytes) // 1024)
    file_type = (file_type or "").lower()

    # --------- حالة PDF ---------
    if "pdf" in file_type:
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception as e:
            raise ValueError(f"PDF error: {e}")

        mat = fitz.Matrix(zoom, zoom)
        out_pdf = fitz.open()

        try:
            for page in doc:
                # تحويل الصفحة إلى صورة
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
                img_bytes = buf.getvalue()

                # صفحة جديدة في PDF الناتج ونضع الصورة عليها
                new_page = out_pdf.new_page(width=pix.width, height=pix.height)
                new_page.insert_image(new_page.rect, stream=img_bytes)
        finally:
            doc.close()

        out_bytes = out_pdf.tobytes()
        out_pdf.close()

        compressed_kb = max(1, len(out_bytes) // 1024)
        return out_bytes, original_kb, compressed_kb, "application/pdf", ".pdf"

    # --------- حالة صورة (JPG / PNG ...) ---------
    try:
        img = Image.open(io.BytesIO(file_bytes))
    except Exception as e:
        raise ValueError(f"IMAGE error: {e}")

    img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
    out_bytes = buf.getvalue()

    compressed_kb = max(1, len(out_bytes) // 1024)
    return out_bytes, original_kb, compressed_kb, "image/jpeg", ".jpg"


@app.route("/compress", methods=["POST"])
def compress_endpoint():
    """
    يستقبل:
      - file (multipart/form-data)
      - mode: high_compression / recommended / low_compression
      - fileType: نوع الملف الأصلي (مثل application/pdf أو image/jpeg)
    """
    try:
        if "file" not in request.files:
            return jsonify(success=False, error="No file field 'file' in request"), 400

        up_file = request.files["file"]
        mode = request.form.get("mode", "recommended")
        file_type = request.form.get("fileType", "")

        file_bytes = up_file.read()
        if not file_bytes:
            return jsonify(success=False, error="Empty file"), 400

        logger.info(
            "Received file size=%d bytes, type=%s, mode=%s",
            len(file_bytes),
            file_type,
            mode,
        )

        out_bytes, orig_kb, comp_kb, out_mime, out_ext = compress_bytes(
            file_bytes, file_type, mode
        )

        out_b64 = base64.b64encode(out_bytes).decode("ascii")

        return jsonify(
            success=True,
            fileBase64=out_b64,
            originalSizeKB=orig_kb,
            compressedSizeKB=comp_kb,
            outputMimeType=out_mime,
            outputExtension=out_ext,
        )

    except ValueError as e:
        logger.exception("Value error while compressing")
        return jsonify(success=False, error=str(e)), 500
    except Exception as e:
        logger.exception("Unexpected error while compressing")
        return jsonify(success=False, error="Unexpected error: " + str(e)), 500


@app.route("/", methods=["GET"])
def index():
    return "Family compressor API is running.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

