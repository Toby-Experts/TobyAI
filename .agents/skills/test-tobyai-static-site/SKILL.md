---
name: test-tobyai-static-site
description: Browser-verify the TobyAI public marketing site (index.html, privacy.html, terms.html, 404.html, robots.txt, sitemap.xml). Covers serving it locally, hitting exact CSS viewport widths on a Devin box, and the live waitlist endpoint that must never receive a test submission.
---

# Testing the TobyAI public static site

Static Jekyll/GitHub Pages site, no build step. Serve the repo root and open it:

```bash
cd <repo root> && python3 -m http.server 8899 >/tmp/tobyai_http.log 2>&1 &
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8899/ http://localhost:8899/privacy.html \
  http://localhost:8899/terms.html http://localhost:8899/robots.txt
```

Reuse an already running server on that port rather than starting a second one.

## Safety: the waitlist form posts to a live endpoint

`index.html` posts to the Sydney API Gateway endpoint
`https://pc24esfy6h.execute-api.ap-southeast-2.amazonaws.com/waitlist`. A valid submission writes
a real row to the production `tobyai-waitlist` DynamoDB table. **Never submit a value containing
`@`.** The client-side guard is `if (!email || !email.includes('@'))`, so the only safe
submissions are the empty field and a malformed string such as `abc`. Stop at the validation
error; the success panel can only be reached by writing to the production table.

Useful ids: `#f-email`, `#form-error` (`Please enter a valid email address.`), `#form-btn`,
`#signup-form`, `#success-msg`. Confirm nothing was sent with:

```js
performance.getEntriesByType('resource').map(r => r.name).filter(n => /script\.google|macros/.test(n))
```

## Hitting exact CSS viewport widths

Chrome on these boxes runs page zoom at 200% for localhost, so `innerWidth` is half the window
width. The window manager will not resize Chrome narrow either, so drive zoom instead. Maximise
first (`wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz`), then step zoom with xdotool
(`ctrl+plus` does not register; use `ctrl+equal`):

```bash
W=$(xdotool search --name "Chrome for Testing" | head -1)
xdotool key --window $W ctrl+minus   # zoom out
xdotool key --window $W ctrl+equal   # zoom in
```

From a maximised 1600px-wide window the reachable CSS widths are roughly 1600, 1280, 1066, 914,
800 (default), 640, 533, 400, 320. So 1280 is exact and 400 is the closest stand-in for a 390px
phone; say so in the report. Always confirm with `innerWidth` before capturing.

## Layout assertions worth scripting rather than eyeballing

```js
document.scrollingElement.scrollWidth  // must equal clientWidth
```

For overlap, compare bounding rects of leaf text elements that are `position: static`, skipping
ancestor/descendant pairs. Expect zero pairs. Decorative `.bg-orb` divs deliberately extend past
the viewport but sit inside `.bg { overflow: hidden }`, so they are not overflow defects: check
the scrolling element, not every rect.

## Typography

Tokens live in `index.html`: `--font-head` (Big Shoulders Display), `--font-body`
(Instrument Sans), `--font-law` (`Georgia, 'Times New Roman', serif`). The verbatim statutory
quote is `.answer-quote` and must resolve to the Georgia stack while `h1`, `body` and
`.answer-cite` resolve to a sans stack. Google Fonts and plausible.io requests are expected,
they are declared in the head.

## Known trap: unstyled inline links on the dark page

The page styles the footer links teal but inline links inside body copy can fall back to the
browser default `rgb(0, 0, 238)` blue (visited purple), which is near-illegible on the navy
background. Read `getComputedStyle(a).color` on every `<a>` in body copy, not just the footer.

## Crawlability

`robots.txt` should be `User-agent: *` / `Allow: /` plus a `Sitemap:` line, and only `404.html`
should keep `<meta name="robots" content="noindex">`:

```bash
for p in index.html privacy.html terms.html 404.html; do echo "== $p"; grep -i 'name="robots"' $p || echo "(none)"; done
```

## Devin Secrets Needed

None. The site needs no login and no credentials.
