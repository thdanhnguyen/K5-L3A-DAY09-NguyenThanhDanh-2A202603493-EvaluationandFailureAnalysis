# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi nhóm 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run ID `E-seeded_regression-20261117-d239` |
| Triệu chứng | `TrialPass` (`lab8_pass=False`, `status resolved != denied`), `DbFactKept=False`, `RefundAmountCorrect=False`; reply nói `"Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."` và ledger ghi `refund_vnd=20000`, `refund_count=1`, trong khi nhãn yêu cầu `denied`, `refund_vnd=0`. |
| Bước sai đầu tiên | Event `#3` `model_override`: `{"delay_days": 5}` — agent lấy `delay_days=5` do khách tự khai trong ticket để ghi đè `delay_days=2` từ DB. |
| Vì sao là bước *đầu tiên* | Event `#1` `handoff` đúng hợp đồng `handoff.v1` với `allowed_tools` chuẩn; event `#2` `investigator` đọc đúng DB đơn `O-202` (`visible=true`, `status="delivered"`, `delay_days=2`). Sai sót bắt đầu ngay tại bước `#3` khi ghi đè sự thật DB bằng thông tin trong ticket, kéo theo event `#4` `quote` tính ra `20000đ` và phát hành hoàn tiền sai. |
| Failure mode | `FM-03` (`ticket_trust — tin ticket hơn DB`) trong [failure_taxonomy.md](failure_taxonomy.md) |
| Đối chứng | Trên `fixed C-002@11`, sau event `#2` `investigator` (`delay_days=2`), không có event `model_override`; event `#3` là `quote` (`amount_vnd=0`, `reason="no_entitlement"`), event `#4` `reply` từ chối đúng (`status=denied`, `ledger refund_vnd=0`). |
| Regression test | `test_trace_case_c002_seeded_regression_vs_fixed` trong [test_lab9_trace_case.py](../src/tests/test_lab9_trace_case.py) dùng `DbFactKept` + `RefundAmountCorrect`: fail trên `seeded_regression C-002@11` và pass trên `fixed C-002@11`. |
| Chưa chắc chắn | MockLLM bỏ qua bước phân tích ngôn ngữ tự nhiên thực tế của LLM thật; với LLM thật cần thêm kiểm tra xem model có tự suy diễn `delay_days` mà không ghi event `model_override` (như biến thể `quiet_override`) hay không. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
