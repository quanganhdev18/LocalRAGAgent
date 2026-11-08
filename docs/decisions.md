# Nhật ký quyết định

## D1. Giữ cấu trúc `localrag/` (không đổi sang `app/`)
Kế hoạch GitHub đề xuất `app/{core,ingest,index,search,ui}`. Mã hiện tại giữ gói `localrag/` phẳng để không tốn công di chuyển; sẽ đổi khi có lý do.

## D2. PDF: pypdfium2 thay pypdf (Apache-2.0/BSD). Không dùng PyMuPDF (AGPL).

## D3. Hợp nhất: RRF k=60 (thay trọng số min-max của v2)
Kèm: bỏ từ quá phổ biến (xuất hiện >20% đoạn) khỏi truy vấn BM25, và nhân đóng góp BM25 với độ phủ từ khóa của đoạn. Lý do: trên golden set, nhiễu từ các từ chung (“và”, “của”, “học”) làm hybrid tệ hơn chỉ ngữ nghĩa ở truy vấn Việt→Anh (3/9 so với 6/9); sau chỉnh còn 5/9.

## D4. OCR engine: Tesseract (mặc định) — CHƯA hoàn thành spike
Spike so Tesseract với RapidOCR (ONNX) trên ≥30 trang scan tiếng Việt theo CER/tốc độ/dung lượng/license **chưa chạy**: bộ cài Tesseract tải về (`scripts/fetch_tesseract.py`, đã ghim URL + SHA-256) chưa được cài trên máy này. Khi có Tesseract: `python evals/run_eval.py` sẽ đo recall qua OCR; CER cần chạy riêng bằng `evals/_generated` (biết chính xác văn bản gốc trong `expected.json`). Ghi kết quả vào mục này.

## D5. Chất lượng Việt → Anh chưa đạt ngưỡng (0,556 < 0,70, INT8 E5-small, golden set tổng hợp 9 truy vấn)
Theo spec: không quảng bá tìm xuyên ngôn ngữ; giữ tìm trong từng ngôn ngữ. Chưa so INT8 với FP32 (ngưỡng ≤2 điểm Recall@10); cần tải FP32 để đối chiếu. Mẫu nhỏ (9 truy vấn): kết luận mang tính chỉ báo.

## D6. Số liệu ẩn danh
Chỉ có công tắc (mặc định tắt) trong DB; chưa có mã gửi dữ liệu nào. Khi làm, chỉ gửi đếm/thời gian/loại lỗi, không nội dung/đường dẫn/truy vấn.

## D7. Feedback
Lưu cục bộ bảng `feedback`; chỉ POST khi `feedback.endpoint` được cấu hình, và chỉ gồm nội dung người dùng gõ.

## D4b. Spike OCR (một nửa): RapidOCR 3.10.0 (Apache-2.0), model latin_PP-OCRv5_rec_mobile
Chạy trên 7 trang scan tổng hợp từ golden set (4 tiếng Việt: sạch/mờ/nghiêng; 3 tiếng Anh), 250 DPI, CPU, ~2–3 giây/trang (trang đầu 6 giây do khởi động).
- Tiếng Anh: CER 0,0 ở cả 3 trang.
- Tiếng Việt: CER có dấu 0,14–0,39; CER sau khi bỏ dấu 0,05–0,32 (3 trang ≈0,05, một trang 0,32). **Không đạt ngưỡng ≤5% cho scan chất lượng tốt** nếu tính có dấu.
- Mẫu rất nhỏ (7 trang, không phải 30), không có bảng. RapidOCR tải model lúc chạy (modelscope) → nếu dùng phải ghim vào MANIFEST và tải bằng `prepare-models`.
- **Tesseract chưa đo được**: bộ cài đòi quyền Administrator (WinError 740) và không tự nâng quyền. Chưa so sánh, nên chưa chốt engine; giữ Tesseract làm mặc định (đúng spec) cho đến khi có số đo. Cần cài Tesseract rồi chạy `python evals/run_eval.py` và lặp phép đo CER trên cùng 7 trang.
- Không tích hợp RapidOCR vào ứng dụng.

## D4c. Spike OCR hoàn tất: chốt Tesseract 5.4.0 (vie+eng, tessdata_fast @87416418)
Cùng 7 trang scan tổng hợp (250 DPI): CER = 0,0 trên cả 7 trang (độ tin cậy trung bình 92–97), ~0,5–0,8 giây/trang; so với RapidOCR CER 0,14–0,39 (tiếng Việt). Recall@10 truy vấn qua OCR trên golden set = 0,909 (≥0,70). Hạn chế: văn bản sinh bằng font Arial sạch nên dễ; CER thật trên scan xấu/ảnh chụp cần đo bằng dữ liệu đại diện hơn, chưa có bảng. Lỗi đã sửa: dùng `-c tessedit_create_tsv=1` thay vì config `tsv` (không có khi dùng thư mục tessdata riêng).
Dữ liệu ngôn ngữ nằm ở `runtime/tessdata` (không cần quyền admin); binary dùng bản cài hệ thống (Program Files).
