# Quyền riêng tư
- Tài liệu, chỉ mục (SQLite, plaintext), kết quả OCR nằm trên máy; không gọi API ngoài với nội dung tài liệu. Ảnh trang OCR tạm bị xóa ngay sau khi nhận dạng.
- Không ghi nội dung tài liệu/truy vấn/token vào log. Chỉ mở file khi người dùng bấm; không sửa/xóa/di chuyển file gốc.
- Góp ý: lưu trên máy; gửi đi chỉ khi có `feedback.endpoint`, và chỉ đúng nội dung người dùng gõ (email tùy chọn).
- Số liệu ẩn danh: mặc định TẮT, người dùng chủ động bật (hiện chưa có mã gửi).
- Khuyến nghị bật BitLocker. Cần rà soát quy định bảo vệ dữ liệu cá nhân hiện hành của Việt Nam trước khi phát hành.
