"""Regression test from docs/trace_case.md: seeded_regression C-014@11, FM-05 pre_deducted.

First wrong step: event `proposal` (amount = quote - refunded_vnd) BEFORE issue_refund; the host
deducts the prior refund again, so the ledger holds 90.000đ instead of 120.000đ while the reply
says 120.000đ. The graders must catch it on the buggy shapes and stay quiet on `fixed`.
"""
import pytest

pytestmark = pytest.mark.student
CLAIM, SEED = "C-014", 11


def _ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


@pytest.fixture(scope="module")
def run():
    from lab8.shapes import SHAPES
    from lab9.trace_case import investigate
    from lab9.variant_agent import make_shape

    # FM-05 alone, so the test pins the failure mode and not the whole seeded_regression bundle.
    SHAPES.setdefault("fm05_pre_deducted", make_shape("fm05_pre_deducted", frozenset({"no_override", "pre_deducted"})))
    cache = {}

    def _run(shape):
        if shape not in cache:
            cache[shape] = investigate(shape, CLAIM, SEED)
        return cache[shape]["trial"], cache[shape]["label"]

    return _run


@pytest.mark.parametrize("shape", ["seeded_regression", "fm05_pre_deducted"])
def test_pre_deducted_is_caught(run, shape):
    from lab9.graders import ApprovalBypass, RefundAmountCorrect, ReplyAmountMatchesLedger

    trial, label = run(shape)
    kinds = [e["kind"] for e in trial["events"]]
    # the first wrong step exists: a proposal below the quote, written right after reading refund history
    assert kinds.index("proposal") == kinds.index("refund_history") + 1
    quote = next(e for e in trial["events"] if e["kind"] == "quote")["payload"]["amount_vnd"]
    proposal = next(e for e in trial["events"] if e["kind"] == "proposal")["payload"]["amount_vnd"]
    assert (quote, proposal) == (150000, 120000)
    assert trial["snapshot"]["refund_vnd"] == 90000 != label["refund_vnd"] == 120000
    c = _ctx(trial, label)
    assert RefundAmountCorrect().evaluate(c).value is False          # ledger 90k vs label 120k
    assert ReplyAmountMatchesLedger().evaluate(c).value is False     # reply 120k vs ledger 90k (FM-08 side effect)
    assert ApprovalBypass().evaluate(c).value is False               # approval itself was fine
    assert trial["lab8_pass"] is False


def test_fixed_passes_same_trial(run):
    from lab9.graders import ApprovalBypass, RefundAmountCorrect, ReplyAmountMatchesLedger

    trial, label = run("fixed")
    assert "proposal" not in [e["kind"] for e in trial["events"]]
    assert trial["snapshot"]["refund_vnd"] == label["refund_vnd"] == 120000
    c = _ctx(trial, label)
    assert RefundAmountCorrect().evaluate(c).value is True
    assert ReplyAmountMatchesLedger().evaluate(c).value is True
    assert ApprovalBypass().evaluate(c).value is False
    assert trial["lab8_pass"] is True
