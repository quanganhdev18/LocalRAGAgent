# Kế hoạch triển khai chi tiết và quy trình đẩy lên GitHub (Giai đoạn 1 và 1.5)

Tài liệu đi kèm `Specv3_MVP.md` (v3.1). Phạm vi: tìm kiếm tài liệu local (DOCX, PDF có text và scan qua OCR, PPTX) cho nghiên cứu sinh và giáo viên; thử nghiệm kín với 10–20 người dùng.

## 1. Giữ và tạm bỏ

| Giữ cho giai đoạn 1 và 1.5 | Tạm bỏ (không tạo thư mục, không commit, không đóng gói) |
|---|---|
| Scanner, reconcile, extractor DOCX/PDF/PPTX | LLM, `llama-server`, module `rag/` |
| OCR (Tesseract, vie+eng) | Reranker `bge-reranker-v2-m3` |
| FTS5, embedding E5-small, RRF | Gateway, Android, pairing, Tailscale, token |
| UI cục bộ, trang tình trạng index, nút Góp ý | SQLCipher, ký manifest, code signing |
| Eval harness và golden set tổng hợp | FAISS, Ollama |
| `prepare-models`, `verify-models`, đóng gói zip/exe | Mọi dữ liệu thật, index, file `.db` |

Chỉ **hai** nhóm tài sản ngoài mã nguồn: model E5-small (ONNX) và dữ liệu/binary OCR. Cả hai không nằm trong Git (mục 3).

## 2. Cấu trúc repo

Chỉ tạo những thư mục có trong danh sách này.

```text
vi-docsearch/                     # tên repo là đề xuất, đổi theo ý bạn
├── README.md                     # cài đặt, chạy dev, chạy test, giới hạn
├── CONTRIBUTING.md               # quy trình nhánh, commit, PR
├── pyproject.toml                # dependency, ruff, pytest, mypy
├── requirements.lock             # có hash (uv hoặc pip-compile)
├── .gitignore  .gitattributes  .pre-commit-config.yaml
├── .github/
│   ├── workflows/ci.yml  eval.yml  release.yml
│   ├── ISSUE_TEMPLATE/ (bug.yml, feature.yml)
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── dependabot.yml
├── app/
│   ├── core/        # config, paths, logging, lỗi, kiểm tra model
│   ├── ingest/      # scanner, reconcile, extractors/{docx,pdf,pptx}.py, ocr/, normalize, chunker
│   ├── index/       # db.py, fts.py, vectors.py, migrations/
│   ├── search/      # hybrid.py, filters.py, rrf.py, highlight.py
│   ├── ui/          # web UI cục bộ, trang tình trạng index, form góp ý
│   └── cli.py       # prepare-models, verify-models, reindex, eval, package
├── models/
│   ├── MANIFEST.json             # chỉ file này và LICENSES/ nằm trong Git
│   └── LICENSES/
├── evals/
│   ├── golden_spec/              # mô tả corpus và cặp truy vấn (YAML), đưa vào Git
│   ├── make_golden.py            # sinh corpus tổng hợp (kể cả scan, PPTX) từ golden_spec
│   └── results/                  # chỉ commit bản tóm tắt nhỏ (.md/.json)
├── tests/ (unit/, integration/, fixtures/ rất nhỏ)
├── scripts/ (prepare_models.py, fetch_tesseract.py, build_windows.ps1)
├── packaging/ (pyinstaller.spec, installer.iss)
└── docs/ (decisions.md, architecture.md, pilot-guide.md, privacy.md)
```

Không có `rag/`, `gateway/`, `android/`, `runtime/llama-server/`, `models/llm/`, `models/rerankers/`.

## 3. Những gì không đưa lên Git và cách phân phối

