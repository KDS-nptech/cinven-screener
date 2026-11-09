"""Stage 3: founder-ownership rules. Produces the `universe` table.

    python -m src.filter.ownership                       # real data under data/parquet
    python -m src.filter.ownership --parquet-dir <dir>   # fixtures (tests)

Inputs under <parquet_dir>:
    size_age.parquet      Stage 2 output (built here if missing)
    psc/ or psc.parquet   PSC register rows (Stage 1a)
    officers.parquet      optional (Stage 4a); absence caps confidence at medium
    filings.parquet       optional (Stage 4a); absence leaves sh01_count NULL

Output: <parquet_dir>/universe.parquet, one row per company that passes Stage 2,
plus <docs_dir>/funnel_stage3.json with the founder_flag distribution.

The rules run in order and the first that fires decides founder_flag,
founder_confidence and exclusion_reason. Every parameter (statement kinds,
band midpoints, thresholds, investor lists) is read from config.ownership.
docs/methodology_ownership.md explains the rules in plain English.
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass, field

import duckdb
import polars as pl

from src.common import cfg, get_logger, normalise_company_number, now_iso
from src.filter.universe import fetch_frame, register_view, resolve_dirs, source, write_table
from src.filter import universe as stage2

log = get_logger("ownership")

# ---------------------------------------------------------------- constants
KIND_INDIVIDUAL = "individual"
KIND_CORPORATE = ("corporate-entity", "legal-person")
KIND_SUPER = "super-secure"
KIND_STATEMENT = ("statement", "exemptions")

OVERSEAS_BAND = "ownership-of-shares-more-than-25-percent-registered-overseas-entity"
BAND_RE = re.compile(
    r"^(ownership-of-shares|voting-rights|right-to-share-surplus-assets)"
    r"-(25-to-50|50-to-75|75-to-100)-percent"
    r"(?:-as-trust|-as-firm)?(?:-limited-liability-partnership|-registered-overseas-entity)?$"
)
TRUST_SUFFIXES = ("-as-trust", "-as-firm")

UK_WORDS = ["ENGLAND AND WALES", "ENGLAND", "WALES", "SCOTLAND", "NORTHERN IRELAND", "UNITED KINGDOM",
            "GREAT BRITAIN", "BRITAIN", "UK", "GB", "GBR"]
UK_PLACE_WORDS = ["COMPANIES HOUSE", "REGISTRAR OF COMPANIES", "COMPANIES REGISTRY"]
JUNK_COUNTRY = {"", "N/A", "NA", "NONE", "NOT APPLICABLE", "UNKNOWN", "NOT KNOWN", "-", "."}
UNKNOWN_COUNTRY_MARKERS = ["NOT SPECIFIED", "NOT APPLICABLE", "UNKNOWN", "NOT KNOWN", "OTHER", "NONE", "VARIOUS"]
UK_LEGAL_WORDS = ["LIMITED", "LTD", "LLP", "PLC", "PRIVATE COMPANY", "COMPANY LIMITED"]
CH_PREFIX_RE = re.compile(r"^(SC|NI|OC|SO|NC|SL|LP|FC|SF|GE|IP|RS|ZC|AC|BR|CE|CS|ES|EW|GN|GS|IC|NA|NF|NL|NO|NP|NR|NV|NZ|PC|R|RC|SA|SE|SG|SI|SP|SR|SZ)[0-9]{6,7}$")

TITLES = {"MR", "MRS", "MS", "MISS", "DR", "SIR", "DAME", "LORD", "LADY", "PROF", "PROFESSOR", "MX", "REV",
          "REVEREND", "HON", "CAPT", "CAPTAIN", "MAJOR", "COL", "COLONEL", "BARON", "BARONESS", "COUNT", "COUNTESS"}
HONOURS = {"OBE", "MBE", "CBE", "KBE", "DBE", "GBE", "QC", "KC", "JP", "FCA", "ACA", "FCCA", "ACCA", "CA", "FRSA",
           "FRS", "PHD", "MBA", "BSC", "MSC", "BA", "MA", "ESQ", "JR", "SR", "SNR", "JNR", "II", "III", "IV", "DL", "TD"}

FLAG_ORDER = ["multiple_corporate_pscs", "holdco_walkup", "holdco_name_resolved", "voting_proxy", "nominee_or_trust", "super_secure",
              "no_ownership_band", "all_pscs_ceased", "director_test_unavailable", "director_test_failed",
              "owners_resident_abroad", "uk_subsidiary_name",
              "check_share_premium", "sh01_heavy", "share_premium_high"]

OUTPUT_SCHEMA = {
    "company_number": pl.String, "name": pl.String, "post_town": pl.String, "postcode": pl.String,
    "sic1": pl.String, "inc_date": pl.Date, "latest_employees": pl.Int64, "latest_period_end": pl.Date,
    "latest_turnover": pl.Float64, "account_category": pl.String, "passes_size": pl.Boolean,
    "passes_age": pl.Boolean, "provisional": pl.Boolean, "founder_flag": pl.String, "founder_confidence": pl.String,
    "exclusion_reason": pl.String, "investor_flag": pl.String, "investor_names": pl.List(pl.String),
    "flags": pl.List(pl.String), "individual_pscs_json": pl.String, "walkup_path": pl.String,
    "combined_pct_mid": pl.Float64, "n_individual_pscs": pl.Int64, "n_corporate_pscs": pl.Int64,
    "n_statements": pl.Int64, "sh01_count": pl.Int64, "share_premium_latest": pl.Float64,
    "founder_led": pl.Boolean, "computed_at": pl.String,
}


# ---------------------------------------------------------------- rules from config
@dataclass
class Rules:
    statement_kinds: set
    high_band: str
    band_mid: dict
    combined_high: float
    combined_medium: float
    max_individuals: int
    director_months: int
    walkup_levels: int
    sh01_threshold: int
    share_premium_threshold: float
    investor_names: list = field(default_factory=list)   # (label, compiled regex)
    investor_tokens: list = field(default_factory=list)  # (label, compiled regex)


def _word_regex(text: str, plural: bool = False) -> re.Pattern:
    """Whole-word, case-insensitive match of a possibly multi-word label.

    Boundaries are 'not preceded or followed by a letter or digit' so that tokens
    with punctuation ('L.P.') work and 'LP' does not match 'LPG'. `plural` allows a
    trailing S on the last word ('Fund' matches 'FUNDS').
    """
    words = [re.escape(w) for w in re.split(r"\s+", text.strip().upper()) if w]
    if not words:
        return re.compile(r"(?!x)x")  # never matches
    body = r"\s+".join(words)
    if plural:
        body += r"S?"
    return re.compile(r"(?<![A-Z0-9])" + body + r"(?![A-Z0-9])")


def compile_rules(c: dict | None = None) -> Rules:
    o = (c or cfg())["ownership"]
    return Rules(
        statement_kinds={s.strip().lower() for s in o["statement_kinds"]},
        high_band=o["high_confidence_band"].strip().lower(),
        band_mid={k.strip().lower(): float(v) for k, v in o["band_midpoints"].items()},
        combined_high=float(o["combined_high_pct"]),
        combined_medium=float(o["combined_medium_pct"]),
        max_individuals=int(o["max_individual_pscs"]),
        director_months=int(o["director_within_months_of_incorporation"]),
        walkup_levels=int(o["holdco_walkup_levels"]),
        sh01_threshold=int(o["sh01_investor_threshold"]),
        share_premium_threshold=float(o["share_premium_investor_threshold_gbp"]),
        investor_names=[(n, _word_regex(n)) for n in o["investor_names"]],
        investor_tokens=[(t, _word_regex(t, plural=True)) for t in o["investor_name_tokens"]],
    )


# ---------------------------------------------------------------- name helpers
def _norm_text(s) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).upper().replace("&", " AND ")).strip()


def investor_match(name, rules: Rules) -> list[str]:
    """Labels from config.ownership.investor_names / investor_name_tokens that the name matches."""
    raw = _norm_text(name)
    if not raw:
        return []
    nodots = re.sub(r"\s+", " ", raw.replace(".", " ")).strip()
    hits = []
    for label, rx in rules.investor_names:
        if rx.search(raw) or rx.search(nodots):
            hits.append(label)
    for label, rx in rules.investor_tokens:
        if rx.search(raw) or rx.search(nodots):
            hits.append(label.strip())
    # Employee ownership trusts: the founders have sold to the trust, so the company is not founder-owned.
    if re.search(r"\bEOT\b|EMPLOYEE[- ]OWN|EMPLOYEE BENEFIT TRUST|\bEBT\b|\(EOT\)", (name or ""), re.I):
        hits.append("employee ownership trust")
    return hits


def person_key(name) -> tuple[str, str] | None:
    """(surname, first forename) in lower case letters only, titles and honours stripped.

    Accepts 'Mr John Michael Smith' (PSC style) and 'SMITH, John Michael' (officer style).
    """
    if not name:
        return None
    s = str(name).strip()
    if "," in s:
        surname, _, rest = s.partition(",")
        forenames = rest.split()
    else:
        toks = s.split()
        while toks and re.sub(r"[^A-Za-z]", "", toks[-1]).upper() in HONOURS:
            toks.pop()
        if not toks:
            return None
        surname = toks[-1]
        forenames = toks[:-1]
    forenames = [t for t in forenames if re.sub(r"[^A-Za-z]", "", t).upper() not in TITLES]
    sur = re.sub(r"[^a-z]", "", surname.lower())
    first = re.sub(r"[^a-z]", "", forenames[0].lower()) if forenames else ""
    if not sur:
        return None
    return (sur, first)


def person_key_from_row(row) -> tuple[str, str] | None:
    """Prefer the register's split name_surname / name_forename; fall back to parsing `name`."""
    sur, fore = row.get("name_surname"), row.get("name_forename")
    if sur:
        s = re.sub(r"[^a-z]", "", str(sur).lower())
        toks = [t for t in str(fore or "").split() if re.sub(r"[^A-Za-z]", "", t).upper() not in TITLES]
        f = re.sub(r"[^a-z]", "", toks[0].lower()) if toks else ""
        if s:
            return (s, f)
    return person_key(row.get("name"))


