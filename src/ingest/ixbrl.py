"""Lean lxml-based iXBRL parser for Companies House accounts.

`parse_file(path)` returns a plain dict:

    {
      "company_number": "06452255",
      "period_start": "2024-07-01", "period_end": "2025-06-30",
      "balance_sheet_date": "2025-06-30", "entity_name": "...",
      "facts": [ {concept, value, unit, decimals, scale, sign, format, context_id,
                  period_type ('instant'|'duration'), instant, start, end,
                  dims (dict dimension-local-name -> member-local-name),
                  is_within_one_year, is_after_one_year}, ... ],
      "nonnumeric": {concept_local_name: text},   # small allowlist, first value wins
      "dimensions": {dimension_local_name: [member_local_name, ...]},  # all members seen
      "officers": [...],                           # NameEntityOfficer texts
      "kind": "ixbrl" | "xbrl",
      "n_numeric": int,
    }

Concepts are matched by LOCAL NAME regardless of prefix (core:, uk-core:, frs-core:,
ns5:, uk-gaap: ...). The parser is the production path; `src.ingest.accounts` falls back
to ixbrlparse when this module raises.

Decisions (see docs/research-log.md):
- scale="-2" on count concepts (local name containing "Employee") is a known vendor bug
  that would turn 84 employees into 0.84. The parser ignores NEGATIVE scales on such
  concepts and records the original `scale` so the choice is auditable. `value_literal`
  carries the spec-literal value for validation against ixbrlparse.
- Parenthesised numbers inside a tag are treated as negative.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from lxml import etree

# ---------------------------------------------------------------- constants
IX_NS_PREFIX = "http://www.xbrl.org/2008/inlineXBRL"
XBRLI_NS = "http://www.xbrl.org/2003/instance"
XBRLDI_NS = "http://xbrl.org/2006/xbrldi"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

NONNUMERIC_ALLOW_PREFIXES = (
    "AccountsType",
    "AccountsStatus",
    "NameEntityOfficer",
)
NONNUMERIC_ALLOW_EXACT = {
    "EntityDormantTruefalse",
    "DescriptionPrincipalActivities",
    "StartDateForPeriodCoveredByReport",
    "EndDateForPeriodCoveredByReport",
    "BalanceSheetDate",
    "UKCompaniesHouseRegisteredNumber",
    "EntityCurrentLegalOrRegisteredName",
    "EntityCurrentLegalName",
    "ReportTitle",
    "EntityTradingStatus",
    "EntityAccountsType",
    "NameProductionSoftware",
    "ReportIncludesDetailedProfitLossStatementTruefalse",
    "EntityHasTakenExemptionUnderCompaniesActInNotPublishingItsOwnProfitLossAccountTruefalse",
    "LegalFormEntity",
    "PrincipalLocation-CityOrTown",
    "PostalCodeZip",
}
DATE_CONCEPTS = {
    "StartDateForPeriodCoveredByReport",
    "EndDateForPeriodCoveredByReport",
    "BalanceSheetDate",
}
COUNT_CONCEPT_MARKERS = ("Employee",)

ZERO_FORMATS = {"zerodash", "numdash", "fixedzero", "fixed-zero", "zero-dash", "num-dash"}
NONE_FORMATS = {"nocontent", "fixedempty", "fixed-empty", "no-content"}
COMMA_DECIMAL_FORMATS = {
    "numcomma", "numdotcomma", "numspacecomma", "numcommadecimal",
    "num-comma-decimal", "num-dot-comma", "num-space-comma",
}
WORD_FORMATS = {"numwordsen", "num-words-en"}
TRUE_FORMATS = {"booleantrue", "fixedtrue", "fixed-true", "boolean-true"}
FALSE_FORMATS = {"booleanfalse", "fixedfalse", "fixed-false", "boolean-false"}

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9

_RE_ORDINAL = re.compile(r"(\d{1,2})(st|nd|rd|th)\b", re.I)
_RE_DMY_TEXT = re.compile(r"^(\d{1,2})\s+([a-z]+),?\s+(\d{2,4})$", re.I)
_RE_MDY_TEXT = re.compile(r"^([a-z]+)\s+(\d{1,2}),?\s+(\d{2,4})$", re.I)
_RE_DMY_NUM = re.compile(r"^(\d{1,2})[\/\.\-](\d{1,2})[\/\.\-](\d{2,4})$")
_RE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_RE_NUM_CLEAN = re.compile(r"[,\s  ]")


class IxbrlParseError(Exception):
    pass


# ---------------------------------------------------------------- helpers
def _local(tag: Any) -> str:
    """Local name of an lxml tag ('{ns}name' -> 'name'); comments/PIs return ''."""
    if not isinstance(tag, str):
        return ""
    return tag.rpartition("}")[2]


def _local_qname(value: str | None) -> str:
    """'core:Turnover' -> 'Turnover'; also strips a '{ns}' form."""
    if not value:
        return ""
    value = value.strip()
    if value.startswith("{"):
        return value.rpartition("}")[2]
    return value.rpartition(":")[2]


def _text_excluding(el: etree._Element) -> str:
    """Concatenated text of `el`, skipping ix:exclude subtrees."""
    if el.find(".//{*}exclude") is None:
        return "".join(el.itertext())
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        if _local(node.tag) == "exclude":
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(el)
    return "".join(parts)


def parse_date(text: str | None) -> str | None:
    """Best-effort date to ISO. Handles ISO, '31 January 2026', '31st Jan 26',
    'January 31, 2026', '31/01/2026', '31.01.2026', '31-01-2026'."""
    if not text:
        return None
    s = " ".join(text.replace(" ", " ").split()).strip().strip(".")
    if not s:
        return None
    m = _RE_ISO.match(s)
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            return None
    s = _RE_ORDINAL.sub(r"\1", s)
    m = _RE_DMY_TEXT.match(s)
    if m:
        mon = _MONTHS.get(m[2].lower()) or _MONTHS.get(m[2].lower()[:3])
        if mon:
            return _mk_date(m[3], mon, m[1])
    m = _RE_MDY_TEXT.match(s)
    if m:
        mon = _MONTHS.get(m[1].lower()) or _MONTHS.get(m[1].lower()[:3])
        if mon:
            return _mk_date(m[3], mon, m[2])
    m = _RE_DMY_NUM.match(s)
    if m:
        return _mk_date(m[3], int(m[2]), m[1])
    return None


def _mk_date(y: str, mon: int, d: str) -> str | None:
    year = int(y)
    if year < 100:
        year += 2000 if year < 70 else 1900
    try:
        return dt.date(year, mon, int(d)).isoformat()
    except ValueError:
        return None


def parse_number(text: str, fmt: str | None, scale: str | None, sign: str | None,
                 concept: str = "") -> tuple[float | None, float | None]:
    """Return (value, value_literal). `value` applies the count-concept scale fix;
    `value_literal` is the spec-literal result (what ixbrlparse computes)."""
    f = _local_qname(fmt).lower() if fmt else ""
    raw = (text or "").strip()
    if f in NONE_FORMATS:
        return None, None
    if f in ZERO_FORMATS:
        base = 0.0
    elif f in WORD_FORMATS:
        base = _words_to_number(raw)
        if base is None:
            return None, None
    else:
        if raw in ("", "-", "–", "—", "nil", "Nil", "NIL", "none", "None"):
            base = 0.0
        else:
            neg = False
            if raw.startswith("(") and raw.endswith(")"):
                neg = True
                raw = raw[1:-1].strip()
            if raw.startswith("-"):
                neg = not neg
                raw = raw[1:].strip()
            if f in COMMA_DECIMAL_FORMATS:
                raw = raw.replace(".", "").replace(" ", "").replace(" ", "").replace(",", ".")
            else:
                raw = _RE_NUM_CLEAN.sub("", raw)
            raw = raw.replace("−", "-").rstrip("%")
            try:
                base = float(raw)
            except ValueError:
                raise IxbrlParseError(f"unparseable number {text!r} (format={fmt})")
            if neg:
                base = -base
    if sign == "-":
        base = -base
    try:
        sc = int(scale) if scale not in (None, "") else 0
    except ValueError:
        sc = 0
    literal = base * (10 ** sc) if sc else base
    value = literal
    if sc < 0 and any(mk in concept for mk in COUNT_CONCEPT_MARKERS):
        value = base
    return value, literal


def _words_to_number(raw: str) -> float | None:
    s = raw.strip().lower()
    if s in ("", "no", "none", "nil", "zero"):
        return 0.0
    try:
        from word2number import w2n  # type: ignore

        return float(w2n.word_to_num(s))
    except Exception:
        try:
            return float(_RE_NUM_CLEAN.sub("", s))
        except ValueError:
            return None


def _allowed_nonnumeric(local: str) -> bool:
    return local in NONNUMERIC_ALLOW_EXACT or local.startswith(NONNUMERIC_ALLOW_PREFIXES)


# ---------------------------------------------------------------- contexts
def _parse_context(el: etree._Element) -> dict | None:
    cid = el.get("id")
    if not cid:
        return None
    instant = start = end = None
    identifier = None
    dims: dict[str, str] = {}
    for node in el.iter():
        ln = _local(node.tag)
        if ln == "instant":
            instant = (node.text or "").strip() or None
        elif ln == "startDate":
            start = (node.text or "").strip() or None
        elif ln == "endDate":
            end = (node.text or "").strip() or None
        elif ln == "identifier":
            identifier = (node.text or "").strip() or None
        elif ln == "explicitMember":
            dims[_local_qname(node.get("dimension"))] = _local_qname(node.text)
        elif ln == "typedMember":
            # rare; keep the dimension with its text content
            dims[_local_qname(node.get("dimension"))] = "".join(node.itertext()).strip()
    instant = parse_date(instant) if instant else None
    start = parse_date(start) if start else None
    end = parse_date(end) if end else None
    period_type = "instant" if instant else "duration"
    within, after = maturity_flags(dims)
    return {
        "id": cid,
        "identifier": identifier,
        "period_type": period_type,
        "instant": instant,
        "start": start,
        "end": end,
        "dims": dims,
        "is_within_one_year": within,
        "is_after_one_year": after,
    }


def maturity_flags(dims: dict[str, str]) -> tuple[bool, bool]:
    """(is_within_one_year, is_after_one_year) from dimension members. FRS 102 filers use
    MaturitiesOrExpirationPeriodsDimension=WithinOneYear/AfterOneYear; micro-entity (FRS 105)
    filers use FinancialInstrumentCurrentNon-currentDimension=CurrentFinancialInstruments /
    Non-currentFinancialInstruments for the same split."""
    members = " ".join(dims.values())
    within = "WithinOneYear" in members or "CurrentFinancialInstruments" in members.replace(
        "Non-currentFinancialInstruments", "")
    after = ("AfterOneYear" in members or "AfterMoreThanOneYear" in members
             or "Non-currentFinancialInstruments" in members)
    return within, after


def _parse_units(root: etree._Element) -> dict[str, str]:
    units: dict[str, str] = {}
    for u in root.iter("{*}unit"):
        uid = u.get("id")
        if not uid:
            continue
        measures = [_local_qname(m.text) for m in u.iter("{*}measure") if m.text]
        if measures:
            units[uid] = "/".join(measures) if len(measures) > 1 else measures[0]
    return units


# ---------------------------------------------------------------- main
def _load_tree(path: str) -> etree._Element:
    parser = etree.XMLParser(huge_tree=True, recover=False, resolve_entities=False,
                             remove_comments=True, no_network=True)
    try:
        return etree.parse(path, parser).getroot()
    except etree.XMLSyntaxError:
        parser = etree.XMLParser(huge_tree=True, recover=True, resolve_entities=False,
                                 remove_comments=True, no_network=True)
        root = etree.parse(path, parser).getroot()
        if root is None:
            raise IxbrlParseError(f"could not parse {path}")
        return root


def parse_file(path: str) -> dict:
    root = _load_tree(str(path))
    root_local = _local(root.tag)
    if root_local == "xbrl":
        return _parse_plain_xbrl(root)
    return _parse_inline(root)


def _fact_from_context(ctx: dict | None, context_id: str) -> dict:
    if ctx is None:
        return {"context_id": context_id, "period_type": None, "instant": None, "start": None,
                "end": None, "dims": {}, "is_within_one_year": False, "is_after_one_year": False}
    return {
        "context_id": context_id,
        "period_type": ctx["period_type"],
        "instant": ctx["instant"],
        "start": ctx["start"],
        "end": ctx["end"],
        "dims": ctx["dims"],
        "is_within_one_year": ctx["is_within_one_year"],
        "is_after_one_year": ctx["is_after_one_year"],
    }


def _parse_inline(root: etree._Element) -> dict:
    contexts: dict[str, dict] = {}
    for c in root.iter("{*}context"):
        ctx = _parse_context(c)
        if ctx:
            contexts[ctx["id"]] = ctx
    units = _parse_units(root)

    facts: list[dict] = []
    nonnumeric: dict[str, str] = {}
    officers: list[str] = []
    n_numeric = 0
    for el in root.iter("{*}nonFraction", "{*}nonNumeric"):
        ln = _local(el.tag)
        name = el.get("name") or ""
        concept = _local_qname(name)
        cref = el.get("contextRef") or ""
        if ln == "nonFraction":
            n_numeric += 1
            if el.get(f"{{{XSI_NS}}}nil") == "true":
                continue
            text = _text_excluding(el)
            value, literal = parse_number(text, el.get("format"), el.get("scale"),
                                          el.get("sign"), concept)
            if value is None:
                continue
            uref = el.get("unitRef") or ""
            fact = {
                "concept": concept,
                "prefix": name.rpartition(":")[0],
                "value": value,
                "value_literal": literal,
                "unit": units.get(uref, uref),
                "decimals": el.get("decimals"),
                "scale": el.get("scale"),
                "sign": el.get("sign"),
                "format": el.get("format"),
            }
            fact.update(_fact_from_context(contexts.get(cref), cref))
            facts.append(fact)
        else:
            if not _allowed_nonnumeric(concept):
                continue
            fmt = _local_qname(el.get("format")).lower() if el.get("format") else ""
            if fmt in TRUE_FORMATS:
                text = "true"
            elif fmt in FALSE_FORMATS:
                text = "false"
            elif fmt in NONE_FORMATS:
                text = ""
            else:
                text = " ".join(_text_excluding(el).split())
            if concept in DATE_CONCEPTS:
                text = parse_date(text) or text
            if concept.startswith("NameEntityOfficer"):
                if text and text not in officers:
                    officers.append(text)
            if text and concept not in nonnumeric:
                nonnumeric[concept] = text

    return _assemble(contexts, facts, nonnumeric, officers, "ixbrl", n_numeric)


def _parse_plain_xbrl(root: etree._Element) -> dict:
    """Plain XBRL instance (xbrli:xbrl root with concept elements as children)."""
    contexts: dict[str, dict] = {}
    for c in root.iter("{*}context"):
        ctx = _parse_context(c)
        if ctx:
            contexts[ctx["id"]] = ctx
    units = _parse_units(root)
    facts: list[dict] = []
    nonnumeric: dict[str, str] = {}
    officers: list[str] = []
    n_numeric = 0
    for el in root:
        ln = _local(el.tag)
        if ln in ("context", "unit", "schemaRef", "linkbaseRef", "roleRef", "arcroleRef", "") or not ln:
            continue
        cref = el.get("contextRef")
        if cref is None:
            continue
        uref = el.get("unitRef")
        text = "".join(el.itertext()).strip()
        if uref is not None:
            n_numeric += 1
            if el.get(f"{{{XSI_NS}}}nil") == "true" or text == "":
                continue
            try:
                value, literal = parse_number(text, None, None, None, ln)
            except IxbrlParseError:
                continue
            if value is None:
                continue
            fact = {
                "concept": ln, "prefix": root.nsmap and _prefix_for(root, el.tag) or "",
                "value": value, "value_literal": literal, "unit": units.get(uref, uref),
                "decimals": el.get("decimals"), "scale": None, "sign": None, "format": None,
            }
            fact.update(_fact_from_context(contexts.get(cref), cref))
            facts.append(fact)
        elif _allowed_nonnumeric(ln):
            if ln in DATE_CONCEPTS:
                text = parse_date(text) or text
            if ln.startswith("NameEntityOfficer") and text and text not in officers:
                officers.append(text)
            if text and ln not in nonnumeric:
                nonnumeric[ln] = text
    return _assemble(contexts, facts, nonnumeric, officers, "xbrl", n_numeric)


def _prefix_for(root: etree._Element, tag: str) -> str:
    ns = tag.rpartition("}")[0].lstrip("{")
    for p, u in (root.nsmap or {}).items():
        if u == ns:
            return p or ""
    return ""


def _assemble(contexts: dict, facts: list[dict], nonnumeric: dict, officers: list[str],
              kind: str, n_numeric: int) -> dict:
    # Dimension members seen across all contexts (accounts type, standard, status live here).
    dimensions: dict[str, list[str]] = {}
    for ctx in contexts.values():
        for d, m in ctx["dims"].items():
            lst = dimensions.setdefault(d, [])
            if m not in lst:
                lst.append(m)

    # Company number: tagged fact first, else the most common context identifier.
    company_number = nonnumeric.get("UKCompaniesHouseRegisteredNumber")
    if not company_number:
        ids: dict[str, int] = {}
        for ctx in contexts.values():
            if ctx["identifier"]:
                ids[ctx["identifier"]] = ids.get(ctx["identifier"], 0) + 1
        if ids:
            company_number = max(ids, key=ids.get)
    if company_number:
        company_number = company_number.strip().upper().replace(" ", "")
        if company_number.isdigit():
            company_number = company_number.zfill(8)

    # Period end: tagged BalanceSheetDate / EndDate, else the duration context most used by
    # facts, else the latest end date among contexts.
    period_end = _iso_or_none(nonnumeric.get("BalanceSheetDate")) or \
        _iso_or_none(nonnumeric.get("EndDateForPeriodCoveredByReport"))
    period_start = _iso_or_none(nonnumeric.get("StartDateForPeriodCoveredByReport"))
    if not period_end:
        counts: dict[str, int] = {}
        for f in facts:
            e = f["end"] or f["instant"]
            if e and not f["dims"]:
                counts[e] = counts.get(e, 0) + 1
        if counts:
            period_end = max(counts, key=lambda k: (counts[k], k))
        else:
            ends = [c["end"] or c["instant"] for c in contexts.values() if (c["end"] or c["instant"])]
            period_end = max(ends) if ends else None
    if not period_start and period_end:
        starts: dict[str, int] = {}
        for c in contexts.values():
            if c["period_type"] == "duration" and c["end"] == period_end and c["start"]:
                starts[c["start"]] = starts.get(c["start"], 0) + 1
        if starts:
            period_start = max(starts, key=starts.get)
    balance_sheet_date = _iso_or_none(nonnumeric.get("BalanceSheetDate")) or period_end
    entity_name = nonnumeric.get("EntityCurrentLegalOrRegisteredName") or \
        nonnumeric.get("EntityCurrentLegalName")

    return {
        "company_number": company_number,
        "period_start": period_start,
        "period_end": period_end,
        "balance_sheet_date": balance_sheet_date,
        "entity_name": entity_name,
        "facts": facts,
        "nonnumeric": nonnumeric,
        "dimensions": dimensions,
        "officers": officers,
        "kind": kind,
        "n_numeric": n_numeric,
        "n_contexts": len(contexts),
    }


def _iso_or_none(s: str | None) -> str | None:
    if not s:
        return None
    return s if _RE_ISO.match(s) else parse_date(s)


# ---------------------------------------------------------------- derived meta
def accounts_type(parsed: dict) -> str | None:
    """FilletedAccounts / FullAccounts / AbridgedAccounts / MicroEntityAccounts ... from the
    AccountsTypeDimension member, falling back to legacy nonNumeric facts."""
    dims = parsed.get("dimensions", {})
    for d in ("AccountsTypeDimension",):
        if dims.get(d):
            return dims[d][0]
    nn = parsed.get("nonnumeric", {})
    for k, v in nn.items():
        if k.startswith("AccountsType") or k == "EntityAccountsType":
            return v
    return None


def accounting_standard(parsed: dict) -> str | None:
    dims = parsed.get("dimensions", {})
    for d in ("AccountingStandardsDimension", "AccountingStandardsAppliedDimension"):
        if dims.get(d):
            return dims[d][0]
    return None


def audit_status(parsed: dict) -> str | None:
    dims = parsed.get("dimensions", {})
    if dims.get("AccountsStatusDimension"):
        return dims["AccountsStatusDimension"][0]
    nn = parsed.get("nonnumeric", {})
    for k, v in nn.items():
        if k.startswith("AccountsStatus"):
            return v
    return None


def is_dormant(parsed: dict) -> bool | None:
    """EntityDormantTruefalse carries 'true'/'false' (format-normalised), but some filers
    write '0', 'FALSE' or a sentence ('The company was not dormant during the period')."""
    v = parsed.get("nonnumeric", {}).get("EntityDormantTruefalse")
    if v is None:
        return None
    s = v.strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no", ""):
        return False
    if "not dormant" in s or "was trading" in s:
        return False
    if "dormant" in s:
        return True
    return None


# ---------------------------------------------------------------- fallback
def parse_file_ixbrlparse(path: str) -> dict:
    """Fallback using ixbrlparse (slow). Produces the same dict shape."""
    from ixbrlparse import IXBRL  # type: ignore

    x = IXBRL.open(str(path), raise_on_error=False)
    contexts: dict[str, dict] = {}
    for cid, c in x.contexts.items():
        dims = {}
        for seg in (c.segments or []):
            if seg.get("dimension"):
                dims[_local_qname(seg["dimension"])] = _local_qname(seg.get("value"))
        instant = c.instant.isoformat() if c.instant else None
        start = c.startdate.isoformat() if c.startdate else None
        end = c.enddate.isoformat() if c.enddate else None
        within, after = maturity_flags(dims)
        contexts[cid] = {
            "id": cid, "identifier": (c.entity or {}).get("identifier"),
            "period_type": "instant" if instant else "duration",
            "instant": instant, "start": start, "end": end, "dims": dims,
            "is_within_one_year": within,
            "is_after_one_year": after,
        }
    facts: list[dict] = []
    for n in x.numeric:
        if n.value is None:
            continue
        cid = n.context.id if hasattr(n.context, "id") else str(n.context)
        concept = n.name or ""
        value = float(n.value)
        literal = value
        sc = getattr(n.format, "scale", 0) or 0
        if sc < 0 and any(mk in concept for mk in COUNT_CONCEPT_MARKERS):
            value = value / (10 ** sc)
        fact = {
            "concept": concept, "prefix": n.schema, "value": value, "value_literal": literal,
            "unit": _local_qname(n.unit) if isinstance(n.unit, str) else None,
            "decimals": None, "scale": str(sc) if sc else None,
            "sign": getattr(n.format, "sign", None) or None,
            "format": getattr(n.format, "format", None),
        }
        fact.update(_fact_from_context(contexts.get(cid), cid))
        facts.append(fact)
    nonnumeric: dict[str, str] = {}
    officers: list[str] = []
    for nn in x.nonnumeric:
        concept = nn.name or ""
        if not _allowed_nonnumeric(concept):
            continue
        v = nn.value
        if isinstance(v, (dt.date, dt.datetime)):
            text = v.isoformat()[:10]
        elif isinstance(v, bool):
            text = "true" if v else "false"
        else:
            text = " ".join(str(v or "").split())
        if concept in DATE_CONCEPTS:
            text = parse_date(text) or text
        if concept.startswith("NameEntityOfficer") and text and text not in officers:
            officers.append(text)
        if text and concept not in nonnumeric:
            nonnumeric[concept] = text
    kind = "ixbrl" if getattr(x, "filetype", "ixbrl") == "ixbrl" else "xbrl"
    return _assemble(contexts, facts, nonnumeric, officers, kind, len(x.numeric))


def parse_with_fallback(path: str) -> tuple[dict, str]:
    """Lean parser first; ixbrlparse if it raises. Returns (parsed, parser_name)."""
    try:
        return parse_file(path), "lean"
    except Exception:
        return parse_file_ixbrlparse(path), "ixbrlparse"
