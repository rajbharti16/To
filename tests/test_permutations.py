import pytest

from app.mail_engine import PermutationGenerator


def test_counts():
    g = PermutationGenerator("ab@gmail.com")
    assert g.total_permutations == 8   # 2^2 case * 2^1 dot


def test_all_unique_and_deliver():
    g = PermutationGenerator("ab@gmail.com")
    out = {g.get_permutation(i) for i in range(g.total_permutations)}
    assert len(out) == 8
    assert all(x.endswith("@gmail.com") for x in out)
    assert all(x.split("@")[0].replace(".", "").lower() == "ab" for x in out)


def test_non_gmail_no_dots():
    g = PermutationGenerator("ab@mail.ru")
    assert g.total_permutations == 4
    assert all("." not in x.split("@")[0] for x in (g.get_permutation(i) for i in range(4)))


def test_get_next_unused():
    g = PermutationGenerator("ab@gmail.com")
    first = g.get_next_unused([])
    assert g.get_next_unused([first]) != first


def test_out_of_range():
    g = PermutationGenerator("a@gmail.com")
    with pytest.raises(IndexError):
        g.get_permutation(99)