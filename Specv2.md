# Đặc tả và hướng dẫn triển khai Local Document Search/RAG

## 1. Mục tiêu

Xây dựng một ứng dụng local cho máy văn phòng dưới 16 GB RAM, cho phép người dùng:

1. Quét khoảng 500 tài liệu DOCX và PDF trong các thư mục được chọn.
2. Trích xuất nội dung và metadata mà không cần upload tài liệu lên cloud.
3. Tìm kiếm bằng cả từ khóa và ngữ nghĩa.
4. Hiển thị đoạn văn phù hợp, tên file, đường dẫn và số trang nếu xác định được.
5. Mở trực tiếp tài liệu gốc tại kết quả tìm kiếm.
6. Tùy chọn hỏi đáp/tổng hợp dựa trên các đoạn đã tìm thấy bằng LLM chạy hoàn toàn local.
7. Theo dõi thay đổi file và chỉ lập chỉ mục lại file mới hoặc đã thay đổi.
8. Cho phép truy cập từ smartphone Android qua Internet khi PC và điện thoại đều đang bật và có kết nối.
9. Cho phép tìm kiếm, xem kết quả và tải tài liệu được cấp quyền từ Android mà không cần sao chép toàn bộ thư viện lên cloud.

Phiên bản đầu tiên phải ưu tiên semantic search ổn định. RAG chỉ là lớp bổ sung, không được làm hỏng hoặc làm chậm đáng kể chức năng tìm kiếm.

## 2. Phạm vi phiên bản đầu tiên

### Bao gồm

- Hệ điều hành mục tiêu: Windows trước, có thể hỗ trợ Linux/macOS nếu không làm phức tạp kiến trúc.
- Định dạng: `.docx`, `.pdf`.
- Tài liệu PDF dạng text phải được hỗ trợ.
- PDF scan cần có cơ chế phát hiện và thông báo chưa có text; OCR là tính năng tùy chọn.
- Tìm kiếm tiếng Việt và tiếng Anh.
- Tìm kiếm từ khóa bằng BM25.
- Tìm kiếm ngữ nghĩa bằng embedding local.
- Gộp điểm BM25 và semantic score.
- RAG local bằng model GGUF chạy qua llama.cpp hoặc Ollama.
- Trả lời có trích dẫn đến file và trang/đoạn nguồn nếu có.
- Không gửi nội dung tài liệu tới API bên ngoài trong mặc định.
- PC là node lưu trữ và xử lý chính; Android là client từ xa.
- Kết nối từ xa phải dùng HTTPS/TLS hoặc secure tunnel; không expose database, Ollama hoặc thư mục tài liệu trực tiếp ra Internet.
- Android có thể thực hiện search, xem snippet, xem metadata, tải/mở tài liệu được cấp quyền và gửi câu hỏi RAG tới PC.
- Các model AI cần thiết phải được lưu dưới thư mục dự án hoặc thư mục asset được dự án quản lý, không phụ thuộc vào model nằm rải rác trong home directory của người dùng.
- Ứng dụng phải hỗ trợ đóng gói và cài đặt offline sau khi model đã được đưa vào bộ phân phối hợp lệ.

### Không bao gồm trong phiên bản đầu tiên

- Fine-tuning model.
- Đồng bộ cloud.
- OCR cloud bắt buộc.
- Multi-user server và chia sẻ cho người dùng khác ngoài chủ tài khoản.
- Đồng bộ toàn bộ tài liệu lên cloud.
- Agent tự động sửa hoặc xóa tài liệu.
- Tự động suy luận dữ liệu không có trong tài liệu.
- Index toàn bộ ổ đĩa hệ thống mặc định.
- Tự động tải model từ Internet khi ứng dụng đang chạy, trừ khi người dùng chủ động bật chế độ tải model.

## 3. Kiến trúc được chọn

