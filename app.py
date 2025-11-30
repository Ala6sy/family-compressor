import base64
import logging
import io

from flask import Flask, request, jsonify
import fitz  # PyMuPDF
from PIL import Image  # Pillow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def get_mode_params(mode: str):
  mode = (mode or "").strip().lower()

  # للـ PDF
  if mode == "high_compression":
      return 0.6, 45
  elif mode == "low_compression":
      return 1.0, 75
  else:
      return 0.8, 60  # recommended


def get_image_quality(mode: str):
  mode = (mode or "").strip().lower()
  if mode == "high_compression":
      return 40
  elif mode == "low_compression":
      return 80
  else:
      return 60


def compress_pdf(pdf_bytes: bytes, mode: str):
  zoom, jpeg_quality = get_mode_params(mode)
  logger.info(
      f"Compressing PDF with mode={mode}, zoom={zoom}, jpeg_quality={jpeg_quality}"
  )

  original_size_kb = round(len(pdf_bytes) / 1024)

  doc = fitz.open(stream=pdf_bytes, filetype="pdf")
  new_doc = fitz.open()

  for page_index in range(len(doc)):
      page = doc.load_page(page_index)
      mat = fitz.Matrix(zoom, zoom)
      pix = page.get_pixmap(matrix=mat, alpha=False)
      img_bytes = pix.tobytes("jpeg", jpg_quality=jpeg_quality)

      img_doc = fitz.open("jpeg", img_bytes)
      img_page = img_doc[0]

      new_page = new_doc.new_page(
          width=img_page.rect.width, height=img_page.rect.height
      )
      new_page.show_pdf_page(new_page.rect, img_doc, 0)
      img_doc.close()

  compressed_bytes = new_doc.write()
  new_doc.close()
  doc.close()

  compressed_size_kb = round(len(compressed_bytes) / 1024)

  return (
      compressed_bytes,
      original_size_kb,
      compressed_size_kb,
      "application/pdf",
      ".pdf",
  )


def compress_image(image_bytes: bytes, mode: str):
  jpeg_quality = get_image_quality(mode)
  logger.info(
      f"Compressing IMAGE with mode={mode}, jpeg_quality={jpeg_quality}"
  )

  original_size_kb = round(len(image_bytes) / 1024)

  img = Image.open(io.BytesIO(image_bytes))
  if img.mode != "RGB":
      img = img.convert("RGB")

  buf = io.BytesIO()
  img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
  compressed_bytes = buf.getvalue()
  compressed_size_kb = round(len(compressed_bytes) / 1024)

  return (
      compressed_bytes,
      original_size_kb,
      compressed_size_kb,
      "image/jpeg",
      ".jpg",
  )


@app.route("/", methods=["GET"])
def health():
  return jsonify({"ok": True, "message": "Family compressor API is running"})


@app.route("/compress", methods=["POST"])
def compress_endpoint():
  try:
      if "file" not in request.files:
          return (
              jsonify({"success": False, "error": "No file part in request"}),
              400,
          )

      file = request.files["file"]
      if file.filename == "":
          return jsonify({"success": False, "error": "Empty filename"}), 400

      mode = request.form.get("mode", "recommended")
      file_type = request.form.get("fileType") or file.mimetype or ""
      file_bytes = file.read()

      logger.info(
          f"Received file for compression, mode={mode}, type={file_type}, size={len(file_bytes)} bytes"
      )

      # اختيار طريقة الضغط حسب النوع
      if file_type == "application/pdf" or file_bytes.startswith(b"%PDF"):
          (
              compressed_bytes,
              original_kb,
              compressed_kb,
              out_mime,
              out_ext,
          ) = compress_pdf(file_bytes, mode)
      elif file_type.startswith("image/"):
          (
              compressed_bytes,
              original_kb,
              compressed_kb,
              out_mime,
              out_ext,
          ) = compress_image(file_bytes, mode)
      else:
          return jsonify(
              {
                  "success": False,
                  "error": f"Unsupported file type: {file_type}",
              }
          ), 400

      file_base64 = base64.b64encode(compressed_bytes).decode("ascii")

      return jsonify(
          {
              "success": True,
              "fileBase64": file_base64,
              "originalSizeKB": original_kb,
              "compressedSizeKB": compressed_kb,
              "outputMimeType": out_mime,
              "outputExtension": out_ext,
          }
      )

  except Exception as e:
      logger.exception("Error while compressing")
      return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=8000)
