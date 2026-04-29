from summarizer.chunker import chunk, estimate_tokens

def test_estimate_tokens():
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcdef") == 2
    assert estimate_tokens("") == 1

def test_single_chunk_when_fits():
    rows = ["hello", "world", "foo"]
    result = chunk(rows, token_budget=1000)
    assert result == [["hello", "world", "foo"]]

def test_splits_on_budget():
    rows = ["a" * 33, "b" * 33, "c" * 33]
    result = chunk(rows, token_budget=20)
    assert len(result) == 3
    assert result[0] == ["a" * 33]
    assert result[1] == ["b" * 33]
    assert result[2] == ["c" * 33]

def test_empty_rows_returns_empty():
    assert chunk([], token_budget=1000) == []

def test_single_large_row_is_own_chunk():
    big = "x" * 10000
    result = chunk([big], token_budget=10)
    assert result == [[big]]
