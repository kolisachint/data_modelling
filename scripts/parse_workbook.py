"""
parse_workbook.py
-----------------
Loads an Excel workbook and extracts structured data into Python dataclasses.

Sheet detection is heuristic: sheet names and header rows are matched against
keyword sets. Unknown/unrecognised sheets are attempted as combined
entity+column sheets before being surfaced as open questions.

Flexibility features:
  - Header row search up to row 10 (handles title/logo rows above headers)
  - Unicode sanitisation (BOM, NBSP, zero-width spaces)
  - Broad keyword aliases for headers (Table/Entity/Tbl, Col/Column/Field, etc.)
  - Merged-cell carry-forward for entity names in column sheets
  - Nullable logic correctly handles both "Nullable=Yes" and "Required=Yes" columns
  - Combined sheet detection (entity name rows mixed with column detail rows)
  - Extended BQ type map (uuid, serial, clob, array, struct, interval, …)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Column:
    name: str
    data_type: str = "STRING"        # BigQuery-compatible type
    nullable: bool = True
    is_pk: bool = False
    is_fk: bool = False
    fk_ref: Optional[str] = None     # "OtherEntity.column_name"
    description: str = ""
    business_rules: str = ""


@dataclass
class Entity:
    name: str
    description: str = ""
    domain: str = ""
    layer: str = ""                  # raw / staging / intermediate / mart
    source_sheet: str = ""
    columns: list[Column] = field(default_factory=list)


@dataclass
class Relationship:
    from_entity: str
    to_entity: str
    cardinality: str = "1..N"        # 1..1 / 1..N / N..M
    label: str = ""


@dataclass
class Mapping:
    source_system: str
    source_table: str
    source_column: str
    target_entity: str
    target_column: str
    transformation: str = ""
    notes: str = ""


@dataclass
class LookupEntry:
    table_name: str
    code: str
    value: str
    description: str = ""


@dataclass
class ChangeLogEntry:
    version: str
    date: str
    author: str
    description: str


@dataclass
class WorkbookData:
    source_file: str
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    mappings: list[Mapping] = field(default_factory=list)
    lookups: list[LookupEntry] = field(default_factory=list)
    changelog: list[ChangeLogEntry] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)
    unrecognised_sheets: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# BQ type normalisation
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, str] = {
    # text / string
    "text": "STRING", "string": "STRING", "varchar": "STRING", "char": "STRING",
    "nvarchar": "STRING", "str": "STRING", "nchar": "STRING",
    "ntext": "STRING", "clob": "STRING", "text_clob": "STRING",
    "character varying": "STRING", "character": "STRING",
    "uniqueidentifier": "STRING", "uuid": "STRING", "guid": "STRING",
    "interval": "STRING",      # BQ has no native interval type
    # integers
    "int": "INT64", "integer": "INT64", "int64": "INT64", "bigint": "INT64",
    "smallint": "INT64", "tinyint": "INT64", "number": "INT64",
    "int32": "INT64", "int16": "INT64", "int8": "INT64",
    "long": "INT64", "serial": "INT64", "auto_increment": "INT64",
    "autoincrement": "INT64",
    # floats
    "float": "FLOAT64", "double": "FLOAT64", "real": "FLOAT64",
    "float32": "FLOAT64", "float64": "FLOAT64", "double precision": "FLOAT64",
    # numeric / decimal
    "decimal": "NUMERIC", "numeric": "NUMERIC", "money": "NUMERIC",
    "bignumeric": "BIGNUMERIC", "bigdecimal": "BIGNUMERIC",
    # boolean
    "bool": "BOOL", "boolean": "BOOL", "bit": "BOOL",
    # dates / times
    "date": "DATE", "datetime": "DATETIME", "timestamp": "TIMESTAMP",
    "time": "TIME", "datetime2": "DATETIME",
    # complex / binary
    "bytes": "BYTES", "blob": "BYTES", "json": "JSON",
    "array": "ARRAY", "struct": "RECORD", "record": "RECORD",
}


def normalise_bq_type(raw: str) -> str:
    """Map any common type string to a BigQuery-compatible type name."""
    if not raw:
        return "STRING"
    cleaned = re.sub(r"\(.*?\)", "", str(raw)).strip().lower()
    return _TYPE_MAP.get(cleaned, str(raw).strip().upper() or "STRING")


# ---------------------------------------------------------------------------
# Sheet type detection
# ---------------------------------------------------------------------------

_SHEET_KEYWORDS: dict[str, list[str]] = {
    "entities":      ["entity", "entities", "table", "tables", "object", "objects",
                      "domain", "model", "data_model", "data model", "tbl",
                      "entity_list", "table_list"],
    "columns":       ["column", "columns", "field", "fields", "attribute", "attributes",
                      "schema", "definition", "definitions", "col", "cols",
                      "properties", "structure"],
    "relationships": ["relationship", "relationships", "relation", "relations",
                      "link", "links", "join", "joins", "ref", "reference",
                      "references"],
    "mappings":      ["mapping", "mappings", "map", "etl", "transform",
                      "transformation", "transformations", "migration",
                      "source_to_target", "lineage"],
    "lookups":       ["lookup", "lookups", "ref", "reference", "code", "codes",
                      "enum", "domain", "picklist", "reference_data", "ref_data",
                      "code_table", "value_set"],
    "changelog":     ["change", "changelog", "log", "version", "history",
                      "revision", "audit", "changes"],
    "notes":         ["note", "notes", "question", "questions", "todo", "open",
                      "issue", "issues", "remark", "remarks"],
}

_HEADER_KEYWORDS: dict[str, list[str]] = {
    "entities":      ["entity", "table", "object", "description", "domain",
                      "layer", "tbl", "table_name", "entity_name", "subject_area"],
    "columns":       ["column", "field", "name", "type", "datatype", "nullable",
                      "pk", "fk", "description", "col_name", "attribute",
                      "data_type", "required", "constraint", "primary", "foreign",
                      "reference"],
    "relationships": ["from", "to", "cardinality", "relationship", "label",
                      "parent", "child", "join", "multiplicity"],
    "mappings":      ["source", "target", "transform", "transformation", "rule",
                      "mapping", "src", "tgt", "expression", "formula", "logic"],
    "lookups":       ["code", "value", "description", "label"],
    "changelog":     ["version", "date", "author", "change", "description"],
    "notes":         [],  # free-form; accept on sheet-name match alone
}

# Flat set of all known header keywords for header-row detection
_ALL_HEADER_KWS: frozenset[str] = frozenset(
    kw for kws in _HEADER_KEYWORDS.values() for kw in kws
)


def _sanitise(value) -> str:
    """Return a clean string from any cell value, stripping Unicode artefacts."""
    if value is None:
        return ""
    s = str(value)
    # Strip BOM, non-breaking space, zero-width space
    s = s.replace("\ufeff", "").replace("\xa0", " ").replace("\u200b", "")
    return s.strip()


def _header_row(ws: Worksheet) -> list[str]:
    """Return the best header row (up to row 10) as lowercase stripped strings.

    Prefers the first row that contains at least one known keyword AND has
    >= 2 non-empty cells.  Falls back to the first non-empty row if nothing
    matches.
    """
    best_fallback: list[str] = []
    for row in ws.iter_rows(max_row=10, values_only=True):
        cells = [_sanitise(c).lower() for c in row if c is not None]
        if len(cells) < 2:
            continue
        if not best_fallback:
            best_fallback = cells
        # Prefer row that contains a known header keyword
        if any(kw in cell for kw in _ALL_HEADER_KWS for cell in cells):
            return cells
    return best_fallback


def _detect_sheet_type(ws: Worksheet) -> Optional[str]:
    name = ws.title.strip().lower()
    headers = _header_row(ws)

    # 1. Match on sheet name
    for stype, name_kws in _SHEET_KEYWORDS.items():
        if any(kw in name for kw in name_kws):
            return stype

    # 2. Match on header content (need >= 2 matching keywords)
    for stype, hdr_kws in _HEADER_KEYWORDS.items():
        if hdr_kws and sum(1 for kw in hdr_kws if any(kw in h for h in headers)) >= 2:
            return stype

    return None


# ---------------------------------------------------------------------------
# Row reading
# ---------------------------------------------------------------------------

def _rows_as_dicts(ws: Worksheet) -> list[dict]:
    """Return worksheet rows as dicts keyed by normalised header names.

    - Scans up to row 10 for the header row (first row with >= 2 cells
      that contains at least one known keyword).
    - Sanitises all cell values (strips BOM, NBSP, zero-width spaces).
    - Skips fully empty rows.
    """
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Locate the header row
    header_idx = 0
    for i, row in enumerate(rows[:10]):
        non_null = [c for c in row if c is not None]
        if len(non_null) < 2:
            continue
        header_idx = i
        cells_lower = [_sanitise(c).lower() for c in row if c is not None]
        if any(kw in cell for kw in _ALL_HEADER_KWS for cell in cells_lower):
            break  # best match found

    headers = [
        _sanitise(c).lower().replace(" ", "_") if c else f"col_{i}"
        for i, c in enumerate(rows[header_idx])
    ]

    result = []
    for row in rows[header_idx + 1:]:
        if all(c is None for c in row):
            continue
        result.append({
            headers[i]: _sanitise(v)
            for i, v in enumerate(row)
            if i < len(headers)
        })
    return result


def _flag(val: str) -> bool:
    """Interpret common yes/true/pk markers as True."""
    return _sanitise(val).lower() in {"yes", "true", "y", "1", "pk", "fk", "x", "✓", "✔"}


def _find_col(row: dict, *candidates: str) -> str:
    """Return the value of the first key in row whose name contains any candidate."""
    for candidate in candidates:
        for key in row:
            if candidate in key:
                return row[key]
    return ""


# ---------------------------------------------------------------------------
# Nullable helper (fixes the inverted-column bug in the original code)
# ---------------------------------------------------------------------------

def _parse_nullable(row: dict) -> bool:
    """Determine column nullability from a row dict.

    Handles two column conventions:
      - "Nullable = Yes/No"  (Yes → nullable)
      - "Required / Not Null = Yes/No"  (Yes → NOT nullable)
    """
    # "Nullable"-style column: Yes means nullable
    val = _find_col(row,
                    "nullable", "null", "is_nullable", "optional", "allow_null",
                    "allows_null", "is_null")
    if val:
        return _flag(val)
    # Inverted column: "Required = Yes" means NOT nullable
    inv = _find_col(row,
                    "not_null", "required", "mandatory", "is_required",
                    "non_null", "notnull")
    if inv:
        return not _flag(inv)
    return True  # default: nullable


# ---------------------------------------------------------------------------
# Sheet parsers
# ---------------------------------------------------------------------------

def _parse_entities(ws: Worksheet) -> list[Entity]:
    entities = []
    for row in _rows_as_dicts(ws):
        name = _find_col(row, "entity", "table", "tbl", "object", "name",
                         "table_name", "entity_name", "subject")
        if not name:
            continue
        entities.append(Entity(
            name=name,
            description=_find_col(row, "description", "desc", "comment",
                                   "definition", "meaning", "purpose", "note"),
            domain=_find_col(row, "domain", "subject", "area", "subject_area"),
            layer=_find_col(row, "layer", "tier", "zone"),
            source_sheet=ws.title,
        ))
    return entities


def _parse_columns(ws: Worksheet, entity_map: dict[str, Entity]) -> None:
    """Parse column definitions and attach them to matching entities.

    Handles merged-cell carry-forward: if the entity/table column in a row
    is blank and the previous row had a value, the previous value is reused.
    This is common when the entity name is in a merged cell spanning all its
    column rows.
    """
    prev_entity_name = ""

    for row in _rows_as_dicts(ws):
        entity_name = _find_col(row, "entity", "table", "tbl", "object",
                                 "table_name", "entity_name", "subject")
        col_name = _find_col(row, "column", "col", "field", "name", "attribute",
                              "col_name", "attribute_name", "field_name")

        if not col_name:
            continue

        # Carry forward entity name from merged cells
        if entity_name:
            prev_entity_name = entity_name
        else:
            entity_name = prev_entity_name

        fk_ref_raw = _find_col(row, "fk_ref", "fk_reference", "references",
                                "ref", "fk_table", "ref_table",
                                "reference_table", "parent_table")
        col = Column(
            name=col_name,
            data_type=normalise_bq_type(
                _find_col(row, "type", "datatype", "data_type",
                          "field_type", "col_type", "bq_type", "dtype")
            ),
            nullable=_parse_nullable(row),
            is_pk=_flag(_find_col(row, "pk", "primary", "primary_key",
                                   "is_pk", "key", "pkey")),
            is_fk=_flag(_find_col(row, "fk", "foreign", "foreign_key",
                                   "is_fk", "fkey")) or bool(fk_ref_raw),
            fk_ref=fk_ref_raw or None,
            description=_find_col(row, "description", "desc", "comment",
                                   "definition", "meaning", "purpose", "note"),
            business_rules=_find_col(row, "rule", "rules", "constraint",
                                      "validation", "business_rule",
                                      "constraint_rule", "check",
                                      "validation_rule", "business_rules"),
        )

        # PKs are never nullable
        if col.is_pk:
            col.nullable = False

        if entity_name in entity_map:
            entity_map[entity_name].columns.append(col)
        else:
            # Entity not in the Tables/Entities sheet — create on the fly
            entity_map[entity_name] = Entity(
                name=entity_name,
                source_sheet=ws.title,
                columns=[col],
            )


def _parse_relationships(ws: Worksheet) -> list[Relationship]:
    rels = []
    for row in _rows_as_dicts(ws):
        from_e = _find_col(row, "from", "source", "parent", "from_entity",
                            "from_table", "parent_table")
        to_e   = _find_col(row, "to", "target", "child", "to_entity",
                            "to_table", "child_table")
        if not from_e or not to_e:
            continue
        cardinality = _find_col(row, "cardinality", "type", "relation",
                                 "multiplicity", "relationship_type") or "1..N"
        cardinality = re.sub(r"(?i)one.to.many|1-n|1:n",  "1..N", cardinality)
        cardinality = re.sub(r"(?i)many.to.many|n-m|n:m|m:n", "N..M", cardinality)
        cardinality = re.sub(r"(?i)one.to.one|1-1|1:1",   "1..1", cardinality)
        rels.append(Relationship(
            from_entity=from_e,
            to_entity=to_e,
            cardinality=cardinality,
            label=_find_col(row, "label", "name", "description", "relation"),
        ))
    return rels


def _parse_mappings(ws: Worksheet) -> list[Mapping]:
    mappings = []
    for row in _rows_as_dicts(ws):
        src_col = _find_col(row, "source_column", "source_field", "src_col",
                             "src_column", "source_attribute")
        tgt_col = _find_col(row, "target_column", "target_field", "tgt_col",
                             "tgt_column", "target_attribute")
        # Accept rows that have at least a source or target column
        if not src_col and not tgt_col:
            continue
        mappings.append(Mapping(
            source_system=_find_col(row, "source_system", "system",
                                    "src_system", "source"),
            source_table=_find_col(row, "source_table", "src_table",
                                    "source_entity", "source_object"),
            source_column=src_col,
            target_entity=_find_col(row, "target_entity", "target_table",
                                     "tgt_entity", "tgt_table", "target"),
            target_column=tgt_col,
            transformation=_find_col(row, "transformation", "transform",
                                      "logic", "rule", "expression",
                                      "formula", "derivation"),
            notes=_find_col(row, "notes", "note", "comment", "remark",
                             "remarks"),
        ))
    return mappings


def _parse_lookups(ws: Worksheet) -> list[LookupEntry]:
    entries = []
    for row in _rows_as_dicts(ws):
        code  = _find_col(row, "code", "key", "id", "value")
        value = _find_col(row, "value", "label", "name", "display")
        if not code:
            continue
        entries.append(LookupEntry(
            table_name=ws.title,
            code=code,
            value=value,
            description=_find_col(row, "description", "desc", "comment",
                                   "meaning"),
        ))
    return entries


def _parse_changelog(ws: Worksheet) -> list[ChangeLogEntry]:
    entries = []
    for row in _rows_as_dicts(ws):
        version = _find_col(row, "version", "ver", "release", "v")
        date    = _find_col(row, "date", "updated", "created", "timestamp")
        if not version and not date:
            continue
        entries.append(ChangeLogEntry(
            version=version,
            date=date,
            author=_find_col(row, "author", "owner", "by", "name",
                              "changed_by", "updated_by"),
            description=_find_col(row, "description", "change", "desc",
                                   "notes", "summary"),
        ))
    return entries


def _parse_notes(ws: Worksheet) -> list[str]:
    items = []
    for row in ws.iter_rows(values_only=True):
        text = " | ".join(_sanitise(c) for c in row if c is not None)
        if text:
            items.append(text)
    return items


# ---------------------------------------------------------------------------
# Combined sheet parser
# ---------------------------------------------------------------------------
# Used as a fallback when a sheet isn't classified as any known type but
# appears to contain both entity headings and column detail rows.
# Pattern recognised: a row with only 1–2 cells filled = entity name row;
# a row with >= 3 cells filled = column row for the most recent entity.

def _looks_like_combined(ws: Worksheet) -> bool:
    """Return True if the sheet seems to mix entity-name rows and column rows."""
    rows = list(ws.iter_rows(max_row=30, values_only=True))
    short_rows = sum(1 for r in rows if 1 <= sum(1 for c in r if c) <= 2)
    long_rows  = sum(1 for r in rows if sum(1 for c in r if c) >= 3)
    return short_rows >= 1 and long_rows >= 2


def _parse_combined_sheet(ws: Worksheet, entity_map: dict[str, Entity]) -> None:
    """Parse a sheet that mixes entity-name rows with column-detail rows."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return

    # Locate the header row (the first long row)
    header_idx = 0
    for i, row in enumerate(rows[:10]):
        if sum(1 for c in row if c) >= 3:
            cells_lower = [_sanitise(c).lower() for c in row if c is not None]
            if any(kw in cell for kw in _ALL_HEADER_KWS for cell in cells_lower):
                header_idx = i
                break

    headers = [
        _sanitise(c).lower().replace(" ", "_") if c else f"col_{i}"
        for i, c in enumerate(rows[header_idx])
    ]
    current_entity = ""

    for row in rows[header_idx + 1:]:
        if all(c is None for c in row):
            continue
        filled = [i for i, c in enumerate(row) if c is not None]

        # Short row with only col 0 filled → entity name heading
        if len(filled) <= 2 and 0 in filled:
            current_entity = _sanitise(row[0])
            if current_entity and current_entity not in entity_map:
                desc = _sanitise(row[1]) if len(filled) > 1 else ""
                entity_map[current_entity] = Entity(
                    name=current_entity,
                    description=desc,
                    source_sheet=ws.title,
                )
            continue

        # Long row → column definition
        if not current_entity:
            continue
        row_dict = {headers[i]: _sanitise(v) for i, v in enumerate(row)
                    if i < len(headers)}
        col_name = _find_col(row_dict, "column", "col", "field", "name",
                              "attribute", "col_name", "attribute_name")
        if not col_name:
            continue

        fk_ref_raw = _find_col(row_dict, "fk_ref", "references", "ref",
                                "fk_reference", "fk_table", "ref_table",
                                "reference_table", "parent_table")
        col = Column(
            name=col_name,
            data_type=normalise_bq_type(
                _find_col(row_dict, "type", "datatype", "data_type",
                          "field_type", "col_type", "bq_type", "dtype")
            ),
            nullable=_parse_nullable(row_dict),
            is_pk=_flag(_find_col(row_dict, "pk", "primary", "primary_key",
                                   "is_pk", "key")),
            is_fk=_flag(_find_col(row_dict, "fk", "foreign", "foreign_key",
                                   "is_fk")) or bool(fk_ref_raw),
            fk_ref=fk_ref_raw or None,
            description=_find_col(row_dict, "description", "desc", "comment",
                                   "definition", "meaning", "purpose"),
            business_rules=_find_col(row_dict, "rule", "rules", "constraint",
                                      "validation", "business_rule", "check"),
        )
        if col.is_pk:
            col.nullable = False

        entity_map[current_entity].columns.append(col)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def parse_workbook(path: str | Path) -> WorkbookData:
    """Load an Excel workbook and return a WorkbookData instance.

    Sheet type is inferred from the sheet name and header row keywords.
    Unrecognised sheets are first tested as combined entity+column sheets;
    if that heuristic does not apply they are listed in
    WorkbookData.unrecognised_sheets.
    """
    wb = openpyxl.load_workbook(str(path), data_only=True)
    data = WorkbookData(source_file=str(Path(path).name))

    entity_map: dict[str, Entity] = {}
    column_sheets: list[Worksheet] = []
    unrecognised: list[Worksheet] = []

    # First pass: entities and other non-column sheets
    for ws in wb.worksheets:
        stype = _detect_sheet_type(ws)

        if stype == "entities":
            for e in _parse_entities(ws):
                entity_map[e.name] = e

        elif stype == "columns":
            column_sheets.append(ws)

        elif stype == "relationships":
            data.relationships.extend(_parse_relationships(ws))

        elif stype == "mappings":
            data.mappings.extend(_parse_mappings(ws))

        elif stype == "lookups":
            data.lookups.extend(_parse_lookups(ws))

        elif stype == "changelog":
            data.changelog.extend(_parse_changelog(ws))

        elif stype == "notes":
            data.open_items.extend(_parse_notes(ws))

        else:
            unrecognised.append(ws)

    # Second pass: column sheets (entity_map must be populated first)
    for ws in column_sheets:
        _parse_columns(ws, entity_map)

    # Fallback: try to parse unrecognised sheets as combined entity+column
    for ws in unrecognised:
        if _looks_like_combined(ws):
            _parse_combined_sheet(ws, entity_map)
        else:
            data.unrecognised_sheets.append(ws.title)

    data.entities = list(entity_map.values())

    # Infer FK relationships from column definitions if no Relationships sheet
    if not data.relationships:
        for entity in data.entities:
            for col in entity.columns:
                if col.is_fk and col.fk_ref:
                    parts = col.fk_ref.split(".")
                    data.relationships.append(Relationship(
                        from_entity=entity.name,
                        to_entity=parts[0],
                        cardinality="1..N",
                        label=f"{entity.name}.{col.name} → {col.fk_ref}",
                    ))

    return data