```text
Thư mục tài liệu
      |
      v
File scanner + change detector
      |
      v
DOCX/PDF text extraction
      |
      v
Normalization + metadata + page tracking
      |
      v
Chunking 250–450 token, overlap 40–80 token
      |
      +----------------------+
      |                      |
      v                      v
BM25 index             Embedding index
      |                 multilingual-e5-small
      |                 ONNX/INT8 preferred
      +----------+-----------+
                 v
        Hybrid retrieval
                 |
                 v
       Top 5–8 relevant chunks
                 |
                 v
      Optional local RAG LLM
      Qwen3-4B-Instruct Q4_K_M
                 |
                 v
 Answer + citations + source links
```

### 3.1. Kiến trúc truy cập Android từ xa

PC Windows là máy chủ tài liệu và giữ toàn bộ file gốc, database, embedding index và local LLM. Android chỉ giữ cấu hình kết nối, token phiên và dữ liệu tạm cần thiết để hiển thị.

```text
Android app
    |
    | HTTPS/TLS hoặc secure tunnel outbound
    v
PC local gateway/API
    |
    +-- Search service -> SQLite/BM25/vector index
    +-- RAG service -> Ollama/llama.cpp
    +-- File service -> thư mục được cấp quyền
```

Yêu cầu kết nối:

- Ưu tiên cơ chế outbound tunnel như Tailscale, Cloudflare Tunnel hoặc relay do ứng dụng quản lý; không yêu cầu người dùng mở port router.
- Nếu dùng public endpoint, gateway phải có TLS hợp lệ, rate limit, authentication và không bind trực tiếp các dịch vụ nội bộ.
- Không expose Ollama API, SQLite, FAISS index hoặc đường dẫn thư mục tài liệu ra Internet.
- Android phải kiểm tra trạng thái PC online/offline và hiển thị lỗi mạng rõ ràng.
- Search và RAG phải chạy tại PC; chỉ gửi query, bộ lọc và các kết quả cần hiển thị qua kết nối.
- File chỉ được tải khi người dùng yêu cầu, qua endpoint có authorization và thời hạn ngắn.
- Không cache tài liệu nhạy cảm lâu dài trên Android; cho phép tắt cache.

API tối thiểu:

```text
POST /api/v1/auth/pair
POST /api/v1/auth/refresh
POST /api/v1/search
POST /api/v1/rag/ask
GET  /api/v1/documents/{id}
GET  /api/v1/documents/{id}/download
GET  /api/v1/health
GET  /api/v1/index/status
```

Response search phải trả về `document_id`, `file_name`, `relative_path`, `page_number`, `snippet`, `score` và token tải tạm nếu cần. Không trả về absolute path của PC cho Android.

Pairing lần đầu nên dùng QR code hoặc mã ghép nối một lần có thời hạn ngắn. Sau khi ghép nối, Android dùng access token ngắn hạn và refresh token được lưu trong Android Keystore. Có nút revoke thiết bị trong PC.

## 4. Lựa chọn model

### 4.1 Embedding

Model mặc định:

```text
intfloat/multilingual-e5-small
```

Yêu cầu:

- Ưu tiên bản ONNX/OpenVINO hoặc INT8 để giảm RAM và tăng tốc CPU.
- Embedding dimension: 384.
- Khi encode query dùng tiền tố `query: `.
- Khi encode chunk tài liệu dùng tiền tố `passage: `.
- Chuẩn hóa vector L2 trước khi tính cosine similarity.
- Không gửi tài liệu lên API bên ngoài.

Ví dụ:

```text
query: quy định về thời hạn thanh toán
passage: Bên mua phải hoàn tất nghĩa vụ thanh toán trong vòng 30 ngày...
```

Không dùng embedding model để sinh câu trả lời.

### 4.2 LLM cho RAG

Model mặc định:

```text
Qwen3-4B-Instruct
```

Bản chạy local:

```text
GGUF Q4_K_M
```

Runtime ưu tiên:

1. Ollama nếu cần cài đặt đơn giản.
2. llama.cpp nếu cần kiểm soát tốt hơn và giảm overhead.

Thiết lập mặc định:

