# Đặc tả MVP v3.1: Kho tài liệu học thuật cục bộ cho nghiên cứu sinh và giáo viên

> v3.1 = v3 + **OCR cho PDF scan** + **đọc và tìm kiếm `.pptx`**, đồng thời tạm loại khỏi repo mọi file, model và dữ liệu chưa cần cho Giai đoạn 1 và 1.5 (mục 3.1). Bỏ Android, Tailscale, pairing, bộ cài ký số và RAG mặc định. Giữ nguyên các quyết định kỹ thuật cốt lõi của v2 (Python, SQLite FTS5, E5-small ONNX, pypdfium2, không cloud). Kế hoạch chi tiết và quy trình GitHub nằm trong `Ke_hoach_trien_khai_GitHub.md`.

## 1. Vai trò của sản phẩm

Đây là **sản phẩm mở đường (wedge)**, không phải sản phẩm cuối. Mục tiêu theo thứ tự ưu tiên:

1. Giải quyết một nỗi đau có thật và hằng tuần của nghiên cứu sinh và giáo viên (tìm lại tài liệu của chính mình).
2. Xây lòng tin và tệp người dùng quen thuộc, có kênh liên lạc hợp lệ.
3. Thu thập có hệ thống các nỗi đau khác của nhóm này, làm đầu vào cho các giải pháp tiếp theo.
4. Doanh thu **không** phải mục tiêu của giai đoạn này.

Mọi quyết định thiết kế phải được đánh giá bằng câu hỏi: nó giúp học được nhiều hơn về người dùng hay làm dự án chậm lại?

## 2. Người dùng và việc cần làm (Jobs To Be Done)

Các mục dưới đây là **giả thuyết**, phải được xác nhận bằng phỏng vấn (xem tệp phỏng vấn).

**Nghiên cứu sinh**
- Có vài chục đến vài trăm bài báo PDF (phần lớn tiếng Anh), đã đọc nhưng quên nằm ở bài nào.
- Muốn hỏi bằng tiếng Việt hoặc tiếng Anh và tìm ra đoạn liên quan cùng trang để trích dẫn.
- Thường dùng laptop cá nhân 8–16 GB RAM.

**Giáo viên/giảng viên**
- Có giáo án, đề thi, slide, tài liệu cũ (DOCX, PDF, thường cả PPTX) nằm rải rác nhiều năm.
- Muốn tìm lại "bài/đề nào nói về …" nhanh, kể cả khi không nhớ tên file.
- Máy thường cũ; một số tài liệu là bản scan.

## 3. Phạm vi

### MVP bao gồm
- Windows 10/11 64-bit; chạy offline sau khi cài.
- Định dạng: `.docx`, `.pdf` (có text, hoặc scan qua OCR), `.pptx`.
- Tìm kiếm lai (từ khóa BM25 và ngữ nghĩa), tiếng Việt và tiếng Anh, **bao gồm tìm xuyên ngôn ngữ** (hỏi tiếng Việt, ra đoạn tiếng Anh) nếu đo được chất lượng đạt ngưỡng ở mục 9.
- Hiển thị đoạn trích, tên file, đường dẫn tương đối, số trang; nút mở file; nút copy trích dẫn.
- PDF scan: phát hiện theo từng trang và OCR cục bộ (tiếng Việt + tiếng Anh) chạy nền, có thể tạm dừng/hủy; PDF lỗi font: báo trạng thái rõ ràng.
- Nút **"Góp ý / Tôi gặp khó khăn với …"** trong ứng dụng (mục 4, F8).
- Cài đặt đơn giản, giao diện tiếng Việt.

### MVP không bao gồm (để giai đoạn sau)
- RAG/hỏi đáp bằng LLM (Giai đoạn 2, chỉ khi người dùng đòi hỏi).
- Android, truy cập từ xa, Tailscale, pairing.
- Plugin Zotero/Obsidian/Moodle (khảo sát sau).
- Đồng bộ cloud, tài khoản người dùng, thanh toán.
- OCR ảnh nằm trong DOCX/PPTX, `.ppt`/`.doc` định dạng cũ.

