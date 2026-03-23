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
# TASK 2 – Minimal OLE2 Compound File Binary (CFB) builder
# ─────────────────────────────────────────────────────────────────────────────
# Layout (512-byte sectors, version 3, no mini-stream):
#   Header  (512 bytes, offset 0 — not a numbered sector)
#   Sector 0  : FAT
#   Sectors 1…N_dir : Directory entries (128 bytes each, 4 per sector)
#   Sectors N_dir+1… : stream data (each stream padded to sector boundary)
#
# Supported hierarchy: root-level streams AND one "VBA/" sub-storage.
# All streams (even small ones) use the regular FAT — no mini-stream.

_ENDOFCHAIN = 0xFFFFFFFE
_FREESECT   = 0xFFFFFFFF
_FATSECT    = 0xFFFFFFFD

# CLSID for the VBA storage entry  (EA7BAE70-FB3B-11CD-A903-00AA00510EA3)
_VBA_STORAGE_CLSID = bytes([
    0x70, 0xAE, 0x7B, 0xEA, 0x3B, 0xFB, 0xCD, 0x11,
    0xA9, 0x03, 0x00, 0xAA, 0x00, 0x51, 0x0E, 0xA3,
])


def _dir_entry(name: str, etype: int, color: int,
               left: int, right: int, child: int,
               clsid: bytes, first_sector: int, size: int) -> bytes:
    """Pack one 128-byte OLE2 directory entry."""
    enc  = name.encode('utf-16-le') if name else b''
    nlen = len(enc) + 2 if name else 0          # includes null terminator
    enc  = (enc + b'\x00' * 64)[:64]            # pad / truncate to 64 bytes
    e = bytearray()
    e += enc                                     # 64 – DirectoryEntryName
    e += struct.pack('<H', nlen)                 #  2 – NameLength
    e += struct.pack('<B', etype)                #  1 – ObjectType
    e += struct.pack('<B', color)                #  1 – ColorFlag (1=black)
    e += struct.pack('<I', left)                 #  4 – LeftSiblingID
    e += struct.pack('<I', right)                #  4 – RightSiblingID
    e += struct.pack('<I', child)                #  4 – ChildID
    e += clsid                                   # 16 – CLSID
    e += struct.pack('<I', 0)                    #  4 – StateBits
    e += struct.pack('<Q', 0)                    #  8 – CreationTime
    e += struct.pack('<Q', 0)                    #  8 – ModifiedTime
    e += struct.pack('<I', first_sector)         #  4 – StartingSectorLocation
    e += struct.pack('<I', size)                 #  4 – SizeLow
    e += struct.pack('<I', 0)                    #  4 – SizeHigh
    assert len(e) == 128
    return bytes(e)


