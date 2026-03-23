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
# TASK 3 – VBA stream builders: dir, PROJECT, PROJECTwm
# ─────────────────────────────────────────────────────────────────────────────

def _rec(id_: int, data: bytes) -> bytes:
    """Encode one dir-stream record: WORD(id) + DWORD(size) + data."""
    return struct.pack('<HI', id_, len(data)) + data


def build_dir_stream_raw(module_names: list) -> bytes:
    """Build the *uncompressed* VBA dir stream for the given module names."""
    b = bytearray()
    b += _rec(0x0001, struct.pack('<I', 1))
    b += _rec(0x0002, struct.pack('<I', 0x0409))
    b += _rec(0x0014, struct.pack('<I', 0x0409))
    b += _rec(0x0003, struct.pack('<H', 1252))
    b += _rec(0x0004, b'VBAProject')
    b += _rec(0x0005, b'')
    b += _rec(0x0040, b'')
    b += _rec(0x0006, b'')
    b += _rec(0x003D, b'')
    b += _rec(0x0007, struct.pack('<I', 0))
    b += _rec(0x0008, struct.pack('<I', 0))
    b += struct.pack('<HI', 0x0009, 4)
    b += struct.pack('<I', 1361)
    b += struct.pack('<H', 5)
    b += _rec(0x000C, b'')
    b += _rec(0x003C, b'')
    b += _rec(0x000F, struct.pack('<H', len(module_names)))
    b += _rec(0x0013, struct.pack('<H', 0xFFFF))
    for name in module_names:
        nb = name.encode('windows-1252')
        nu = name.encode('utf-16-le')
        b += _rec(0x0019, nb)
        b += _rec(0x0031, nu)
        b += _rec(0x001A, nb)
        b += _rec(0x0032, nu)
        b += _rec(0x001C, b'')
        b += _rec(0x0048, b'')
        b += _rec(0x0031, struct.pack('<I', 0))
        b += _rec(0x001E, struct.pack('<I', 0))
        b += _rec(0x002C, struct.pack('<H', 0xFFFF))
        b += _rec(0x0021, b'')
        b += struct.pack('<HI', 0x002B, 0)
    b += struct.pack('<HI', 0x0010, 0)
    return bytes(b)


def build_project_stream(module_names: list) -> bytes:
    """Build the plaintext PROJECT stream."""
    lines = [
        'ID="{00000000-0000-0000-0000-000000000000}"',
        'Document=ThisWorkbook/&H00000000',
    ]
    for name in module_names:
        lines.append(f'Module={name}')
    lines += ['HelpContextID=0', 'VersionCompatible32="393222000"',
              'CMG=""', 'DPB=""', 'GC=""', '']
    return '\r\n'.join(lines).encode('windows-1252')


def build_projectwm_stream(module_names: list) -> bytes:
    """Build the PROJECTwm stream (MBCS ↔ UTF-16LE name pairs)."""
    b = bytearray()
    for name in module_names:
        b += name.encode('windows-1252') + b'\x00'
        b += name.encode('utf-16-le')    + b'\x00\x00'
    b += b'\x00'
    return bytes(b)


# ─────────────────────────────────────────────────────────────────────────────
# TASK 4 – VBA macro source strings (3 standard modules)
# Each string starts with the Attribute VB_Name line required by Excel.
# Line endings are \n here; encoded to CRLF (\r\n) when building streams.
# ─────────────────────────────────────────────────────────────────────────────