### 3.1. Tài sản tạm loại khỏi repo và bản phát hành (Giai đoạn 1 và 1.5)

Không tạo thư mục, không commit và không đóng gói các mục sau cho đến khi có quyết định mở giai đoạn tương ứng:

| Mục tạm bỏ | Gồm | Mở lại khi |
|---|---|---|
| LLM và RAG | `models/llm/` (Qwen GGUF), `runtime/llama-server/`, module `rag/`, prompt, hàng đợi RAG | Giai đoạn 2, khi phỏng vấn/thử nghiệm cho thấy người dùng đòi hỏi |
| Reranker | `models/rerankers/` (bge-reranker-v2-m3) | Chỉ khi đo thấy MRR cần cải thiện |
| Truy cập từ xa | `gateway/`, `android/`, pairing, token, Tailscale, bảng `paired_devices`, `pairing_sessions`, `audit_events` | Khi nhiều người dùng yêu cầu |
| Mã hóa DB, ký số | SQLCipher, code signing, ký manifest bằng Ed25519 | Trước khi phát hành rộng rãi |
| FAISS, Ollama | Mọi dependency liên quan | Không dùng ở v1 |
| Dữ liệu thật | Mọi tài liệu của người dùng/người phỏng vấn, index, cơ sở dữ liệu `.db`, log | Không bao giờ commit |
| Binary và model lớn | Model ONNX, Tesseract, `tessdata`, bản build | Không commit; tải bằng `prepare-models` hoặc đính kèm GitHub Release (xem kế hoạch GitHub) |

Chỉ còn **hai** loại model/asset cần cho giai đoạn này: embedding `multilingual-e5-small` và dữ liệu OCR Tesseract (`vie`, `eng`).

## 4. Chức năng

### F1. Chọn thư mục
Thêm nhiều thư mục; danh sách thư mục đã index; nút quét lại. Bỏ qua thư mục hệ thống/ẩn, file tạm (`~$*`), file OneDrive chưa tải về. Hỗ trợ trỏ vào thư mục lưu trữ của trình quản lý tài liệu tham khảo (ví dụ Zotero) như một thư mục thông thường. *Cần kiểm tra thực tế cấu trúc thư mục đó; không giả định.*

### F2. Phát hiện thay đổi và đối soát
Chỉ xử lý file mới hoặc đã đổi (size/mtime, băm khi cần). File bị xóa sau thời gian chờ (mặc định 24 giờ) bị gỡ khỏi index; file đổi tên (cùng hash) giữ nguyên index. Search không trả về file không còn tồn tại. Thư mục gốc không truy cập được (USB/ổ mạng rút ra) thì không xóa dữ liệu.

Trạng thái: `pending`, `indexed`, `partial_content`, `needs_ocr`, `ocr_pending`, `ocr_low_quality`, `no_text`, `text_suspect`, `encrypted`, `locked`, `corrupt`, `too_large`, `skipped_cloud_placeholder`, `missing`, `error`.

### F3. Trích xuất
- **DOCX** (`python-docx` + lxml): giữ thứ tự heading/paragraph/table; không xác định được trang thì lưu `page_number = NULL`.
- **PDF** (`pypdfium2`): text theo trang; loại header/footer lặp; phát hiện `no_text`; kiểm tra chất lượng ký tự để gắn `text_suspect` (font cũ).
- Parser chạy trong tiến trình con có timeout; file lỗi không làm dừng quá trình index.
- Tuyệt đối **không dùng PyMuPDF** (AGPL).
- Trang không có text (hoặc quá ít) được đánh dấu cần OCR theo **từng trang**; PDF hỗn hợp (trang text xen trang scan) vẫn được xử lý đúng.