def same_person(a: tuple | None, b: tuple | None) -> bool:
    if not a or not b:
        return False
    if a[1] != b[1] or not a[1]:
        return False
    sa, sb = a[0], b[0]
    if sa == sb:
        return True
    # 'vanderberg' vs 'berg' when a multi-word surname is split differently
    shorter, longer = sorted((sa, sb), key=len)
    return len(shorter) >= 3 and longer.endswith(shorter)


# ---------------------------------------------------------------- PSC row helpers
def _kind(row) -> str:
    return str(row.get("kind") or "").lower()


def is_statement(row) -> bool:
    k = _kind(row)
    return any(t in k for t in KIND_STATEMENT) or (not k and row.get("statement"))


def is_corporate(row) -> bool:
    return any(t in _kind(row) for t in KIND_CORPORATE)


def is_individual(row) -> bool:
    return _kind(row).startswith(KIND_INDIVIDUAL)


def is_super_secure(row) -> bool:
    return KIND_SUPER in _kind(row)


def is_active(row) -> bool:
    v = row.get("is_active")
    if v is None:
        return row.get("ceased_on") is None
    return bool(v)


def _statement_value(row) -> str:
    return str(row.get("statement") or "").strip().lower()


def dispersed_statements(stmts: list, rules: Rules) -> bool:
    """True when every statement is one of the configured 'nobody holds 25%' kinds (or an exemption)."""
    if not stmts:
        return False
    for s in stmts:
        if "exemptions" in _kind(s):
            continue
        if _statement_value(s) not in rules.statement_kinds:
            return False
    return True