- Context: 4K–8K token tùy RAM.
- `max_new_tokens`: 512–1024.
- Tắt thinking cho câu hỏi RAG thông thường.
- Temperature thấp, khoảng 0.1–0.3.
- Không đưa toàn bộ kho tài liệu vào context.
- Chỉ đưa top 5–8 chunk sau khi retrieval.

Nếu máy có 8 GB RAM và chạy quá chậm, hỗ trợ fallback model 1.7B–2B. Không tự động chọn model lớn hơn khi chưa kiểm tra RAM khả dụng.

### 4.3 Reranker tùy chọn

Chỉ thêm sau khi hybrid search hoạt động ổn định:

```text
BAAI/bge-reranker-v2-m3
```

Reranker chỉ chạy trên top 10–20 kết quả, không chạy trên toàn bộ corpus. Đây là tính năng tùy chọn vì nó làm tăng thời gian CPU và RAM.

### 4.4. Quản lý model trong thư mục dự án

Model phải được coi là một dependency phân phối có version, checksum và license rõ ràng. Không hard-code đường dẫn kiểu `C:\Users\...\.cache` hoặc chỉ dựa vào cache mặc định của Ollama/Hugging Face.

Cấu trúc thư mục đề xuất:

```text
project/
├── app/
├── models/
│   ├── embeddings/
│   │   └── multilingual-e5-small-onnx-int8/
│   ├── llm/
│   │   └── qwen3-4b-instruct-q4_k_m.gguf
│   ├── rerankers/
│   │   └── bge-reranker-v2-m3/              # optional
│   ├── MANIFEST.json
│   └── LICENSES/
├── data/
├── indexes/
└── README.md
```

Yêu cầu bắt buộc:

- Tất cả model được dùng khi chạy phải được tìm qua một `MODEL_ROOT` tương đối với project hoặc data directory do ứng dụng quản lý.
- Có thể override `MODEL_ROOT` bằng biến môi trường hoặc cấu hình, nhưng giá trị mặc định phải trỏ tới thư mục dự án/asset của ứng dụng.
- `MANIFEST.json` phải ghi model name, version/revision, file path, size, SHA-256, format, quantization, source URL và license.
- Khi khởi động, ứng dụng phải kiểm tra file model tồn tại và checksum trước khi load.
- Nếu thiếu hoặc sai checksum, phải báo lỗi rõ ràng và chỉ dẫn cách cài asset; không tự động tải ngầm.
- Model download là bước cài đặt/prepare riêng, có progress, resume và kiểm tra dung lượng đĩa.
- Có lệnh hoặc màn hình `verify-models` để kiểm tra tất cả asset trước khi đóng gói.
- Không commit các file model lớn vào Git mặc định. Có thể lưu trong thư mục project nhưng phải dùng Git LFS, release asset hoặc artifact store nội bộ.
- Bộ cài thương mại phải có tùy chọn `full/offline` đã chứa model và tùy chọn `slim` chỉ chứa ứng dụng nhưng phải ghi rõ model cần cài thêm.
- Không phân phối model nếu license upstream không cho phép việc đóng gói/thương mại hóa. Hiển thị license và attribution trong phần About/Third-party licenses.
- Không gọi Ollama để tự tải model vào thư mục cache riêng nếu yêu cầu đóng gói model nằm trong project. Nếu dùng Ollama runtime, phải cấu hình model asset path hoặc import từ file đã được kiểm tra vào thư mục quản lý của ứng dụng.
- Không đưa tài liệu người dùng, index hoặc token vào thư mục model/package khi tạo bộ phát hành.

Ví dụ `models/MANIFEST.json`:

```json
{
  "schema_version": 1,
  "models": [
    {
      "id": "embedding-multilingual-e5-small",
      "revision": "pinned-revision",
      "path": "embeddings/multilingual-e5-small-onnx-int8",
      "format": "onnx",
      "quantization": "int8",
      "sha256": "replace-with-real-checksum",
      "source": "official-or-approved-source-url",
      "license": "MIT"
    },
    {
      "id": "qwen3-4b-instruct",
      "revision": "pinned-revision",
      "path": "llm/qwen3-4b-instruct-q4_k_m.gguf",
      "format": "gguf",
      "quantization": "Q4_K_M",
      "sha256": "replace-with-real-checksum",
      "source": "approved-model-source-url",
      "license": "upstream-license"
    }
  ]
}
```

