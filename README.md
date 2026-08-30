# TobyAI public site

Source of [www.tobyai.io](https://www.tobyai.io), served by GitHub Pages from
`main`. This repository holds the public site and the waitlist endpoint behind
its signup form. It does not hold the TobyAI product, which is private.

## What TobyAI is

An Australian compliance platform for businesses, bookkeepers, accountants and
advisers. Every compliance figure is computed in auditable Python from
versioned schedules and a cited corpus of legislation and regulator data, and
each answer carries its source, the publisher's own date, and the working.
An AI model explains an answer and never originates a figure, a rate, a
threshold or a date.

Day-one coverage is income tax, GST, PAYG withholding, payroll tax, workers
compensation, work health and safety, and Fair Work awards, for businesses
operating in Queensland, New South Wales and Victoria.

## Layout

- `index.html`, `privacy.html`, `terms.html`, `404.html`: the site.
- `robots.txt`, `sitemap.xml`, `CNAME`, `_config.yml`: publication and indexing.
- `toby_logo_*`: brand assets used by the pages and the social card.
- `waitlist/`: the Lambda handler, tests and deployment script for the Sydney
  waitlist endpoint. See `waitlist/README.md` for the stack it deploys into.

There is no build step. Jekyll publishes the files as they are, with
`README.md` excluded from the published site.

## Working on it locally

```bash
python3 -m http.server 8899
```

Then open `http://localhost:8899/`. The signup form posts to the live
production endpoint, so do not submit a real address while testing.

Waitlist handler tests:

```bash
python -m pip install -r waitlist/requirements-dev.txt
python -m pytest waitlist/
```

## Contributing

The site is maintained by Toby Experts. Issues and pull requests from outside
the organisation are not expected. Nothing here is licensed for reuse.
