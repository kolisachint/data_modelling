#!/usr/bin/env python3
"""
create_macro_workbook.py
Creates input/sample_data_model.xlsm with three embedded VBA macros:
  1. GenerateMermaidDiagram    – erDiagram → Mermaid_Output sheet
  2. GenerateTerraformBQSchema – Terraform HCL → Terraform_Output sheet
  3. GenerateDbtModel          – transformations.yml + SQL → DBT_Output sheet

Usage:
    python scripts/create_macro_workbook.py
"""
from __future__ import annotations

import math
import struct
import zipfile
import io
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# TASK 1 – MS-OVBA §2.4.1  LZ compression / decompression
# ─────────────────────────────────────────────────────────────────────────────

def _copytoken_help(pos: int):
    """Return (length_mask, offset_mask, bit_count, max_length) for chunk position."""
    temp = max(pos - 1, 0)
    bit_count = 4
    while temp >= 16:
        temp >>= 1
        bit_count += 1
    length_mask = (1 << (16 - bit_count)) - 1
    offset_mask = length_mask ^ 0xFFFF
    max_length  = length_mask + 3
    return length_mask, offset_mask, bit_count, max_length


def _compress_chunk(chunk: bytes) -> bytes:
    """Compress one decompressed chunk (≤ 4096 bytes) → raw compressed bytes."""
    out = bytearray()
    pos = 0
    n   = len(chunk)

    while pos < n:
        flag_pos = len(out)
        out.append(0)          # placeholder flag byte
        flag = 0

        for bit in range(8):
            if pos >= n:
                break

            length_mask, offset_mask, bit_count, max_len = _copytoken_help(pos)
            window_start = max(0, pos - (1 << bit_count))

            best_len    = 0
            best_offset = 0

            for j in range(window_start, pos):
                ml = 0
                while (pos + ml < n
                       and ml < max_len
                       and chunk[j + ml] == chunk[pos + ml]):
                    ml += 1
                if ml > best_len:
                    best_len    = ml
                    best_offset = pos - j

            if best_len >= 3:
                length_bits = 16 - bit_count
                token = ((best_offset - 1) << length_bits) | (best_len - 3)
                out.extend(struct.pack('<H', token))
                flag |= (1 << bit)
                pos  += best_len
            else:
                out.append(chunk[pos])
                pos += 1

        out[flag_pos] = flag

    return bytes(out)


def vba_compress(data: bytes) -> bytes:
    """MS-OVBA compress.  Returns bytes starting with signature 0x01."""
    result = bytearray([0x01])   # SignatureByte
    i = 0
    if not data:
        # Empty input: one compressed chunk with header indicating 0-byte payload
        # Use a raw (uncompressed) chunk header with 0 size isn't valid either;
        # emit one compressed chunk for an empty decompressed chunk.
        raw = _compress_chunk(b'')
        raw = raw if raw else b'\x00'     # at least one byte
        header_val = (0b011 << 13) | (1 << 12) | max(0, len(raw) - 3)
        result.extend(struct.pack('<H', header_val))
        result.extend(raw)
        return bytes(result)

    while i < len(data):
        chunk     = data[i: i + 4096]
        i        += 4096
        raw       = _compress_chunk(chunk)
        # Ensure at least 3 bytes (header uses size-3 encoding)
        while len(raw) < 3:
            raw += b'\x00'
        header_val = (0b011 << 13) | (1 << 12) | (len(raw) - 3)
        result.extend(struct.pack('<H', header_val))
        result.extend(raw)

    return bytes(result)


def vba_decompress(data: bytes) -> bytes:
    """MS-OVBA decompress (used for round-trip testing)."""
    if not data or data[0] != 0x01:
        raise ValueError("Missing signature byte 0x01")
    out = bytearray()
    i   = 1
    while i < len(data):
        if i + 1 >= len(data):
            break
        header = struct.unpack_from('<H', data, i)[0]
        i += 2
        compressed_size = (header & 0x0FFF) + 3
        is_compressed   = bool((header >> 12) & 1)
        chunk_end       = i + compressed_size

        if not is_compressed:
            out.extend(data[i: i + 4096])
            i = chunk_end
            continue

        chunk_start = len(out)
        while i < chunk_end and (len(out) - chunk_start) < 4096:
            if i >= len(data):
                break
            flag = data[i]; i += 1
            for bit in range(8):
                if i >= chunk_end or i >= len(data):
                    break
                if (len(out) - chunk_start) >= 4096:
                    break
                if flag & (1 << bit):
                    if i + 1 >= len(data):
                        break
                    token = struct.unpack_from('<H', data, i)[0]; i += 2
                    decompressed_so_far = len(out) - chunk_start
                    _, _, bit_count, _ = _copytoken_help(decompressed_so_far)
                    length_mask  = (1 << (16 - bit_count)) - 1
                    length       = (token & length_mask) + 3
                    offset       = (token >> (16 - bit_count)) + 1
                    copy_from    = len(out) - offset
                    for k in range(length):
                        out.append(out[copy_from + k])
                else:
                    out.append(data[i]); i += 1
    return bytes(out)


# ─────────────────────────────────────────────────────────────────────────────
# Self-test for Task 1 (run when executed directly)
# ─────────────────────────────────────────────────────────────────────────────

def _task1_selftest():
    cases = [
        b"Hello World Hello World Hello",
        b"AAAAAAAAAAAAAAAAAAAAA",
        b"The quick brown fox jumps over the lazy dog" * 10,
        b"\x00" * 4096,
        b"abc",
    ]
    for original in cases:
        compressed   = vba_compress(original)
        decompressed = vba_decompress(compressed)
        assert decompressed == original, (
            f"Round-trip failed for {original[:20]!r}…\n"
            f"  compressed len={len(compressed)}, decompressed len={len(decompressed)}"
        )
    # Check that repetitive data compresses
    rep = b"Hello World Hello World Hello"
    assert len(vba_compress(rep)) < len(rep), "Expected compression to reduce size"
    print("TASK 1 PASS — vba_compress/vba_decompress round-trip OK")


if __name__ == "__main__":
    _task1_selftest()