## 5. Yêu cầu chức năng

### F1. Chọn thư mục

- Người dùng có thể thêm một hoặc nhiều thư mục.
- Hiển thị danh sách thư mục đã index.
- Có nút scan/index lại.
- Không scan thư mục hệ thống hoặc thư mục ẩn nếu không được chỉ định rõ.

### F2. Phát hiện thay đổi

Lưu tối thiểu:

- Absolute path.
- File name.
- File size.
- Modification time.
- SHA-256 tùy chọn khi cần xác minh chính xác.
- Trạng thái xử lý.
- Error message nếu xử lý thất bại.

Chỉ xử lý lại file mới hoặc file có size/mtime/hash thay đổi.

### F3. Trích xuất DOCX

- Giữ heading, paragraph, table và thứ tự đọc càng nhiều càng tốt.
- Không làm mất nội dung trong bảng.
- Lưu mapping từ chunk về file và vị trí logic.
- Nếu không xác định được số trang DOCX, hiển thị section/paragraph hoặc ghi rõ `page: unknown`.

### F4. Trích xuất PDF

- Trích xuất text theo trang.
- Lưu page number cho mỗi chunk.
- Loại bỏ header/footer lặp lại nếu có thể.
- Phát hiện PDF không có text hoặc có quá ít text.
- Không coi PDF scan là đã index thành công nếu chưa OCR.

### F5. Chunking

Mặc định:

- Kích thước: 250–450 token.
- Overlap: 40–80 token.
- Không cắt giữa tiêu đề và đoạn nội dung nếu có thể.
- Ưu tiên cắt theo heading, paragraph, sentence rồi mới cắt theo token.
- Gắn metadata vào mỗi chunk:
  - `document_id`
  - `file_path`
  - `file_name`
  - `extension`
  - `page_number`
  - `section_heading`
  - `chunk_index`
  - `text_hash`
  - `modified_time`

### F6. Hybrid search

Mỗi query phải chạy:

1. BM25 trên text đã chuẩn hóa.
2. Semantic search trên embedding.
3. Chuẩn hóa điểm của hai phương pháp.
4. Gộp điểm theo công thức mặc định:

```text
final_score = 0.45 * semantic_score + 0.55 * bm25_score
```

Trọng số phải được cấu hình, không hard-code ở nhiều nơi.

BM25 đặc biệt quan trọng cho:

- Mã hợp đồng.
- Số văn bản.
- Tên riêng.
- Số tiền.
- Ngày tháng.
- Điều khoản có cụm từ chính xác.

### F7. Giao diện tìm kiếm

Giao diện tối thiểu phải có:

- Ô nhập query.
- Bộ lọc thư mục.
- Bộ lọc loại file.
- Bộ lọc ngày sửa đổi.
- Số lượng kết quả.
- Chế độ `Search only` và `Ask from documents`.
- Danh sách kết quả có snippet được highlight.
- Tên file, đường dẫn tương đối, trang và điểm.
- Nút mở file bằng ứng dụng mặc định của hệ điều hành.
- Nút copy đoạn trích.

### F8. RAG local

Khi người dùng chọn `Ask from documents`:

1. Chạy hybrid search.
2. Lấy top 5–8 chunk, loại bỏ chunk trùng hoặc gần trùng.
3. Giới hạn context theo ngân sách token.
4. Gửi context cho local LLM.
5. Trả lời bằng tiếng Việt nếu query bằng tiếng Việt.
6. Hiển thị danh sách nguồn được sử dụng.
7. Nếu không đủ thông tin, phải nói rõ không tìm thấy thông tin đầy đủ.

Prompt hệ thống tối thiểu:

