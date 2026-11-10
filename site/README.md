# Site

Everything the dashboard needs is in this folder. `index.html` is the whole screener: every view, the styles, the script and the data are inlined in one file, so there is no build step and no server code.

## Deploy on Cloudflare Pages

1. Cloudflare dashboard, Workers & Pages, Create, Pages, Connect to Git, pick `KDS-nptech/cinven-screener` (a private repo works).
2. Framework preset: None. Build command: leave empty. Build output directory: `site`.
3. Save and Deploy. Every push that changes this folder redeploys.

Without Git: Workers & Pages, Create, Pages, Upload assets, and drag this folder in.

## Files

- `index.html`: the screener (about 13 MB; Cloudflare's limit is 25 MB a file).
- `_headers`: asks search engines not to index the site and sets basic security headers.
- `.nojekyll`: only matters on GitHub Pages.

## Regenerating

`index.html` is generated; do not edit it by hand. From the repo root:

```
python -m src.site.export   # writes site/data.json from the scored tables (gitignored)
python -m src.site.build    # inlines the data into src/site/template.html and writes site/index.html
```

The page layout, styles and script live in `src/site/template.html`.