def build_ole2(stream_map: dict) -> bytes:
    """Build a minimal OLE2 CFB file.

    stream_map keys:
        'StreamName'        – root-level stream
        'VBA/StreamName'    – stream inside the 'VBA' sub-storage
    Returns the complete binary content of the compound file.
    """
    SECTOR = 512

    # ── Separate root-level from VBA/ streams ────────────────────────────────
    vba_streams  = {}   # name → bytes  (inside VBA storage)
    root_streams = {}   # name → bytes  (root-level)
    for key, val in stream_map.items():
        if key.startswith('VBA/'):
            vba_streams[key[4:]] = val
        else:
            root_streams[key] = val

    # ── Directory entry plan ─────────────────────────────────────────────────
    # Entry 0 : Root Entry
    # Entry 1 : VBA  (storage)
    # Entry 2…2+|vba|-1  : VBA stream entries  (in insertion order)
    # Entry 2+|vba|…     : root-level stream entries
    vba_names  = list(vba_streams.keys())
    root_names = list(root_streams.keys())
    n_entries  = 1 + 1 + len(vba_names) + len(root_names)
    n_dir_sectors = math.ceil(n_entries / 4)

    # ── Assign sector numbers to streams ─────────────────────────────────────
    # Sector 0 = FAT, sectors 1…n_dir_sectors = directory
    first_data_sector = 1 + n_dir_sectors

    def _sectors_for(data: bytes):
        padded = data + b'\x00' * ((-len(data)) % SECTOR)
        return padded, math.ceil(max(len(data), 1) / SECTOR)

    assignments = {}   # stream_key → (first_sector, raw_size, padded_bytes)
    next_sec = first_data_sector
    for name in vba_names:
        padded, n = _sectors_for(vba_streams[name])
        assignments['VBA/' + name] = (next_sec, len(vba_streams[name]), padded)
        next_sec += n
    for name in root_names:
        padded, n = _sectors_for(root_streams[name])
        assignments[name] = (next_sec, len(root_streams[name]), padded)
        next_sec += n

    total_sectors = next_sec   # sector 0 is FAT, so total file sectors = next_sec

    # ── Build FAT ─────────────────────────────────────────────────────────────
    fat = [_FREESECT] * total_sectors
    fat[0] = _FATSECT                                  # sector 0 = FAT itself
    # Directory chain
    for s in range(1, 1 + n_dir_sectors):
        fat[s] = s + 1 if s < n_dir_sectors else _ENDOFCHAIN
    # Stream chains
    def _chain(first, n_secs):
        for k in range(n_secs):
            fat[first + k] = first + k + 1 if k < n_secs - 1 else _ENDOFCHAIN

    for name in vba_names:
        fs, raw_size, padded = assignments['VBA/' + name]
        _chain(fs, len(padded) // SECTOR)
    for name in root_names:
        fs, raw_size, padded = assignments[name]
        _chain(fs, len(padded) // SECTOR)

    # ── Build directory entries ───────────────────────────────────────────────
    NONE = _FREESECT

    # VBA storage child tree: vba streams chained right-only
    # vba_names[0] is root of VBA's RB-tree; each points right to next
    def _vba_entry_idx(i):   return 2 + i
    def _root_entry_idx(i):  return 2 + len(vba_names) + i

    # Root-level sibling tree: VBA storage is root; root streams hang left/right
    # Simple right-chain: VBA → root_streams[0] → root_streams[1] → …
    vba_child = _vba_entry_idx(0) if vba_names else NONE
    # VBA storage right sibling = first root stream entry
    vba_right = _root_entry_idx(0) if root_names else NONE

    root_entry = _dir_entry(
        'Root Entry', 5, 1, NONE, NONE, 1,   # child=1 (VBA storage)
        b'\x00' * 16, _ENDOFCHAIN, 0,
    )
    vba_storage = _dir_entry(
        'VBA', 1, 1, NONE, vba_right, vba_child,
        _VBA_STORAGE_CLSID, _ENDOFCHAIN, 0,
    )

    entries = [root_entry, vba_storage]

    for i, name in enumerate(vba_names):
        fs, raw_size, _ = assignments['VBA/' + name]
        right = _vba_entry_idx(i + 1) if i + 1 < len(vba_names) else NONE
        entries.append(_dir_entry(
            name, 2, 1, NONE, right, NONE,
            b'\x00' * 16, fs, raw_size,
        ))

    for i, name in enumerate(root_names):
        fs, raw_size, _ = assignments[name]
        right = _root_entry_idx(i + 1) if i + 1 < len(root_names) else NONE
        entries.append(_dir_entry(
            name, 2, 1, NONE, right, NONE,
            b'\x00' * 16, fs, raw_size,
        ))

    # Pad to full directory sectors
    empty = _dir_entry('', 0, 1, NONE, NONE, NONE, b'\x00' * 16, _ENDOFCHAIN, 0)
    while len(entries) % 4:
        entries.append(empty)

    # ── Build OLE2 header (512 bytes) ─────────────────────────────────────────
    hdr = bytearray()
    hdr += b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'  # magic
    hdr += b'\x00' * 16                            # CLSID
    hdr += struct.pack('<H', 0x003E)               # minor version
    hdr += struct.pack('<H', 0x0003)               # major version 3
    hdr += struct.pack('<H', 0xFFFE)               # byte order LE
    hdr += struct.pack('<H', 9)                    # sector size = 2^9 = 512
    hdr += struct.pack('<H', 6)                    # mini sector size = 2^6
    hdr += b'\x00' * 6                             # reserved
    hdr += struct.pack('<I', 0)                    # dir sectors (0 for v3)
    hdr += struct.pack('<I', 1)                    # FAT sectors count
    hdr += struct.pack('<I', 1)                    # first dir sector = 1
    hdr += struct.pack('<I', 0)                    # transaction sig
    hdr += struct.pack('<I', 4096)                 # mini stream cutoff
    hdr += struct.pack('<I', _FREESECT)            # first mini FAT sector
    hdr += struct.pack('<I', 0)                    # mini FAT sectors
    hdr += struct.pack('<I', _FREESECT)            # first DIFAT sector
    hdr += struct.pack('<I', 0)                    # DIFAT sectors
    hdr += struct.pack('<I', 0)                    # DIFAT[0] = sector 0 (FAT)
    hdr += struct.pack('<I', _FREESECT) * 108      # DIFAT[1..108] unused
    assert len(hdr) == 512

    # ── Build FAT sector (sector 0) ───────────────────────────────────────────
    fat_sector = bytearray()
    for f in fat:
        fat_sector += struct.pack('<I', f)
    # Pad to 512
    fat_sector += struct.pack('<I', _FREESECT) * (128 - len(fat))
    fat_sector = bytes(fat_sector[:512])

    # ── Assemble file ─────────────────────────────────────────────────────────
    out = bytearray()
    out += hdr
    out += fat_sector
    out += b''.join(entries)                       # directory sectors
    for name in vba_names:
        out += assignments['VBA/' + name][2]       # padded stream data
    for name in root_names:
        out += assignments[name][2]

    assert len(out) % 512 == 0
    return bytes(out)


# ─────────────────────────────────────────────────────────────────────────────
# Self-test for Task 2
# ─────────────────────────────────────────────────────────────────────────────

def _task2_selftest():
    payload = b'\xCC\x61\xFF\xFF' + b'\x00' * 12
    data = build_ole2({'VBA/_VBA_PROJECT': payload})

    # 1. Magic bytes
    assert data[:8] == b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1', "Bad magic"
    # 2. Sector-aligned
    assert len(data) % 512 == 0, f"Not sector-aligned: {len(data)}"
    # 3. FAT sector 0 entry = FATSECT marker
    fat0 = struct.unpack_from('<I', data, 512)[0]
    assert fat0 == _FATSECT, f"FAT[0] should be FATSECT, got {fat0:#010x}"
    # 4. Root entry name = "Root Entry" in UTF-16LE
    #    First dir sector is sector 1 → file offset 512 + 1*512 = 1024
    first_dir_sector = struct.unpack_from('<I', data, 48)[0]
    dir_offset = 512 + first_dir_sector * 512
    root_name_raw = data[dir_offset: dir_offset + 22]
    assert b'R\x00o\x00o\x00t' in root_name_raw, "Root entry name not found"
    # 5. Payload round-trip: locate _VBA_PROJECT stream
    #    Entry 2 (offset dir_offset + 2*128) should be _VBA_PROJECT
    e2_off   = dir_offset + 2 * 128
    e2_sec   = struct.unpack_from('<I', data, e2_off + 116)[0]
    e2_size  = struct.unpack_from('<I', data, e2_off + 120)[0]
    data_off = 512 + e2_sec * 512
    recovered = data[data_off: data_off + e2_size]
    assert recovered == payload, f"Payload mismatch: {recovered!r} vs {payload!r}"

    print("TASK 2 PASS — OLE2 builder: magic, alignment, FAT, root entry, payload round-trip OK")


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
    _task2_selftest()