_MERMAID_SRC = '''\
Attribute VB_Name = "Module1"
Option Explicit

' GenerateMermaidDiagram
' Reads Tables and Columns sheets; writes Mermaid erDiagram to Mermaid_Output.
Sub GenerateMermaidDiagram()
    Dim wsTbl As Worksheet, wsCol As Worksheet, wsOut As Worksheet
    Dim lastT As Long, lastC As Long
    Dim i As Long, j As Long, outRow As Long
    Dim tblName As String, colName As String, colType As String
    Dim isPK As String, isFK As String, fkRef As String, descr As String
    Dim lbl As String, dotPos As Integer, toEnt As String

    Application.ScreenUpdating = False
    On Error Resume Next
    Set wsTbl = ThisWorkbook.Sheets("Tables")
    Set wsCol = ThisWorkbook.Sheets("Columns")
    On Error GoTo 0
    If wsTbl Is Nothing Or wsCol Is Nothing Then
        MsgBox "Sheets 'Tables' and/or 'Columns' not found.", vbExclamation
        GoTo Cleanup
    End If

    Application.DisplayAlerts = False
    On Error Resume Next: ThisWorkbook.Sheets("Mermaid_Output").Delete
    On Error GoTo 0
    Application.DisplayAlerts = True
    Set wsOut = ThisWorkbook.Sheets.Add(After:=ThisWorkbook.Sheets(ThisWorkbook.Sheets.Count))
    wsOut.Name = "Mermaid_Output"

    lastT = wsTbl.Cells(wsTbl.Rows.Count, 1).End(xlUp).Row
    lastC = wsCol.Cells(wsCol.Rows.Count, 1).End(xlUp).Row
    outRow = 1
    wsOut.Cells(outRow, 1).Value = "erDiagram"
    outRow = outRow + 1

    For i = 2 To lastT
        tblName = Trim(CStr(wsTbl.Cells(i, 1).Value))
        If tblName = "" Then GoTo NextEntity
        wsOut.Cells(outRow, 1).Value = "    " & tblName & " {"
        outRow = outRow + 1
        For j = 2 To lastC
            If Trim(CStr(wsCol.Cells(j, 1).Value)) = tblName Then
                colName = Trim(CStr(wsCol.Cells(j, 2).Value))
                colType = Trim(CStr(wsCol.Cells(j, 3).Value))
                isPK    = Trim(CStr(wsCol.Cells(j, 5).Value))
                isFK    = Trim(CStr(wsCol.Cells(j, 6).Value))
                descr   = Trim(CStr(wsCol.Cells(j, 8).Value))
                lbl = ""
                If UCase(isPK) = "YES" Then lbl = "PK "
                If UCase(isFK) = "YES" Then lbl = lbl & "FK "
                lbl = Trim(lbl & descr)
                If lbl <> "" Then
                    wsOut.Cells(outRow, 1).Value = "        " & colType & " " & colName & " " & Chr(34) & lbl & Chr(34)
                Else
                    wsOut.Cells(outRow, 1).Value = "        " & colType & " " & colName
                End If
                outRow = outRow + 1
            End If
        Next j
        wsOut.Cells(outRow, 1).Value = "    }"
        outRow = outRow + 1
NextEntity:
    Next i

    wsOut.Cells(outRow, 1).Value = ""
    outRow = outRow + 1

    For j = 2 To lastC
        If UCase(Trim(CStr(wsCol.Cells(j, 6).Value))) = "YES" Then
            fkRef   = Trim(CStr(wsCol.Cells(j, 7).Value))
            tblName = Trim(CStr(wsCol.Cells(j, 1).Value))
            colName = Trim(CStr(wsCol.Cells(j, 2).Value))
            If fkRef <> "" Then
                dotPos = InStr(fkRef, ".")
                If dotPos > 0 Then
                    toEnt = Left(fkRef, dotPos - 1)
                Else
                    toEnt = fkRef
                End If
                wsOut.Cells(outRow, 1).Value = "    " & tblName & " ||--o{ " & toEnt & " : " & Chr(34) & colName & " -> " & fkRef & Chr(34)
                outRow = outRow + 1
            End If
        End If
    Next j

    wsOut.Columns(1).AutoFit
    wsOut.Activate
    wsOut.Cells(1, 1).Select
    MsgBox "Mermaid erDiagram generated!" & Chr(10) & "See the Mermaid_Output sheet.", vbInformation, "Done"
Cleanup:
    Application.ScreenUpdating = True
End Sub
'''