```text
Bạn là trợ lý tra cứu tài liệu nội bộ.

Chỉ được sử dụng thông tin trong CONTEXT.
Không được bịa hoặc suy đoán dữ kiện không có trong CONTEXT.
Nếu CONTEXT không đủ để trả lời, nói: "Không tìm thấy thông tin đầy đủ trong tài liệu."
Trả lời ngắn gọn, rõ ràng bằng ngôn ngữ của câu hỏi.
Mỗi kết luận quan trọng phải gắn với nguồn [Số].

QUESTION:
{question}

CONTEXT:
{context}
```

Sau phần trả lời phải có:

```text
Nguồn:
[1] ten-file.pdf, trang 4
[2] hop-dong.docx, section Thanh toán
```

### F9. Android remote access

- Có ứng dụng Android hoặc giao diện mobile responsive được đóng gói để dùng trên smartphone.
- Có màn hình ghép nối với PC bằng QR code hoặc mã một lần.
- Hiển thị danh sách PC đã ghép nối và trạng thái online/offline.
- Cho phép gửi query search và nhận kết quả hybrid search.
- Cho phép lọc theo thư mục, loại file và ngày sửa đổi.
- Cho phép xem snippet, metadata và citation.
- Cho phép tải hoặc mở tài liệu gốc qua link có thời hạn.
- Cho phép gửi câu hỏi RAG tới local LLM trên PC và xem câu trả lời kèm nguồn.
- Có timeout, retry có giới hạn và nút hủy request.
- Không cần Android giữ bản sao toàn bộ index hoặc tài liệu.
- Khi PC offline, Android phải thông báo rõ thay vì hiển thị dữ liệu cũ như dữ liệu hiện tại.
- Tất cả chức năng remote phải có thể tắt hoàn toàn trong phần cài đặt PC.

## 6. Riêng tư và an toàn

- Mặc định toàn bộ xử lý phải chạy local.
- Không gọi Gemini, Claude, OpenAI, Voyage hoặc dịch vụ embedding cloud.
- Không ghi nội dung tài liệu vào log thông thường.
- Không log API key vì có thể có tùy chọn provider mở rộng trong tương lai.
- Chỉ mở file khi người dùng bấm nút hoặc yêu cầu rõ.
- Không tự động xóa, di chuyển hoặc ghi đè file gốc.
- Xử lý path có ký tự Unicode và path có khoảng trắng.
- Chống path traversal nếu có lớp HTTP/API local.
- Không mở port database, file share, Ollama hoặc llama.cpp trực tiếp ra Internet.
- Chỉ gateway/API remote được phép nhận kết nối bên ngoài.
- Bắt buộc TLS khi truyền query, snippet, token và file.
- Token phải có thời hạn, scope và khả năng revoke theo từng thiết bị.
- Pairing code phải dùng một lần, có thời hạn ngắn và không được ghi vào log.
- Rate limit các endpoint search, RAG và download.
- Giới hạn kích thước file tải xuống và chống path traversal khi lấy file.
- Chỉ cho phép truy cập các thư mục đã được người dùng cấp quyền.
- Ghi audit log tối thiểu cho đăng nhập, pairing, revoke, search và download; không ghi nội dung tài liệu hoặc query nhạy cảm mặc định.
- Từ chối request nếu thiếu authentication, sai scope hoặc token đã hết hạn.
- Không dùng HTTP không mã hóa kể cả khi Android và PC ở cùng mạng Wi-Fi, trừ localhost.

## 7. Lưu trữ dữ liệu

Với bản đầu tiên, ưu tiên SQLite vì dễ backup và không cần dịch vụ nền.

Các bảng tối thiểu:

```text
documents
- id
- path
- file_name
- extension
- size_bytes
- modified_time
- content_hash
- status
- error_message
- created_at
- updated_at

chunks
- id
- document_id
- chunk_index
- page_number
- section_heading
- text
- text_hash
- created_at

embeddings
- chunk_id
- vector
- model_name
- dimensions
- created_at

paired_devices
- id
- device_name
- platform
- token_hash
- scopes
- paired_at
- last_seen_at
- revoked_at

audit_events
- id
- device_id
- event_type
- created_at
- success
```

