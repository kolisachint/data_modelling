"""
parse_workbook.py
-----------------
Loads an Excel workbook and extracts structured data into Python dataclasses.

Sheet detection is heuristic: sheet names and header rows are matched against
keyword sets. Unknown sheets are surfaced as open questions.
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
    # text
    "text": "STRING", "string": "STRING", "varchar": "STRING", "char": "STRING",
    "nvarchar": "STRING", "str": "STRING",
    # integers
    "int": "INT64", "integer": "INT64", "int64": "INT64", "bigint": "INT64",
    "smallint": "INT64", "tinyint": "INT64", "number": "INT64",
    # floats
    "float": "FLOAT64", "double": "FLOAT64", "real": "FLOAT64",
    "decimal": "NUMERIC", "numeric": "NUMERIC", "money": "NUMERIC",
    # boolean
    "bool": "BOOL", "boolean": "BOOL", "bit": "BOOL",
    # dates/times
    "date": "DATE", "datetime": "DATETIME", "timestamp": "TIMESTAMP",
    "time": "TIME", "datetime2": "DATETIME",
    # binary / json
    "bytes": "BYTES", "blob": "BYTES", "json": "JSON",
}

def normalise_bq_type(raw: str) -> str:
    """Map any common type string to a BigQuery-compatible type name."""
    if not raw:
        return "STRING"
    cleaned = re.sub(r"\(.*\)", "", str(raw)).strip().lower()
    return _TYPE_MAP.get(cleaned, str(raw).strip().upper() or "STRING")


# ---------------------------------------------------------------------------
# Sheet type detection
# ---------------------------------------------------------------------------

_SHEET_KEYWORDS: dict[str, list[str]] = {
    "entities":      ["entity", "entities", "table", "tables", "object", "domain", "model"],
    "columns":       ["column", "columns", "field", "fields", "attribute", "schema", "definition"],
    "relationships": ["relationship", "relationships", "relation", "link", "join", "ref", "reference"],
    "mappings":      ["mapping", "mappings", "map", "etl", "transform", "migration", "lineage"],
    "lookups":       ["lookup", "lookups", "ref", "reference", "code", "enum", "domain", "picklist"],
    "changelog":     ["change", "changelog", "log", "version", "history", "revision"],
    "notes":         ["note", "notes", "question", "questions", "todo", "open", "issue", "remark"],
}

_HEADER_KEYWORDS: dict[str, list[str]] = {
    "entities":      ["entity", "table", "object", "description", "domain", "layer"],
    "columns":       ["column", "field", "name", "type", "datatype", "nullable", "pk", "fk", "description"],
    "relationships": ["from", "to", "cardinality", "relationship", "label"],
    "mappings":      ["source", "target", "transform", "transformation", "rule", "mapping"],
    "lookups":       ["code", "value", "description", "label"],
    "changelog":     ["version", "date", "author", "change", "description"],
    "notes":         [],  # free-form; accept if sheet name matched
}


def _header_row(ws: Worksheet) -> list[str]:
    """Return the first non-empty row as lowercase stripped strings."""
    for row in ws.iter_rows(max_row=5, values_only=True):
        cells = [str(c).strip().lower() for c in row if c is not None]
        if cells:
            return cells
    return []


def _detect_sheet_type(ws: Worksheet) -> Optional[str]:
    name = ws.title.strip().lower()
    headers = _header_row(ws)

    for stype, name_kws in _SHEET_KEYWORDS.items():
        if any(kw in name for kw in name_kws):
            return stype

    for stype, hdr_kws in _HEADER_KEYWORDS.items():
        if hdr_kws and sum(1 for kw in hdr_kws if any(kw in h for h in headers)) >= 2:
            return stype

    return None


# ---------------------------------------------------------------------------
# Sheet parsers
# ---------------------------------------------------------------------------

def _rows_as_dicts(ws: Worksheet) -> list[dict]:
    """Return worksheet rows as dicts keyed by normalised header names."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Find header row (first row that has at least 2 non-None cells)
    header_idx = 0
    for i, row in enumerate(rows[:5]):
        non_null = [c for c in row if c is not None]
        if len(non_null) >= 2:
            header_idx = i
            break

    headers = [str(c).strip().lower().replace(" ", "_") if c else f"col_{i}"
               for i, c in enumerate(rows[header_idx])]

    result = []
    for row in rows[header_idx + 1:]:
        if all(c is None for c in row):
            continue
        result.append({headers[i]: (str(v).strip() if v is not None else "")
                       for i, v in enumerate(row) if i < len(headers)})
    return result


def _flag(val: str) -> bool:
    """Interpret common yes/true/pk markers as True."""
    return str(val).strip().lower() in {"yes", "true", "y", "1", "pk", "fk", "x", "✓", "✔"}


def _find_col(row: dict, *candidates: str) -> str:
    """Return the value of the first matching key in a dict row."""
    for candidate in candidates:
        for key in row:
            if candidate in key:
                return row[key]
    return ""


def _parse_entities(ws: Worksheet) -> list[Entity]:
    entities = []
    for row in _rows_as_dicts(ws):
        name = _find_col(row, "entity", "table", "name", "object")
        if not name:
            continue
        entities.append(Entity(
            name=name,
            description=_find_col(row, "description", "desc", "comment", "note"),
            domain=_find_col(row, "domain", "subject", "area"),
            layer=_find_col(row, "layer", "tier", "zone"),
            source_sheet=ws.title,
        ))
    return entities


