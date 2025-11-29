import os
import tempfile

import requests
from flask import Flask, request, send_file, jsonify
from pikepdf import Pdf
from PIL import Image

app = Flask(__name__)


@app.get("/")
def index():
    """
    نقطة فحص بسيطة للتأكد أن السيرفر شغال.
    """
    return "Family Compressor API is running", 200


@app.post("/compress")
def compress():
    """
    يستقبل JSON فيه:
        { "url": "https://...." }

    يقوم بـ:
    1) تحميل الملف من الرابط.
    2) معرفة هل هو PDF أم صورة.
    3) ضغطه باستخدام pikepdf أو Pillow.
    4) إرجاع الملف المضغوط كـ response (binary).
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        url = data.get("url")
        if not url:
            return jsonify({"success": False, "error": "missing 'url' in JSON body"}), 400

        # 1) تحميل الملف من الرابط
        try:
            resp = requests.get(url, stream=True, timeout=60)
        except Exception as e:
            return jsonify({"success": False, "error": f"download error: {e}"}), 400

        if resp.status_code != 200:
            return jsonify(
                {
                    "success": False,
                    "error": f"cannot download file, http {resp.status_code}",
                }
            ), 400

        content_type = (resp.headers.get("Content-Type") or "").lower()
        url_lower = url.lower()

        # 2) تحديد نوع الملف (بدون تعقيد)
        if "pdf" in content_type or url_lower.endswith(".pdf"):
            kind = "pdf"
            suffix = ".pdf"
        elif "image" in content_type or any(
            url_lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]
        ):
            kind = "image"
            suffix = ".jpg"
        else:
            # نفترض PDF لو مش معروف
            kind = "pdf"
            suffix = ".pdf"

        # 3) حفظ الملف في ملف مؤقت
        src_fd, src_path = tempfile.mkstemp(suffix=suffix)
        os.close(src_fd)
        with open(src_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)

        # ملف مؤقت للإخراج
        dst_fd, dst_path = tempfile.mkstemp(suffix=suffix)
        os.close(dst_fd)

        # 4) عملية الضغط
        if kind == "pdf":
            # ضغط PDF
            with Pdf.open(src_path) as pdf:
                pdf.save(
                    dst_path,
                    compress_streams=True,
                    optimize_version=True,
                )
        else:
            # ضغط صورة
            img = Image.open(src_path)
            img = img.convert("RGB")
            # quality 70 تقريباً ضغط محترم بدون فقد كبير
            img.save(dst_path, optimize=True, quality=70)

        # حجم الملف الجديد (للمعلومة فقط)
        compressed_size = os.path.getsize(dst_path)

        # 5) إرجاع الملف المضغوط
        # لا نحذف dst_path الآن لتجنب مشاكل مع send_file،
        # النظام المؤقت في Render يُمسح بعد إعادة التشغيل.
        try:
            return send_file(
                dst_path,
                as_attachment=False,
                download_name=os.path.basename(dst_path),
            )
        finally:
            # تنظيف ملف المصدر على الأقل
            try:
                os.remove(src_path)
            except Exception:
                pass

    except Exception as e:
        # أي خطأ غير متوقع
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    # تشغيل محلياً فقط (على Render سيُستخدم gunicorn app:app)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
