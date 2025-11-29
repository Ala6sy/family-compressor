import io
import base64
import logging

from flask import Flask, request, jsonify
import requests
import fitz  # PyMuPDF
from PIL import Image

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_file(url: str) -> bytes:
    """تنزيل الملف من رابط (Google Drive direct link)."""
    resp = requests.get(url, timeout=40)
    resp.raise_for_status()
    return resp.content


def compress_pdf_images(pdf_bytes: bytes, target_kb: int | None = None):
    """
    ضغط PDF عن طريق إعادة ضغط الصور بداخله بجودة أقل.
    target_kb: الحجم المطلوب تقريبياً بالكيلو بايت (اختياري).
    """
    original_size = len(pdf_bytes)
    original_kb = round(original_size / 1024)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    # حساب نسبة التقريب للحجم
    if target_kb and target_kb > 0:
        ratio = target_kb / max(original_kb, 1)
        ratio = max(0.2, min(ratio, 0.9))
    else:
        ratio = 0.7

    base_quality = 95
    quality = int(base_quality * ratio)
    quality = max(35, min(quality, 90))

    # مقياس لتصغير الأبعاد
    if target_kb and target_kb < original_kb:
        scale = max(0.4, min(ratio, 0.9))
    else:
        scale = 0.8

    logger.info(
        f"Original size: {original_kb} KB, target: {target_kb}, "
        f"ratio={ratio:.2f}, jpeg_quality={quality}, scale={scale:.2f}"
    )

    pages_count = len(doc)
    images_replaced = 0

    for page_index in range(pages_count):
        page = doc[page_index]
        img_list = page.get_images(full=True)

        for img in img_list:
            xref = img[0]
            try:
                pix = fitz.Pixmap(doc, xref)
            except Exception as e:
                logger.warning(f"Failed to get pixmap for xref {xref}: {e}")
                continue

            # تخطي الصور الصغيرة جداً
            if pix.width < 400 and pix.height < 400:
                pix = None
                continue

            if pix.n >= 4:
                pix = fitz.Pixmap(fitz.csRGB, pix)

            mode = "RGB"
            img_pil = Image.frombytes(mode, (pix.width, pix.height), pix.samples)

            # تصغير الأبعاد
            new_w = int(img_pil.width * scale)
            new_h = int(img_pil.height * scale)
            if new_w < 200 or new_h < 200:
                new_w = max(new_w, 200)
                new_h = max(new_h, 200)

            if (new_w, new_h) != img_pil.size:
                img_pil = img_pil.resize((new_w, new_h), Image.LANCZOS)

            buf = io.BytesIO()
            img_pil.save(buf, format="JPEG", quality=quality, optimize=True)
            new_image_bytes = buf.getvalue()

            try:
                doc.update_image(xref, new_image_bytes)
                images_replaced += 1
            except Exception as e:
                logger.warning(f"Failed to update image xref {xref}: {e}")
            finally:
                pix = None

    logger.info(f"Images replaced: {images_replaced}")

    out_buf = io.BytesIO()
    doc.save(out_buf)
    doc.close()

    compressed_bytes = out_buf.getvalue()
    compressed_kb = round(len(compressed_bytes) / 1024)

    return compressed_bytes, original_kb, compressed_kb


@app.route("/")
def index():
    return "Family compressor is running."


@app.route("/compress", methods=["POST"])
def compress():
    try:
        # نحاول أولاً قراءة JSON
        data = request.get_json(silent=True)

        if data:
            # طلب JSON (الشكل الجديد من Code.gs)
            file_url = data.get("fileUrl")
            target_kb = data.get("targetKB")
        else:
            # لو مافي JSON، نحاول نقرأ من form (الشكل القديم)
            file_url = request.form.get("fileUrl")
            target_kb = request.form.get("targetKB")

        if not file_url:
            return jsonify({"success": False, "error": "fileUrl is required"}), 400

        if target_kb is not None:
            try:
                target_kb = int(target_kb)
            except (ValueError, TypeError):
                target_kb = None

        logger.info(f"Downloading file: {file_url}")
        pdf_bytes = download_file(file_url)

        compressed_bytes, orig_kb, comp_kb = compress_pdf_images(pdf_bytes, target_kb)

        # لو ما نقص الحجم بشكل ملحوظ نرجع الأصل
        if comp_kb >= orig_kb * 0.98:
            logger.info("Compressed file not significantly smaller; returning original.")
            compressed_bytes = pdf_bytes
            comp_kb = orig_kb

        pdf_b64 = base64.b64encode(compressed_bytes).decode("ascii")

        return jsonify({
            "success": True,
            "pdfBase64": pdf_b64,
            "originalSizeKB": orig_kb,
            "compressedSizeKB": comp_kb
        })

    except Exception as e:
        logger.exception("Compression error")
        return jsonify({"success": False, "error": f"Compression error: {e}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
