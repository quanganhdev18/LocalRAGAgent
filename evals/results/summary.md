# Kết quả golden set

OCR: Tesseract  
Index: 13.1 giây · trạng thái: {'encrypted': 1, 'indexed': 41}

| Chỉ số | Giá trị | Ngưỡng | Kết quả |
|---|---|---|---|
| overall | 0.933 | 0.85 | PASS |
| exact | 1.0 | 0.95 | PASS |
| nodiacritic | 1.0 | 0.85 | PASS |
| vi2en | 0.5 | 0.7 | FAIL |
| pptx | 1.0 | 0.85 | PASS |
| ocr | 0.909 | 0.7 | PASS |
| mrr | 0.843 | 0.6 | PASS |
| p95_latency_s | 0.024 | 5.0 | PASS |

Truy vấn trượt: 5
- [vi2en] mạng nơ-ron đồ thị bị làm mịn quá mức (cần en03, top: ['pp03', 'pp01', 'pp02'])
- [vi2en] học liên kết bảo vệ quyền riêng tư (cần en06, top: ['vi01', 'pp07', 'vi09'])
- [vi2en] hệ vi sinh đường ruột và trầm cảm (cần en09, top: ['vi04', 'pp02', 'pp01'])
- [vi2en] học tăng cường từ phản hồi của con người (cần en10, top: ['pp07', 'vi03', 'vi12'])
- [vi2en] đánh giá quá trình cải thiện động lực học toán (cần sc05, top: ['vi03', 'pp07', 'vi09'])
