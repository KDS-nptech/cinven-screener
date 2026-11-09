"""Build the static site from the exported bundle.

    python -m src.site.export && python -m src.site.build

Writes site/index.html (a complete document, for GitHub Pages or opening from disk) and
site/artifact.html (the same page without the document skeleton, for publishing as an artifact).
The data is inlined so the page is one self-contained file.
"""
from __future__ import annotations

import json
import pathlib

from src.common import REPO, get_logger

log = get_logger("site_build")
SITE = REPO / "site"
TEMPLATE = pathlib.Path(__file__).with_name("template.html")


def main():
    data = (SITE / "data.json").read_text()
    # </script> inside the JSON would end the data block early; escape the one character that matters.
    data = data.replace("</", "<\\/")
    body = TEMPLATE.read_text().replace("__DATA__", data)
    (SITE / "artifact.html").write_text(body)
    full = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<meta name=\"color-scheme\" content=\"light dark\">\n<style>html,body{margin:0;min-height:100%}img{max-width:100%}[hidden]{display:none!important}</style>\n</head>\n<body>\n"
            + body + "\n</body>\n</html>\n")
    (SITE / "index.html").write_text(full)
    (SITE / ".nojekyll").write_text("")
    log.info("wrote site/index.html (%.1f MB) and site/artifact.html", (SITE / "index.html").stat().st_size / 1e6)


if __name__ == "__main__":
    main()