_TERRAFORM_SRC = '''\
Attribute VB_Name = "Module2"
Option Explicit

' GenerateTerraformBQSchema
' Reads Tables and Columns sheets; writes Terraform HCL to Terraform_Output.
Sub GenerateTerraformBQSchema()
    Dim wsTbl As Worksheet, wsCol As Worksheet, wsOut As Worksheet
    Dim lastT As Long, lastC As Long
    Dim i As Long, j As Long, outRow As Long, colIdx As Long, colCount As Long
    Dim tblName As String, tblDesc As String, layer As String, tfName As String
    Dim colName As String, colType As String, nullable As String, isPK As String
    Dim descr As String, bizRule As String, bqType As String, mode As String
    Dim fullDesc As String, firstTS As String, pkCol As String, comma As String

    Application.ScreenUpdating = False
    On Error Resume Next
    Set wsTbl = ThisWorkbook.Sheets("Tables")
    Set wsCol = ThisWorkbook.Sheets("Columns")
    On Error GoTo 0
    If wsTbl Is Nothing Or wsCol Is Nothing Then
        MsgBox "Sheets 'Tables' and/or 'Columns' not found.", vbExclamation
        GoTo Cleanup
    End If

    Application.DisplayAlerts = False
    On Error Resume Next: ThisWorkbook.Sheets("Terraform_Output").Delete
    On Error GoTo 0
    Application.DisplayAlerts = True
    Set wsOut = ThisWorkbook.Sheets.Add(After:=ThisWorkbook.Sheets(ThisWorkbook.Sheets.Count))
    wsOut.Name = "Terraform_Output"

    lastT = wsTbl.Cells(wsTbl.Rows.Count, 1).End(xlUp).Row
    lastC = wsCol.Cells(wsCol.Rows.Count, 1).End(xlUp).Row
    outRow = 1

    For i = 2 To lastT
        tblName = Trim(CStr(wsTbl.Cells(i, 1).Value))
        If tblName = "" Then GoTo NextTFEntity
        tblDesc = Trim(CStr(wsTbl.Cells(i, 2).Value))
        layer   = Trim(CStr(wsTbl.Cells(i, 4).Value))
        If layer = "" Then layer = "mart"
        tfName  = LCase(tblName)
        firstTS = "": pkCol = ""
        colCount = 0
        For j = 2 To lastC
            If Trim(CStr(wsCol.Cells(j, 1).Value)) = tblName Then colCount = colCount + 1
        Next j

        wsOut.Cells(outRow, 1).Value = "resource " & Chr(34) & "google_bigquery_table" & Chr(34) & " " & Chr(34) & layer & "_" & tfName & Chr(34) & " {"
        outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "  dataset_id = google_bigquery_dataset." & layer & ".dataset_id"
        outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "  table_id   = " & Chr(34) & tfName & Chr(34)
        outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "  project     = var.project"
        outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "  description = " & Chr(34) & tblDesc & Chr(34)
        outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "  schema = jsonencode(["
        outRow = outRow + 1

        colIdx = 0
        For j = 2 To lastC
            If Trim(CStr(wsCol.Cells(j, 1).Value)) = tblName Then
                colName  = Trim(CStr(wsCol.Cells(j, 2).Value))
                colType  = UCase(Trim(CStr(wsCol.Cells(j, 3).Value)))
                nullable = Trim(CStr(wsCol.Cells(j, 4).Value))
                isPK     = Trim(CStr(wsCol.Cells(j, 5).Value))
                descr    = Trim(CStr(wsCol.Cells(j, 8).Value))
                bizRule  = Trim(CStr(wsCol.Cells(j, 9).Value))
                Select Case colType
                    Case "INT64", "INTEGER", "INT", "BIGINT": bqType = "INTEGER"
                    Case "FLOAT64", "FLOAT", "REAL":          bqType = "FLOAT"
                    Case "NUMERIC", "DECIMAL":                bqType = "NUMERIC"
                    Case "BOOL", "BOOLEAN":                   bqType = "BOOLEAN"
                    Case "DATE":                              bqType = "DATE"
                    Case "TIMESTAMP", "DATETIME":             bqType = "TIMESTAMP"
                    Case Else:                                bqType = "STRING"
                End Select
                If UCase(nullable) = "NO" Then mode = "REQUIRED" Else mode = "NULLABLE"
                If UCase(isPK) = "YES" And pkCol = "" Then pkCol = colName
                If bqType = "TIMESTAMP" And firstTS = "" Then firstTS = colName
                fullDesc = descr
                If bizRule <> "" Then fullDesc = fullDesc & " | " & bizRule
                colIdx = colIdx + 1
                If colIdx < colCount Then comma = "," Else comma = ""
                wsOut.Cells(outRow, 1).Value = "    { " & Chr(34) & "name" & Chr(34) & ": " & Chr(34) & colName & Chr(34) & ", " & Chr(34) & "type" & Chr(34) & ": " & Chr(34) & bqType & Chr(34) & ", " & Chr(34) & "mode" & Chr(34) & ": " & Chr(34) & mode & Chr(34) & ", " & Chr(34) & "description" & Chr(34) & ": " & Chr(34) & fullDesc & Chr(34) & " }" & comma
                outRow = outRow + 1
            End If
        Next j

        wsOut.Cells(outRow, 1).Value = "  ])"
        outRow = outRow + 1
        If firstTS <> "" Then
            wsOut.Cells(outRow, 1).Value = "  time_partitioning { type = " & Chr(34) & "DAY" & Chr(34) & " field = " & Chr(34) & firstTS & Chr(34) & " }"
            outRow = outRow + 1
        End If
        If pkCol <> "" Then
            wsOut.Cells(outRow, 1).Value = "  clustering = [" & Chr(34) & pkCol & Chr(34) & "]"
            outRow = outRow + 1
        End If
        wsOut.Cells(outRow, 1).Value = "  labels = { entity = " & Chr(34) & tfName & Chr(34) & ", layer = " & Chr(34) & layer & Chr(34) & ", managed_by = " & Chr(34) & "terraform" & Chr(34) & " }"
        outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "}"
        outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = ""
        outRow = outRow + 1
NextTFEntity:
    Next i

    wsOut.Columns(1).AutoFit
    wsOut.Activate
    wsOut.Cells(1, 1).Select
    MsgBox "Terraform BQ schema generated!" & Chr(10) & "See the Terraform_Output sheet.", vbInformation, "Done"
Cleanup:
    Application.ScreenUpdating = True
End Sub
'''