| Tài sản | Vì sao không commit | Cách phân phối |
|---|---|---|
| Model E5-small ONNX (khoảng trăm MB đến vài trăm MB tùy FP32/INT8) | Git thường giới hạn mỗi file ~100 MB; model làm repo phình vĩnh viễn | `prepare-models` tải từ nguồn đã ghim revision, hoặc tải từ GitHub Release `models-v1`; kiểm tra SHA-256 theo `MANIFEST.json` |
| Binary Tesseract và `tessdata_fast` (vie, eng) | Binary và dữ liệu lớn, thay đổi theo phiên bản | `scripts/fetch_tesseract.py` tải bản đã ghim URL và SHA-256; kiểm tra license trước khi đóng gói |
| Bản build (`dist/`, `.exe`, `.zip`) | Sinh ra từ mã nguồn | Đính kèm GitHub Release do workflow `release.yml` tạo |
| Tài liệu thật, index, `.db`, log | Riêng tư | Không bao giờ vào Git; `.gitignore` và hook chặn |
| Golden corpus sinh ra (PDF/PPTX/scan) | Có thể tái tạo | Chỉ commit `golden_spec/` và `make_golden.py`; corpus sinh ra nằm ở `evals/_generated/` (bị ignore), nhưng có thể đính kèm release `golden-vN` để CI dùng lại |

Lưu ý giới hạn: file đơn lẻ trên GitHub thường bị chặn ở khoảng 100 MB, Git LFS có hạn mức lưu trữ/băng thông miễn phí nhỏ, và tệp đính kèm của Release cũng có trần cho mỗi file. Các con số này thay đổi theo thời gian, nên kiểm tra tài liệu hiện hành của GitHub trước khi chốt. Khuyến nghị ban đầu: **dùng Release assets thay vì LFS** cho model.

## 4. Cấu hình repo

### `.gitignore` (tối thiểu)

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/

# Build
build/
dist/

# Môi trường và bí mật
.env
.env.*
*.pem
*.key
secrets/

# Model, binary, dữ liệu, index (không bao giờ commit)
models/*
!models/MANIFEST.json
!models/LICENSES/
runtime/
tessdata/
*.onnx
*.gguf
*.safetensors
*.traineddata
data/
indexes/
*.db
*.sqlite
*.sqlite3
*.db-wal
*.db-shm
evals/_generated/
evals/results/*
!evals/results/summary-*.md
!evals/results/summary-*.json

# Tài liệu thật (đề phòng đặt nhầm)
*.docx
*.pdf
*.pptx
!tests/fixtures/**
!docs/**/*.pdf