### F3b. Trích xuất PPTX
- Dùng `python-pptx` (MIT). Mỗi slide tương ứng một "trang": `page_number` là số thứ tự slide, `section_heading` là tiêu đề slide nếu có.
- Đọc theo thứ tự: tiêu đề, khung văn bản, bảng, nhóm hình (đệ quy).
- Ghi chú người nói (speaker notes) đọc riêng, gắn `source = 'notes'`, có thể tắt trong cấu hình. Slide ẩn vẫn được lập chỉ mục và gắn cờ `hidden`.
- Không gộp text xuyên slide; thêm tiêu đề slide vào đầu text chunk để chunk ngắn vẫn có ngữ cảnh.
- Hạn chế cần kiểm tra bằng file thật: text trong SmartArt, biểu đồ và ảnh chèn có thể không đọc được. Khi nghi ngờ, gắn trạng thái `partial_content` và hiển thị cảnh báo trong "Tình trạng index", không âm thầm bỏ qua. Ảnh trong slide không OCR ở giai đoạn này.
- File có mật khẩu: `encrypted`. Định dạng `.ppt` cũ nằm ngoài phạm vi.

### F3c. OCR cho PDF scan
- **Engine mặc định:** Tesseract (Apache-2.0), gọi bằng tiến trình con, ngôn ngữ `vie+eng`, dữ liệu `tessdata_fast` ghim phiên bản và SHA-256. Không dùng dịch vụ OCR cloud.
- **Quy trình:** render trang bằng `pypdfium2` ở 200–300 DPI (cấu hình) → tiền xử lý nhẹ bằng Pillow/numpy (thang xám, tăng tương phản, tùy chọn chỉnh nghiêng) → Tesseract → lưu văn bản với `source = 'ocr'` và độ tin cậy trung bình của trang (`ocr_confidence`). Ảnh tạm xóa ngay sau khi OCR xong.
- **Chạy nền, tiếp tục được:** hàng đợi OCR riêng, ưu tiên thấp, song song tối đa `ocr.max_parallel` (mặc định 1), có tạm dừng/hủy/tiếp tục; kết quả lưu **theo từng trang** nên tắt máy giữa chừng không mất công.
- **Không tự chạy hàng loạt:** trước khi OCR, hiển thị số trang cần OCR và thời gian ước tính, yêu cầu người dùng đồng ý (có thể chọn "luôn OCR" cho thư mục đó).
- **Giới hạn:** `ocr.max_pages_per_document` (mặc định 300), timeout mỗi trang.
- **Chất lượng:** trang có độ tin cậy dưới ngưỡng thì gắn `ocr_low_quality`, vẫn lập chỉ mục nhưng có nhãn cảnh báo. Kết quả tìm kiếm hiển thị nhãn "OCR" cho đoạn đến từ OCR.
- **Lưu ý tiếng Việt:** lỗi OCR thường rơi vào dấu thanh và dấu mũ; chỉ mục BM25 đã bỏ dấu (F5) giúp giảm ảnh hưởng, nhưng phải đo bằng golden set, không giả định.
- **Spike chọn engine (2 ngày, trước M2 trong kế hoạch):** so Tesseract với một phương án ONNX (ví dụ RapidOCR) trên ít nhất 30 trang scan tiếng Việt (sạch, mờ, nghiêng, có bảng) theo tỷ lệ lỗi ký tự (CER), tốc độ, dung lượng và license. Ghi kết quả vào `docs/decisions.md`. Chất lượng OCR tiếng Việt chưa được kiểm chứng, nên không quảng bá khi chưa đạt ngưỡng ở mục 9.

### F4. Chuẩn hóa và chunking
Unicode NFC; chunk 250–450 token (đo bằng tokenizer E5, tối đa 500 cả tiền tố), overlap 40–80 token; ưu tiên cắt theo heading → đoạn → câu. Mỗi chunk có `document_id`, `page_number`, `section_heading`, `chunk_index`, `text_hash`.

### F5. Tìm kiếm lai
- **BM25 (SQLite FTS5)** trên văn bản đã bỏ dấu (xử lý riêng `đ`), kèm cụm hai âm tiết liền kề; gõ có dấu hay không dấu đều tìm được.
- **Ngữ nghĩa:** `intfloat/multilingual-e5-small` (ONNX, 384 chiều), tiền tố `query: ` / `passage: `, chuẩn hóa L2. Ma trận vector nạp vào RAM bằng numpy; bảng `embeddings` trong SQLite là nguồn sự thật duy nhất. Không dùng FAISS.
- **Gộp:** Reciprocal Rank Fusion (k = 60). Bộ lọc áp dụng **trước** khi lấy top-k.
- Loại chunk trùng; tối đa 3 chunk mỗi tài liệu theo mặc định, cho phép gộp theo tài liệu.
- Mã/số hiệu/ngày tháng giữ nguyên ở cột token chính xác.

