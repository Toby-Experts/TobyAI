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

`index.html` submits to a live production endpoint that writes to the owner's real waitlist
store. **The endpoint has changed between page versions** — read `ENDPOINT_URL`/`SCRIPT_URL` at
the top of the inline `<script>` before testing, and build the negative-evidence filter from what
you find there. It has been a Google Apps Script (`script.google.com/macros/...`) and, more
recently, an AWS API Gateway URL
(`https://<id>.execute-api.ap-southeast-2.amazonaws.com/waitlist`, DynamoDB-backed).

**Never submit a value containing `@`.** The client-side guard is
`if (!email || !email.includes('@'))`, so the only safe submissions are the empty field and a
malformed string such as `abc`. Stop at the validation error; the success panel can only be
reached by writing a real row.

Useful ids: `#f-email`, `#form-error` (`Please enter a valid email address.`), `#form-btn`,
`#signup-form`, `#success-msg`, honeypot `#company-website` (only read *after* the guard, so it
cannot trigger a request on the safe inputs). Confirm nothing was sent with:

```js
performance.getEntriesByType('resource').map(r => r.name)
  .filter(n => /execute-api|waitlist|script\.google|macros/.test(n))
```

The success panel is revealed only by `done()`, the fetch callback, so it cannot be reached
without writing to the sheet. To prove its markup and legibility instead:

```js
document.getElementById('signup-form').style.display='none';
document.getElementById('success-msg').style.display='block';
```

Say in the report that this proves styling only, not that a real submission reaches `done()`.

### Request-listener trap (negative network evidence)

A long-lived background Playwright process that only attaches over CDP
(`connect_over_cdp` + `page.on("request", ...)`) and then idles may silently stop receiving
events once another CDP client (e.g. the computer-use tool) touches the same tab: the process
stays alive and the log stays empty, so "zero Apps Script requests" would be meaningless. Do the
network-evidence run in **one short script** that attaches, registers the listener, reloads (a
reload must log ~6 requests as a liveness sanity check), performs the clicks itself, then prints
the request list. Corroborate with `performance.getEntriesByType('resource')`.

## Hitting exact CSS viewport widths

Chrome on these boxes runs page zoom at 200% for localhost, so `innerWidth` is half the window
width. The window manager will not resize Chrome narrow either, so drive zoom instead. Maximise
first (`wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz`), then step zoom with xdotool
(`ctrl+plus` does not register; use `ctrl+equal`):

```bash
W=$(xdotool search --name "Chrome for Testing" | head -1)
xdotool key --window $W ctrl+minus   # zoom OUT -> LARGER CSS viewport
xdotool key --window $W ctrl+equal   # zoom IN  -> SMALLER CSS viewport
```

The direction is counter-intuitive: to reach a *phone* width you zoom **in**. From a maximised
1600px window, `ctrl+0` then eight `ctrl+equal` presses lands on exactly 400 CSS px, and `ctrl+0`
then two lands on exactly 1280. Re-read `innerWidth` after every batch; the zoom state persists
across navigations and across sessions, so never assume it starts at 100%.

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

Tokens are rewritten between page versions, so read `:root` rather than assuming. Current tokens:
`--sans: 'Instrument Sans', system-ui, sans-serif` on `body`, and
`--serif: 'Source Serif 4', Georgia, serif` applied only to `blockquote`, `.strip p` and
`.success h3`. Assert computed `fontFamily` on the serif surfaces and on `body`, `h1`, `.cite`,
`.card-head`, `table` (sans), plus one visual zoom, since a Georgia fallback would also pass a
"is it serif" check. Google Fonts and plausible.io requests are expected, declared in the head.
plausible.io is usually blocked by uBlock in these browsers, producing exactly one console error
`Failed to load resource: net::ERR_BLOCKED_BY_CLIENT` — expected, not a defect.

## Responsive breakpoints differ from each other

The page can collapse layout and abbreviate content at *different* widths (currently
`max-width: 860px` for one-column hero/grids and hidden top nav, `max-width: 640px` for
`.full` -> `.abbr` jurisdiction labels). Always test an intermediate width (800px) as well as
desktop and ~400px: that is the zone where a one-column layout still renders full labels
(`New South Wales`, `nil, phased out`) and a wide table is most likely to overflow.

## Known trap: unstyled inline links on the dark page

The page styles the footer links teal but inline links inside body copy can fall back to the
browser default `rgb(0, 0, 238)` blue (visited purple), which is near-illegible on the navy
background. Read `getComputedStyle(a).color` on every `<a>` in body copy, not just the footer.

One standing **false positive**: the brand-mark link in `404.html`'s nav computes
`rgb(0, 0, 238)`, but its child spans set their own white/teal colour, so nothing blue is ever
painted. Before reporting a default-blue link, zoom into the pixels and confirm it is actually
visible; an `<a>` whose text lives entirely in coloured children is harmless.

## Copy-change PRs: scan rendered text *and* attributes

Wording changes often live in attributes (e.g. the email `placeholder`), which
`document.body.innerText` will not catch. Scan both:

```js
const txt = document.body.innerText;
const attrs = [...document.querySelectorAll('*')].flatMap(el =>
  ['placeholder','alt','title','aria-label'].map(a => el.getAttribute(a)).filter(Boolean));
[txt, ...attrs].join(' | ').match(/<old wording>/gi)
```

Run it over every page (`/`, `/privacy.html`, `/terms.html`, `/404.html`) and also confirm the
new strings are visible in the pixels with a zoom, not merely present in the DOM.

## Crawlability

`robots.txt` should be `User-agent: *` / `Allow: /` plus a `Sitemap:` line, and only `404.html`
should keep `<meta name="robots" content="noindex">`:

```bash
for p in index.html privacy.html terms.html 404.html; do echo "== $p"; grep -i 'name="robots"' $p || echo "(none)"; done
```

## Devin Secrets Needed

None. The site needs no login and no credentials.