def parse_bands(natures, rules: Rules) -> dict:
    """Pick the ownership band (else the voting band as proxy) from a natures_of_control list."""
    natures = [str(n).strip().lower() for n in (natures or []) if n]
    own, vote = [], []
    for n in natures:
        if n.startswith(OVERSEAS_BAND):
            own.append(OVERSEAS_BAND)
            continue
        m = BAND_RE.match(n)
        if not m:
            continue
        base = f"ownership-of-shares-{m.group(2)}-percent"
        if m.group(1) == "ownership-of-shares":
            own.append(base)
        else:
            vote.append(base)
    trust_or_firm_only = bool(natures) and all(any(t in n for t in TRUST_SUFFIXES) for n in natures)
    band, proxy = None, False
    if own:
        band = max(own, key=lambda b: rules.band_mid.get(b, 0.0))
    elif vote:
        band = max(vote, key=lambda b: rules.band_mid.get(b, 0.0))
        proxy = True
    mid = rules.band_mid.get(band, 0.0) if band else 0.0
    return {"natures": natures, "band": band, "mid": mid, "voting_proxy": proxy, "trust_or_firm_only": trust_or_firm_only}


def norm_reg_number(v) -> str | None:
    """Companies House number from a PSC corporate_reg_number, or None when it is not one."""
    if v is None:
        return None
    s = re.sub(r"[^A-Z0-9]", "", str(v).upper())
    s = re.sub(r"^(COMPANYNUMBER|COMPANYNO|REGNO|REGISTRATIONNUMBER|REGISTRATIONNO|NUMBER|CRN|NO)(?=[0-9])", "", s)
    if not s:
        return None
    if s.isdigit():
        return s.zfill(8) if len(s) <= 8 else None
    if CH_PREFIX_RE.match(s):
        return s.zfill(8) if len(s) < 8 else s
    return None


def _has_word(text: str, words: list[str]) -> bool:
    for w in words:
        if re.search(r"(?<![A-Z])" + re.escape(w) + r"(?![A-Z])", text):
            return True
    return False


def classify_corporate(row) -> tuple[str, str | None]:
    """('uk', reg) when the corporate PSC can be looked up on the register, ('foreign', None)
    when registered outside the UK, ('unresolved', None) otherwise."""
    country = _norm_text(row.get("country_registered"))
    country = re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", " ", country)).strip()
    place = re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", " ", _norm_text(row.get("place_registered")))).strip()
    legal = _norm_text(row.get("legal_form"))
    reg = norm_reg_number(row.get("corporate_reg_number"))

    country_uk = _has_word(country, UK_WORDS)
    country_known = country not in JUNK_COUNTRY and not any(m in country for m in UNKNOWN_COUNTRY_MARKERS)
    country_foreign = country_known and not country_uk
    place_uk = _has_word(place, UK_WORDS) or _has_word(place, UK_PLACE_WORDS)
    legal_uk = _has_word(legal, UK_LEGAL_WORDS)

    if country_foreign and not place_uk:
        return ("foreign", None)
    if reg and (country_uk or place_uk or legal_uk or not country_known):
        return ("uk", reg)
    return ("unresolved", None)


# ---------------------------------------------------------------- evaluation
def _add_months(d: dt.date, months: int) -> dt.date:
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _to_date(v) -> dt.date | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _person_key_of(p: dict) -> tuple[str, str] | None:
    if p.get("surname"):
        return (p["surname"], p.get("forename") or "")
    return person_key(p.get("name"))