### F6. Giao diện
Ô tìm kiếm; bộ lọc thư mục, loại file, ngày sửa; danh sách kết quả có snippet đánh dấu, tên file, đường dẫn tương đối, trang. Nút mở file bằng ứng dụng mặc định (không hứa nhảy đúng trang; hiển thị "Trang N"). Nút copy đoạn trích kèm nguồn dạng `tên file, tr. N`. Trang "Tình trạng index" liệt kê file có vấn đề (cần OCR, OCR chất lượng thấp, lỗi font, mật khẩu, nội dung PPTX đọc không đủ) kèm gợi ý xử lý, và có nút bắt đầu/tạm dừng/hủy OCR cùng thanh tiến độ theo trang. Kết quả từ PPTX hiển thị "Slide N" thay cho "Trang N". Tiến độ index có thể tạm dừng và hủy; giao diện không bị treo.

### F7. Chế độ máy yếu
Tự phát hiện RAM khả dụng. Search-only phải chạy mượt trên máy 8 GB. Index chạy nền ưu tiên thấp, giới hạn luồng ONNX (mặc định nửa số lõi), batch 8–16.

### F8. Học hỏi từ người dùng (quan trọng với mục tiêu của dự án)
1. Nút **"Góp ý"** luôn hiển thị, mở một form ngắn: "Bạn đang cố làm gì mà phần mềm chưa giúp được?" kèm trường email **không bắt buộc**. Nội dung gửi đi chỉ gồm những gì người dùng tự gõ.
2. **Số liệu sử dụng ẩn danh, mặc định TẮT, người dùng chủ động bật:** số lần tìm kiếm, thời gian phản hồi, tỷ lệ kết quả được mở, loại lỗi. Không gửi nội dung tài liệu, không gửi nội dung truy vấn, không gửi đường dẫn.
3. Ở màn hình đầu tiên, nói rõ bằng tiếng Việt: dữ liệu nào ở lại máy, dữ liệu nào (nếu có) được gửi đi và vì sao.
4. Một mục "Tôi muốn nhận tin khi có tính năng mới" (đăng ký tự nguyện) để hình thành tệp khách hàng hợp lệ.

Hạ tầng thu phản hồi (một form web đơn giản hoặc email) là một tệp riêng, không nằm trong lõi tìm kiếm.

## 5. Quyết định kỹ thuật đã chốt

| Hạng mục | Quyết định |
|---|---|
| Ngôn ngữ | Python 3.11/3.12 |
| Giao diện | Web UI cục bộ (FastAPI) bọc bằng `pywebview` hoặc mở trình duyệt; bind `127.0.0.1` |
| Database | SQLite WAL + FTS5 |
| Vector | numpy brute force từ bảng `embeddings` |
| PDF / DOCX / PPTX | `pypdfium2` / `python-docx` / `python-pptx` |
| OCR | Tesseract (subprocess) + Pillow/numpy; engine chốt sau spike (F3c) |
| Embedding runtime | `onnxruntime` CPU + `tokenizers` (không dùng PyTorch) |
| Đóng gói | PyInstaller onedir; bản cài `.exe` (Inno Setup) và bản zip portable. Giai đoạn đầu chấp nhận chưa ký số, ghi chú cách bỏ qua cảnh báo SmartScreen trong hướng dẫn |
| License | Mọi dependency phải qua `pip-licenses`; cấm AGPL/GPL khi chưa phê duyệt |

Bảo vệ API cục bộ: token phiên ngẫu nhiên, kiểm tra `Host`/`Origin`, không mở CORS (xem mục 8.6 của v2).

## 6. Model

