"""Stage 3: ownership route. Reads the PSC register and says who owns each universe company and
therefore how a buyout fund would get to it.

    python -m src.filter.routes                      # real data under data/parquet
    python -m src.filter.routes --parquet-dir <dir>  # fixtures (tests)

Inputs under <parquet_dir>:
    size_age.parquet      Stage 2 output (one row per universe company)
    psc/ or psc.parquet   PSC register rows (Stage 1a), every company (drives the walk-up)
    companies.parquet     name fallback for corporate PSCs with no registration number

Output: <parquet_dir>/universe.parquet with one row per Stage 2 company and these columns added:
    route                 founder_family | sponsor | sponsor_offshore | foreign_parent | uk_group |
                          plc_dispersed | employee_owned | public_sector | uncertain
    route_confidence      high | medium | low
    route_reason          the rule that decided
    owner_names           the controlling owners at the top of the chain (list)
    sponsor_names         investor labels matched (list)
    hold_start            earliest notified_on of the sponsor's PSC record (ISO date) or NULL
    hold_years            years from hold_start to the build date
    parent_name, parent_country   terminal corporate for foreign_parent and uk_group
    individuals_pct_mid   look-through midpoint share held by individuals
    n_individuals, family_surname_shared, oldest_owner_age, youngest_owner_age
    founder_rollover      individuals at 25%+ alongside a sponsor
    walkup_path           the chain of company numbers walked
    flags                 list of informational flags

The rules are documented in docs/methodology.md (Ownership route). Every threshold and name list
is read from config.ownership and config.ownership_routes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass, field

import duckdb
import polars as pl

from src.common import cfg, get_logger, now_iso, today
from src.filter.ownership import (
    Rules, _person, _split, _word_regex, classify_corporate, compile_rules, dispersed_statements,
    investor_match, is_active, lookup_key, parse_bands, person_key_from_row, resolve_corporate,
)
from src.filter.universe import fetch_frame, register_view, resolve_dirs, source, write_table

log = get_logger("routes")

OFFSHORE = {"JERSEY", "GUERNSEY", "CAYMAN ISLANDS", "CAYMAN", "LUXEMBOURG", "ISLE OF MAN", "BRITISH VIRGIN ISLANDS",
            "BVI", "BERMUDA", "MAURITIUS", "GIBRALTAR", "DELAWARE", "NETHERLANDS", "MALTA", "CYPRUS", "IRELAND"}
PE_VEHICLE_RE = re.compile(r"\b(TOPCO|MIDCO|BIDCO|HOLDCO|FINCO|ACQUISITIONS?|ACQUISITION CO|HOLDINGS?|INVESTMENTS?|S\.?A\.?R\.?L|S\.?C\.?A|S\.?C\.?S|GP|L\.?P\.?|LP|LIMITED PARTNERSHIP|NOMINEES?|FEEDER|CO-INVEST|COINVEST)\b", re.I)
EMPLOYEE_RE = re.compile(r"\bEOT\b|EMPLOYEE[- ]OWN|EMPLOYEE BENEFIT TRUST|\bEBT\b|\(EOT\)|EMPLOYEE SHARE|EMPLOYEE TRUST", re.I)
SOVEREIGN_RE = re.compile(r"\b(MINISTER FOR FINANCE|GIC\b|GIC PRIVATE|TEMASEK|ABU DHABI INVESTMENT|MUBADALA|QATAR INVESTMENT|QATAR HOLDING|PUBLIC INVESTMENT FUND|NORGES BANK|CHINA INVESTMENT CORP|KUWAIT INVESTMENT|CDPQ|CAISSE DE D|CPP INVESTMENT|CANADA PENSION|ONTARIO TEACHERS|OMERS|PSP INVESTMENTS|BRITISH COLUMBIA INVESTMENT|BCI\b|AIMCO|ALBERTA INVESTMENT|AUSTRALIANSUPER|FUTURE FUND|KHAZANAH|SAUDI ARABIAN|ADQ\b|ADIA\b|LA CAISSE|UNIVERSITIES SUPERANNUATION|USS\b|RAILPEN|BORDER TO COAST|LGPS|PENSION)\b", re.I)
PUBLIC_RE = re.compile(r"\b(NHS|COUNCIL|SECRETARY OF STATE|HM TREASURY|TREASURY|GOVERNMENT|MINISTRY|DEPARTMENT FOR|UNIVERSITY|HOUSING ASSOCIATION|CROWN|LOCAL AUTHORITY|BOROUGH|COUNTY|CITY OF|TRANSPORT FOR|BBC|PUBLIC HEALTH|NATIONAL HEALTH|ROYAL MAIL|NETWORK RAIL|UK INFRASTRUCTURE BANK|BRITISH BUSINESS BANK|STATE OF|REPUBLIC OF|KINGDOM OF|EMIRATE)\b", re.I)
MUTUAL_RE = re.compile(r"\b(CO-?OPERATIVE|COOPERATIVE|MUTUAL|FRIENDLY SOCIETY|BUILDING SOCIETY|MEMBERS?|SOCIETY LIMITED|CHARITY|CHARITABLE|FOUNDATION|TRUSTEES OF THE .*(CHARIT|FOUNDATION))\b", re.I)
UK_RES = {"ENGLAND", "WALES", "SCOTLAND", "NORTHERN IRELAND", "UNITED KINGDOM", "UK", "GREAT BRITAIN", "ISLE OF MAN",
          "JERSEY", "GUERNSEY", "BRITAIN", "GB", "GBR", "ENGLAND AND WALES"}


@dataclass
class RouteRules:
    base: Rules
    walkup_levels: int
    founder_high_pct: float
    founder_min_pct: float
    rollover_min_pct: float
    sponsor_names: list = field(default_factory=list)


def compile_route_rules(c: dict | None = None) -> RouteRules:
    c = c or cfg()
    base = compile_rules(c)
    r = c.get("ownership_routes", {})
    extra = [(n, _word_regex(n)) for n in r.get("sponsor_names", [])]
    base.investor_names = base.investor_names + extra
    return RouteRules(
        base=base,
        walkup_levels=int(r.get("walkup_levels", 4)),
        founder_high_pct=float(r.get("founder_high_pct", 75)),
        founder_min_pct=float(r.get("founder_min_pct", 50)),
        rollover_min_pct=float(r.get("rollover_min_pct", 25)),
        sponsor_names=[n for n, _ in extra],
    )


# ---------------------------------------------------------------- walk
@dataclass
class Node:
    cn: str
    depth: int
    scale: float
    name: str | None = None


@dataclass
class Walk:
    persons: list = field(default_factory=list)
    sponsors: list = field(default_factory=list)       # dicts: label, name, cn_level, notified_on, scale
    foreign: list = field(default_factory=list)        # dicts: name, country, cn_level, scale
    dispersed_at: list = field(default_factory=list)   # company numbers whose register says nobody holds 25%
    unresolved: list = field(default_factory=list)
    supers: list = field(default_factory=list)
    employee: list = field(default_factory=list)
    public: list = field(default_factory=list)
    mutual: list = field(default_factory=list)
    paths: list = field(default_factory=list)
    visited: set = field(default_factory=set)
    flags: list = field(default_factory=list)


def _flag(w: Walk, f: str) -> None:
    if f not in w.flags:
        w.flags.append(f)


def _country(row) -> str:
    c = re.sub(r"[^A-Z ]", " ", str(row.get("country_registered") or "").upper())
    return re.sub(r"\s+", " ", c).strip()


def _notified(row) -> str | None:
    v = row.get("notified_on")
    return str(v)[:10] if v is not None else None


def _classify_corporate_row(c, rules: RouteRules, level_cn: str, scale: float, w: Walk, name_lookup) -> str:
    """Decide what one corporate PSC row is: sponsor, employee trust, public body, mutual, foreign, uk, unresolved."""
    nm = str(c.get("name") or "")
    hits = investor_match(nm, rules.base)
    if SOVEREIGN_RE.search(nm) and not EMPLOYEE_RE.search(nm):
        w.sponsors.append({"labels": hits or ["sovereign or pension fund"], "name": nm, "cn_level": level_cn, "notified_on": _notified(c), "scale": scale,
                           "country": _country(c) or None})
        return "sponsor"
    if EMPLOYEE_RE.search(nm):
        w.employee.append({"name": nm, "cn_level": level_cn})
        return "employee"
    if PUBLIC_RE.search(nm):
        w.public.append({"name": nm, "cn_level": level_cn})
        return "public"
    if MUTUAL_RE.search(nm):
        w.mutual.append({"name": nm, "cn_level": level_cn})
        return "mutual"
    hits = [h for h in hits if h != "employee ownership trust"]
    if hits:
        w.sponsors.append({"labels": hits, "name": nm, "cn_level": level_cn, "notified_on": _notified(c), "scale": scale,
                           "country": _country(c) or None})
        return "sponsor"
    kind, reg, by_name = resolve_corporate(c, name_lookup)
    if kind == "foreign":
        w.foreign.append({"name": nm, "country": _country(c) or None, "cn_level": level_cn, "scale": scale,
                          "notified_on": _notified(c), "pe_vehicle_name": bool(PE_VEHICLE_RE.search(nm))})
        return "foreign"
    if kind == "uk" and reg:
        return f"uk:{reg}" + (":byname" if by_name else "")
    w.unresolved.append({"name": nm, "cn_level": level_cn, "country": _country(c) or None})
    return "unresolved"


def walk(cn: str, company_name: str | None, psc_index: dict, rules: RouteRules, name_lookup: dict | None) -> Walk:
    """Breadth-first walk up the ownership chain from company cn."""
    w = Walk()
    queue = [Node(cn, 0, 100.0, company_name)]
    w.visited.add(cn)
    while queue:
        node = queue.pop(0)
        rows = [r for r in psc_index.get(node.cn, []) if is_active(r)]
        all_rows = psc_index.get(node.cn, [])
        if not rows:
            if all_rows:
                _flag(w, f"all_pscs_ceased@{node.cn}")
            else:
                _flag(w, f"no_psc@{node.cn}")
            if node.depth > 0:
                w.unresolved.append({"name": node.name, "cn_level": node.cn, "country": "UK", "reason": "no_psc_at_holdco"})
            continue
        stmts, corps, inds, supers = _split(rows)
        if stmts and not (corps or inds or supers):
            if dispersed_statements(stmts, rules.base):
                w.dispersed_at.append(node.cn)
            else:
                w.unresolved.append({"name": node.name, "cn_level": node.cn, "country": "UK", "reason": "psc_unidentified"})
            continue
        for r in inds:
            w.persons.append(_person(r, rules.base, via_holdco=node.depth > 0, holdco=node.cn if node.depth > 0 else None,
                                     holdco_mid=node.scale if node.depth > 0 else None))
        w.supers.extend(supers)
        for c in corps:
            hold = parse_bands(c.get("natures_of_control"), rules.base)
            if not hold["band"]:
                hold_mid = node.scale
            elif hold["band"] == rules.base.high_band:
                hold_mid = node.scale
            else:
                hold_mid = hold["mid"] * node.scale / 100.0
            kind = _classify_corporate_row(c, rules, node.cn, hold_mid, w, name_lookup)
            if kind.startswith("uk:"):
                reg = kind.split(":")[1]
                if ":byname" in kind:
                    _flag(w, "holdco_name_resolved")
                if reg == node.cn or reg in w.visited:
                    continue
                if node.depth + 1 > rules.walkup_levels:
                    w.unresolved.append({"name": c.get("name"), "cn_level": node.cn, "country": "UK", "reason": "walkup_limit"})
                    _flag(w, "walkup_limit")
                    continue
                w.visited.add(reg)
                w.paths.append(f"{node.cn} -> {reg}")
                queue.append(Node(reg, node.depth + 1, hold_mid, c.get("name")))
    return w


# ---------------------------------------------------------------- decision
def _ages(persons: list, as_of: dt.date) -> tuple[int | None, int | None]:
    ys = [p.get("dob_year") for p in persons if p.get("dob_year")]
    if not ys:
        return None, None
    ages = [as_of.year - int(y) for y in ys]
    return max(ages), min(ages)


def evaluate(company: dict, psc_index: dict, rules: RouteRules, name_lookup: dict | None, as_of: dt.date) -> dict:
    cn = company["company_number"]
    is_plc = "PUBLIC LIMITED" in str(company.get("category") or "").upper() or str(company.get("name") or "").upper().rstrip().endswith(" PLC")
    w = walk(cn, company.get("name"), psc_index, rules, name_lookup)
    # attach dob to persons from the raw rows
    raw_ind = {}
    for level_rows in [psc_index.get(cn, [])] + [psc_index.get(p.split(" -> ")[1], []) for p in w.paths]:
        for r in level_rows:
            if str(r.get("kind") or "").startswith("individual"):
                k = person_key_from_row(r)
                if k:
                    raw_ind[k] = r
    for p in w.persons:
        k = (p.get("surname"), p.get("forename"))
        r = raw_ind.get(k)
        if r is not None:
            p["dob_year"] = r.get("dob_year")
    # look-through share held by individuals, deduplicated by person key
    seen = {}
    for p in w.persons:
        k = (p.get("surname"), p.get("forename"))
        if k in seen:
            seen[k]["pct_mid"] = min(100.0, (seen[k].get("pct_mid") or 0) + (p.get("pct_mid") or 0))
        else:
            seen[k] = dict(p)
    persons = list(seen.values())
    ind_pct = round(min(100.0, sum((p.get("pct_mid") or 0) for p in persons)), 1)
    surnames = [p.get("surname") for p in persons if p.get("surname")]
    family = len(surnames) >= 2 and len(set(surnames)) < len(surnames)
    oldest, youngest = _ages(persons, as_of)
    res = [str(p.get("country_of_residence") or "").strip().upper() for p in persons]
    known = [r for r in res if r]
    abroad = bool(known) and all(r not in UK_RES for r in known)
    rollover = any((p.get("pct_mid") or 0) >= rules.rollover_min_pct for p in persons)

    out = {
        "route": "uncertain", "route_confidence": "low", "route_reason": None,
        "owner_names": [], "sponsor_names": [], "hold_start": None, "hold_years": None,
        "parent_name": None, "parent_country": None,
        "individuals_pct_mid": ind_pct, "n_individuals": len(persons), "family_surname_shared": family,
        "oldest_owner_age": oldest, "youngest_owner_age": youngest, "founder_rollover": False,
        "walkup_path": "; ".join(w.paths) if w.paths else None, "flags": list(w.flags),
        "owners_resident_abroad": abroad, "is_plc": is_plc,
        "persons_json": json.dumps(persons, default=str),
    }

    def done(route, conf, reason):
        out["route"], out["route_confidence"], out["route_reason"] = route, conf, reason
        return out

    no_active = all(f.startswith("no_psc@") or f.startswith("all_pscs_ceased@") for f in w.flags) and w.flags and not (
        persons or w.sponsors or w.foreign or w.dispersed_at or w.unresolved or w.supers or w.employee or w.public or w.mutual)
    if no_active:
        if is_plc:
            return done("plc_dispersed", "medium", "plc_no_psc")
        return done("uncertain", "low", "no_psc")

    if w.public and not w.sponsors:
        out["owner_names"] = [x["name"] for x in w.public]
        return done("public_sector", "high", "public_body_psc")
    if w.mutual and not w.sponsors and ind_pct < rules.founder_min_pct:
        out["owner_names"] = [x["name"] for x in w.mutual]
        return done("public_sector", "medium", "mutual_or_charity_psc")
    if w.employee and not w.sponsors and ind_pct < rules.founder_min_pct:
        out["owner_names"] = [x["name"] for x in w.employee]
        return done("employee_owned", "high", "employee_trust_psc")

    if w.sponsors:
        labels = sorted({l for s in w.sponsors for l in s["labels"]})
        out["sponsor_names"] = labels
        out["owner_names"] = sorted({s["name"] for s in w.sponsors})
        dates = [s["notified_on"] for s in w.sponsors if s.get("notified_on")]
        if dates:
            out["hold_start"] = min(dates)
            try:
                hs = dt.date.fromisoformat(out["hold_start"])
                out["hold_years"] = round((as_of - hs).days / 365.25, 1)
            except ValueError:
                pass
        out["founder_rollover"] = rollover
        conf = "high" if any(l for l in labels if l not in {"Fund", "LP", "L.P.", "Nominees", "Trustees", "Capital Partners", "Investments LLP"}) else "medium"
        return done("sponsor", conf, "investor_psc" if len(w.paths) == 0 else "investor_psc_via_holdco")

    # individuals control the company
    if ind_pct >= rules.founder_min_pct and not w.supers:
        out["owner_names"] = [p.get("name") for p in persons if (p.get("pct_mid") or 0) >= 10][:6]
        if abroad:
            return done("foreign_parent", "medium", "individual_owners_resident_abroad")
        conf = "high" if ind_pct >= rules.founder_high_pct else "medium"
        if any(p.get("trust_or_firm") for p in persons) and conf == "high":
            conf = "medium"
        if w.foreign or w.unresolved:
            conf = "medium"
        return done("founder_family", conf, "individuals_control" + ("_via_holdco" if w.paths else ""))

    # a foreign corporate at the top
    if w.foreign:
        top = max(w.foreign, key=lambda f: f.get("scale") or 0)
        out["parent_name"], out["parent_country"] = top["name"], top.get("country")
        out["owner_names"] = [top["name"]]
        out["founder_rollover"] = rollover
        country = (top.get("country") or "").upper()
        if any(o in country for o in OFFSHORE) and top.get("pe_vehicle_name"):
            out["hold_start"] = top.get("notified_on")
            if out["hold_start"]:
                try:
                    out["hold_years"] = round((as_of - dt.date.fromisoformat(out["hold_start"])).days / 365.25, 1)
                except ValueError:
                    pass
            return done("sponsor_offshore", "medium", "offshore_vehicle_parent")
        if any(o in country for o in OFFSHORE):
            return done("foreign_parent", "low", "offshore_parent_unknown_owner")
        return done("foreign_parent", "medium" if not w.unresolved else "low", "foreign_corporate_parent")

    # a UK group whose top company says nobody holds 25% (listed parent or widely held)
    if w.dispersed_at:
        top_cn = w.dispersed_at[0]
        if top_cn == cn:
            if is_plc:
                return done("plc_dispersed", "high", "plc_dispersed_statement")
            return done("uk_group", "low", "dispersed_statement_private")
        out["parent_name"] = name_lookup.get(f"__cn__{top_cn}") if name_lookup else None
        out["parent_country"] = "UK"
        out["walkup_path"] = out["walkup_path"]
        return done("uk_group", "medium", "uk_parent_dispersed")

    if w.supers:
        return done("uncertain", "low", "super_secure_psc")
    if persons and ind_pct >= rules.rollover_min_pct and not (w.foreign or w.unresolved or w.dispersed_at):
        # one or two individuals in the 25% to 50% band and nothing else on the register: the rest is below the
        # 25% reporting line (minority investors, staff, family). Founder-led, with the stake uncertain.
        out["owner_names"] = [p.get("name") for p in persons][:6]
        if abroad:
            return done("foreign_parent", "low", "individual_owners_resident_abroad")
        return done("founder_family", "low", "individuals_lead_25_50")
    if w.unresolved:
        u = w.unresolved[0]
        out["parent_name"] = u.get("name")
        out["parent_country"] = u.get("country")
        return done("uncertain", "low", u.get("reason") or "corporate_unresolved")
    if persons:
        out["owner_names"] = [p.get("name") for p in persons][:6]
        return done("uncertain", "low", "individuals_below_control")
    return done("uncertain", "low", "no_rule_fired")


# ---------------------------------------------------------------- IO
def _cn_sql(col: str) -> str:
    return (f"CASE WHEN regexp_matches(trim({col}), '^[0-9]+$') THEN lpad(trim({col}), 8, '0') "
            f"ELSE upper(trim({col})) END")


def _psc_index(con, numbers: list[str], levels: int) -> dict[str, list[dict]]:
    """PSC rows for the universe companies and every UK corporate PSC reachable in `levels` hops."""
    con.execute("CREATE OR REPLACE TEMP TABLE seed(cn VARCHAR)")
    con.executemany("INSERT INTO seed VALUES (?)", [(n,) for n in numbers])
    con.execute("CREATE OR REPLACE TEMP TABLE want AS SELECT cn FROM seed")
    for _ in range(levels):
        con.execute("""
            INSERT INTO want
            SELECT DISTINCT p.corporate_reg_number FROM psc p JOIN want w ON p.company_number = w.cn
            WHERE p.corporate_reg_number IS NOT NULL AND length(p.corporate_reg_number) = 8
              AND p.corporate_reg_number NOT IN (SELECT cn FROM want)
        """)
    df = fetch_frame(con, """
        SELECT p.* FROM psc p JOIN (SELECT DISTINCT cn FROM want) w ON p.company_number = w.cn
    """)
    idx: dict[str, list[dict]] = {}
    for row in df.iter_rows(named=True):
        idx.setdefault(row["company_number"], []).append(row)
    return idx


def _name_lookup(con, idx: dict) -> dict[str, str]:
    """Exact register-name lookup for unresolved corporate PSCs, plus __cn__ -> name for parents."""
    names = set()
    cns = set(idx.keys())
    for rows in idx.values():
        for r in rows:
            if str(r.get("kind") or "").startswith(("corporate", "legal")) and not r.get("corporate_reg_number"):
                names.add(lookup_key(r.get("name")))
    out: dict[str, str] = {}
    if names:
        con.execute("CREATE OR REPLACE TEMP TABLE nm(k VARCHAR)")
        con.executemany("INSERT INTO nm VALUES (?)", [(n,) for n in names if n])
        for k, cn in con.execute("""
            SELECT nm.k, c.company_number FROM nm JOIN companies c ON upper(regexp_replace(c.name, '\\s+', ' ', 'g')) = nm.k
            WHERE c.status = 'Active'
        """).fetchall():
            out[k] = cn
    if cns:
        con.execute("CREATE OR REPLACE TEMP TABLE cns(cn VARCHAR)")
        con.executemany("INSERT INTO cns VALUES (?)", [(c,) for c in cns])
        for cn, name in con.execute("SELECT c.company_number, c.name FROM cns JOIN companies c ON c.company_number = cns.cn").fetchall():
            out[f"__cn__{cn}"] = name
    return out


def run(parquet_dir=None, docs_dir=None) -> pl.DataFrame:
    pq, docs = resolve_dirs(parquet_dir, docs_dir)
    rules = compile_route_rules()
    con = duckdb.connect()
    con.execute("SET threads TO 2; SET memory_limit='3GB'")
    sa = source(pq, "size_age")
    if not sa:
        raise FileNotFoundError("size_age.parquet missing; run src.filter.universe first")
    register_view(con, "size_age", sa)
    register_view(con, "psc", source(pq, "psc"))
    register_view(con, "companies", source(pq, "companies"))
    base = fetch_frame(con, "SELECT * FROM size_age WHERE passes_all ORDER BY company_number")
    numbers = base["company_number"].to_list()
    log.info("%d universe companies; loading PSC index (%d walk-up levels)", len(numbers), rules.walkup_levels)
    idx = _psc_index(con, numbers, rules.walkup_levels)
    lookup = _name_lookup(con, idx)
    as_of = today()
    rows = []
    for company in base.iter_rows(named=True):
        r = evaluate(company, idx, rules, lookup, as_of)
        r["company_number"] = company["company_number"]
        r["computed_at"] = now_iso()
        rows.append(r)
    routes = pl.DataFrame(rows)
    for col in ("owner_names", "sponsor_names", "flags"):
        routes = routes.with_columns(pl.col(col).cast(pl.List(pl.Utf8)))
    out = base.join(routes, on="company_number", how="left")
    # Group head: the highest UK company in the walked chain that itself files GROUP accounts and sits in the
    # universe. Subsidiaries and acquisition vehicles collapse onto it, so one business is ranked once and the
    # consolidated accounts are the ones read.
    cat = dict(zip(base["company_number"].to_list(), base["account_category"].to_list()))
    heads = {}
    for cn, path_ in zip(out["company_number"].to_list(), out["walkup_path"].to_list()):
        head = cn
        if path_:
            chain = []
            for hop in path_.split("; "):
                a, b = hop.split(" -> ")
                chain.append(b)
            for c in chain:
                if c in cat and str(cat[c]).upper() == "GROUP":
                    head = c
        heads[cn] = head
    out = out.with_columns(pl.col("company_number").replace_strict(heads, default=None).alias("group_head"))
    out = out.with_columns((pl.col("group_head") == pl.col("company_number")).alias("is_group_head"))
    write_table(out, pq, "universe")
    summary = {
        "computed_at": now_iso(), "rows": out.height,
        "route": dict(out.group_by("route").len().sort("len", descending=True).iter_rows()),
        "route_confidence": {f"{a}|{b}": n for a, b, n in out.group_by(["route", "route_confidence"]).len().iter_rows()},
        "sponsor_top": dict(out.filter(pl.col("route") == "sponsor").explode("sponsor_names").group_by("sponsor_names").len()
                            .sort("len", descending=True).head(40).iter_rows()),
        "hold_years_quartiles_sponsor": [round(x, 1) if x is not None else None for x in
                                          [out.filter(pl.col("route") == "sponsor")["hold_years"].quantile(q) for q in (0.25, 0.5, 0.75)]],
        "founder_family_age_quartiles": [out.filter(pl.col("route") == "founder_family")["oldest_owner_age"].quantile(q) for q in (0.25, 0.5, 0.75)],
        "group_heads": int(out["is_group_head"].sum()),
        "collapsed_onto_a_head": int((~pl.Series(out["is_group_head"])).sum()),
    }
    (docs / "funnel_stage3.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("routes: %s", json.dumps(summary["route"]))
    con.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet-dir")
    ap.add_argument("--docs-dir")
    a = ap.parse_args(argv)
    run(a.parquet_dir, a.docs_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
