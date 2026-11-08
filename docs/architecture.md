# Kiến trúc
`config.py` → `core.py` (container) → `indexer.py` (quét, đối soát, trích xuất trong tiến trình con, chunk, embed, lưu nguyên tử) · `extract.py` (DOCX/PDF/PPTX) · `ocr.py` (Tesseract + hàng đợi theo trang) · `search.py` (FTS5 + vector numpy + RRF) · `web/app.py` (FastAPI, loopback, token phiên) · `cli.py`.
SQLite là nguồn sự thật duy nhất (documents, chunks, embeddings, ocr_pages, feedback).
Luồng OCR: trang không có text → `needs_ocr` → người dùng đồng ý → `ocr_pending` → từng trang lưu `ocr_pages` → dựng lại chunk (nguồn `ocr`).