- Chỉ **một** model AI trong MVP: `intfloat/multilingual-e5-small`.
- Dữ liệu OCR (không phải model lớn): `tessdata_fast` cho `vie` và `eng`, cùng binary Tesseract đã ghim phiên bản. Cùng quy tắc như model: có trong `MANIFEST.json` với SHA-256 và license, nằm dưới `MODEL_ROOT`/`runtime`, không commit vào Git, tải bằng `prepare-models`.
- Đặt dưới `MODEL_ROOT`; có `MANIFEST.json` (revision cố định, SHA-256, license) và kiểm tra khi khởi động. Chỉ định dạng ONNX; không pickle.
- Nếu dùng INT8, phải so với FP32 trên golden set; chỉ chấp nhận khi Recall@10 không giảm quá 2 điểm phần trăm.
- Không tự tải model khi chạy; tải model là bước chuẩn bị riêng.
- LLM (Qwen3-4B-Instruct-2507 Q4_K_M qua `llama-server`) chỉ thêm ở Giai đoạn 2, thiết kế như trong v2.

## 7. Hiệu năng mục tiêu (phải đo, không cam kết khi chưa đo)

- Khởi động ≤ 10 giây khi đã có index.
- Tìm kiếm: p50 ≤ 1,5 giây, p95 ≤ 5 giây trên 500 tài liệu.
- Ghi lại tốc độ index lần đầu (trang/giây) trên ít nhất hai cấu hình máy (8 GB và 16 GB) và hiển thị thời gian ước tính trong giao diện.
- RAM đỉnh khi index và khi tìm kiếm được đo và ghi vào báo cáo.
- OCR: đo tốc độ (giây/trang) trên cả hai cấu hình máy và hiển thị ước tính trong giao diện; OCR không được làm giao diện giật hoặc làm tìm kiếm chậm hơn ngưỡng ở trên.

## 8. Riêng tư và an toàn

- Mặc định mọi xử lý chạy local; không gọi API ngoài với nội dung tài liệu.
- Không ghi nội dung tài liệu hoặc truy vấn vào log; không log token. OCR chạy hoàn toàn local; ảnh trang tạm được xóa ngay sau khi xử lý và không nằm trong thư mục được commit hay sao lưu.
- Chỉ mở file khi người dùng bấm; không bao giờ sửa/xóa/di chuyển file gốc.
- Mọi dữ liệu gửi đi (F8) phải minh bạch, có thể tắt, và tuân thủ quy định bảo vệ dữ liệu cá nhân hiện hành của Việt Nam (cần kiểm tra bản mới nhất trước khi phát hành).
- Khuyến nghị người dùng bật BitLocker vì SQLite chứa văn bản gốc dạng plaintext; ghi trong hướng dẫn.
- Không tạo hoặc lưu hồ sơ người dùng nếu họ chưa đồng ý rõ ràng.

## 9. Nghiệm thu bằng số đo

### Golden set (dùng tài liệu tổng hợp, không dùng tài liệu thật của người dùng)
Ít nhất 40 file: PDF học thuật tiếng Anh nhiều trang, DOCX giáo án tiếng Việt có dấu, file có bảng, **PPTX bài giảng (có bảng, nhóm hình, ghi chú, slide ẩn)**, **PDF scan tiếng Việt và tiếng Anh ở nhiều chất lượng (sạch, mờ, nghiêng), PDF hỗn hợp text và scan**, PDF lỗi font, file có mật khẩu. Các file scan được **sinh bằng script** từ văn bản tổng hợp (render thành ảnh rồi thêm nhiễu/nghiêng) để tái tạo được và biết chính xác văn bản đúng để tính CER; không dùng tài liệu thật. 80–100 cặp truy vấn → đáp án, chia nhóm: từ khóa chính xác, diễn đạt khác, không dấu, tiếng Anh, **Việt hỏi → Anh trả lời**, và truy vấn không có đáp án.