# Log và tạm
*.log
logs/
tmp/
```

### `.gitattributes`

```gitattributes
* text=auto eol=lf
*.ps1 text eol=crlf
*.iss text eol=crlf
*.pdf binary
*.docx binary
*.pptx binary
*.png binary
```

### `.pre-commit-config.yaml` (ý chính)

- `ruff` (lint và format), `mypy` (kiểu), `check-added-large-files` với `--maxkb=2000`, `detect-private-key`, `gitleaks` hoặc `detect-secrets`.
- Một hook tùy biến `forbid-user-docs`: **từ chối** commit mọi `.pdf/.docx/.pptx/.db/.sqlite/.onnx/.gguf/.traineddata` ngoài `tests/fixtures/` và `docs/`. Đây là lớp bảo vệ chính để tài liệu thật của người dùng không lọt vào repo.
- CI chạy lại cùng các kiểm tra này, để không phụ thuộc máy cục bộ.

### Giấy phép của repo
Để repo **private** và **chưa thêm** `LICENSE` cho đến khi bạn quyết định hướng thương mại hoặc mã nguồn mở. Khi chọn giấy phép phải đối chiếu với dependency (cấm AGPL/GPL trừ khi có phê duyệt). Ghi `THIRD_PARTY_LICENSES.md` sinh từ `pip-licenses` ngay từ M0.

## 5. Quy trình làm việc

- Nhánh `main` luôn chạy được; làm việc trên nhánh ngắn `feat/…`, `fix/…`, `chore/…`.
- Commit theo quy ước (ví dụ `feat(ocr): add per-page resume`); gộp bằng squash khi merge PR.
- PR bắt buộc có: mô tả, cách kiểm tra, kết quả test; thay đổi retrieval phải đính kèm kết quả `cli eval`.
- Mỗi milestone kết thúc bằng một issue "báo cáo milestone": đã làm, lệnh test, số đo, việc còn lại (theo quy tắc ở spec mục 12).
- Bảo vệ `main`: yêu cầu CI xanh và PR; một số tính năng bảo vệ nhánh và quét bí mật cho repo private phụ thuộc gói GitHub bạn dùng, nên kiểm tra trước khi dựa vào chúng.

## 6. Milestone và issue chi tiết

Thời gian là ước tính cho một người làm cùng coding agent, cần hiệu chỉnh sau M1.

### M0: Nền tảng repo (tuần 0–1)
- M0-01 Tạo repo private, đẩy khung ban đầu (mục 9), bật CI.
- M0-02 `pyproject.toml`, khóa dependency có hash, `ruff`, `mypy`, `pytest`.
- M0-03 `.gitignore`, `.gitattributes`, pre-commit, hook `forbid-user-docs`.
- M0-04 `core/`: cấu hình YAML (`safe_load`), đường dẫn, log không ghi nội dung tài liệu.
- M0-05 `docs/decisions.md` với các quyết định D1–D14 đã chốt, danh sách "tạm bỏ".
- M0-06 `THIRD_PARTY_LICENSES.md` tự sinh và kiểm tra license trong CI.
- M0-07 **Spike OCR (2 ngày):** `evals/make_golden.py` sinh ≥ 30 trang scan tiếng Việt; so Tesseract với một phương án ONNX theo CER, tốc độ, dung lượng, license; ghi quyết định.
- **Hoàn thành khi:** CI xanh trên `main`; repo không chứa file bị cấm; quyết định OCR được ghi lại.

### M1: Trích xuất và chunking (tuần 1–3)
- M1-01 Scanner, bỏ qua file tạm/ẩn/placeholder OneDrive, xử lý Unicode và đường dẫn dài.
- M1-02 Schema SQLite, migration, backup trước khi migrate.
- M1-03 Reconcile: file mới/đổi/xóa/đổi tên (hash), thư mục gốc không truy cập được.
- M1-04 Extractor DOCX (thứ tự body, bảng) trong tiến trình con có timeout.
- M1-05 Extractor PDF bằng `pypdfium2`: text theo trang, loại header/footer, phát hiện trang cần OCR, kiểm tra chất lượng ký tự (`text_suspect`).
- M1-06 Extractor PPTX: slide, bảng, nhóm hình đệ quy, ghi chú, slide ẩn, cờ `partial_content`.
- M1-07 Chuẩn hóa NFC, chunker đo bằng tokenizer E5.
- M1-08 Test với fixtures nhỏ và golden corpus; test Unicode, đường dẫn có khoảng trắng.
- **Hoàn thành khi:** toàn bộ file golden được gán trạng thái đúng; không file nào làm dừng quá trình.

### M2: OCR (tuần 3–4)
- M2-01 `scripts/fetch_tesseract.py` và mục OCR trong `MANIFEST.json`, `verify-models` kiểm tra cả OCR.
- M2-02 Render trang, tiền xử lý, gọi OCR (subprocess), lưu theo từng trang kèm `ocr_confidence`.
- M2-03 Hàng đợi nền, ưu tiên thấp, tạm dừng/hủy/tiếp tục, xóa ảnh tạm.
- M2-04 Hỏi trước khi OCR hàng loạt, hiển thị ước tính trang và thời gian.
- M2-05 Trạng thái `needs_ocr`, `ocr_pending`, `ocr_low_quality`; PDF hỗn hợp.
- M2-06 Đo CER và tốc độ trên golden scan; ghi báo cáo.
- **Hoàn thành khi:** đạt ngưỡng CER ở spec mục 9 hoặc ghi rõ giới hạn và hạ cấp định vị; tắt máy giữa chừng không mất trang đã OCR.

### M3: Index và tìm kiếm (tuần 4–5)
- M3-01 FTS5 trên văn bản bỏ dấu (xử lý `đ`), cột token chính xác cho mã/số.
- M3-02 Embedding E5-small ONNX, tiền tố, L2, nạp ma trận numpy, singleton session.
- M3-03 Bộ lọc áp dụng trước top-k; RRF; loại trùng; giới hạn chunk mỗi tài liệu.
- M3-04 `cli eval` và báo cáo theo nhóm (kể cả Việt → Anh, PPTX, OCR).
- M3-05 So INT8 với FP32 nếu tự quantize; chỉ dùng INT8 khi Recall@10 không giảm quá 2 điểm.
- **Hoàn thành khi:** đạt các ngưỡng retrieval trong spec mục 9, p95 tìm kiếm ≤ 5 giây.

### M4: Giao diện và học hỏi người dùng (tuần 5–7)
- M4-01 UI cục bộ: tìm kiếm, bộ lọc, snippet có đánh dấu, mở file, copy trích dẫn ("Slide N" cho PPTX).
- M4-02 Trang "Tình trạng index": file có vấn đề, OCR, tiến độ, hủy.
- M4-03 Bảo vệ API cục bộ: token phiên, kiểm tra `Host`/`Origin`, không mở CORS.
- M4-04 Chế độ máy yếu: phát hiện RAM, giới hạn luồng, batch.
- M4-05 Nút Góp ý (lưu cục bộ nếu chưa có endpoint), số liệu ẩn danh tắt mặc định, màn hình đầu tiên giải thích dữ liệu.
- **Hoàn thành khi:** người dùng không kỹ thuật làm được luồng chọn thư mục → tìm kiếm → mở file mà không cần hướng dẫn trực tiếp (kiểm tra với 2 người).

### M5: Đóng gói và tài liệu (tuần 7–8)
- M5-01 PyInstaller onedir, Inno Setup, bản zip portable; chưa ký số, hướng dẫn xử lý cảnh báo SmartScreen.
- M5-02 `prepare-models`, `verify-models`, `package`; bản phát hành offline có kèm model E5 và dữ liệu OCR.
- M5-03 README Windows, `docs/pilot-guide.md`, `docs/privacy.md` bằng tiếng Việt dễ hiểu.
- M5-04 Kiểm thử trên máy sạch 8 GB và 16 GB, tắt Internet; ghi RAM đỉnh, tốc độ index, tốc độ OCR.
- **Hoàn thành khi:** máy sạch cài và dùng được, bản phát hành có checksum.

### M6: Giai đoạn 1.5, thử nghiệm kín (tuần 8–11)
- M6-01 Chọn 10–20 người từ bộ phỏng vấn; gửi bản cài kèm hướng dẫn và thông tin về dữ liệu.
- M6-02 Theo dõi bằng nút Góp ý và số liệu ẩn danh (chỉ khi người dùng bật); gọi hỏi thăm sau tuần 1 và tuần 3.
- M6-03 Vá lỗi theo mức độ nghiêm trọng; phát hành `v0.1.x` nhỏ.
- M6-04 Báo cáo: tỷ lệ còn dùng ở tuần 3, nỗi đau thứ hai được nêu, số lượt giới thiệu; quyết định theo điều kiện dừng/tiếp tục ở spec mục 10.

## 7. CI/CD (GitHub Actions)

**`ci.yml`** (mỗi PR và push lên `main`)
- Ma trận: `windows-latest` (kiểm tra đường dẫn, đóng gói thử) và `ubuntu-latest` (nhanh).
- Bước: cài dependency từ khóa hash, `ruff`, `mypy`, `pytest` (unit và integration dùng embedder giả để không cần model), `pip-audit`, kiểm tra license, hook `forbid-user-docs`.
- Không cần bí mật nào; không đưa token vào log.

**`eval.yml`** (thủ công `workflow_dispatch`, hoặc hằng đêm, hoặc khi gắn nhãn `run-eval`)
- Tải model từ Release `models-v1` (cache theo SHA-256), sinh golden corpus (hoặc tải `golden-vN`), cài Tesseract, chạy `cli eval`, tải báo cáo lên artifact và so với ngưỡng; fail nếu tụt dưới ngưỡng.
- Tách riêng vì nặng và chậm.

**`release.yml`** (khi đẩy tag `v*`)
- Build trên `windows-latest`, chạy `verify-models`, tạo zip/exe, tính SHA-256, tạo **Release dạng draft** để bạn kiểm tra thủ công trước khi công bố.

**`dependabot.yml`**: cập nhật dependency Python và GitHub Actions hằng tuần.

## 8. Bảo mật repo

- Repo private; chỉ cấp quyền cho người cần thiết; bật xác thực hai yếu tố cho tài khoản.
- Không đưa token cá nhân vào mã hay lịch sử; dùng GitHub Secrets nếu sau này cần.
- Nếu lỡ commit dữ liệu thật hoặc bí mật: coi như đã lộ, xoay vòng khóa/xóa dữ liệu và làm sạch lịch sử bằng công cụ chuyên dụng; xóa commit sau không đủ.
- Tuân thủ quy định bảo vệ dữ liệu cá nhân của Việt Nam với mọi phản hồi/số liệu người dùng bạn thu thập; kiểm tra bản hiện hành.

## 9. Lần đẩy đầu tiên lên GitHub (checklist)

1. Tạo repo **rỗng và private** trên GitHub (không tick README/.gitignore/license).
2. Trên máy, trong thư mục dự án:
   ```bash
   git init -b main
   # thêm .gitignore, .gitattributes, README, pyproject, docs/ trước
   git add .
   git status            # kiểm tra: không có model, dữ liệu, .db, .pdf/.docx/.pptx ngoài fixtures
   git commit -m "chore: initial project skeleton"
   git remote add origin https://github.com/<owner>/<repo>.git
   git push -u origin main
   ```
3. Cài và chạy `pre-commit install`, rồi `pre-commit run --all-files`.
4. Bật bảo vệ nhánh `main`, Dependabot, quét bí mật (nếu gói của bạn hỗ trợ).
5. Tạo milestone M0–M6 và các issue M0-01 … M6-04 ở mục 6 (có thể tạo hàng loạt bằng `gh issue create`).
6. Đẩy tag đầu tiên `v0.0.1` chỉ để thử luồng `release.yml` với bản build mẫu; kiểm tra Release dạng draft.
7. Tạo Release `models-v1` (model E5 + manifest + checksum) sau khi đã kiểm tra license; **không** đưa model vào Git.

## 10. Rủi ro chính và cách giảm

| Rủi ro | Giảm thiểu |
|---|---|
| Chất lượng OCR tiếng Việt thấp | Spike ở M0; đo CER; BM25 bỏ dấu; hạ cấp định vị nếu không đạt |
| OCR quá chậm trên máy yếu | Hỏi trước, hàng đợi nền, ưu tiên thấp, lưu theo trang, giới hạn trang |
| PPTX có nội dung ở SmartArt/biểu đồ/ảnh | Gắn `partial_content`, báo trong UI, đo trên golden |
| Dung lượng bộ cài tăng (Tesseract, tessdata) | Đo và ghi vào README; bản `slim` tải dữ liệu OCR riêng |
| Lộ dữ liệu người dùng vào repo | Hook `forbid-user-docs`, `.gitignore`, CI kiểm tra lại, repo private |
| Lệch tiến độ | Hiệu chỉnh ước tính sau M1; cắt số liệu ẩn danh ở F8 nếu cần, giữ nút Góp ý |
| Cảnh báo SmartScreen làm người dùng thử e ngại | Hướng dẫn kèm ảnh; cân nhắc ký số trước khi phát hành rộng |
