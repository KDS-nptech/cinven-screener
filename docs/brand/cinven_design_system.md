# Cinven design system, read from cinven.com (9 Nov 2026)

Source: https://www.cinven.com/wp-content/themes/cinven/public/build/style-414cabed.css (saved as style.css), home.html, portfolio.html, approach.html, team.html, news.html in this folder. Fonts saved as .woff2 next to this file.

**Conclusion:** cinven.com is a dark-teal and taupe system set in two typefaces: Bagoss Condensed (light 300 and regular 400) for every heading, Suisse Int'l (400 and 500) for everything else. Backgrounds are white or light gray with a teal footer block; accents are one bright teal and a set of soft pastels (lime, lavender, orange, coral) used sparingly as tags and chart fills. Buttons are full pills. Radii are 10px on cards and 16px on large blocks. Eyebrow labels in small caps sit above every section heading.

## Colour tokens (CSS variables, verbatim)

| Token | Value | Use on the site |
|---|---|---|
| --teal | #003544 | primary text colour, footer background, primary button |
| --teal-mid | #00D6D3 | bright accent, links on dark, chart highlight |
| --button-focus | #00959A | hover and focus state for buttons |
| --teal-mid-60 | rgba(61,140,153,.6) | secondary accent |
| --teal-dark-80 / 40 / 20 | rgba(0,53,68,.8 / .4 / .2) | muted text, dividers, rules |
| --taupe | #E4E0DC | card backgrounds, read-more buttons |
| --taupe-40 / 20 | rgba(228,224,220,.4 / .2) | hover tints |
| --light-gray | #F4F3F1 | page section background |
| --white | #fff | page background |
| --home-eyebrow | #BAD1D8 | eyebrow label colour on dark |
| --lime | #C6E264 | tag and chart fill |
| --lavender | #ADC4FF | tag and chart fill |
| --orange | #F0B643 | tag and chart fill |
| --coral | #FF6D6B | tag and chart fill, warnings |
| --black | #000 | borders |

Secondary colours seen in the stylesheet: #144553 (deep teal hover), #C3CDCF (muted border), #FAF9F8 (off-white), #46FFF1 (bright teal highlight).

## Typography

- Headings: `font-family: "Bagoss Condensed", sans-serif`; h1 300 weight, letter-spacing -0.01em, line-height 1.1 (1.05 at 1024px+); sizes h1 1.75rem to 3rem (768px) to 4rem (1024px); h2 2rem 400; h3 1.5rem 400; h4 1.125rem 400.
- Body: `font-family: "Suisse Int'l", sans-serif`; weights 400 and 500 only; utility sizes .t-12 to .t-36 (12, 14, 16, 18, 20, 24, 28, 32, 36 px equivalents).
- Eyebrow: small uppercase label (`.eyebrow`, t-12 or t-14, letter-spaced) with an animated underline rule (`.eyebrow--border`), above every section heading. Copy examples: "Our approach", "sectors in which we specialise", "Featured portfolio companies", "news & insights".
- Statistic cards (`.card`): value 4rem to 6rem Bagoss 400 letter-spacing -0.02em, label 1.25rem to 1.5rem; card 10px radius, taupe or pastel backgrounds.

## Components

- Button: pill (`border-radius: 200px`), teal background, white text, weight 500, hover `--button-focus`; secondary variant outlined with a 1px box-shadow; read-more variant on taupe.
- Header: fixed, white, teal text; dark variant inverts to white text. Nav: Team, Portfolio, Approach, News & Insights, plus Company, Sustainability, Governance, Contact Us.
- Footer: `.footer__inner` teal block with 1rem radius inset from the page edge, white text, generous top margin.
- Filters (portfolio page): a filter panel, pill toggles by sector and status, cards in a grid.
- Spacing: 1rem page padding on phone, 3.5rem at 1024px+; sections separated by 5rem to 15rem.

## Voice

Short declarative lines. Homepage h1 "Discover the power of partnership"; h2 "We're an international private equity firm that invests in high-performing businesses with strong potential for growth." Sections: Our approach, A track record of realising untapped potential, sectors in which we specialise, Featured portfolio companies.

## How the screener uses it

The static site reads these tokens: teal rail and footer, white and light-gray content, Bagoss Condensed headings with eyebrows, Suisse Int'l body, pill buttons, 10px cards, pastel tags for sectors (Business Services lavender, Consumer orange, Financial Services teal-mid, Healthcare lime, Industrials taupe, TMT coral). No Cinven logo, wordmark or trademark is reproduced; the site is labelled as an independent screener built on public data.