def director_test(persons: list[dict], officers: list[dict], inc_date, rules: Rules) -> bool:
    """At least one PSC individual was appointed director within N months of incorporation."""
    inc = _to_date(inc_date)
    if inc is None or not officers:
        return False
    cutoff = _add_months(inc, rules.director_months)
    keys = [_person_key_of(p) for p in persons]
    for o in officers:
        role = str(o.get("role") or "").lower()
        if "director" not in role:
            continue
        appointed = _to_date(o.get("appointed_on"))
        if appointed is None or appointed < inc or appointed > cutoff:
            continue
        ok = person_key(o.get("name"))
        if any(same_person(k, ok) for k in keys):
            return True
    return False


_SUBSIDIARY_NAME_RE = re.compile(r"\b(UK|U\.K\.|GREAT BRITAIN|GB|EUROPE|EMEA|INTERNATIONAL)\b\s*(LIMITED|LTD\.?|PLC)?\s*$|\((UK|GB|EUROPE)\)", re.I)


def _subsidiary_name(name: str | None) -> bool:
    """Names like 'Acme UK Ltd', 'Acme (UK) Limited', 'Acme Europe Ltd' usually mark a foreign group's subsidiary."""
    return bool(name) and bool(_SUBSIDIARY_NAME_RE.search(name.strip()))


def _person(row, rules: Rules, via_holdco=False, holdco=None, holdco_mid=None) -> dict:
    b = parse_bands(row.get("natures_of_control"), rules)
    mid = b["mid"]
    if via_holdco and holdco_mid is not None and mid:
        mid = round(mid * holdco_mid / 100.0, 2)
    key = person_key_from_row(row)
    return {
        "name": row.get("name"),
        "surname": key[0] if key else None,
        "forename": key[1] if key else None,
        "bands": b["natures"],
        "band": b["band"],
        "pct_mid": mid,
        "notified_on": (str(row.get("notified_on"))[:10] if row.get("notified_on") is not None else None),
        "via_holdco": via_holdco,
        "holdco": holdco,
        "holdco_pct_mid": holdco_mid,
        "voting_proxy": b["voting_proxy"],
        "trust_or_firm": b["trust_or_firm_only"],
        "country_of_residence": row.get("country_of_residence"),
        "nationality": row.get("nationality"),
    }


@dataclass
class _Walk:
    pending: str | None = None
    investor_names: list = field(default_factory=list)
    persons: list = field(default_factory=list)
    supers: list = field(default_factory=list)
    paths: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    visited: set = field(default_factory=set)


def _flag(flags: list, name: str) -> None:
    if name not in flags:
        flags.append(name)


def _split(active: list):
    stmts = [r for r in active if is_statement(r)]
    corps = [r for r in active if is_corporate(r)]
    inds = [r for r in active if is_individual(r)]
    supers = [r for r in active if is_super_secure(r)]
    return stmts, corps, inds, supers


def lookup_key(name) -> str:
    """Register-name key for the name fallback: upper case, single spaces."""
    return re.sub(r"\s+", " ", str(name or "").upper()).strip()


def resolve_corporate(row, name_lookup: dict[str, str] | None = None) -> tuple[str, str | None, bool]:
    """classify_corporate plus a fallback: a UK-looking corporate PSC with no usable registration
    number is matched by exact name against companies.parquet. Returns (kind, reg, by_name)."""
    kind, reg = classify_corporate(row)
    if kind == "unresolved" and name_lookup:
        found = name_lookup.get(lookup_key(row.get("name")))
        if found:
            return ("uk", found, True)
    return (kind, reg, False)


def _walk(cn: str, corps: list, psc_index: dict, rules: Rules, depth: int, path: str, scale: float, w: _Walk,
          name_lookup: dict[str, str] | None = None) -> str | None:
    """Walk up each non-investor corporate PSC. Returns 'investor_present' or 'dispersed' when the
    holdco excludes the operating company; otherwise None, with individuals and pending reasons on `w`."""
    for c in corps:
        kind, reg, by_name = resolve_corporate(c, name_lookup)
        hold = parse_bands(c.get("natures_of_control"), rules)
        # The holdco's own stake in the company below. A 75-100 band is read as wholly owned
        # (the usual holdco structure) so that band midpoints do not compound down a stack;
        # smaller bands scale the individuals' midpoints to their look-through stake.
        if not hold["band"]:
            hold_mid = None
        elif hold["band"] == rules.high_band:
            hold_mid = scale
        else:
            hold_mid = hold["mid"] * scale / 100.0
        if kind == "foreign":
            w.pending = w.pending or "foreign_corporate"
            continue
        if kind != "uk" or reg == cn or reg in w.visited or depth >= rules.walkup_levels:
            w.pending = w.pending or "corporate_unresolved"
            continue
        w.visited.add(reg)
        if by_name:
            _flag(w.flags, "holdco_name_resolved")
        active = [r for r in psc_index.get(reg, []) if is_active(r)]
        if not active:
            w.pending = w.pending or "corporate_unresolved"
            continue
        h_stmts, h_corps, h_inds, h_supers = _split(active)
        inv = [r.get("name") for r in h_corps if investor_match(r.get("name"), rules)]
        if inv:
            w.investor_names.extend(inv)
            return "investor_present"
        if h_stmts and not (h_corps or h_inds or h_supers) and dispersed_statements(h_stmts, rules):
            return "dispersed"
        _flag(w.flags, "holdco_walkup")
        here = f"{path} -> {reg}"
        w.paths.append(here)
        for r in h_inds:
            w.persons.append(_person(r, rules, via_holdco=True, holdco=reg, holdco_mid=hold_mid))
        w.supers.extend(h_supers)
        if h_corps:
            res = _walk(reg, h_corps, psc_index, rules, depth + 1, here, (hold_mid or 100.0), w, name_lookup)
            if res:
                return res
    return None


