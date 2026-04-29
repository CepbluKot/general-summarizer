import json
import tempfile
import os
import pytest
from summarizer.loader import load

def _write(content, suffix):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name

def test_load_json_array():
    data = [{"id": 1, "msg": "hello"}, {"id": 2, "msg": "world"}]
    path = _write(json.dumps(data), ".json")
    try:
        rows = load(path, "json")
        assert len(rows) == 2
        assert json.loads(rows[0]) == {"id": 1, "msg": "hello"}
        assert json.loads(rows[1]) == {"id": 2, "msg": "world"}
    finally:
        os.unlink(path)

def test_load_text():
    path = _write("line one\n\nline two\nline three\n", ".txt")
    try:
        rows = load(path, "text")
        assert rows == ["line one", "line two", "line three"]
    finally:
        os.unlink(path)

def test_load_json_raises_on_non_array():
    path = _write('{"key": "value"}', ".json")
    try:
        with pytest.raises(ValueError, match="JSON array"):
            load(path, "json")
    finally:
        os.unlink(path)

def test_load_unknown_format_raises():
    with pytest.raises(ValueError, match="format"):
        load("whatever.csv", "csv")
