"""The known-answer test's cases and scoring (M7d S2, docs/erd/face-tree.md "Known-answer
test"): pure, scored with `FakeClassifier`."""

from dataclasses import fields
from decimal import Decimal

import pytest

from bedrock.classify import evaluate, questions
from bedrock.classify.evaluate import Band, Case, Score
from bedrock.classify.fake import FakeClassifier
from bedrock.classify.types import Candidate, LineAnswer, Usage
from bedrock.statements.structure import FaceLines
from tests.classify_data import question
from tests.engine_data import Row, facts, mappings
from tests.test_classify_questions import FACTS, ITEMS, LINES, MAPS
from tests.test_projection import Y23, at, line, lines_frame

VERDICTS = {("ext", "Memo"): (), ("ext", "Fees"): ("cogs",)}
OTHER_LINES = frozenset({("ext", "Tools")})


def face(rows: list[Row] = LINES, fact_rows: list[Row] = FACTS, maps: object = MAPS) -> FaceLines:
    return FaceLines(lines_frame(rows), facts(fact_rows), maps, VERDICTS, OTHER_LINES)  # type: ignore[arg-type]


def expected(found: list[Case]) -> dict[str, tuple[str, ...]]:
    return {c.question.key: c.expected for c in found}


def test_a_mapped_leaf_with_one_code_expects_that_code() -> None:
    found = expected(evaluate.cases(face(), ITEMS))

    assert found["BS|us-gaap|CashAndCashEquivalents"] == ("cash",)
    assert found["IS|us-gaap|Revenues"] == ("revenue",)


def test_an_other_line_and_a_verdict_without_a_code_expect_none() -> None:
    found = expected(evaluate.cases(face(), ITEMS))

    assert found["BS|ext|Tools"] == ()  # under `other_lines`
    assert found["BS|ext|Memo"] == ()  # a triage verdict that names no code


def test_what_has_no_known_answer_is_not_a_case() -> None:
    found = expected(evaluate.cases(face(), ITEMS))

    assert set(found) == {
        "IS|us-gaap|Revenues",
        "BS|us-gaap|CashAndCashEquivalents",
        "BS|ext|Tools",
        "BS|ext|Memo",
    }
    # not: totals (AssetsCurrent, Assets, PropertyPlantAndEquipmentNet has a child), open lines
    # (Widgets, Gone), a verdict that names a code (Fees), a line with no amount (Zero)


def test_a_line_mapped_to_two_rows_is_not_a_case() -> None:
    maps = mappings(
        *[(r.canonical_code, r.concept, 0) for r in MAPS.itertuples()],
        ("inventory", "CashAndCashEquivalents", 0),
    )

    assert "BS|us-gaap|CashAndCashEquivalents" not in expected(
        evaluate.cases(face(maps=maps), ITEMS)
    )


def test_a_line_whose_row_is_not_among_its_candidates_is_not_a_case() -> None:
    # A leaf mapped to a parent row (total_current_assets) could never be answered right
    rows = [*LINES, line("ext:Lump", "Assets")]
    maps = mappings(
        *[(r.canonical_code, r.concept, 0) for r in MAPS.itertuples()],
        ("total_current_assets", "ext:Lump", 1),
    )

    found = expected(evaluate.cases(face(rows, [*FACTS, at("ext:Lump", Y23, 1)], maps), ITEMS))

    assert "BS|ext|Lump" not in found


def test_the_question_hides_the_answer_and_is_built_as_for_an_open_line() -> None:
    (cash,) = [
        c for c in evaluate.cases(face(), ITEMS) if c.question.concept == "CashAndCashEquivalents"
    ]

    assert {f.name for f in fields(cash.question)} == {f.name for f in fields(question())}
    assert cash.question.candidates == questions.candidates(ITEMS, "BS", "total_current_assets")
    assert cash.question.candidates == (
        Candidate("cash", "Cash"),
        Candidate("inventory", "Inventory"),
    )
    assert cash.question.sibling_labels == ("Label of Widgets", "Label of Zero")


def test_cases_are_distinct_and_in_question_order() -> None:
    keys = [c.question.key for c in evaluate.cases(face(), ITEMS)]

    assert keys == [
        "IS|us-gaap|Revenues",
        "BS|us-gaap|CashAndCashEquivalents",
        "BS|ext|Tools",
        "BS|ext|Memo",
    ]
    assert evaluate.cases(face([], []), ITEMS) == []