def evaluate(company: dict, psc_index: dict, officers: list[dict] | None, sh01_count: int | None,
             share_premium: float | None, rules: Rules, officers_available: bool,
             name_lookup: dict[str, str] | None = None) -> dict:
    """Apply rules 1 to 8 to one company. `officers` is the list of its officer rows (any role)."""
    cn = company["company_number"]
    rows = psc_index.get(cn, [])
    active = [r for r in rows if is_active(r)]
    stmts, corps, inds, supers = _split(active)
    flags: list[str] = []
    persons = [_person(r, rules) for r in inds]  # direct individuals, recorded even when excluded
    out = {
        "founder_flag": None, "founder_confidence": None, "exclusion_reason": None,
        "investor_flag": "none", "investor_names": [], "flags": flags, "persons": persons, "founder_led": False,
        "walkup_path": None, "combined_pct_mid": 0.0,
        "n_individual_pscs": len(inds), "n_corporate_pscs": len(corps), "n_statements": len(stmts),
    }

    def finish(flag, conf, reason=None):
        out["founder_flag"], out["founder_confidence"], out["exclusion_reason"] = flag, conf, reason
        # Founder-led is wider than founder-owned: a direct or walked-up individual at 25%+ who passes the
        # founding-director test, whatever else sits on the register (a VC, a holdco, a trust). That is the
        # measured Brighton Park pattern (80% founder-led at entry, 25% first institutional capital).
        # Owners resident abroad stay out (UK subsidiaries of foreign founder-led groups).
        led = [p for p in out["persons"] if (p.get("pct_mid") or 0) >= 25 and not p.get("trust_or_firm")]
        if flag == "founder":
            out["founder_led"] = True
        elif led and "owners_resident_abroad" not in flags and officers_available and officers:
            out["founder_led"] = bool(director_test(led, officers, company.get("inc_date"), rules))
        else:
            out["founder_led"] = False
        return out

    # Rule 1: nothing on the register for this company.
    if not rows:
        return _second_check(finish("uncertain", "low", "no_psc"), sh01_count, share_premium, rules)
    if not active:
        _flag(flags, "all_pscs_ceased")
        return _second_check(finish("uncertain", "low", "no_psc"), sh01_count, share_premium, rules)

    # Rule 2: only statements, and they say nobody reaches 25%.
    if stmts and not (corps or inds or supers):
        if dispersed_statements(stmts, rules):
            return finish("excluded", None, "dispersed")
        # A statement such as 'psc-contacted-but-no-response' says a PSC exists but is unidentified.
        return _second_check(finish("uncertain", "low", "no_psc"), sh01_count, share_premium, rules)

    # Rule 3: an investor sits on the register directly.
    inv = [r.get("name") for r in corps if investor_match(r.get("name"), rules)]
    if inv:
        out["investor_flag"], out["investor_names"] = "present", inv
        return finish("excluded", None, "investor_present")

    # Rule 4: walk up UK holding companies.
    w = _Walk()
    if corps:
        if len(corps) >= 2:
            _flag(flags, "multiple_corporate_pscs")
        res = _walk(cn, corps, psc_index, rules, 0, cn, 100.0, w, name_lookup)
        for f in w.flags:
            _flag(flags, f)
        if w.paths:
            out["walkup_path"] = "; ".join(w.paths)
        if res == "investor_present":
            out["investor_flag"], out["investor_names"] = "present", w.investor_names
            return finish("excluded", None, "investor_present")
        if res == "dispersed":
            return finish("excluded", None, "dispersed")
        persons.extend(w.persons)
        supers = supers + w.supers

    out["persons"] = persons
    out["n_individual_pscs"] = len(persons)
    out["combined_pct_mid"] = round(min(100.0, sum(p["pct_mid"] for p in persons)), 2)
    if w.pending:
        return _second_check(finish("uncertain", "low", w.pending), sh01_count, share_premium, rules)

    # Rule 7 gates: anything that stops us reading the individuals as the owners.
    if supers:
        _flag(flags, "super_secure")
        return _second_check(finish("uncertain", "low"), sh01_count, share_premium, rules)
    if not persons:
        return _second_check(finish("uncertain", "low", "no_psc"), sh01_count, share_premium, rules)
    keys = [_person_key_of(p) for p in persons]
    distinct = len({k for k in keys if k}) + sum(1 for k in keys if not k)
    if distinct > rules.max_individuals:
        return _second_check(finish("uncertain", "low"), sh01_count, share_premium, rules)
    trust = [p for p in persons if p["trust_or_firm"]]
    if trust:
        _flag(flags, "nominee_or_trust")
        if len(trust) == len(persons):
            return _second_check(finish("uncertain", "low"), sh01_count, share_premium, rules)
    if not any(p["band"] for p in persons):
        _flag(flags, "no_ownership_band")
        return _second_check(finish("uncertain", "low"), sh01_count, share_premium, rules)
    if any(p["voting_proxy"] for p in persons):
        _flag(flags, "voting_proxy")

    # Residency: a UK company whose individual owners all live abroad is almost always the UK
    # subsidiary of a founder-led foreign group (Backbase, Ripple, Linedata), not a UK target.
    # It is kept as a comparable, not ranked.
    UK_RES = {"ENGLAND", "WALES", "SCOTLAND", "NORTHERN IRELAND", "UNITED KINGDOM", "UK", "GREAT BRITAIN", "ISLE OF MAN", "JERSEY", "GUERNSEY"}
    res = [str(p.get("country_of_residence") or "").strip().upper() for p in persons]
    known = [r for r in res if r]
    if known and all(r not in UK_RES for r in known):
        _flag(flags, "owners_resident_abroad")
        return _second_check(finish("uncertain", "low", "owners_resident_abroad"), sh01_count, share_premium, rules)
    if _subsidiary_name(company.get("name")):
        _flag(flags, "uk_subsidiary_name")

    # Rules 5 and 6: ownership tests, then the director test.
    combined = out["combined_pct_mid"]
    holds_high = any(
        p["band"] == rules.high_band and (not p["via_holdco"] or p["holdco_pct_mid"] is None
                                         or p["holdco_pct_mid"] >= rules.band_mid.get(rules.high_band, 0))
        for p in persons
    )
    high_ownership = holds_high or combined >= rules.combined_high
    medium_ownership = combined >= rules.combined_medium
    # Officers may exist for only part of the universe (Stage 4a pulls them in batches); a company
    # with no officer rows is "unavailable", not "failed".
    company_officers_available = officers_available and bool(officers)
    officers_available = company_officers_available
    directors_ok = director_test(persons, officers or [], company.get("inc_date"), rules) if officers_available else None

    if high_ownership:
        if not officers_available:
            _flag(flags, "director_test_unavailable")
            conf = "medium"
        elif directors_ok:
            conf = "high"
        else:
            _flag(flags, "director_test_failed")
            conf = "medium"
    elif medium_ownership:
        if officers_available and not directors_ok:
            _flag(flags, "director_test_failed")
        elif not officers_available:
            _flag(flags, "director_test_unavailable")
        conf = "medium"
    else:
        return _second_check(finish("uncertain", "low"), sh01_count, share_premium, rules)

    if trust and conf == "high":
        conf = "medium"  # part of the holding sits in a trust or firm: verify before calling it high
    if conf == "medium":
        _flag(flags, "check_share_premium")
    return _second_check(finish("founder", conf), sh01_count, share_premium, rules)


