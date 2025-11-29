import base64
import logging

from flask import Flask, request, jsonify
import fitz  # PyMuPDF

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def render_pdf_with_quality(pdf_bytes: bytes, jpg_quality: int, zoom: float = 1.0):
    """
    يرندر كل صفحة كصورة JPEG بجودة محددة ثم يعيد تجميعها في PDF جديد.
    """
    src_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out_doc = fitz.open()

    mat = fitz.Matrix(zoom, zoom)

    for page in src_doc:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        # في PyMuPDF 1.24.9 اسم البراميتر هو jpg_quality
        img_bytes = pix.tobytes("jpeg", jpg_quality=jpg_quality)

        rect = fitz.Rect(0, 0, pix.width, pix.height)
        new_page = out_doc.new_page(width=rect.width, height=rect.height)
        new_page.insert_image(rect, stream=img_bytes)

    out_bytes = out_doc.tobytes()
    return out_bytes, len(out_bytes) // 1024


def compress_pdf(pdf_bytes: bytes, target_kb: int | None = None):
    """
    خوارزمية ضغط ذكية:
    - لو ما في target_kb أو أكبر من الحجم الأصلي → نرجع الملف كما هو.
    - غير ذلك: نعمل "بحث ثنائي" على جودة JPEG لنقترب من الحجم المطلوب قدر الإمكان.
    """
    original_size_kb = len(pdf_bytes) // 1024
    logger.info("Original PDF size: %d KB, target=%s", original_size_kb, str(target_kb))

    # لو ما في هدف، أو الهدف أكبر من الأصلي → لا تضغط
    if (not target_kb) or target_kb <= 0 or target_kb >= original_size_kb:
        logger.info("No need to compress, returning original PDF.")
        return pdf_bytes, original_size_kb, original_size_kb

    # نطاق الجودة المسموح: من 30 إلى 90
    low_q = 30
    high_q = 90

    # نستخدم تكبير بسيط للوضوح (١.٢ تقريبًا ٨٦dpi بدل ٧٢dpi)
    zoom = 1.2

    best_bytes = None
    best_size = None
    best_diff = None

    # نسمح بعدد محاولات محدود حتى لا يتأخر السيرفر
    for _ in range(6):
        q = (low_q + high_q) // 2
        out_bytes, out_kb = render_pdf_with_quality(pdf_bytes, jpg_quality=q, zoom=zoom)

        diff = abs(out_kb - target_kb)
        logger.info(
            "Try quality=%d → size=%d KB (target=%d KB, diff=%d)",
            q, out_kb, target_kb, diff
        )

        # حفظ أفضل نتيجة حتى الآن
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_size = out_kb
            best_bytes = out_bytes

        # ضبط البحث الثنائي
        if out_kb > target_kb * 1.05:
            # الحجم أكبر من المطلوب → نخفّض الجودة
            high_q = q - 1
        elif out_kb < target_kb * 0.85:
            # الحجم أصغر بكثير من المطلوب → نستطيع رفع الجودة
            low_q = q + 1
        else:
            # داخل النطاق المقبول تقريباً → نوقف
            break

        if low_q > high_q:
            break

    # لو لأي سبب فشلنا في إنتاج ملف، نرجع الأصلي
    if best_bytes is None:
        logger.warning("Fell back to original PDF (no compressed candidate).")
        return pdf_bytes, original_size_kb, original_size_kb

    logger.info(
        "Best compressed size: %d KB (original %d KB, target %d KB)",
        best_size, original_size_kb, target_kb
    )
    return best_bytes, original_size_kb, best_size


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
    # للتجريب المحلي فقط
    app.run(host="0.0.0.0", port=10000, debug=True)
