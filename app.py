from flask import Flask, request, send_file, abort
import requests
import tempfile
import os
from pikepdf import Pdf
from PIL import Image

app = Flask(__name__)


@app.post("/compress")
def compress():
    data = request.get_json(force=True)
    url = data.get("url")
    if not url:
        abort(400, "missing url")

    # 1) تحميل الملف من الرابط (يفضل يكون Anyone with the link في Google Drive)
    resp = requests.get(url, stream=True)
    if resp.status_code != 200:
        abort(400, f"cannot download source: {resp.status_code}")

    content_type = resp.headers.get("Content-Type", "").lower()
    url_lower = url.lower()

    # نحدد النوع بشكل بسيط
    if "pdf" in content_type or url_lower.endswith(".pdf"):
        kind = "pdf"
        suffix = ".pdf"
    elif "image" in content_type or any(url_lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]):
        kind = "image"
        suffix = ".jpg"
    else:
        # نحاول كأنه PDF افتراضياً
        kind = "pdf"
        suffix = ".pdf"

    # 2) حفظ الملف في ملف مؤقت
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as src:
        for chunk in resp.iter_content(8192):
            src.write(chunk)
        src_path = src.name

    dst_fd, dst_path = tempfile.mkstemp(suffix=suffix)
    os.close(dst_fd)

    try:
        # 3) ضغط حسب النوع
        if kind == "pdf":
            with Pdf.open(src_path) as pdf:
                # إعدادات ضغط بسيطة (تقدر تعدلها لاحقاً)
                pdf.save(
                    dst_path,
                    compress_streams=True,
                    optimize_version=True
                )
        else:
            img = Image.open(src_path)
            img = img.convert("RGB")
            img.save(dst_path, optimize=True, quality=70)

        # 4) إعادة الملف المضغوط كـ binary
        return send_file(dst_path, as_attachment=False)
    finally:
        # تنظيف الملفات المؤقتة
        try:
            os.remove(src_path)
        except Exception:
            pass
        try:
            if os.path.exists(dst_path):
                os.remove(dst_path)
        except Exception:
            pass


@app.get("/")
def index():
    return "Compressor API OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
