"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.stats import bootstrap

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    if len(human) != len(judge):
        raise ValueError(f"human ({len(human)}) and judge ({len(judge)}) lengths must match")
    tp = fp = fn = tn = 0
    for h_raw, j_raw in zip(human, judge):
        # Chuẩn hóa chữ hoa và bỏ khoảng trắng để tránh lỗi lệch format CSV
        h_pos = str(h_raw).strip().upper() == POS
        j_pos = str(j_raw).strip().upper() == POS
        if h_pos and j_pos:
            tp += 1   # Cả người và judge đều bắt đúng lỗi (FAIL)
        elif not h_pos and j_pos:
            fp += 1   # Người bảo đạt (PASS) nhưng judge báo lỗi (báo nhầm / false alarm)
        elif h_pos and not j_pos:
            fn += 1   # Người bảo lỗi (FAIL) nhưng judge cho qua (bỏ sót lỗi)
        else:
            tn += 1   # Cả hai đều đồng ý đạt (PASS)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    """Precision = TP/(TP+FP) và Recall = TP/(TP+FN) với lớp dương là FAIL."""
    cm = confusion(human, judge)
    tp, fp, fn = cm["tp"], cm["fp"], cm["fn"]
    # Trả về 0.0 khi mẫu số bằng 0 để tránh ZeroDivisionError lúc judge không dự đoán/không có nhãn FAIL
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return precision, recall


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    n = len(human)
    if n == 0:
        raise ValueError("Cannot compute Cohen's kappa on empty sequence")
    cm = confusion(human, judge)
    tp, fp, fn, tn = cm["tp"], cm["fp"], cm["fn"], cm["tn"]
    # p_o: tỉ lệ đồng thuận quan sát được (observed agreement)
    p_o = (tp + tn) / n
    # p_e: tỉ lệ đồng thuận ngẫu nhiên nếu người và judge đoán độc lập theo biên phân phối
    human_pos = tp + fn
    human_neg = fp + tn
    judge_pos = tp + fp
    judge_neg = fn + tn
    p_e = (human_pos * judge_pos + human_neg * judge_neg) / (n * n)
    # Khi p_e == 1 (ví dụ cả hai luôn trả cùng 1 nhãn hằng số), mẫu số = 0 -> vô định -> phải báo lỗi
    if math.isclose(p_e, 1.0, abs_tol=1e-12):
        raise ValueError("Cohen's kappa is undefined when p_e == 1 (no label variance)")
    return (p_o - p_e) / (1.0 - p_e)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    # Công thức Rogan-Gladen hiệu chỉnh tỉ lệ lỗi quan sát (p_obs) theo độ nhạy (recall) và độ đặc hiệu (specificity):
    # p_true = (p_obs + spec - 1) / (sens + spec - 1)
    # Vì p_obs = p_true * sens + (1 - p_true) * (1 - spec)
    denom = sensitivity + specificity - 1.0
    if math.isclose(denom, 0.0, abs_tol=1e-12):
        # Judge không hơn đoán ngẫu nhiên (Youden's J = 0); giữ giá trị quan sát đã clip trong [0, 1]
        return min(1.0, max(0.0, float(observed_rate)))
    corrected = (float(observed_rate) + float(specificity) - 1.0) / denom
    return min(1.0, max(0.0, corrected))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    if len(a) != len(b) or len(a) == 0:
        raise ValueError("a and b must be non-empty sequences of equal length")
    a_arr = np.asarray(a, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    # Nếu mọi item của PR và baseline giống hệt nhau thì hiệu và CI đều bằng 0
    if np.array_equal(a_arr, b_arr):
        return (0.0, 0.0, 0.0)
    delta = float(np.mean(a_arr - b_arr))
    # Paired bootstrap lấy mẫu lại theo từng CẶP (a[i], b[i]) cùng item để triệt tiêu nhiễu giữa các item
    res = bootstrap(
        (a_arr, b_arr),
        lambda x, y: np.mean(x - y),
        paired=True,
        n_resamples=n_resamples,
        confidence_level=confidence,
        method="percentile",
        rng=np.random.default_rng(rng),
    )
    return (delta, float(res.confidence_interval.low), float(res.confidence_interval.high))


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    if n <= 0 or k <= 0 or k > n or c < 0 or c > n:
        raise ValueError(f"Invalid (n={n}, c={c}, k={k}): require 0 <= c <= n and 1 <= k <= n")
    # Nếu số lần fail (n - c) ít hơn k thì rút k lần bất kỳ chắc chắn có ít nhất 1 lần pass
    if n - c < k:
        return 1.0
    # Xác suất cả k lần rút đều rơi vào nhóm fail là C(n-c, k) / C(n, k)
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    if n <= 0 or k <= 0 or k > n or c < 0 or c > n:
        raise ValueError(f"Invalid (n={n}, c={c}, k={k}): require 0 <= c <= n and 1 <= k <= n")
    # Nếu tổng số lần pass (c) ít hơn k thì không thể nào chọn được k lần đều pass
    if c < k:
        return 0.0
    # Xác suất cả k lần rút (không hoàn lại) đều nằm trong c lần pass
    return math.comb(c, k) / math.comb(n, k)