### Ngưỡng tối thiểu (điểm khởi đầu; chỉnh có lý do, không âm thầm hạ)
| Chỉ số | Ngưỡng |
|---|---|
| Recall@10 tổng | ≥ 0,85 |
| Recall@10 nhóm mã/số chính xác | ≥ 0,95 |
| Recall@10 nhóm không dấu | ≥ 0,85 |
| Recall@10 nhóm Việt → Anh | ≥ 0,70 (nếu thấp hơn, bỏ tính năng này khỏi lời quảng bá) |
| MRR@10 | ≥ 0,60 |
| p95 latency tìm kiếm | ≤ 5 giây |
| Recall@10 truy vấn trên PPTX | ≥ 0,85 |
| CER OCR trên scan tiếng Việt chất lượng tốt | ≤ 5% (điểm khởi đầu, chỉnh sau spike có lý do) |
| Recall@10 truy vấn trên tài liệu qua OCR | ≥ 0,70 (nếu thấp hơn, chỉ quảng bá OCR như tính năng "cố gắng tốt nhất") |

### Checklist chức năng
- [ ] Quét DOCX/PDF/PPTX, không index lại file không đổi; file xóa/đổi tên được đối soát đúng.
- [ ] Gõ "bao cao khoa hoc" và "báo cáo khoa học" ra kết quả tương đương.
- [ ] Mở file gốc từ kết quả, hiển thị đúng số trang; copy trích dẫn đúng định dạng.
- [ ] PDF lỗi font và file có mật khẩu hiển thị trạng thái và gợi ý rõ ràng; một file lỗi không dừng cả quá trình.
- [ ] PDF scan: phát hiện đúng trang cần OCR (kể cả PDF hỗn hợp), hỏi trước khi OCR hàng loạt, OCR tạm dừng/hủy/tiếp tục được, tắt máy giữa chừng không mất kết quả các trang đã xong.
- [ ] Kết quả từ OCR có nhãn "OCR"; trang tin cậy thấp có cảnh báo.
- [ ] PPTX: tìm thấy nội dung trong khung văn bản, bảng, nhóm hình và ghi chú; kết quả hiển thị đúng số slide; nội dung không đọc được (SmartArt, biểu đồ) được báo `partial_content`.
- [ ] Repo không chứa model, binary, dữ liệu thật hay index (kiểm tra bằng hook ở kế hoạch GitHub).
- [ ] Đóng ứng dụng giữa lúc index không làm hỏng database.
- [ ] Chạy hoàn toàn khi tắt Internet; `verify-models` phát hiện model thiếu hoặc sai checksum.
- [ ] Nút Góp ý hoạt động; số liệu ẩn danh tắt mặc định; không có dữ liệu nào rời máy khi người dùng chưa bật.
- [ ] Cài và chạy được trên máy sạch 8 GB RAM.

## 10. Kế hoạch ra mắt thử và điều kiện dừng

### Giai đoạn 0 (song song với code): khám phá
Phỏng vấn 8–12 người theo tệp phỏng vấn kèm theo, trước và trong lúc xây MVP. Ghi lại "nhật ký nỗi đau" (xem tệp phỏng vấn).

### Giai đoạn 1 (ước tính 7–9 tuần, tăng do OCR và PPTX): MVP
Triển khai F1–F8 theo mục 4. Không thêm tính năng ngoài mục 3.

### Giai đoạn 1.5: thử nghiệm kín
Phát cho 10–20 người dùng đã phỏng vấn; theo dõi bằng F8 và gọi điện/nhắn tin hỏi thăm sau 1 và 3 tuần.

### Chỉ số thành công của thử nghiệm (đề xuất)
- Ít nhất 40% người dùng thử còn dùng ở tuần thứ ba.
- Ít nhất 5 người nói rõ một nỗi đau thứ hai ngoài tìm kiếm, mà họ sẵn lòng thử giải pháp.
- Ít nhất 3 người chủ động giới thiệu cho người khác.

### Điều kiện dừng hoặc đổi hướng
- Dưới 20% còn dùng sau 3 tuần: nỗi đau tìm kiếm không đủ mạnh; đổi sang nỗi đau mà phỏng vấn cho thấy nặng hơn, tận dụng tệp người đã tham gia.
- Chất lượng Việt → Anh không đạt ngưỡng: bỏ tính năng đó khỏi định vị, giữ tìm kiếm trong từng ngôn ngữ.

