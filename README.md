# Kho tài liệu học thuật cục bộ (MVP v3.1)

Tìm kiếm lai (BM25 + ngữ nghĩa, RRF) trên `.docx`, `.pdf` (có text hoặc scan qua OCR) và `.pptx`, chạy hoàn toàn offline. Đặc tả: `Specv3_MVP.md`; kế hoạch: `Ke_hoach_trien_khai_GitHub.md`.

## Dùng bằng giao diện (không cần terminal)
1. Double-click **`LocalRAG.vbs`** (có thể tạo shortcut ra Desktop). Ứng dụng mở trong cửa sổ riêng (Edge WebView2; nếu thiếu thì tự dùng trình duyệt tại `http://127.0.0.1:8700`). Phím tắt: `Ctrl K` hoặc `/` để tìm, `Esc` để xóa, nút mặt trời đổi sáng/tối.
2. Lần đầu, thẻ **"Thiết lập lần đầu"** tự hiện: bấm *Tải model* (cần Internet một lần), và nếu có PDF scan thì *Tải & mở bộ cài* Tesseract (Windows sẽ hỏi quyền quản trị, bạn tự xác nhận) rồi *Tải dữ liệu OCR*.
3. *Chọn thư mục…* → *Thêm* → *Quét lại*. Chọn chế độ OCR cho từng thư mục (Hỏi trước / Luôn OCR / Không OCR). PDF scan sẽ hiện ở "Tình trạng index" kèm *Bắt đầu OCR*, *Tạm dừng*, *Hủy*.
4. Gõ từ khóa/câu hỏi, *Mở file*, *Copy trích dẫn*. *Góp ý* ở góc trên. *Thoát* để tắt ứng dụng.
Nhật ký lỗi: `data/app.log` (không chứa nội dung tài liệu/truy vấn).

## Dòng lệnh (tùy chọn, cho dev)
```powershell
python -m venv .venv-local; .\.venv-local\Scripts\pip install -r requirements.txt   # (dev: requirements-dev.txt)
python -m localrag verify-models | add-folder | index | ocr [--yes] | search "..." | serve
python -m pytest -q
python evals/run_eval.py          # golden set (cần model; OCR nếu đã cài Tesseract)
```
Lưu ý: file `LocalRAG.vbs` luôn tạo/sửa `\.venv-local` riêng cho từng máy; nó không tái sử dụng `.venv` đã copy từ máy khác, vì bản đó thường trỏ đến Python cũ và có thể làm `onnxruntime` không cài được.
Tesseract: dữ liệu ngôn ngữ ở `runtime/tessdata`; binary tìm theo `ocr.tesseract_path`, `runtime/tesseract`, PATH, rồi Program Files. Không commit binary/model vào Git.

## Hành vi chính
- Trạng thái file: `indexed, partial_content, needs_ocr, ocr_pending, ocr_low_quality, no_text, text_suspect, encrypted, locked, corrupt, too_large, skipped_cloud_placeholder, missing, error` (xem trang "Tình trạng index").
- PDF phân tích theo từng trang (`pypdfium2`): trang không có text vào hàng đợi OCR; PDF hỗn hợp xử lý đúng. OCR **không tự chạy**: phải đồng ý (hoặc đặt thư mục "Luôn OCR"); tạm dừng/hủy/tiếp tục được, kết quả lưu theo trang.
- PPTX: mỗi slide là một "trang", có ghi chú người nói và slide ẩn; SmartArt/biểu đồ/ảnh đọc không được thì gắn `partial_content`.
- File bị xóa → `missing` (ẩn khỏi tìm kiếm), gỡ sau `reconcile_grace_hours`; đổi tên (cùng hash) giữ nguyên index; thư mục gốc không truy cập được thì không xóa gì.
- UI cục bộ chỉ bind `127.0.0.1`, kiểm tra `Host`/`Origin`, token phiên ngẫu nhiên, không CORS.
- Nút "Góp ý" lưu cục bộ; chỉ gửi đi khi `feedback.endpoint` được cấu hình. Số liệu ẩn danh mặc định TẮT.

## Giới hạn đã biết
Golden set tổng hợp đã chạy (xem `evals/results/summary.md`): Việt→Anh chưa đạt ngưỡng nên không quảng bá. OCR mới đo trên scan tổng hợp sạch (CER 0%), chưa đo trên scan thật xấu/ảnh chụp. Khuyến nghị bật BitLocker (SQLite chứa văn bản gốc).