def case(concept: str, expected_codes: tuple[str, ...]) -> Case:
    return Case(question(concept), expected_codes)


def test_ask_sends_batches_of_the_classifiers_size_and_pairs_the_answers() -> None:
    asked = [case("A", ("cash",)), case("B", ()), case("C", ("inventory",))]
    fake = FakeClassifier(
        {"BS|ext|A": (("cash",), 0.95), "BS|ext|C": (("cash",), 0.6)}, batch_size=2
    )

    outcomes, usage = evaluate.ask(fake, asked)

    assert [[q.key for q in batch] for batch in fake.calls] == [
        ["BS|ext|A", "BS|ext|B"],
        ["BS|ext|C"],
    ]
    assert outcomes == [
        (asked[0], LineAnswer("BS|ext|A", ("cash",), 0.95)),
        (asked[1], None),  # failed
        (asked[2], LineAnswer("BS|ext|C", ("cash",), 0.6)),
    ]
    assert usage == Usage(300, 30)


def test_ask_with_no_case_asks_nothing() -> None:
    fake = FakeClassifier({})

    assert evaluate.ask(fake, []) == ([], Usage(0, 0))
    assert fake.calls == []


def test_score_counts_answered_failed_and_correct() -> None:
    a, b, c, d = case("A", ("cash",)), case("B", ()), case("C", ("inventory",)), case("D", ())
    outcomes = [
        (a, LineAnswer("BS|ext|A", ("cash",), 0.95)),  # right, confident
        (b, LineAnswer("BS|ext|B", (), 0.75)),  # right: none
        (c, LineAnswer("BS|ext|C", ("cash",), 0.92)),  # wrong, confident
        (d, None),  # failed
    ]

    score = evaluate.score(outcomes)

    assert (score.cases, score.answered, score.failed, score.correct) == (4, 3, 1, 2)
    assert score.bands == (
        Band("below 0.5", 0, 0),
        Band("0.5–0.7", 0, 0),
        Band("0.7–0.9", 1, 1),
        Band("0.9 and above", 2, 1),
    )
    assert score.confident == Band("0.9 and above", 2, 1)


@pytest.mark.parametrize(
    ("confidence", "band"),
    [(0.0, 0), (0.49, 0), (0.5, 1), (0.69, 1), (0.7, 2), (0.89, 2), (0.9, 3), (1.0, 3)],
)
def test_a_band_holds_its_lower_bound(confidence: float, band: int) -> None:
    a = case("A", ("cash",))

    score = evaluate.score([(a, LineAnswer("BS|ext|A", ("cash",), confidence))])

    assert [b.answered for b in score.bands] == [int(n == band) for n in range(4)]


def test_a_combined_answer_is_wrong_for_a_single_row_and_code_order_does_not_matter() -> None:
    single = case("A", ("cash",))
    pair = Case(question("B"), ("cash", "inventory"))

    score = evaluate.score(
        [
            (single, LineAnswer("BS|ext|A", ("cash", "inventory"), 0.9)),
            (pair, LineAnswer("BS|ext|B", ("inventory", "cash"), 0.9)),
        ]
    )

    assert (score.answered, score.correct) == (2, 1)


def test_the_score_of_nothing_is_all_zero() -> None:
    score = evaluate.score([])

    assert score == Score(0, 0, 0, 0, tuple(Band(b.label, 0, 0) for b in score.bands))
    assert evaluate.ratio(score.correct, score.answered) is None


def test_ratio_is_a_decimal_share_or_none() -> None:
    assert evaluate.ratio(2, 3) == Decimal("0.6667")
    assert evaluate.ratio(0, 5) == Decimal("0.0000")
    assert evaluate.ratio(1, 0) is None


def test_the_counts_always_reconcile() -> None:
    import random

    rng = random.Random(7)
    for _ in range(50):
        outcomes = []
        for n in range(rng.randint(0, 30)):
            c = case(f"Q{n}", rng.choice([(), ("cash",), ("inventory",)]))
            answer = (
                None
                if rng.random() < 0.2
                else LineAnswer(c.question.key, rng.choice([(), ("cash",)]), rng.random())
            )
            outcomes.append((c, answer))

        score = evaluate.score(outcomes)

        assert score.cases == len(outcomes) == score.answered + score.failed
        assert sum(b.answered for b in score.bands) == score.answered
        assert sum(b.correct for b in score.bands) == score.correct <= score.answered
