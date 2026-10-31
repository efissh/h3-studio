#!/usr/bin/env python3
"""Print the header of a GGUF file (metadata + tensor table) without loading any weights.

    python3 tools/gguf_index.py model.gguf

Read-only; reads only the header, so it is fast even for 30 GB files. Useful to check tensor naming/dtypes before importing a file into H3cApp.
"""
import collections
import struct
import sys

SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
MAX_ITEMS = 5_000_000          # sanity limit against corrupt headers


def read(f, fmt):
    return struct.unpack(fmt, f.read(struct.calcsize(fmt)))


def read_str(f):
    (n,) = read(f, "<Q")
    if n > 1 << 24:
        raise ValueError("implausible string length: not a valid GGUF file")
    return f.read(n).decode("utf-8", "replace")


def read_value(f, vtype):
    if vtype in SCALARS:
        return read(f, SCALARS[vtype])[0]
    if vtype == 8:
        return read_str(f)
    if vtype == 9:
        (etype,) = read(f, "<I")
        (n,) = read(f, "<Q")
        if n > MAX_ITEMS:
            raise ValueError("implausible array length: not a valid GGUF file")
        items = [read_value(f, etype) for _ in range(n)]
        return items if n < 64 else f"<array of {n}>"
    raise ValueError(f"unknown GGUF value type {vtype}")


def parse(path):
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("not a GGUF file (bad magic)")
        version, n_tensors, n_kv = read(f, "<IQQ")
        if n_tensors > MAX_ITEMS or n_kv > MAX_ITEMS:
            raise ValueError("implausible header counts: not a valid GGUF file")
        kv = {}
        for _ in range(n_kv):
            key = read_str(f)
            (vtype,) = read(f, "<I")
            kv[key] = read_value(f, vtype)
        tensors = {}
        for _ in range(n_tensors):
            name = read_str(f)
            (ndim,) = read(f, "<I")
            dims = read(f, "<" + "Q" * ndim)
            (dtype,) = read(f, "<I")
            (offset,) = read(f, "<Q")
            tensors[name] = (dims, dtype, offset)
    return version, kv, tensors


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    try:
        version, kv, tensors = parse(sys.argv[1])
    except (ValueError, struct.error, OSError) as e:
        raise SystemExit(f"error: {e}")
    names = list(tensors)
    print(f"GGUF version {version}, {len(tensors)} tensors, {len(kv)} metadata keys")
    for k, v in kv.items():
        print(f"  {k} = {str(v)[:90]}")
    print("first tensors:", names[:6])
    print("last tensors: ", names[-4:])
    print("ggml dtypes (id: count):", dict(collections.Counter(d for _, d, _ in tensors.values())))


if __name__ == "__main__":
    main()