def _parse_columns(ws: Worksheet, entity_map: dict[str, Entity]) -> None:
    """Parse column definitions and attach them to the matching entity."""
    for row in _rows_as_dicts(ws):
        entity_name = _find_col(row, "entity", "table", "object")
        col_name = _find_col(row, "column", "field", "name", "attribute")
        if not col_name:
            continue

        fk_ref_raw = _find_col(row, "fk_ref", "references", "fk_reference", "ref")
        col = Column(
            name=col_name,
            data_type=normalise_bq_type(_find_col(row, "type", "datatype", "data_type")),
            nullable=not _flag(_find_col(row, "not_null", "required", "mandatory"))
                     if _find_col(row, "not_null", "required", "mandatory")
                     else not _flag(_find_col(row, "nullable")) or True,
            is_pk=_flag(_find_col(row, "pk", "primary", "primary_key")),
            is_fk=_flag(_find_col(row, "fk", "foreign", "foreign_key")) or bool(fk_ref_raw),
            fk_ref=fk_ref_raw or None,
            description=_find_col(row, "description", "desc", "comment"),
            business_rules=_find_col(row, "rule", "rules", "constraint", "validation"),
        )

        # Nullable: PK columns are implicitly NOT NULL
        if col.is_pk:
            col.nullable = False

        if entity_name in entity_map:
            entity_map[entity_name].columns.append(col)
        else:
            # Entity not in Entities sheet — create it on the fly
            entity_map[entity_name] = Entity(
                name=entity_name,
                source_sheet=ws.title,
                columns=[col],
            )


def _parse_relationships(ws: Worksheet) -> list[Relationship]:
    rels = []
    for row in _rows_as_dicts(ws):
        from_e = _find_col(row, "from", "source", "parent", "from_entity")
        to_e = _find_col(row, "to", "target", "child", "to_entity")
        if not from_e or not to_e:
            continue
        cardinality = _find_col(row, "cardinality", "type", "relation") or "1..N"
        # Normalise common cardinality notation
        cardinality = re.sub(r"(?i)one.to.many|1-n|1:n", "1..N", cardinality)
        cardinality = re.sub(r"(?i)many.to.many|n-m|n:m|m:n", "N..M", cardinality)
        cardinality = re.sub(r"(?i)one.to.one|1-1|1:1", "1..1", cardinality)
        rels.append(Relationship(
            from_entity=from_e,
            to_entity=to_e,
            cardinality=cardinality,
            label=_find_col(row, "label", "name", "description"),
        ))
    return rels


def _parse_mappings(ws: Worksheet) -> list[Mapping]:
    mappings = []
    for row in _rows_as_dicts(ws):
        src_col = _find_col(row, "source_column", "source_field", "src_col", "source")
        tgt_col = _find_col(row, "target_column", "target_field", "tgt_col", "target")
        if not src_col and not tgt_col:
            continue
        mappings.append(Mapping(
            source_system=_find_col(row, "source_system", "system", "src_system"),
            source_table=_find_col(row, "source_table", "src_table", "source_entity"),
            source_column=src_col,
            target_entity=_find_col(row, "target_entity", "target_table", "tgt_entity"),
            target_column=tgt_col,
            transformation=_find_col(row, "transformation", "transform", "logic", "rule"),
            notes=_find_col(row, "notes", "note", "comment", "remark"),
        ))
    return mappings


def _parse_lookups(ws: Worksheet) -> list[LookupEntry]:
    entries = []
    for row in _rows_as_dicts(ws):
        code = _find_col(row, "code", "key", "id", "value")
        value = _find_col(row, "value", "label", "name", "description")
        if not code:
            continue
        entries.append(LookupEntry(
            table_name=ws.title,
            code=code,
            value=value,
            description=_find_col(row, "description", "desc", "comment"),
        ))
    return entries


def _parse_changelog(ws: Worksheet) -> list[ChangeLogEntry]:
    entries = []
    for row in _rows_as_dicts(ws):
        version = _find_col(row, "version", "ver", "release")
        date = _find_col(row, "date", "updated", "created")
        if not version and not date:
            continue
        entries.append(ChangeLogEntry(
            version=version,
            date=date,
            author=_find_col(row, "author", "owner", "by", "name"),
            description=_find_col(row, "description", "change", "desc", "notes"),
        ))
    return entries


def _parse_notes(ws: Worksheet) -> list[str]:
    items = []
    for row in ws.iter_rows(values_only=True):
        text = " | ".join(str(c).strip() for c in row if c is not None)
        if text:
            items.append(text)
    return items


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def parse_workbook(path: str | Path) -> WorkbookData:
    """
    Load an Excel workbook and return a WorkbookData instance.

    Sheet type is inferred from the sheet name and header row.
    Unrecognised sheets are listed in WorkbookData.unrecognised_sheets.
    """
    wb = openpyxl.load_workbook(str(path), data_only=True)
    data = WorkbookData(source_file=str(Path(path).name))

    entity_map: dict[str, Entity] = {}
    column_sheets: list[Worksheet] = []

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
            data.unrecognised_sheets.append(ws.title)

    # Second pass: columns (need entity_map populated first)
    for ws in column_sheets:
        _parse_columns(ws, entity_map)

    data.entities = list(entity_map.values())

    # Infer FK relationships from column definitions if Relationships sheet was empty
    if not data.relationships:
        for entity in data.entities:
            for col in entity.columns:
                if col.is_fk and col.fk_ref:
                    parts = col.fk_ref.split(".")
                    ref_entity = parts[0]
                    data.relationships.append(Relationship(
                        from_entity=entity.name,
                        to_entity=ref_entity,
                        cardinality="1..N",
                        label=f"{entity.name}.{col.name} → {col.fk_ref}",
                    ))

    return data