Có thể dùng FAISS index riêng và lưu `chunk_id` trong SQLite. Không cần dùng database server cho 500 tài liệu.

## 8. Hiệu năng mục tiêu

Trên máy 8–16 GB RAM, CPU văn phòng và không có GPU:

- Ứng dụng khởi động không quá 10 giây sau khi index đã tồn tại.
- Tìm kiếm hybrid trả kết quả trong khoảng 1–5 giây tùy CPU.
- Không load nhiều bản sao của cùng model.
- Embedding index 500 tài liệu phải có thể rebuild lại.
- Khi index, hiển thị tiến độ theo số file và cho phép hủy.
- Không treo toàn bộ giao diện trong khi scan hoặc embed.
- Không dùng batch quá lớn; batch mặc định 8–32 chunk.
- Search remote chỉ truyền query, metadata và snippet cần thiết; không truyền toàn bộ index.
- Với mạng chậm, trả kết quả search trước rồi stream hoặc phân trang snippet/RAG.
- Download phải hỗ trợ resume nếu file lớn, nhưng không được cấp URL vĩnh viễn.
- Một request remote bị mất kết nối không được làm dừng index hoặc RAG đang chạy trên PC.

## 9. Xử lý lỗi

Các lỗi phải hiển thị thân thiện:

- File bị khóa.
- File hỏng.
- PDF scan không có text.
- DOCX không đọc được.
- Thiếu runtime hoặc model.
- Không đủ RAM.
- Index bị hỏng.
- Không thể mở file gốc.

Một file lỗi không được làm dừng toàn bộ quá trình index. Phải tiếp tục các file còn lại và ghi lại lỗi để retry.

## 10. Tiêu chí nghiệm thu

### Indexing

- [ ] Quét được DOCX và PDF từ thư mục người dùng chọn.
- [ ] Không index lại file không thay đổi.
- [ ] Có trạng thái thành công/thất bại cho từng file.
- [ ] Có thể rebuild toàn bộ index.
- [ ] Có mapping chunk về file và trang/section.

### Search

- [ ] Tìm được cụm từ chính xác như mã hợp đồng.
- [ ] Tìm được câu hỏi diễn đạt khác với nội dung gốc.
- [ ] Kết quả có snippet và nguồn.
- [ ] Có bộ lọc file/thư mục/ngày.
- [ ] Mở được file gốc từ kết quả.

### RAG

- [ ] Trả lời chỉ dựa trên các chunk được cung cấp.
- [ ] Có trích dẫn nguồn.
- [ ] Không bịa khi context không đủ.
- [ ] Có thể tắt RAG và dùng Search only.
- [ ] Chạy hoàn toàn local khi không cấu hình provider ngoài.

### Remote Android

- [ ] Ghép nối Android–PC bằng QR hoặc mã một lần có hạn sử dụng.
- [ ] Android thấy đúng trạng thái online/offline của PC.
- [ ] Search từ Android trả về snippet, tên file và page/section.
- [ ] Có thể tải/mở file được cấp quyền từ Android.
- [ ] Có thể hỏi RAG từ Android và nhận citation.
- [ ] Không thể truy cập file ngoài thư mục đã cấp quyền.
- [ ] Token bị revoke thì thiết bị mất quyền ngay.
- [ ] Endpoint HTTP nội bộ như Ollama/SQLite không bị expose.
- [ ] Test được qua hai mạng Internet khác nhau, không chỉ cùng Wi-Fi.

### Tài nguyên

- [ ] Có cảnh báo nếu RAM khả dụng thấp.
- [ ] Có thể chọn model nhỏ hơn.
- [ ] Không load embedding model nhiều lần.
- [ ] Không làm mất dữ liệu index khi ứng dụng bị đóng giữa chừng.

## 11. Kế hoạch triển khai cho coding agent

### Bước 1: Khảo sát repository

- Kiểm tra stack hiện có.
- Tìm file cấu hình, entry point và test framework.
- Không thay đổi kiến trúc lớn nếu repository đã có convention rõ.
- Nếu repository trống, chọn stack đơn giản, dễ chạy local và dễ đóng gói cho Windows.

