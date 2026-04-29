from summarizer.chunker import chunk, estimate_tokens

def test_estimate_tokens():
    assert estimate_tokens("ab") == 1       # 2 // 2 = 1
    assert estimate_tokens("abcdef") == 3   # 6 // 2 = 3
    assert estimate_tokens("") == 1         # max(1, 0)

def test_single_chunk_when_fits():
    rows = ["hello", "world", "foo"]
    result = chunk(rows, token_budget=1000)
    assert result == [["hello", "world", "foo"]]

def test_splits_on_budget():
    rows = ["a" * 20, "b" * 20, "c" * 20]  # 20 // 2 = 10 tok each
    result = chunk(rows, token_budget=15)   # fits 1 per chunk
    assert len(result) == 3
    assert result[0] == ["a" * 20]
    assert result[1] == ["b" * 20]
    assert result[2] == ["c" * 20]

def test_empty_rows_returns_empty():
    assert chunk([], token_budget=1000) == []

def test_single_large_row_is_own_chunk():
    big = "x" * 10000
    result = chunk([big], token_budget=10)
    assert result == [[big]]
