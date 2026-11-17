"""Regression tests for docs/trace_case.md, FM-08 grader, and hidden integrity traps."""

from __future__ import annotations

import copy
from pathlib import Path
import tempfile

import pytest

from lab8.db import load_json, load_jsonl

pytestmark = pytest.mark.student


def _ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(
        name="regression",
        inputs={},
        metadata=None,
        expected_output=label,
        output=trial,
        duration=0.0,
        _span_tree=None,
        attributes={},
        metrics={},
    )


def test_trace_case_c002_seeded_regression_vs_fixed():
    """Regression test cho docs/trace_case.md: C-002@11 trên seeded_regression vs fixed."""
    # Import lab9 bên trong hàm test để CI của Lab 8 (chỉ cài requirements.txt) collect không bị lỗi thiếu pydantic_evals/scipy
    from lab9 import graders, variants
    from lab9.eval import WORLD, make_task

    variants.register()
    world = load_json(WORLD)
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    with tempfile.TemporaryDirectory(prefix="lab9-reg-") as tmp:
        bad = make_task("seeded_regression", world, claims, labels, Path(tmp))({"claim_id": "C-002", "seed": 11})
        good = make_task("fixed", world, claims, labels, Path(tmp))({"claim_id": "C-002", "seed": 11})

    # Bước sai đầu tiên ở seeded_regression là model_override ghi đè delay_days của DB
    assert graders.DbFactKept().evaluate(_ctx(bad, labels["C-002"])).value is False
    assert graders.RefundAmountCorrect().evaluate(_ctx(bad, labels["C-002"])).value is False
    # Trên bản fixed, không có model_override và ledger giữ nguyên 0đ
    assert graders.DbFactKept().evaluate(_ctx(good, labels["C-002"])).value is True
    assert graders.RefundAmountCorrect().evaluate(_ctx(good, labels["C-002"])).value is True


def test_fm08_reply_matches_ledger_and_proposal_quote():
    """Regression test cho FM-08 (reply nói sai số tiền ledger) và FM-04/05 (proposal lệch quote)."""
    from lab9 import graders, variants
    from lab9.eval import WORLD, make_task

    variants.register()
    world = load_json(WORLD)
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    with tempfile.TemporaryDirectory(prefix="lab9-fm08-") as tmp:
        bad_fm08 = make_task("seeded_regression", world, claims, labels, Path(tmp))({"claim_id": "C-008", "seed": 11})
        good_fm08 = make_task("fixed", world, claims, labels, Path(tmp))({"claim_id": "C-008", "seed": 11})
        bad_c013 = make_task("seeded_regression", world, claims, labels, Path(tmp))({"claim_id": "C-013", "seed": 11})

    # C-008: lab8_pass=True nhưng reply nói 35.000đ trong khi ledger chỉ ghi 20.000đ
    assert bad_fm08["lab8_pass"] is True
    assert graders.ReplyMatchesLedger().evaluate(_ctx(bad_fm08, labels["C-008"])).value is False
    assert graders.ReplyMatchesLedger().evaluate(_ctx(good_fm08, labels["C-008"])).value is True
    # C-013: pre_deducted sửa proposal xuống 0 khác quote 35.000đ
    assert graders.ProposalMatchesQuote().evaluate(_ctx(bad_c013, labels["C-013"])).value is False


def test_hidden_integrity_traps_blocked():
    """Kiểm tra các trap ẩn: dòng trùng lặp, evaluator_failures trên run xanh, đổi nhãn slice."""
    from lab9 import gate
    rows = [
        {"item_id": f"E-{i:03d}", "seed": s, "pass_rate": True, "slices": ["money_movement"] if i == 0 else []}
        for i in range(4)
        for s in (1, 2)
    ]
    spec = {
        "eval_set_version": "v2",
        "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True, "threshold": {"min": 0.8}}],
        "slices": [{"name": "money_movement", "metric": "pass_rate", "min": 0.9, "blocking": True}],
    }
    base = {"manifest": {"eval_set_sha": "x", "items": 4, "seeds": [1, 2]},
            "rows": rows, "metrics": {"pass_rate": 1.0}, "evaluator_failures": []}

    # Trap ẩn 1: nhân bản dòng dễ và bỏ dòng khó để giữ nguyên tổng số 8 dòng
    dup = copy.deepcopy(base)
    dup["rows"][-1] = copy.deepcopy(dup["rows"][0])
    assert gate.integrity_check(dup, base, spec)

    # Trap ẩn 2: mọi metric đều xanh (1.0) nhưng evaluator_failures khác rỗng
    ev_fail = copy.deepcopy(base)
    ev_fail["evaluator_failures"] = ["E-001@1:SomeGrader:TimeoutError"]
    assert gate.integrity_check(ev_fail, base, spec)

    # Trap ẩn 3: xóa nhãn slice trên 1 item để né slice gate
    relabeled = copy.deepcopy(base)
    relabeled["rows"][0]["slices"] = []
    assert gate.integrity_check(relabeled, base, spec)
