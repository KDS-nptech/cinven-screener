"""Targeted OCR of a Companies House annual report (image-only PDF).

Companies House rasterises every PDF it publishes, so the text layer is gone. OCR of a whole
60 to 120 page annual report costs minutes; this module reads only the pages that carry the
numbers a buyout screener needs:

  1. the first pages (cover, contents, financial highlights) at 100 dpi;
  2. the contents page is parsed for the printed page of the income statement (profit and loss
     account) and of the notes; printed numbers are offset from PDF indices, so a window of
     pages around the printed number is OCRed and the page whose text carries the P&L labels
     is kept;
  3. when the contents page gives nothing, a scan of the pages between 30% and 65% of the
     document stops at the first page with an operating profit line.

Returns the concatenated text of the pages read plus which pages they were, so the regex
extractor in accounts_api can run unchanged. The optional vision fallback (Anthropic key)
sends the chosen P&L page image to Claude Haiku when the regex finds no revenue figure.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from src.common import REPO, get_logger

log = get_logger("pdf_ocr")

PL_LABELS_RE = re.compile(r"(income statement|profit and loss account|statement of comprehensive income|statement of profit or loss)", re.I)
PL_LINE_RE = re.compile(r"^\s*(operating (profit|loss)|turnover|revenue|gross profit|cost of sales)\b", re.I | re.M)
CONTENTS_PL_RE = re.compile(r"(consolidated\s+)?(group\s+)?(statement of comprehensive income|income statement|profit and loss account|statement of profit or loss|statement of profit and loss)[^\d\n]{0,120}?(\d{1,3})\s*$", re.I | re.M)
CONTENTS_PL_PRE_RE = re.compile(r"(?<![\d.,])(\d{1,3})\s+(?:consolidated\s+|group\s+)?(?:income statement|statement of comprehensive income|profit and loss account|statement of profit or loss)", re.I)
HIGHLIGHT_RE = re.compile(r"(revenue|turnover|group revenue|adjusted ebitda|underlying ebitda|ebitda|operating profit|adjusted operating profit)\s*[:\-]?\s*(?:\n\s*)?£\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(m|bn|k|million|billion)?\b", re.I)


def highlights(text: str) -> dict:
    """KPI figures printed as '£541.4m' in a highlights section. Returns pounds per label."""
    out = {}
    for m in HIGHLIGHT_RE.finditer(text or ""):
        label = m.group(1).lower()
        v = float(m.group(2).replace(",", ""))
        unit = (m.group(3) or "").lower()
        mult = {"m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9, "k": 1e3}.get(unit, 1)
        if mult == 1 and v < 100000:
            continue  # a bare small number is not a KPI in pounds
        key = "revenue" if label in ("revenue", "turnover", "group revenue") else ("ebitda" if "ebitda" in label else "operating_profit")
        out.setdefault(key, v * mult)
        out.setdefault(key + "_match", m.group(0)[:120])
    return out
CONTENTS_NOTES_RE = re.compile(r"notes? (to|forming part of) the (consolidated |group )?financial statements[^\d\n]{0,120}?(\d{1,3})\s*$", re.I | re.M)
CONTENTS_STRAT_RE = re.compile(r"strategic report[^\d\n]{0,120}?(\d{1,3})\s*$", re.I | re.M)


def n_pages(pdf: Path) -> int:
    try:
        r = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=60)
        m = re.search(r"Pages:\s+(\d+)", r.stdout)
        return int(m.group(1)) if m else 0
    except (OSError, subprocess.TimeoutExpired):
        return 0


def render(pdf: Path, first: int, last: int, outdir: Path, dpi: int = 100) -> list[Path]:
    """Render pages first..last (1-based, inclusive) to grayscale PGM. Returns paths in page order."""
    if last < first:
        return []
    prefix = outdir / f"p{first}"
    subprocess.run(["pdftoppm", "-q", "-r", str(dpi), "-gray", "-f", str(first), "-l", str(last), str(pdf), str(prefix)],
                   capture_output=True, timeout=180)
    return sorted(outdir.glob(f"p{first}-*.pgm"), key=lambda p: int(p.stem.split("-")[-1]))


def ocr_page(img: Path) -> str:
    try:
        r = subprocess.run(["tesseract", str(img), "-", "--psm", "6", "-l", "eng"], capture_output=True, text=True, timeout=120)
        return r.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _page_index(img: Path) -> int:
    return int(img.stem.split("-")[-1])


STRICT_PL_RE = re.compile(r"(^[ \t]*(turnover|revenue|group revenue|total revenue)\b.*\d)", re.I | re.M)
STRICT_OP_RE = re.compile(r"operating (profit|loss|\(loss\))|profit.{0,40}before tax|loss.{0,40}before tax", re.I)


def is_pl_page(text: str) -> bool:
    return bool(STRICT_PL_RE.search(text) and STRICT_OP_RE.search(text) and len(re.findall(r"\d{1,3}(?:,\d{3})+|\(\d", text)) >= 6)


def read_report(pdf: Path, window: int = 10, use_vision: bool = True, dpi: int = 90) -> dict:
    """Targeted read of an image-only annual report.

    1. OCR pages 2 to 4 (contents, highlights); parse the printed page of the income statement.
    2. OCR candidate pages one at a time from that printed page forward (the PDF index runs ahead of
       the printed number by the unnumbered front pages) and stop at the first page that reads like a
       P&L: a turnover or revenue line, an operating profit or profit before tax line, six or more
       figures. Without a printed page, scan 30% to 70% of the document.
    3. Regex the figures from that page; call the vision model on the page image only when revenue or
       operating profit is still missing.
    Returns {text, pages_read, pl_page, n_pages, method, vision, vision_calls, highlights, pl_text}."""
    n = n_pages(pdf)
    out = {"text": "", "pages_read": [], "pl_page": None, "n_pages": n, "method": None, "vision": None, "vision_calls": 0,
           "highlights": {}, "pl_text": ""}
    if n == 0:
        return out
    tmp = Path(tempfile.mkdtemp(prefix="ocr_"))
    texts: dict[int, str] = {}
    try:
        for img in render(pdf, 2, min(4, n), tmp, dpi=100):
            texts[_page_index(img)] = ocr_page(img)
        front_text = "\n".join(texts[k] for k in sorted(texts))
        out["highlights"] = highlights(front_text)
        printed = None
        m = CONTENTS_PL_RE.search(front_text)
        if m:
            printed = int(m.group(4))
        else:
            m2 = CONTENTS_PL_PRE_RE.search(front_text)
            if m2:
                printed = int(m2.group(1))
        if (not printed or not (1 <= printed <= n)) and use_vision and n > 12:
            # the OCR of the contents page did not parse: one cheap vision call reads the contents page
            for pg in (2, 3):
                img = next(iter(tmp.glob(f"p2-{pg}.pgm")), None) or next(iter(tmp.glob(f"p2-0{pg}.pgm")), None) or next(iter(tmp.glob(f"p2-00{pg}.pgm")), None)
                if img is None:
                    continue
                cv = vision_contents(img)
                out["vision_calls"] += 1
                if cv and isinstance(cv.get("pl_printed_page"), int) and 1 <= cv["pl_printed_page"] <= n:
                    printed = cv["pl_printed_page"]
                    out["method"] = "contents-vision"
                    break
        if printed and 1 <= printed <= n:
            candidates = [p for p in range(printed, min(n, printed + window) + 1) if p not in texts]
            out["method"] = out["method"] or "contents"
        else:
            lo, hi = max(5, int(n * 0.33)), min(n, int(n * 0.70) + 1)
            step = 1 if n <= 30 else (2 if n <= 60 else 3)
            candidates = [p for p in range(lo, hi, step) if p not in texts][:12]
            out["method"] = "scan"
        pl_img = None
        # a short set of accounts (under 30 pages) sometimes has the P&L in the front pages already read
        for k in sorted(texts):
            if k >= 3 and is_pl_page(texts[k]):
                out["pl_page"] = k
                out["method"] = "front"
                break
        if out["pl_page"] is None:
            for pg in candidates:
                imgs = render(pdf, pg, pg, tmp, dpi=dpi)
                if not imgs:
                    continue
                t = ocr_page(imgs[0])
                texts[pg] = t
                if is_pl_page(t):
                    out["pl_page"] = pg
                    pl_img = imgs[0]
                    if pg + 1 <= n and (pg + 1) not in texts:
                        nxt = render(pdf, pg + 1, pg + 1, tmp, dpi=dpi)
                        if nxt:
                            texts[pg + 1] = ocr_page(nxt[0])
                    break
        if out["pl_page"] is not None:
            out["pl_text"] = texts.get(out["pl_page"], "")
        if out["pl_page"] is not None and use_vision:
            # regex first; the model reads the page only when the key lines did not parse
            from src.ingest.accounts_api import extract_from_pdf_text, extract_pl_from_text

            page_text = out["pl_text"] + "\n" + texts.get(out["pl_page"] + 1, "")
            ex = extract_from_pdf_text(page_text)
            pl_ = extract_pl_from_text(page_text, ex.get("scale", 1))
            need = pl_.get("revenue") is None or pl_.get("operating_profit") is None
            if need:
                if pl_img is None:
                    rendered = render(pdf, out["pl_page"], out["pl_page"], tmp, dpi=110)
                    pl_img = rendered[0] if rendered else None
                if pl_img is not None:
                    v = vision_extract(pl_img)
                    out["vision_calls"] += 1
                    if v and (v.get("revenue") is not None or v.get("operating_profit") is not None or v.get("profit_before_tax") is not None):
                        out["vision"] = v
        out["pages_read"] = sorted(texts)
        out["text"] = "\n".join(f"\n[page {k}]\n" + texts[k] for k in sorted(texts))
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("ocr failed for %s: %s", pdf.name, e)
        out["pages_read"] = sorted(texts)
        out["text"] = "\n".join(texts[k] for k in sorted(texts))
        return out
    finally:
        for f in tmp.glob("*"):
            f.unlink(missing_ok=True)
        try:
            tmp.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------- vision fallback
VISION_PROMPT = """You are reading one page of a UK company's statutory annual report (an income statement or profit and loss account, possibly with a financial highlights section). Extract the current-year figures and answer with JSON only:
{"period_end": "YYYY-MM-DD or null", "unit": "GBP|GBP thousands|GBP millions|other", "consolidated": true|false|null,
 "revenue": number or null, "operating_profit": number or null, "profit_before_tax": number or null, "ebitda": number or null,
 "employees": number or null, "notes": "one line on what you read"}