## 11. Lộ trình sau MVP (chỉ làm khi dữ liệu thử nghiệm ủng hộ)

1. Cải thiện OCR (tiền xử lý tốt hơn, engine khác nếu spike cho thấy cần) và OCR ảnh trong slide/DOCX.
2. Hỏi đáp có trích dẫn bằng LLM cục bộ (thiết kế như v2: citation do code sinh, từ chối khi thiếu thông tin, chống prompt injection).
3. Công cụ liên quan đến nỗi đau mới phát hiện (ví dụ gom danh mục tài liệu tham khảo, tạo mục lục/tóm tắt, soạn đề từ ngân hàng câu hỏi). Chưa cam kết; phụ thuộc phỏng vấn.
4. Truy cập từ xa hoặc plugin cho các nền tảng quen thuộc, chỉ khi nhiều người dùng yêu cầu.

## 12. Quy tắc làm việc cho coding agent

1. Không mở rộng phạm vi ngoài mục 3 khi chưa có chỉ thị.
2. Không thêm API cloud hoặc gửi dữ liệu ra ngoài khi chưa có lựa chọn và thông báo rõ.
3. Không thêm dependency khi chưa kiểm tra license; cấm AGPL/GPL khi chưa phê duyệt.
4. Mọi thay đổi retrieval phải chạy lại golden set và không làm giảm các chỉ số; không tự hạ ngưỡng.
5. Không dùng tài liệu thật của người dùng làm fixture test.
6. Không xóa dữ liệu, index hoặc file gốc trong migration khi chưa backup.
7. Lỗi model/runtime phải báo hướng dẫn khắc phục, không nuốt exception.
8. Kết thúc mỗi milestone bằng báo cáo: đã làm, file đã đổi, lệnh test, kết quả kèm số đo, việc còn lại.
9. Không tin đường dẫn từ client nếu sau này thêm lớp HTTP; kiểm tra path traversal, symlink, junction.
10. Không tạo thư mục, module hay dependency thuộc danh sách "tạm bỏ" ở mục 3.1. Không commit model, binary, dữ liệu thật, index hay file `.db` vào Git; tuân thủ `Ke_hoach_trien_khai_GitHub.md`.

## 13. Cấu hình mặc định

```yaml
language: vi
privacy:
  cloud_api_enabled: false
  log_queries: false
  telemetry_enabled: false      # chỉ bật khi người dùng chủ động đồng ý

models:
  root: ./models
  manifest: ./models/MANIFEST.json
  verify_on_start: true
  allow_runtime_download: false
  embedding_path: ./models/embeddings/multilingual-e5-small-onnx

index:
  chunk_tokens: 350
  chunk_overlap_tokens: 60
  vector_dimensions: 384
  batch_size: 16
  onnx_threads: auto
  max_file_mb: 200
  max_pages: 2000
  parse_timeout_seconds: 120
  reconcile_deleted: true
  reconcile_grace_hours: 24
  skip_cloud_placeholders: true
  include_extensions: [docx, pdf, pptx]

pptx:
  include_notes: true
  include_hidden_slides: true

ocr:
  enabled: true
  engine: tesseract            # chốt sau spike; ghi vào docs/decisions.md
  languages: [vie, eng]
  render_dpi: 250
  max_parallel: 1
  max_pages_per_document: 300
  timeout_seconds_per_page: 60
  ask_before_bulk: true
  min_confidence: 60           # dưới ngưỡng thì gắn ocr_low_quality; chỉnh theo spike
  priority: below_normal

retrieval:
  fusion: rrf
  rrf_k: 60
  top_k_candidates: 30
  top_k_results: 10
  max_chunks_per_document: 3
  dedupe_cosine: 0.95
  filter_before_topk: true

local_ui:
  bind: 127.0.0.1
  allowed_hosts: [127.0.0.1, localhost]
  cors_origins: []

feedback:
  enabled: true
  endpoint: ""                  # điền khi có kênh thu phản hồi; để trống thì chỉ lưu cục bộ
  collect_email_optional: true
```