def _second_check(out: dict, sh01_count, share_premium, rules: Rules) -> dict:
    """Rule 8: SH01 count and share premium hint at investors the PSC register does not show."""
    if out["founder_flag"] not in ("founder", "uncertain"):
        return out
    if sh01_count is not None and sh01_count >= rules.sh01_threshold:
        _flag(out["flags"], "sh01_heavy")
        out["investor_flag"] = "possible"
    if share_premium is not None and share_premium > rules.share_premium_threshold:
        _flag(out["flags"], "share_premium_high")
        out["investor_flag"] = "possible"
    return out


# ---------------------------------------------------------------- IO
def _cn_sql(col: str) -> str:
    return f"CASE WHEN regexp_matches(CAST({col} AS VARCHAR), '^[0-9]+$') THEN lpad(CAST({col} AS VARCHAR), 8, '0') ELSE upper(trim(CAST({col} AS VARCHAR))) END"


def _columns(con, view: str) -> dict[str, str]:
    """column name -> DuckDB type for a registered view."""
    return {r[0]: r[1] for r in con.execute(f'DESCRIBE "{view}"').fetchall()}


def _psc_select(con) -> str:
    want = ["kind", "name", "name_forename", "name_surname", "natures_of_control", "notified_on", "ceased_on",
            "is_active", "statement", "corporate_reg_number", "country_registered", "place_registered",
            "legal_form", "dob_year", "country_of_residence", "nationality"]
    have = _columns(con, "psc")
    parts = [f"{_cn_sql('company_number')} AS company_number"]
    for c in want:
        if c not in have:
            parts.append(f"NULL AS {c}")
        elif c == "natures_of_control":
            t = have[c].upper()
            if t.endswith("[]") or t.startswith("LIST"):
                parts.append(f"CAST({c} AS VARCHAR[]) AS {c}")
            else:  # a JSON string from an earlier flattening
                parts.append(f"TRY_CAST(TRY_CAST({c} AS JSON) AS VARCHAR[]) AS {c}")
        else:
            parts.append(f'"{c}"')
    return ", ".join(parts)