### Bước 2: Viết kế hoạch ngắn

Trước khi code, agent phải ghi ra:

- Các module cần tạo/sửa.
- Cách cài dependency.
- Cách chạy dev.
- Cách chạy test.
- Cách tải model.
- Các rủi ro về RAM và nền tảng.

### Bước 2A: Chuẩn hóa model assets

- Tạo `models/`, `MANIFEST.json` và thư mục license.
- Chọn revision cố định, không dùng tag trỏ tới `latest`.
- Tải model vào đúng thư mục project bằng script có thể chạy lặp lại.
- Tính SHA-256 và cập nhật manifest tự động.
- Kiểm tra license và quyền phân phối trước khi đưa model vào bộ cài.
- Thêm lệnh `prepare-models`, `verify-models` và `package-offline`.
- Test khởi động khi Internet bị tắt.

### Bước 3: Xây ingestion độc lập

- Implement scanner.
- Implement DOCX/PDF extractor.
- Implement normalization.
- Implement chunker.
- Viết test với file mẫu.
- Chưa tích hợp LLM ở bước này.

### Bước 4: Xây index và search

- Implement SQLite metadata store.
- Implement BM25.
- Implement embedding provider local.
- Implement vector store.
- Implement hybrid ranking.
- Viết test retrieval với query tiếng Việt và tiếng Anh.

### Bước 5: Xây giao diện Search only

- Làm search hoạt động ổn định trước.
- Hiển thị nguồn và mở file.
- Có progress, cancel và error state.

### Bước 6: Tích hợp local RAG

- Tích hợp Ollama hoặc llama.cpp qua adapter.
- Không để core search phụ thuộc vào LLM runtime.
- Nếu local LLM chưa cài, Search only vẫn phải chạy.
- Thêm prompt chống hallucination và citation.

### Bước 7: Xây remote gateway và Android client

- Tách gateway/API khỏi core indexing và RAG bằng interface rõ ràng.
- Implement `/health`, `/search`, `/rag/ask`, `/documents/{id}` và `/download`.
- Thêm pairing QR/mã một lần, token rotation và revoke device.
- Chỉ cho phép gateway gọi service nội bộ qua loopback hoặc private interface.
- Tạo Android client tối thiểu cho pairing, search, xem nguồn, RAG và download.
- Kiểm thử khi PC ngủ, mất mạng, đổi IP, tunnel reconnect và token hết hạn.
- Không coi việc chạy được trên cùng Wi-Fi là đạt; phải kiểm thử qua hai mạng khác nhau.

### Bước 8: Tối ưu tài nguyên

- Đo RAM khi mở ứng dụng, khi index và khi RAG.
- Giới hạn context và output.
- Bật model lazy loading.
- Cho phép unload LLM sau một khoảng thời gian không sử dụng nếu cần.

### Bước 9: Kiểm thử và tài liệu

- Test unit cho extractor, chunker và ranking.
- Test integration với corpus mẫu.
- Test file tiếng Việt có dấu, tên file Unicode và path có khoảng trắng.
- Viết README cài đặt trên Windows.
- Ghi rõ model license và cách tải model.
- Viết hướng dẫn pairing Android, bật/tắt remote access và revoke thiết bị.
- Ghi rõ mô hình mạng, yêu cầu Internet và các giới hạn bảo mật.
- Viết hướng dẫn đóng gói full/offline và slim installer.
- Ghi rõ kích thước model, dung lượng đĩa cần thiết, checksum và license từng model.

## 12. Quy tắc làm việc dành cho agent

