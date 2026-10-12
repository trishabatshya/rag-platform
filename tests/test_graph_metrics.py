"""Hand-computed normalization, token multiplicity and title-recall cases."""

import pytest

from graphrag.metrics import exact_match, f1, normalize, supporting_recall


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (" The, CEDAR  Bay! ", "cedar bay"),
        ("An apple and a pear.", "apple and pear"),
        ("", ""),
        ("Theatre", "theatre"),
        ("red-blue", "redblue"),
    ],
)
def test_normalization(text, expected):
    assert normalize(text) == expected


@pytest.mark.parametrize(
    ("pred", "gold", "em", "score"),
    [
        ("The Cedar Bay", "cedar bay!", 1, 1),
        ("cedar", "cedar bay", 0, 2 / 3),
        ("red red blue", "red blue blue", 0, 2 / 3),
        ("x", "y", 0, 0),
        ("", "the", 1, 1),
        ("", "hello", 0, 0),
    ],
)
def test_answer_metrics(pred, gold, em, score):
    assert exact_match(pred, gold) == em
    assert f1(pred, gold) == pytest.approx(score)


def test_title_recall_deduplicates_and_ignores_distractors():
    assert supporting_recall(["A", "A", "D"], ["A", "B", "B"]) == 0.5
    assert supporting_recall([], ["A"]) == 0
    assert supporting_recall([], []) == 1
