# Microbiome Faculty Jobs

An open, daily-updated tracker of **faculty positions in microbiome science** worldwide, with a searchable website, a world map, and a page for every position.

Positions are sorted into research areas — **human health, animal health, ocean & marine, aquaculture & fisheries, soil, plant, agriculture, food & fermentation, environment & climate, computational & data**, and general microbiology & ecology — and labelled by **rank** (assistant, associate, full, open rank, lecturer, group leader), **tenure status** (tenure-track, tenured, permanent/continuing, non-tenure-track), **institution type** (R1, R2, doctoral, primarily undergraduate institution (PUI), medical school, Ivy League, HBCU, women's/historically women's college, tribal college, land-grant, research institute, outside the US), and the **research/teaching effort split** and teaching load when the posting states them (or "not stated").

Positions whose **review start or full-consideration date has already passed are marked "low priority"** and listed after the rest: the search may be well underway.

Everything runs free on GitHub: a GitHub Action collects postings once a day and GitHub Pages hosts the site.

---

## What the site does

- **Search and filters** — free text, research area, rank, tenure, institution type, research/teaching effort (research-heavy, balanced, teaching-heavy, not stated), world region and country, how recently a position was first listed, hide low-priority, include closed. Filters are kept in the page address, so a filtered view can be bookmarked or shared.
- **World map** — every position with a known location, colored by research area; click a pin for a link.
- **Detail page per position** (opens in a new tab) — rank, tenure, institution type with its Carnegie classification, effort split and teaching load (with the sentence they came from), research areas, review date and deadline with the sentence they were taken from, salary when stated, location map, every board it was listed on, and a button to the **original posting**.
- **Feed and download** — `feed.xml` (subscribe in any feed reader to get new positions) and `data/jobs.csv`.
- **Source health** — the footer shows which boards were read successfully on the last run.

## Where postings come from

| Source | How it's read |
|---|---|
| Science Careers (AAAS) | keyword RSS search + the schema.org data on each job page |
| Nature Careers | **off by default** — nature.com's robots.txt disallows its job feeds for automated tools |
| The Chronicle of Higher Education Jobs | same |
| Inside Higher Ed Careers | same |
| Times Higher Education Unijobs | same |
| HigherEdJobs | official category RSS feeds (biology, animal & plant & soil science, veterinary medicine, public health, oceanography, …); each faculty-titled posting is opened once to read its description |
| Community submissions | any URL in `data/submitted_urls.txt` |

Boards are searched for *microbiome, microbiota, metagenomics, microbial ecology, host-microbe, holobiont, rhizosphere, phytobiome*. A posting is kept only if its title looks like a faculty rank (not postdoc, technician, adjunct, …) and its text mentions a microbiome term. All of these rules are plain lists in [`config/taxonomy.yaml`](config/taxonomy.yaml) and [`config/sources.yaml`](config/sources.yaml) — edit them to tune the tracker, no programming needed.

The collector is deliberately polite: it identifies itself, obeys `robots.txt`, waits between requests, uses each board's own RSS feeds, opens a posting page only once (then re-checks active ones weekly), and **does not try to get around bot protection**. If a board blocks the GitHub servers, that board is skipped and shown as failed in the footer; the rest still update.

The institution directory (IPEDS "HD" file, public domain, from nces.ed.gov) is downloaded on the first run and refreshed about once a year; it also supplies campus coordinates for the map.

Only short excerpts are stored. The site always links to the original posting, which is authoritative.

---

## Set it up (about 10 minutes)