def _fetch_psc(con, numbers: list[str]) -> dict[str, list[dict]]:
    if not numbers:
        return {}
    con.register("want", pl.DataFrame({"company_number": numbers}, schema={"company_number": pl.String}).to_arrow())
    sel = _psc_select(con)
    df = fetch_frame(con, f"SELECT {sel} FROM psc WHERE {_cn_sql('company_number')} IN (SELECT company_number FROM want)")
    index: dict[str, list[dict]] = {}
    for row in df.iter_rows(named=True):
        index.setdefault(row["company_number"], []).append(row)
    return index


def _name_lookup(con, names: list[str]) -> dict[str, str]:
    """Exact register-name matches in companies.parquet; only names with a single company number."""
    if not names:
        return {}
    con.register("want_names", pl.DataFrame({"n": names}, schema={"n": pl.String}).to_arrow())
    rows = con.execute(
        f"""
        SELECT w.n, {_cn_sql('c.company_number')} AS company_number
        FROM companies c JOIN want_names w ON regexp_replace(upper(trim(c.name)), '\\s+', ' ', 'g') = w.n
        """
    ).fetchall()
    hits: dict[str, set[str]] = {}
    for n, cn in rows:
        hits.setdefault(n, set()).add(cn)
    return {n: next(iter(cns)) for n, cns in hits.items() if len(cns) == 1}


def load_universe(con, pq: pathlib.Path, docs: pathlib.Path) -> pl.DataFrame:
    if not source(pq, "size_age"):
        log.info("size_age missing under %s; running Stage 2 first", pq)
        stage2.run(pq, docs)
    register_view(con, "size_age", source(pq, "size_age"))
    cols = _columns(con, "size_age")
    sp = "latest_share_premium" if "latest_share_premium" in cols else "NULL::DOUBLE"
    prov = "COALESCE(provisional, FALSE)" if "provisional" in cols else "FALSE"
    df = fetch_frame(
        con,
        f"""
        SELECT {_cn_sql('company_number')} AS company_number, name, post_town, postcode,
               CAST(sic1 AS VARCHAR) AS sic1, inc_date, latest_employees, latest_period_end, latest_turnover,
               account_category, passes_size, passes_age, {prov} AS provisional, {sp} AS share_premium_latest
        FROM size_age WHERE passes_all ORDER BY company_number
        """,
    )
    return df