_DBT_SRC = '''\
Attribute VB_Name = "Module3"
Option Explicit

' GenerateDbtModel
' Reads Tables and Columns sheets; writes transformations.yml and
' dbt staging SQL stubs to DBT_Output.
Sub GenerateDbtModel()
    Dim wsTbl As Worksheet, wsCol As Worksheet, wsOut As Worksheet
    Dim lastT As Long, lastC As Long
    Dim i As Long, j As Long, outRow As Long
    Dim tblName As String, tblDesc As String, srcSys As String
    Dim colName As String, isPK As String, descr As String
    Dim srcLow As String, entLow As String, lastColName As String

    Application.ScreenUpdating = False
    On Error Resume Next
    Set wsTbl = ThisWorkbook.Sheets("Tables")
    Set wsCol = ThisWorkbook.Sheets("Columns")
    On Error GoTo 0
    If wsTbl Is Nothing Or wsCol Is Nothing Then
        MsgBox "Sheets 'Tables' and/or 'Columns' not found.", vbExclamation
        GoTo Cleanup
    End If

    Application.DisplayAlerts = False
    On Error Resume Next: ThisWorkbook.Sheets("DBT_Output").Delete
    On Error GoTo 0
    Application.DisplayAlerts = True
    Set wsOut = ThisWorkbook.Sheets.Add(After:=ThisWorkbook.Sheets(ThisWorkbook.Sheets.Count))
    wsOut.Name = "DBT_Output"

    lastT = wsTbl.Cells(wsTbl.Rows.Count, 1).End(xlUp).Row
    lastC = wsCol.Cells(wsCol.Rows.Count, 1).End(xlUp).Row
    outRow = 1

    ' -- PART A: transformations.yml ------------------------------------------
    wsOut.Cells(outRow, 1).Value = "# ===== PART A: transformations.yml =====": outRow = outRow + 1
    wsOut.Cells(outRow, 1).Value = "version: 2":                                outRow = outRow + 1
    wsOut.Cells(outRow, 1).Value = "transformations:":                          outRow = outRow + 1

    For i = 2 To lastT
        tblName = Trim(CStr(wsTbl.Cells(i, 1).Value))
        If tblName = "" Then GoTo NextYaml
        entLow = LCase(tblName)
        For j = 2 To lastC
            If Trim(CStr(wsCol.Cells(j, 1).Value)) = tblName Then
                colName = Trim(CStr(wsCol.Cells(j, 2).Value))
                isPK    = Trim(CStr(wsCol.Cells(j, 5).Value))
                descr   = Trim(CStr(wsCol.Cells(j, 8).Value))
                wsOut.Cells(outRow, 1).Value = "  - target_entity: " & entLow:   outRow = outRow + 1
                wsOut.Cells(outRow, 1).Value = "    target_column: " & colName:  outRow = outRow + 1
                wsOut.Cells(outRow, 1).Value = "    source_system: " & Chr(34) & Chr(34): outRow = outRow + 1
                wsOut.Cells(outRow, 1).Value = "    source_table:  " & Chr(34) & Chr(34): outRow = outRow + 1
                wsOut.Cells(outRow, 1).Value = "    source_column: " & colName:  outRow = outRow + 1
                wsOut.Cells(outRow, 1).Value = "    logic:         Direct":      outRow = outRow + 1
                wsOut.Cells(outRow, 1).Value = "    notes:         " & Chr(34) & descr & Chr(34): outRow = outRow + 1
                If UCase(isPK) = "YES" Then
                    wsOut.Cells(outRow, 1).Value = "    tested:        true"
                Else
                    wsOut.Cells(outRow, 1).Value = "    tested:        false"
                End If
                outRow = outRow + 1
            End If
        Next j
NextYaml:
    Next i

    outRow = outRow + 1

    ' -- PART B: dbt staging SQL -----------------------------------------------
    wsOut.Cells(outRow, 1).Value = "# ===== PART B: dbt Staging SQL Model Stubs =====": outRow = outRow + 1

    For i = 2 To lastT
        tblName = Trim(CStr(wsTbl.Cells(i, 1).Value))
        If tblName = "" Then GoTo NextSQL
        tblDesc = Trim(CStr(wsTbl.Cells(i, 2).Value))
        srcSys  = Trim(CStr(wsTbl.Cells(i, 3).Value))
        If srcSys = "" Then srcSys = "src"
        srcLow = LCase(srcSys): entLow = LCase(tblName)

        lastColName = ""
        For j = 2 To lastC
            If Trim(CStr(wsCol.Cells(j, 1).Value)) = tblName Then
                lastColName = Trim(CStr(wsCol.Cells(j, 2).Value))
            End If
        Next j

        wsOut.Cells(outRow, 1).Value = "-- stg_" & srcLow & "_" & entLow & ".sql": outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "-- " & tblDesc:                             outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "with source as (":                          outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "    select * from {{ source('" & srcLow & "', '" & entLow & "') }}": outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "),":                                        outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "renamed as (":                              outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "    select":                                outRow = outRow + 1
        For j = 2 To lastC
            If Trim(CStr(wsCol.Cells(j, 1).Value)) = tblName Then
                colName = Trim(CStr(wsCol.Cells(j, 2).Value))
                If colName = lastColName Then
                    wsOut.Cells(outRow, 1).Value = "        " & colName
                Else
                    wsOut.Cells(outRow, 1).Value = "        " & colName & ","
                End If
                outRow = outRow + 1
            End If
        Next j
        wsOut.Cells(outRow, 1).Value = "    from source":  outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = ")":                outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "select * from renamed": outRow = outRow + 1
        wsOut.Cells(outRow, 1).Value = "":                 outRow = outRow + 1
NextSQL:
    Next i

    wsOut.Columns(1).AutoFit
    wsOut.Activate
    wsOut.Cells(1, 1).Select
    MsgBox "dbt model generated!" & Chr(10) & "See the DBT_Output sheet." & Chr(10) & "Part A: transformations.yml" & Chr(10) & "Part B: staging SQL stubs", vbInformation, "Done"
Cleanup:
    Application.ScreenUpdating = True
End Sub
'''


# ─────────────────────────────────────────────────────────────────────────────
# Self-test for Task 3
# ─────────────────────────────────────────────────────────────────────────────

def _task3_selftest():
    names = ['Module1', 'Module2', 'Module3']
    raw = build_dir_stream_raw(names)
    assert raw[0:6] == b'\x01\x00\x04\x00\x00\x00', f"Bad PROJECTSYSKIND header: {raw[0:6]!r}"
    assert b'Module1' in raw
    assert b'Module3' in raw
    assert b'VBAProject' in raw
    proj = build_project_stream(names)
    assert b'Module=Module1' in proj
    assert b'Module=Module3' in proj
    assert b'VersionCompatible32' in proj
    pwm = build_projectwm_stream(names)
    assert b'Module1\x00' in pwm
    assert b'M\x00o\x00d\x00u\x00l\x00e\x001\x00' in pwm
    compressed = vba_compress(raw)
    assert vba_decompress(compressed) == raw
    print("TASK 3 PASS — dir/PROJECT/PROJECTwm streams built and verified OK")


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


