"""tools/gguf_index.py reads real headers and rejects garbage without crashing."""
import struct
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import gguf_index  # noqa: E402


def s(x: str) -> bytes:
    b = x.encode()
    return struct.pack("<Q", len(b)) + b


def make(tensors=2) -> Path:
    p = Path(tempfile.mkdtemp()) / "m.gguf"
    body = b"GGUF" + struct.pack("<IQQ", 3, tensors, 2)
    body += s("general.architecture") + struct.pack("<I", 8) + s("qwen3vl")
    body += s("h3c.text_layers") + struct.pack("<I", 4) + struct.pack("<I", 50)
    for i in range(tensors):
        body += s(f"blk.{i}.attn_q.weight") + struct.pack("<I", 2) + struct.pack("<QQ", 64, 32) + struct.pack("<I", 8) + struct.pack("<Q", i * 4096)
    p.write_bytes(body)
    return p


def test_parses_metadata_and_tensor_table():
    version, kv, tensors = gguf_index.parse(make())
    assert version == 3 and kv["general.architecture"] == "qwen3vl" and kv["h3c.text_layers"] == 50
    assert list(tensors) == ["blk.0.attn_q.weight", "blk.1.attn_q.weight"] and tensors["blk.1.attn_q.weight"] == ((64, 32), 8, 4096)


@pytest.mark.parametrize("blob", [b"", b"NOPE" + b"\0" * 64, b"GGUF" + struct.pack("<IQQ", 3, 10**12, 1), b"GGUF" + struct.pack("<IQQ", 3, 1, 1) + struct.pack("<Q", 1 << 40)])
def test_rejects_garbage_cleanly(blob):
    p = Path(tempfile.mkdtemp()) / "x.gguf"
    p.write_bytes(blob)
    with pytest.raises((ValueError, struct.error)):
        gguf_index.parse(p)
