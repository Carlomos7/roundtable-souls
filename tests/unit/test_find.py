"""Find / replace helpers behind the editor's find bar."""

from roundtable_souls import find

TEXT = "path = 'mod/Flora'\npath = 'mod/flora'\nenabled = true\n"


def test_find_all_literal_regex_and_case():
    assert find.find_all(TEXT, "flora") == [(12, 17), (31, 36)]
    assert find.find_all(TEXT, "flora", case=True) == [(31, 36)]
    assert find.find_all(TEXT, r"path = '([^']+)'", regex=True) == [(0, 18), (19, 37)]
    assert find.find_all(TEXT, "(", regex=True) == []  # invalid pattern, no crash
    assert find.find_all(TEXT, "(", regex=False) == []  # literal paren, just no hit
    assert find.find_all(TEXT, "", regex=True) == []
    assert find.find_all("aaa", "a*", regex=True) == [(0, 3)]  # empty matches are dropped


def test_next_match_wraps_both_ways():
    m = [(0, 2), (10, 12), (20, 22)]
    assert find.next_match(m, 0) == (0, 2) and find.next_match(m, 1) == (10, 12)
    assert find.next_match(m, 21) == (0, 2)  # wraps
    assert find.next_match(m, 10, backward=True) == (0, 2)
    assert find.next_match(m, 0, backward=True) == (20, 22)  # wraps backwards
    assert find.next_match([], 5) is None


def test_replace_all_literal_and_groups():
    new, n = find.replace_all(TEXT, "flora", "fauna")
    assert n == 2 and "Flora" not in new and new.count("fauna") == 2
    new, n = find.replace_all(TEXT, "flora", "fauna", case=True)
    assert n == 1 and "Flora" in new
    new, n = find.replace_all(TEXT, r"path = '([^']+)'", r"path = '\1/x'", regex=True)
    assert n == 2 and "mod/Flora/x" in new and "mod/flora/x" in new
    new, n = find.replace_all(TEXT, "flora", r"\1", regex=False)  # literal backslashes stay literal
    assert n == 2 and r"\1" in new
    assert find.replace_all(TEXT, "(flora)", r"\9", regex=True) == (TEXT, 0)  # bad group: nothing changes
    assert find.replace_all(TEXT, "", "x") == (TEXT, 0)


def test_replace_one_checks_the_span():
    assert find.replace_one(TEXT, (12, 17), "flora", "fauna") == "fauna"
    assert find.replace_one(TEXT, (12, 16), "flora", "fauna") is None  # not a whole match
    assert find.replace_one(TEXT, (0, 18), r"path = '([^']+)'", r"\1", regex=True) == "mod/Flora"
    assert find.replace_one(TEXT, (0, 18), r"path = '([^']+)'", r"\2", regex=True) is None