# ─────────────────────────────────────────────────────────────────────────────
# TASK 5 – Assemble vbaProject.bin
#
# Layout (FAT12 compound file with 9 streams):
#   Root Entry
#   ├─ VBA/                   (Storage)
#   │   ├─ _VBA_PROJECT       (raw – opaque performance cache, no source)
#   │   ├─ dir                (compressed dir stream)
#   │   ├─ Module1            (compressed VBA source for Mermaid)
#   │   ├─ Module2            (compressed VBA source for Terraform)
#   │   └─ Module3            (compressed VBA source for dbt)
#   ├─ PROJECT                (text, UTF-8)
#   └─ PROJECTwm              (Unicode name map)
#
# The _VBA_PROJECT stream is the compiled p-code cache.  Excel regenerates it
# when it opens the file, so it is safe to emit a valid but empty stub.
# The MS-OVBA spec (2.3.4.1) says the stream MUST start with the magic bytes
# 0x61 0x08 followed by two reserved bytes 0x00 0x00.
# ─────────────────────────────────────────────────────────────────────────────

import io

_VBA_PROJECT_STUB = b'\x61\x08\x00\x00'   # magic + 2 reserved bytes


def _module_stream(vba_src: str) -> bytes:
    """
    Build an MS-OVBA module stream for one VBA module.

    Structure (MODULEOFFSET points to where the compressed source starts):
        offset 0x00: MODULEOFFSET record (4 LE bytes) – offset of compressed text
        Then any number of additional records can precede the compressed text.
        We use the simplest legal layout accepted by Excel:
            bytes 0–3  : u32 LE = offset to compressed text (= 8, after 8-byte header)
            bytes 4–7  : 4 zero bytes (padding / reserved area)
            bytes 8+   : compressed source
    """
    compressed = vba_compress(vba_src.replace('\n', '\r\n').encode('latin-1'))
    header = struct.pack('<II', 8, 0)       # offset=8, reserved=0
    return header + compressed


def build_vba_project_bin() -> bytes:
    """
    Build and return the complete vbaProject.bin bytes as an OLE2 compound
    document.  Streams are inserted in FAT order via build_ole2_cfb().
    """
    # ── module source streams ────────────────────────────────────────────────
    mod1_stream = _module_stream(_MERMAID_SRC)
    mod2_stream = _module_stream(_TERRAFORM_SRC)
    mod3_stream = _module_stream(_DBT_SRC)

    module_names = ['Module1', 'Module2', 'Module3']
    module_streams = [mod1_stream, mod2_stream, mod3_stream]

    # Compute the MODULEOFFSET for each module.
    # The dir stream references each module by its stream offset (the 4-byte
    # value at bytes 0-3 of the module stream – which we fixed at 8 above).
    # build_dir_stream_raw() already writes the correct MODULEOFFSET record
    # value (8) for every module when we call it with the same module names.

    # ── assemble all streams for OLE2 builder ───────────────────────────────
    dir_raw  = build_dir_stream_raw(module_names)
    dir_compressed = vba_compress(dir_raw)

    project_bytes = build_project_stream(module_names)
    projectwm_bytes = build_projectwm_stream(module_names)

    # build_ole2() uses flat dict keys: 'VBA/Name' for VBA sub-storage,
    # plain 'Name' for root-level streams.
    stream_map = {
        'VBA/_VBA_PROJECT': _VBA_PROJECT_STUB,
        'VBA/dir':          dir_compressed,
        'VBA/Module1':      mod1_stream,
        'VBA/Module2':      mod2_stream,
        'VBA/Module3':      mod3_stream,
        'PROJECT':          project_bytes,
        'PROJECTwm':        projectwm_bytes,
    }

    return build_ole2(stream_map)


# ─────────────────────────────────────────────────────────────────────────────
# Self-test for Task 5
# ─────────────────────────────────────────────────────────────────────────────

def _task5_selftest():
    data = build_vba_project_bin()
    # Must start with OLE2 magic
    assert data[:8] == b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1', \
        f"Bad OLE2 magic: {data[:8]!r}"
    # Must be a multiple of 512 bytes (sector size)
    assert len(data) % 512 == 0, \
        f"Length {len(data)} not a multiple of 512"
    # Must be large enough to be a real CFB
    assert len(data) >= 7 * 512, \
        f"Suspiciously small: {len(data)} bytes"
    # PROJECT stream (uncompressed text) must appear verbatim
    assert b'Module=Module1' in data, "Module1 ref not in binary"
    assert b'Module=Module2' in data, "Module2 ref not in binary"
    assert b'Module=Module3' in data, "Module3 ref not in binary"
    print(f"TASK 5 PASS — vbaProject.bin assembled OK ({len(data)} bytes)")


# ─────────────────────────────────────────────────────────────────────────────
# TASK 6 – XLSM assembler + main()
#
# An .xlsm file is a ZIP archive (Open Packaging Convention) containing:
#   [Content_Types].xml
#   _rels/.rels
#   xl/workbook.xml
#   xl/_rels/workbook.xml.rels
#   xl/worksheets/sheet1.xml   (Tables)
#   xl/worksheets/sheet2.xml   (Columns)
#   xl/sharedStrings.xml
#   xl/styles.xml
#   xl/vbaProject.bin          (the OLE2 blob built in Task 5)
#   docProps/app.xml
#   docProps/core.xml
#
# All XML is written as plain UTF-8 strings; the ZIP is assembled with
# Python's zipfile module (deflate compression for XML, store for .bin).
# ─────────────────────────────────────────────────────────────────────────────

import zipfile
import datetime


# ── XML helpers ──────────────────────────────────────────────────────────────

def _x(tag: str, attrs: dict = None, children=(), text: str = '') -> str:
    """Minimal XML element builder (returns a string)."""
    attr_str = ''
    if attrs:
        attr_str = ' ' + ' '.join(f'{k}="{v}"' for k, v in attrs.items())
    inner = text + ''.join(children)
    if inner:
        return f'<{tag}{attr_str}>{inner}</{tag}>'
    return f'<{tag}{attr_str}/>'


