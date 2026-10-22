# Contributing

This tracker is meant to be useful to the whole microbiome community. Contributions of every size are welcome.

## No code needed

- **Missing position?** Open a **Submit a position** issue with the link.
- **Wrong label, date or location?** Use **Report a problem** on the position's page (or open that issue form directly).
- **Better filters.** The rules are plain lists in [`config/taxonomy.yaml`](config/taxonomy.yaml):
  - `microbiome_terms` — a posting must mention one of these to be included;
  - `faculty_title_patterns` / `exclude_title_patterns` — what counts as a faculty title;
  - `domains` — keywords for each research area (add a new area by adding a block with a `label`, `color` and `patterns`).
  Edit the file on github.com and propose the change; the tests run automatically.
- **Another job board.** Add it to [`config/sources.yaml`](config/sources.yaml). Many academic boards (Science Careers, Nature Careers, the Chronicle, Inside Higher Ed, THE, New Scientist and others) run on the same platform (`type: madgex`), so a new one is often three lines.

## Code

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

- Keep the collector polite: one request at a time per site with a delay, respect `robots.txt`, use feeds where they exist, and never work around bot protection or log-ins.
- Store short excerpts only and always link to the original posting.
- Add a test (fictional fixture) when you change a rule that decides inclusion, rank, tenure or dates.