Numbers are in the unit stated on the page (do not rescale). Parentheses mean negative. Use the current year column (the left-hand or first numeric column), never the comparative. If the page is not a P&L, return nulls."""


def _env(name: str) -> str | None:
    v = os.environ.get(name)
    if v:
        return v
    f = REPO / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return None


VISION_CALLS = {"n": 0, "in": 0, "out": 0}


def _vision_post(png: Path, prompt: str, model: str, max_tokens: int) -> dict | None:
    """One image plus prompt to the Messages API, JSON back. Retries 429 and 5xx with backoff."""
    import time as _t

    import httpx

    key = _env("ANTHROPIC_API_KEY")
    if not key:
        return None
    b64 = base64.b64encode(png.read_bytes()).decode()
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    ws = _env("ANTHROPIC_WORKSPACE_ID")
    if ws:
        headers["anthropic-workspace-id"] = ws
    body = {"model": model, "max_tokens": max_tokens, "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": prompt}]}]}
    for attempt in range(5):
        try:
            r = httpx.post("https://api.anthropic.com/v1/messages", json=body, headers=headers, timeout=60)
        except Exception as e:  # noqa: BLE001
            log.warning("vision error: %s", e)
            _t.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            j = r.json()
            VISION_CALLS["n"] += 1
            u = j.get("usage") or {}
            VISION_CALLS["in"] += u.get("input_tokens") or 0
            VISION_CALLS["out"] += u.get("output_tokens") or 0
            txt = "".join(c.get("text", "") for c in j.get("content", []))
            m = re.search(r"\{.*\}", txt, re.S)
            try:
                return json.loads(m.group(0)) if m else None
            except json.JSONDecodeError:
                return None
        if r.status_code in (429, 500, 502, 503, 529):
            ra = r.headers.get("retry-after")
            wait = float(ra) if ra and ra.replace(".", "").isdigit() else 3.0 * (attempt + 1)
            log.warning("vision %s, sleeping %.0fs", r.status_code, wait)
            _t.sleep(min(wait, 60))
            continue
        if r.status_code == 400 and "temperature" in r.text and "temperature" in body:
            body.pop("temperature")  # newer models reject the parameter
            continue
        log.warning("vision %s: %s", r.status_code, r.text[:200])
        return None
    return None


def _to_png(image: Path, resize: str | None = None) -> Path | None:
    png = Path(image).with_suffix(".png")
    cmd = ["convert", str(image)] + (["-resize", resize] if resize else []) + [str(png)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return png if png.exists() else None


def vision_extract(image: Path, model: str = "claude-haiku-4-5") -> dict | None:
    """Ask Claude to read the P&L page image. Returns the parsed JSON or None."""
    if not image or not Path(image).exists():
        return None
    png = _to_png(image)
    if not png:
        return None
    try:
        return _vision_post(png, VISION_PROMPT, model, 400)
    finally:
        png.unlink(missing_ok=True)


CONTENTS_PROMPT = """This is the contents page of a UK company's annual report. Answer with JSON only:
{"pl_printed_page": integer or null, "notes_printed_page": integer or null, "strategic_report_printed_page": integer or null}
pl_printed_page is the printed page number of the (consolidated) income statement, statement of comprehensive income or profit and loss account. If this is not a contents page, return nulls."""


def vision_contents(image: Path, model: str = "claude-haiku-4-5") -> dict | None:
    if not image or not Path(image).exists():
        return None
    png = _to_png(image, "70%")
    if not png:
        return None
    try:
        return _vision_post(png, CONTENTS_PROMPT, model, 120)
    finally:
        png.unlink(missing_ok=True)


def read_report_vision(pdf: Path, dpi: int = 110) -> dict:
    """Vision-only read, no tesseract: the contents page gives the printed page of the P&L, then the
    candidate PDF pages (printed + 1, + 2, + 0, + 3: the index runs ahead of the printed number by the
    unnumbered front pages) are read until one is a P&L. Without a usable contents page, pages at 50%,
    60% and 40% of the document are tried. At most six model calls."""
    n = n_pages(pdf)
    out = {"text": "", "pages_read": [], "pl_page": None, "n_pages": n, "method": None, "vision": None, "vision_calls": 0, "highlights": {}, "pl_text": ""}
    if n == 0:
        return out
    tmp = Path(tempfile.mkdtemp(prefix="ocr_"))
    try:
        printed = None
        if n > 8:
            for pg in (2, 3):
                imgs = render(pdf, pg, pg, tmp, dpi=80)
                if not imgs:
                    continue
                cv = vision_contents(imgs[0])
                out["vision_calls"] += 1
                if cv and isinstance(cv.get("pl_printed_page"), int) and 1 <= cv["pl_printed_page"] <= n:
                    printed = cv["pl_printed_page"]
                    break
        if printed:
            candidates = [q for q in (printed + 1, printed + 2, printed, printed + 3) if 1 <= q <= n]
            out["method"] = "contents-vision"
        else:
            fr = (0.5, 0.6, 0.4) if n > 12 else (0.5, 0.7)
            candidates = list(dict.fromkeys(max(1, int(n * f)) for f in fr))
            out["method"] = "scan-vision"
        for q in candidates:
            if out["vision_calls"] >= 6:
                break
            imgs = render(pdf, q, q, tmp, dpi=dpi)
            if not imgs:
                continue
            v = vision_extract(imgs[0])
            out["vision_calls"] += 1
            out["pages_read"].append(q)
            if v and (v.get("revenue") is not None or v.get("operating_profit") is not None or v.get("profit_before_tax") is not None):
                out["vision"] = v
                out["pl_page"] = q
                break
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("vision read failed for %s: %s", pdf.name, e)
        return out
    finally:
        for f in tmp.glob("*"):
            f.unlink(missing_ok=True)
        try:
            tmp.rmdir()
        except OSError:
            pass


def vision_to_pounds(v: dict) -> dict:
    """Scale the vision JSON to pounds by its unit field."""
    unit = (v.get("unit") or "").lower()
    mult = 1_000_000 if "million" in unit else (1_000 if "thousand" in unit or "'000" in unit else 1)
    out = {}
    for k in ("revenue", "operating_profit", "profit_before_tax", "ebitda"):
        x = v.get(k)
        if isinstance(x, (int, float)):
            out[k] = float(x) * mult
    if isinstance(v.get("employees"), (int, float)):
        out["employees"] = int(v["employees"])
    out["period_end"] = v.get("period_end")
    out["consolidated"] = v.get("consolidated")
    out["unit"] = unit
    return out