def _xml_decl(root: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + root


# ── Static XML parts ─────────────────────────────────────────────────────────

_CONTENT_TYPES = _xml_decl(_x(
    'Types',
    {'xmlns': 'http://schemas.openxmlformats.org/package/2006/content-types'},
    children=[
        _x('Default', {'Extension': 'rels',
            'ContentType': 'application/vnd.openxmlformats-package.relationships+xml'}),
        _x('Default', {'Extension': 'xml',
            'ContentType': 'application/xml'}),
        _x('Override', {'PartName': '/xl/workbook.xml',
            'ContentType': 'application/vnd.ms-excel.sheet.macroEnabled.main+xml'}),
        _x('Override', {'PartName': '/xl/worksheets/sheet1.xml',
            'ContentType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'}),
        _x('Override', {'PartName': '/xl/worksheets/sheet2.xml',
            'ContentType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'}),
        _x('Override', {'PartName': '/xl/sharedStrings.xml',
            'ContentType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml'}),
        _x('Override', {'PartName': '/xl/styles.xml',
            'ContentType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml'}),
        _x('Override', {'PartName': '/xl/vbaProject.bin',
            'ContentType': 'application/vnd.ms-office.activeX+xml'}),
        _x('Override', {'PartName': '/docProps/app.xml',
            'ContentType': 'application/vnd.openxmlformats-officedocument.extended-properties+xml'}),
        _x('Override', {'PartName': '/docProps/core.xml',
            'ContentType': 'application/vnd.openxmlformats-package.core-properties+xml'}),
    ]
))

_ROOT_RELS = _xml_decl(_x(
    'Relationships',
    {'xmlns': 'http://schemas.openxmlformats.org/package/2006/relationships'},
    children=[
        _x('Relationship', {'Id': 'rId1', 'Type':
            'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument',
            'Target': 'xl/workbook.xml'}),
        _x('Relationship', {'Id': 'rId2', 'Type':
            'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties',
            'Target': 'docProps/core.xml'}),
        _x('Relationship', {'Id': 'rId3', 'Type':
            'http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties',
            'Target': 'docProps/app.xml'}),
    ]
))

_WB_RELS = _xml_decl(_x(
    'Relationships',
    {'xmlns': 'http://schemas.openxmlformats.org/package/2006/relationships'},
    children=[
        _x('Relationship', {'Id': 'rId1', 'Type':
            'http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet',
            'Target': 'worksheets/sheet1.xml'}),
        _x('Relationship', {'Id': 'rId2', 'Type':
            'http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet',
            'Target': 'worksheets/sheet2.xml'}),
        _x('Relationship', {'Id': 'rId3', 'Type':
            'http://schemas.microsoft.com/office/2006/relationships/vbaProject',
            'Target': 'vbaProject.bin'}),
        _x('Relationship', {'Id': 'rId4', 'Type':
            'http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings',
            'Target': 'sharedStrings.xml'}),
        _x('Relationship', {'Id': 'rId5', 'Type':
            'http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles',
            'Target': 'styles.xml'}),
    ]
))

_WORKBOOK = _xml_decl(_x(
    'workbook',
    {'xmlns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
     'xmlns:r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
     'xmlns:mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
     'mc:Ignorable': 'x15',
     'xmlns:x15': 'http://schemas.microsoft.com/office/spreadsheetml/2010/11/main'},
    children=[
        _x('fileVersion', {'appName': 'xl', 'lastEdited': '7',
                           'lowestEdited': '7', 'rupBuild': '22228'}),
        _x('workbookPr', {'defaultThemeVersion': '166925',
                          'codeName': 'ThisWorkbook'}),
        _x('sheets', children=[
            _x('sheet', {'name': 'Tables',  'sheetId': '1', 'r:id': 'rId1'}),
            _x('sheet', {'name': 'Columns', 'sheetId': '2', 'r:id': 'rId2'}),
        ]),
        _x('calcPr', {'calcId': '191029'}),
    ]
))

_STYLES = _xml_decl(_x(
    'styleSheet',
    {'xmlns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'},
    children=[
        _x('fonts', {'count': '2'}, children=[
            _x('font', children=[
                _x('sz', {'val': '11'}), _x('name', {'val': 'Calibri'})]),
            _x('font', children=[
                _x('b'), _x('sz', {'val': '11'}), _x('name', {'val': 'Calibri'})]),
        ]),
        _x('fills', {'count': '3'}, children=[
            _x('fill', children=[_x('patternFill', {'patternType': 'none'})]),
            _x('fill', children=[_x('patternFill', {'patternType': 'gray125'})]),
            _x('fill', children=[_x('patternFill', {'patternType': 'solid'},
                children=[_x('fgColor', {'rgb': 'FF4472C4'}),
                           _x('bgColor', {'indexed': '64'})])]),
        ]),
        _x('borders', {'count': '1'}, children=[
            _x('border', children=[
                _x('left'), _x('right'), _x('top'), _x('bottom'), _x('diagonal')])]),
        _x('cellStyleXfs', {'count': '1'}, children=[
            _x('xf', {'numFmtId': '0', 'fontId': '0', 'fillId': '0', 'borderId': '0'})]),
        _x('cellXfs', {'count': '2'}, children=[
            _x('xf', {'numFmtId': '0', 'fontId': '0', 'fillId': '0',
                      'borderId': '0', 'xfId': '0'}),
            _x('xf', {'numFmtId': '0', 'fontId': '1', 'fillId': '2',
                      'borderId': '0', 'xfId': '0', 'applyFont': '1', 'applyFill': '1'}),
        ]),
    ]
))

_APP_XML = _xml_decl(_x(
    'Properties',
    {'xmlns': 'http://schemas.openxmlformats.org/officeDocument/2006/extended-properties'},
    children=[
        _x('Application', text='Microsoft Excel'),
        _x('DocSecurity', text='0'),
        _x('ScaleCrop', text='false'),
        _x('SharedDoc', text='false'),
        _x('HyperlinksChanged', text='false'),
        _x('AppVersion', text='16.0300'),
    ]
))


def _core_xml() -> str:
    now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    return _xml_decl(_x(
        'cp:coreProperties',
        {'xmlns:cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
         'xmlns:dc': 'http://purl.org/dc/elements/1.1/',
         'xmlns:dcterms': 'http://purl.org/dc/terms/',
         'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance'},
        children=[
            _x('dc:creator', text='create_macro_workbook.py'),
            _x('dcterms:created', {'xsi:type': 'dcterms:W3CDTF'}, text=now),
            _x('dcterms:modified', {'xsi:type': 'dcterms:W3CDTF'}, text=now),
        ]
    ))


# ── Sheet data builders ───────────────────────────────────────────────────────

def _cell_ref(row: int, col: int) -> str:
    """Convert 1-based (row, col) to Excel ref like A1, B3."""
    letters = ''
    c = col
    while c > 0:
        c, rem = divmod(c - 1, 26)
        letters = chr(65 + rem) + letters
    return f'{letters}{row}'


def _build_sheet(headers: list[str], rows: list[list[str]]) -> str:
    """
    Build a worksheet XML string.
    All cells are inline strings (t="inlineStr") to avoid shared-string
    index management complexity.  Header row uses style 1 (bold + blue fill).
    """
    NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    xml_rows = []
    # Header row
    header_cells = []
    for ci, h in enumerate(headers, start=1):
        ref = _cell_ref(1, ci)
        header_cells.append(
            _x('c', {'r': ref, 't': 'inlineStr', 's': '1'},
               children=[_x('is', children=[_x('t', text=h)])]))
    xml_rows.append(_x('row', {'r': '1', 'spans': f'1:{len(headers)}'},
                       children=header_cells))
    # Data rows
    for ri, row_data in enumerate(rows, start=2):
        cells = []
        for ci, val in enumerate(row_data, start=1):
            ref = _cell_ref(ri, ci)
            cells.append(
                _x('c', {'r': ref, 't': 'inlineStr'},
                   children=[_x('is', children=[_x('t', text=str(val))])]))
        xml_rows.append(_x('row', {'r': str(ri), 'spans': f'1:{len(headers)}'},
                           children=cells))

    sheet_data = _x('sheetData', children=xml_rows)
    col_widths = [_x('col', {'min': str(i), 'max': str(i), 'width': '20',
                              'customWidth': '1'})
                  for i in range(1, len(headers) + 1)]
    cols_el = _x('cols', children=col_widths)
    return _xml_decl(_x(
        'worksheet',
        {'xmlns': NS,
         'xmlns:r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'},
        children=[cols_el, sheet_data]
    ))


def _empty_shared_strings() -> str:
    return _xml_decl(_x(
        'sst',
        {'xmlns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
         'count': '0', 'uniqueCount': '0'}
    ))


# ── Sample data ───────────────────────────────────────────────────────────────

_TABLES_HEADERS = [
    'TableName', 'Description', 'SourceSystem', 'Layer',
    'OwnerTeam', 'RefreshFrequency', 'Notes',
]

_TABLES_ROWS = [
    ['dim_customer',  'Customer master data',        'CRM',      'mart',    'Analytics', 'Daily',   ''],
    ['dim_product',   'Product catalogue',           'ERP',      'mart',    'Analytics', 'Weekly',  ''],
    ['fact_orders',   'Order transactions',          'OMS',      'mart',    'Analytics', 'Hourly',  ''],
    ['stg_crm_acct',  'Raw CRM account extract',     'CRM',      'staging', 'DataEng',   'Daily',   ''],
    ['stg_oms_order', 'Raw OMS order extract',       'OMS',      'staging', 'DataEng',   'Hourly',  ''],
]

_COLUMNS_HEADERS = [
    'TableName', 'ColumnName', 'DataType', 'Nullable',
    'IsPK', 'IsFK', 'FKReference', 'Description', 'BusinessRule',
]

_COLUMNS_ROWS = [
    # dim_customer
    ['dim_customer', 'customer_id',   'INT64',     'NO',  'YES', 'NO',  '',                          'Surrogate PK',        ''],
    ['dim_customer', 'customer_key',  'STRING',    'NO',  'NO',  'NO',  '',                          'Natural key from CRM',''],
    ['dim_customer', 'full_name',     'STRING',    'YES', 'NO',  'NO',  '',                          'Full name',           ''],
    ['dim_customer', 'email',         'STRING',    'YES', 'NO',  'NO',  '',                          'Email address',       'Must be unique'],
    ['dim_customer', 'created_at',    'TIMESTAMP', 'NO',  'NO',  'NO',  '',                          'Row created time',    ''],
    # dim_product
    ['dim_product',  'product_id',    'INT64',     'NO',  'YES', 'NO',  '',                          'Surrogate PK',        ''],
    ['dim_product',  'product_sku',   'STRING',    'NO',  'NO',  'NO',  '',                          'SKU code',            ''],
    ['dim_product',  'product_name',  'STRING',    'YES', 'NO',  'NO',  '',                          'Display name',        ''],
    ['dim_product',  'unit_price',    'NUMERIC',   'YES', 'NO',  'NO',  '',                          'List price',          'Must be >= 0'],
    # fact_orders
    ['fact_orders',  'order_id',      'INT64',     'NO',  'YES', 'NO',  '',                          'Surrogate PK',        ''],
    ['fact_orders',  'customer_id',   'INT64',     'NO',  'NO',  'YES', 'dim_customer.customer_id',  'FK to dim_customer',  ''],
    ['fact_orders',  'product_id',    'INT64',     'NO',  'NO',  'YES', 'dim_product.product_id',    'FK to dim_product',   ''],
    ['fact_orders',  'order_date',    'TIMESTAMP', 'NO',  'NO',  'NO',  '',                          'Order placed time',   ''],
    ['fact_orders',  'quantity',      'INT64',     'NO',  'NO',  'NO',  '',                          'Units ordered',       'Must be > 0'],
    ['fact_orders',  'total_amount',  'NUMERIC',   'NO',  'NO',  'NO',  '',                          'Line total',          ''],
    # stg_crm_acct
    ['stg_crm_acct', 'account_id',    'STRING',    'NO',  'YES', 'NO',  '',                          'Source PK',           ''],
    ['stg_crm_acct', 'account_name',  'STRING',    'YES', 'NO',  'NO',  '',                          'Account name',        ''],
    ['stg_crm_acct', '_loaded_at',    'TIMESTAMP', 'NO',  'NO',  'NO',  '',                          'ETL load time',       ''],
    # stg_oms_order
    ['stg_oms_order','order_ref',     'STRING',    'NO',  'YES', 'NO',  '',                          'Source PK',           ''],
    ['stg_oms_order','order_status',  'STRING',    'YES', 'NO',  'NO',  '',                          'Order status code',   ''],
    ['stg_oms_order','_loaded_at',    'TIMESTAMP', 'NO',  'NO',  'NO',  '',                          'ETL load time',       ''],
]


# ── XLSM assembler ────────────────────────────────────────────────────────────

def build_xlsm(output_path: str) -> None:
    """
    Assemble the complete .xlsm workbook and write it to *output_path*.
    """
    vba_bin = build_vba_project_bin()

    sheet1_xml = _build_sheet(_TABLES_HEADERS, _TABLES_ROWS)
    sheet2_xml = _build_sheet(_COLUMNS_HEADERS, _COLUMNS_ROWS)

    with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        def _add(name: str, data, compress=True):
            method = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
            if isinstance(data, str):
                data = data.encode('utf-8')
            zf.writestr(zipfile.ZipInfo(name), data,
                        compress_type=method)

        _add('[Content_Types].xml',          _CONTENT_TYPES)
        _add('_rels/.rels',                  _ROOT_RELS)
        _add('xl/workbook.xml',              _WORKBOOK)
        _add('xl/_rels/workbook.xml.rels',   _WB_RELS)
        _add('xl/worksheets/sheet1.xml',     sheet1_xml)
        _add('xl/worksheets/sheet2.xml',     sheet2_xml)
        _add('xl/sharedStrings.xml',         _empty_shared_strings())
        _add('xl/styles.xml',                _STYLES)
        _add('xl/vbaProject.bin',            vba_bin,  compress=False)
        _add('docProps/app.xml',             _APP_XML)
        _add('docProps/core.xml',            _core_xml())


# ─────────────────────────────────────────────────────────────────────────────
# Self-test for Task 6
# ─────────────────────────────────────────────────────────────────────────────

def _task6_selftest():
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix='.xlsm', delete=False) as tmp:
        path = tmp.name
    try:
        build_xlsm(path)
        size = os.path.getsize(path)
        assert size > 10_000, f"Output too small: {size} bytes"
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            assert '[Content_Types].xml' in names
            assert 'xl/vbaProject.bin' in names
            assert 'xl/worksheets/sheet1.xml' in names
            assert 'xl/worksheets/sheet2.xml' in names
            # vbaProject.bin must start with OLE2 magic
            vba_data = zf.read('xl/vbaProject.bin')
            assert vba_data[:8] == b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1'
            # Tables sheet must contain sample data
            s1 = zf.read('xl/worksheets/sheet1.xml').decode()
            assert 'dim_customer' in s1
            assert 'fact_orders' in s1
            s2 = zf.read('xl/worksheets/sheet2.xml').decode()
            assert 'customer_id' in s2
            assert 'dim_customer.customer_id' in s2
        print(f"TASK 6 PASS — xlsm assembled OK ({size:,} bytes) → {path}")
    except Exception:
        os.unlink(path)
        raise


# ─────────────────────────────────────────────────────────────────────────────
# main()
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse, os
    parser = argparse.ArgumentParser(
        description='Generate a macro-enabled Excel workbook (.xlsm) with '
                    'Mermaid, Terraform, and dbt VBA generators.')
    parser.add_argument(
        '-o', '--output',
        default=os.path.join(os.path.dirname(__file__),
                             '..', 'output', 'data_dictionary_macros.xlsm'),
        help='Output .xlsm file path (default: output/data_dictionary_macros.xlsm)')
    args = parser.parse_args()

    out = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    build_xlsm(out)
    print(f"Written: {out}")


if __name__ == "__main__":
    _task1_selftest()
    _task2_selftest()
    _task3_selftest()
    _task5_selftest()
    _task6_selftest()
    main()