You need a free GitHub account and [GitHub Desktop](https://desktop.github.com/).

**1. Put the folder in GitHub Desktop**
- Open GitHub Desktop → **File → Add local repository…** → choose this `microbiome-faculty-jobs` folder.
- It will say the folder isn't a Git repository yet — click **create a repository** (keep the name, leave "Initialize with README" unticked), then **Create repository**.
- Click **Publish repository**. **Untick "Keep this code private"** so the site can be public and open access, then **Publish**.

**2. Let the daily job save its results**
- On github.com open the repository → **Settings → Actions → General**.
- Under **Workflow permissions** choose **Read and write permissions** → **Save**.

**3. Turn on the website**
- **Settings → Pages** → under **Build and deployment**: Source **Deploy from a branch**, Branch **main**, folder **/docs** → **Save**.
- After a minute the site is live at `https://<your-username>.github.io/microbiome-faculty-jobs/` (the address is shown on that page).

**4. Run it the first time**
- **Actions** tab → if asked, click **I understand my workflows, go ahead and enable them**.
- Choose **Daily update** → **Run workflow** → **Run workflow**.
- The first run opens many postings once, so it can take 20–60 minutes. Later runs take a few minutes. After that it runs by itself every morning.

**5. Pull the updates to your laptop (optional)**
- The daily job commits new data to GitHub. In GitHub Desktop click **Fetch origin → Pull origin** before you edit anything locally, so your copy stays in sync.

### Optional
- **Accepting community submissions:** create a label named `add-to-tracker` (**Issues → Labels → New label**). When someone uses **Submit a position**, add that label to their issue: the URL is added, an update runs, and the issue is closed with a reply.
- **Geocoding contact:** add a repository secret `GEOCODER_EMAIL` (Settings → Secrets and variables → Actions) so OpenStreetMap's Nominatim service can reach you if needed.
- **Your own copy of the site address** in feeds and links is filled in automatically from the repository name.

---

## Run or test it locally

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt pytest
python -m pytest -q                                    # offline tests on fictional fixtures
python -m collector.run --only sciencecareers          # one live source
python -m http.server -d docs 8000                     # then open http://localhost:8000
```

## How the labels are decided

| Label | Rule (simplified) |
|---|---|
| Research area | keywords in title + description, per area, in `config/taxonomy.yaml` |
| Rank | title first (`Assistant`, `Associate`, `Professor`, `Open rank`, `Asst/Assoc/Full`, `Lecturer`, `Group leader`); if the title is vague, the opening of the description ("at the rank of …") |
| Tenure | "tenure-track", "tenured / with tenure", "permanent / continuing" (common outside the US), "non-tenure-track / clinical / research / teaching professor / fixed-term" |
| Review date | the earliest date in a sentence about review beginning, first review, priority date or full consideration |
| Deadline | the board's "application due" field, or the latest date in a sentence about a deadline / closing date |
| Effort split | percentages tied to research / teaching / extension / service / clinical ("60% research and 40% teaching", "research (70%)", "75/25 research/teaching"); otherwise "not stated" |
| Teaching load | "2-2 teaching load", "3/3 load", "teaching load of two courses per semester" |
| Institution type (US) | the employer is matched to the U.S. Department of Education's IPEDS directory: Carnegie basic classification (R1, R2, doctoral/professional, master's and baccalaureate = **PUI**, medical school/center, special focus, two-year) and official HBCU, tribal, land-grant and medical-degree flags. If the employer is listed as a department, the institution's name is looked for in the posting text. Ivy League and women's/historically women's colleges come from [`config/institution_lists.yaml`](config/institution_lists.yaml) |
| Institution type (non-US) | "Outside the US", plus "Research institute/hospital" when the employer is an institute, centre, laboratory or hospital |
| Low priority | review date is in the past |
| Review soon | review date or deadline within 14 days |
| Closed | deadline passed, or not seen on any board for 10 days, or the listing expired |

Labels come from text matching and will sometimes be wrong. Use **Report a problem** on any position page, or improve the rules with a pull request.

## Repository layout

```
collector/            Python collector (run daily by GitHub Actions)
config/sources.yaml   which boards and search keywords
config/taxonomy.yaml  microbiome terms, faculty/non-faculty titles, research-area keywords
config/institution_lists.yaml  Ivy League and women's / historically women's colleges
data/                 caches (geocoding, postings already checked, IPEDS institution directory) and submitted URLs
docs/                 the website (GitHub Pages) and its data: docs/data/jobs.json, meta.json, jobs.csv, feed.xml
tests/                offline tests with fictional fixtures
.github/              daily workflow, tests, submission workflow, issue forms
```

## License

Code: [MIT](LICENSE). Collected data (`docs/data/`): [CC BY 4.0](DATA_LICENSE.md). Job postings remain the property of the hiring institutions and job boards; this project stores short excerpts and links to the originals.
