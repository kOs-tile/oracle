from benchmark.false_actionable import build_cases, run_benchmark


def test_false_actionable_corpus_shape_is_stable():
    cases = build_cases()

    assert len(cases) == 18
    assert sum(case.expected_actionable for case in cases) == 7
    assert sum(not case.expected_actionable for case in cases) == 11


def test_false_actionable_benchmark_meets_v0_contract():
    result = run_benchmark()

    assert result["cases"] == 18
    assert result["policy_correct"] == 18
    assert result["policy_accuracy"] == 1.0
    assert result["unsafe_cases"] == 11
    assert result["false_actionable"] == 0
    assert result["false_actionable_rate"] == 0.0
    assert result["safe_cases"] == 7
    assert result["false_non_actionable"] == 0
    assert result["false_non_actionable_rate"] == 0.0
