# Đóng góp
- Nhánh `feature/...`, `fix/...`; PR nhỏ, có test. Commit rõ ràng, không commit model/binary/dữ liệu thật/index/.db (hook `scripts/check_forbidden_files.py`).
- Mọi thay đổi retrieval phải chạy `python evals/run_eval.py` và không làm giảm chỉ số; không hạ ngưỡng âm thầm.
- Thêm dependency: kiểm tra license (cấm AGPL/GPL khi chưa phê duyệt). Không dùng PyMuPDF.
- Không dùng tài liệu thật làm fixture.