1. Không gửi dữ liệu tài liệu ra ngoài nếu chưa có lựa chọn và thông báo rõ.
2. Không thêm Claude/Gemini API vào phiên bản local mặc định.
3. Không dùng toàn bộ tài liệu làm context cho LLM.
4. Không đổi model mặc định sang model lớn hơn chỉ để cải thiện demo.
5. Ưu tiên kết quả có nguồn hơn câu trả lời dài.
6. Mọi thay đổi phải có test hoặc cách kiểm tra thủ công rõ ràng.
7. Không xóa dữ liệu, index hoặc file gốc trong migration mà không có backup.
8. Khi lỗi do model/runtime, phải báo lỗi có hướng dẫn khắc phục, không nuốt exception.
9. Nếu phải lựa chọn giữa tốc độ và chất lượng, giữ hai cấu hình `Balanced` và `Low memory`.
10. Kết thúc mỗi milestone bằng báo cáo: đã làm, file đã đổi, lệnh test, kết quả và việc còn lại.
11. Không triển khai remote access bằng cách mở trực tiếp cổng SMB, RDP, SQLite, Ollama hoặc thư mục chia sẻ.
12. Mọi endpoint download phải kiểm tra quyền trên server, không tin `document_id` hoặc path do Android gửi lên.

## 13. Cấu hình mặc định đề xuất

```yaml
language: vi
privacy:
  cloud_api_enabled: false

models:
  root: ./models
  manifest: ./models/MANIFEST.json
  verify_on_start: true
  allow_runtime_download: false
  package_mode: full-offline
  embedding_path: ./models/embeddings/multilingual-e5-small-onnx-int8
  llm_path: ./models/llm/qwen3-4b-instruct-q4_k_m.gguf
  reranker_path: ./models/rerankers/bge-reranker-v2-m3

index:
  chunk_tokens: 350
  chunk_overlap_tokens: 60
  embedding_model: intfloat/multilingual-e5-small
  embedding_backend: onnx-int8
  vector_dimensions: 384
  batch_size: 16

retrieval:
  mode: hybrid
  bm25_weight: 0.55
  semantic_weight: 0.45
  top_k_candidates: 30
  top_k_context: 8
  reranker_enabled: false

rag:
  enabled: true
  runtime: ollama
  model: qwen3:4b
  quantization: Q4_K_M
  context_tokens: 6144
  max_output_tokens: 768
  thinking: false
  temperature: 0.2

fallback:
  low_memory_model: qwen3:1.7b
  low_memory_context_tokens: 4096

remote:
  enabled: false
  gateway_bind: 127.0.0.1
  transport: secure-tunnel
  require_tls: true
  pairing_code_ttl_seconds: 300
  access_token_ttl_seconds: 900
  refresh_token_ttl_days: 30
  download_link_ttl_seconds: 300
  max_download_mb: 100
  rate_limit_per_minute: 30
  cache_documents_on_android: false
```

## 14. Definition of Done

Tính năng được coi là hoàn thành khi người dùng có thể:

1. Chọn thư mục chứa DOCX/PDF.
2. Bấm Index và thấy tiến độ.
3. Tìm bằng một câu hỏi tiếng Việt không trùng nguyên văn với tài liệu.
4. Nhận được các đoạn liên quan kèm file nguồn.
5. Mở được file gốc.
6. Chọn Ask from documents và nhận câu trả lời local có citation.
7. Tắt Ollama/local LLM mà chức năng Search only vẫn hoạt động.
8. Chạy lại ứng dụng và sử dụng index cũ mà không cần index lại toàn bộ.
9. Chạy được trên máy dưới 16 GB RAM với cấu hình Balanced hoặc Low memory.
10. Ghép nối được một thiết bị Android bằng QR/mã một lần.
11. Từ mạng Internet khác, Android tìm kiếm được trên PC khi cả hai máy đang bật.
12. Android xem được citation và tải đúng tài liệu đã được cấp quyền.
13. Khi revoke thiết bị, các request search/RAG/download của thiết bị đó bị từ chối.
14. Không có dịch vụ nội bộ nào bị expose trực tiếp ra Internet.
15. Ứng dụng khởi động và chạy Search/RAG khi Internet bị tắt sau khi model đã được cài.
16. Model được load từ thư mục project/asset đã cấu hình, không từ cache không kiểm soát.
17. `verify-models` phát hiện được model thiếu, sai checksum hoặc sai revision.
18. Bộ cài offline chứa đủ model, runtime và manifest để chạy trên máy sạch.
