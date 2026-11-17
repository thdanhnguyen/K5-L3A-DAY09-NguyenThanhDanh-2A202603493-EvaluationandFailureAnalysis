# Judge audit

Chạy:
- `python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10`
- `python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 10`

| Tiêu chí | n | κ | Precision | Recall | Observed → Corrected Fail Rate | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 0.280 → 0.300 (`TP=24, FP=4, FN=6, TN=66`) | Đạt (0.757≥0.6, 0.857≥0.8, 0.800≥0.7) | **dùng** (theo dõi định kỳ + sửa rubric cho các edge case) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 0.090 → 0.300 (`TP=9, FP=0, FN=21, TN=70`) | **Không đạt** (κ=0.375 < 0.6, R=0.300 < 0.7) | **loại** (tuyệt đối không dùng làm gate) |

## ≥5 case audit thủ công (10 bất đồng tiêu biểu)
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | `H-008` (`tone_ok`) | PASS | FAIL | Người đúng | `"Em đã hoàn tiền cho anh rồi nha..."`: xưng "em/nha" quá suồng sã; judge nhầm thân thiện = lịch sự. **Sửa rubric:** cấm đại từ thân mật ("em/nha/bạn"), bắt buộc "LogiX / anh/chị / ạ". |
| 2 | `H-029` (`tone_ok`) | PASS | FAIL | Người đúng | `"Dạ, vui lòng chờ... không cần nhắn thêm."`: giọng ra lệnh, đuổi khách dù có "Dạ, vui lòng". **Sửa rubric:** kiểm tra ngữ nghĩa cả câu, phạt câu ngăn khách phản hồi. |
| 3 | `H-051` (`tone_ok`) | FAIL | PASS | Người đúng | `"Dạ, LogiX đã refund 90.000đ..."`: CSKH LogiX cho phép từ "refund", judge tự phạt vì tiếng Anh. **Sửa rubric:** nêu rõ whitelist thuật ngữ ("refund") được chấp nhận. |
| 4 | `H-063` (`tone_ok`) | PASS | FAIL | Người đúng | `"...và sẽ hoàn thêm cho anh/chị ạ"`: hứa hẹn ngoài kết quả hệ thống dù câu chữ lễ phép. **Sửa rubric:** thêm quy tắc cấm cam kết/hứa hoàn thêm ngoài ledger. |
| 5 | `H-070` (`tone_ok`) | PASS | FAIL | Người đúng | `"Dạ, LogiX đã hoàn 90.000đ... 😂😂"`: dùng emoji cười trong ngữ cảnh khiếu nại. **Sửa rubric:** cấm emoji/biểu cảm không trang trọng. |
| 6 | `H-081` (`tone_ok`) | FAIL | PASS | **Judge đúng** | Nhãn người ghi nhầm (đọc nhầm ticket); câu trả lời thực sự đúng quy chuẩn. **Hành động:** sửa nhãn vàng trong bộ calibration. |
| 7 | `H-094` (`tone_ok`) | PASS | FAIL | Người đúng | `"Da, LogiX da hoan... xin loi vi su bat tien."`: văn bản mất dấu tiếng Việt (lỗi encoding/dịch máy). **Sửa rubric:** bắt buộc tiếng Việt có dấu chuẩn. |
| 8 | `HL-015` (`helpful`) | PASS | FAIL | Người đúng | `"Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ."` nhưng ledger ghi `40.000đ`. Judge chỉ đọc reply, không thấy ledger nên không thể phát hiện sai tiền. |
| 9 | `HL-016` (`helpful`) | PASS | FAIL | Người đúng | `"Dạ, LogiX thành thật xin lỗi... hoàn 55.000đ..."` (ledger `35.000đ`). **Verbosity bias:** câu xin lỗi dài, hoa mỹ đánh lừa judge cho `PASS`. |
| 10 | `HL-047` (`helpful`) | PASS | FAIL | Người đúng | `"Ok bạn, đơn O-515 xử lý rồi nhé."`: sai xưng hô và không rõ kết quả/số tiền, judge vẫn cho `PASS`. |

## Kết luận
- **Tiêu chí bị loại:** `helpful` bị loại vì `κ = 0.375 < 0.6` và `Recall = 0.300 < 0.7` (`TP=9, FP=0, FN=21, TN=70`). Tuy `Precision = 1.0` (không báo nhầm), judge bỏ sót tới **21/30 (70.0%)** lỗi thật (`FN=21`), khiến tỉ lệ lỗi quan sát chỉ là `0.09` trong khi tỉ lệ lỗi thực sau hiệu chỉnh Rogan-Gladen là `0.30`. Nguyên nhân gốc rễ: (1) judge không được cấp dữ liệu ledger nên mù hoàn toàn với lỗi sai tiền (FM-08), và (2) dính *verbosity bias* — các câu xin lỗi dài, lịch sự đều được judge cho `PASS`. Do đó mọi tiêu chí liên quan đến số tiền/ledger phải chấm bằng **code grader** (M3), không dùng LLM judge.
- **Rủi ro còn lại:**
  - `tone_ok` chỉ được kiểm trên 100 mẫu replay công khai (`judge_tone_public.csv`), chưa có tập held-out nhãn người mới sau khi sửa rubric (khi đổi rubric/prompt phải calibrate lại từ đầu).
  - Một số nhãn người gốc vẫn có nhiễu (như `H-081`), cần double-annotation trước khi dùng cho bản kiểm định tiếp theo.