def run(parquet_dir: str | os.PathLike | None = None, docs_dir: str | os.PathLike | None = None) -> pl.DataFrame:
    pq, docs = resolve_dirs(parquet_dir, docs_dir)
    rules = compile_rules()
    con = duckdb.connect()
    uni = load_universe(con, pq, docs)
    log.info("%s companies pass Stage 2", f"{len(uni):,}")
    numbers = uni["company_number"].to_list()

    psc_src = source(pq, "psc")
    if not psc_src:
        raise FileNotFoundError(f"psc table not found under {pq}")
    register_view(con, "psc", psc_src)
    psc_index = _fetch_psc(con, numbers)
    log.info("PSC rows fetched for %s universe companies", f"{len(psc_index):,}")

    # Further passes, one per walk-up level: PSCs of every UK corporate PSC (by registration
    # number, or by exact name against companies.parquet when the number is missing).
    companies_src = source(pq, "companies")
    if companies_src:
        register_view(con, "companies", companies_src)
    name_lookup: dict[str, str] = {}
    fetched: set[str] = set(numbers)
    frontier = list(numbers)
    for level in range(rules.walkup_levels):
        regs: set[str] = set()
        names: set[str] = set()
        for cn in frontier:
            for r in psc_index.get(cn, []):
                if not (is_active(r) and is_corporate(r)) or investor_match(r.get("name"), rules):
                    continue
                kind, reg = classify_corporate(r)
                if kind == "uk":
                    regs.add(reg)
                elif kind == "unresolved" and r.get("name"):
                    names.add(lookup_key(r.get("name")))
        new_names = names - set(name_lookup)
        if new_names and companies_src:
            name_lookup.update(_name_lookup(con, sorted(new_names)))
        regs |= {name_lookup[n] for n in names if n in name_lookup}
        new = sorted(regs - fetched)
        fetched |= regs
        if new:
            psc_index.update(_fetch_psc(con, new))
            log.info("level %d: PSC rows fetched for %s holding companies (%s resolved by name)",
                     level + 1, f"{len(new):,}", f"{len(name_lookup):,}")
        frontier = sorted(regs)
        if not frontier:
            break

    con.register("uni_df", uni.select("company_number", "inc_date").to_arrow())

    officers_available = source(pq, "officers") is not None
    officers_index: dict[str, list[dict]] = {}
    if officers_available:
        register_view(con, "officers", source(pq, "officers"))
        odf = fetch_frame(
            con,
            f"""
            SELECT u.company_number, o.name, o.role, o.appointed_on, o.resigned_on
            FROM officers o JOIN uni_df u ON {_cn_sql('o.company_number')} = u.company_number
            WHERE lower(COALESCE(CAST(o.role AS VARCHAR), '')) LIKE '%director%'
            """,
        )
        for row in odf.iter_rows(named=True):
            officers_index.setdefault(row["company_number"], []).append(row)
        log.info("officer rows (directors) for %s universe companies", f"{len(officers_index):,}")
    else:
        log.warning("officers.parquet absent; director test skipped, confidence capped at medium")

    filings_available = source(pq, "filings") is not None
    sh01: dict[str, int] = {}
    if filings_available:
        register_view(con, "filings", source(pq, "filings"))
        fdf = fetch_frame(
            con,
            f"""
            SELECT u.company_number, count(*) AS n
            FROM filings f JOIN uni_df u ON {_cn_sql('f.company_number')} = u.company_number
            WHERE upper(trim(CAST(f.type AS VARCHAR))) = 'SH01'
              AND (f.date IS NULL OR u.inc_date IS NULL OR TRY_CAST(f.date AS DATE) IS NULL
                   OR TRY_CAST(f.date AS DATE) >= u.inc_date)
            GROUP BY 1
            """,
        )
        sh01 = {r["company_number"]: int(r["n"]) for r in fdf.iter_rows(named=True)}
    else:
        log.warning("filings.parquet absent; sh01_count left NULL")

    computed_at = now_iso()
    out_rows = []
    for c in uni.iter_rows(named=True):
        cn = c["company_number"]
        res = evaluate(
            c, psc_index, officers_index.get(cn), (sh01.get(cn, 0) if filings_available else None),
            c.get("share_premium_latest"), rules, officers_available, name_lookup,
        )
        out_rows.append({
            "company_number": cn, "name": c["name"], "post_town": c["post_town"], "postcode": c["postcode"],
            "sic1": c["sic1"], "inc_date": c["inc_date"], "latest_employees": c["latest_employees"],
            "latest_period_end": c["latest_period_end"], "latest_turnover": c["latest_turnover"],
            "account_category": c["account_category"], "passes_size": c["passes_size"], "passes_age": c["passes_age"],
            "provisional": bool(c.get("provisional")), "founder_flag": res["founder_flag"], "founder_confidence": res["founder_confidence"],
            "exclusion_reason": res["exclusion_reason"], "investor_flag": res["investor_flag"],
            "investor_names": list(dict.fromkeys(n for n in res["investor_names"] if n)),
            "flags": sorted(res["flags"], key=lambda f: FLAG_ORDER.index(f) if f in FLAG_ORDER else 99),
            "individual_pscs_json": json.dumps(res["persons"], default=str),
            "walkup_path": res["walkup_path"], "combined_pct_mid": res["combined_pct_mid"],
            "n_individual_pscs": res["n_individual_pscs"], "n_corporate_pscs": res["n_corporate_pscs"],
            "n_statements": res["n_statements"],
            "sh01_count": (sh01.get(cn, 0) if filings_available else None),
            "share_premium_latest": c.get("share_premium_latest"), "founder_led": bool(res.get("founder_led")), "computed_at": computed_at,
        })
    df = pl.DataFrame(out_rows, schema=OUTPUT_SCHEMA)
    out = write_table(df, pq, "universe")
    summary = summarise(df, officers_available, filings_available, computed_at)
    print_summary(summary)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "funnel_stage3.json").write_text(json.dumps(summary, indent=2))
    log.info("wrote %s (%s rows) and %s", out, f"{len(df):,}", docs / "funnel_stage3.json")
    return df


def summarise(df: pl.DataFrame, officers_available: bool, filings_available: bool, computed_at: str) -> dict:
    def counts(cols):
        if not len(df):
            return {}
        g = df.group_by(cols).len().sort(cols, nulls_last=True)
        return {" / ".join("null" if v is None else str(v) for v in row[:-1]): int(row[-1]) for row in g.iter_rows()}
    flag_counts = {}
    if len(df):
        ex = df.select(pl.col("flags").explode()).drop_nulls()
        if len(ex):
            flag_counts = {k: int(v) for k, v in ex.group_by("flags").len().sort("flags").iter_rows()}
    return {
        "computed_at": computed_at,
        "inputs": {"officers_available": officers_available, "filings_available": filings_available},
        "rows": len(df),
        "founder_flag": counts(["founder_flag"]),
        "founder_flag_confidence": counts(["founder_flag", "founder_confidence"]),
        "exclusion_reason": counts(["exclusion_reason"]),
        "investor_flag": counts(["investor_flag"]),
        "flags": flag_counts,
    }


def print_summary(s: dict) -> None:
    print(f"Stage 3 universe: {s['rows']:,} companies")
    for section in ("founder_flag_confidence", "exclusion_reason", "investor_flag", "flags"):
        print(f"  {section}:")
        for k, v in s[section].items():
            print(f"    {k.ljust(34)} {v:>8,}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parquet-dir", default=None, help="override data/parquet (used by tests)")
    ap.add_argument("--docs-dir", default=None, help="override docs/ for funnel_stage3.json")
    a = ap.parse_args(argv)
    try:
        run(a.parquet_dir, a.docs_dir)
    except FileNotFoundError as e:
        log.error("%s; upstream outputs are not there yet, nothing written", e)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
