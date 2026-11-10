# Microbiome Faculty Jobs

An open, daily-updated tracker of **faculty positions in microbiome science** worldwide, with a searchable website, a world map, and a page for every position.

Positions are sorted into research areas — **human health, animal health, ocean & marine, aquaculture & fisheries, soil, plant, agriculture, food & fermentation, environment & climate, computational & data**, and general microbiology & ecology — and labelled by **rank** (assistant, associate, full, open rank, lecturer, group leader), **tenure status** (tenure-track, tenured, permanent/continuing, non-tenure-track), **institution type** (R1, R2, doctoral, primarily undergraduate institution (PUI), medical school, veterinary school, Ivy League, HBCU, women's/historically women's college, tribal college, land-grant, research institute, outside the US), and the **research/teaching effort split** and teaching load when the posting states them (or "not stated"). Positions that call for **bioinformatics** or **multi-omics** work are flagged too.

Positions whose **review start or full-consideration date has already passed are marked "low priority"** and listed after the rest: the search may be well underway.

Everything runs free on GitHub: a GitHub Action collects postings once a day and GitHub Pages hosts the site.

---

## What the site does

- **Search and filters** — free text, research area, rank, tenure, institution type, methods (bioinformatics, multi-omics — tick both to require both), research/teaching effort (research-heavy, balanced, teaching-heavy, not stated), world region and country, how recently a position was first listed, hide low-priority, include closed. Filters are kept in the page address, so a filtered view can be bookmarked or shared.
- **World map** — every position with a known location, colored by research area; click a pin for a link.
- **Detail page per position** (opens in a new tab) — rank, tenure, institution type with its Carnegie classification, effort split and teaching load (with the sentence they came from), research areas, review date and deadline with the sentence they were taken from, salary when stated, location map, every board it was listed on, and a button to the **original posting**.
- **Feed and download** — `feed.xml` (subscribe in any feed reader to get new positions) and `data/jobs.csv`.
- **Source health** — the footer shows which boards were read successfully on the last run.

## Where postings come from

| Source | Region | How it's read |
|---|---|---|
| Science Careers (AAAS) | worldwide | keyword RSS search + the schema.org data on each job page |
| The Chronicle of Higher Education Jobs | worldwide | same |
| Inside Higher Ed Careers | mostly US | same |
| HigherEdJobs | US | official category RSS feeds (biology, animal & plant & soil science, veterinary medicine, public health, oceanography, …); each faculty-titled posting is opened once to read its description |
| Times Higher Education Unijobs | worldwide | life-science and health category pages, plus Hong Kong, Singapore, China, Australia and New Zealand region pages (its robots.txt disallows job feeds and keyword searches) |
| EURAXESS (European Commission) | Europe and worldwide | new job pages by job number, ~250 a day, plus a month of older ones read gradually; only faculty-level profiles (R3/R4) or faculty titles are kept. Its robots.txt asks robots not to run searches, so none are run |
| jobs.ac.uk | UK and Europe | keyword search pages + schema.org data |
| Academic Positions | Europe | **off** — refuses requests from GitHub's servers; linked under Where else to look |
| University Positions | Europe | category pages (its RSS feed is disallowed in robots.txt) |
| Max Planck Society | Germany | official job RSS feed |
| JREC-IN Portal | Japan | keyword search with Japanese terms (マイクロバイオーム, 微生物叢, 腸内細菌, …); postings machine-translated |
| jobRxiv | worldwide | faculty category RSS feed (latest 100) + schema.org data on each job page |
| FEMS | Europe | microbiology job board RSS feed |
| Nature Careers | worldwide | **off** — nature.com's robots.txt disallows its job feeds for automated tools |
| Community submissions | anywhere | any URL in `data/submitted_urls.txt` |

Boards that can't be read automatically (Academics.com, AcademicTransfer, national portals in Hong Kong, Singapore, China, India, Japan, Korea, Taiwan, Australia and New Zealand) and fellowships that lead to faculty posts (Emmy Noether, NRF, Ramanujan, Ramalingaswami) are listed under **Where else to look** on the website. That list lives in [`config/resources.yaml`](config/resources.yaml).

Boards are searched for *microbiome, microbiota, metagenomics, microbial ecology, host-microbe, holobiont, rhizosphere, phytobiome*. A posting is kept only if its title looks like a faculty rank (not postdoc, technician, adjunct, …) and its text mentions a microbiome term. Titles and terms in German, Dutch, French, Nordic and Southern European languages are recognised too (e.g. *W2/W3-Professur, Juniorprofessur, universitair (hoofd)docent, hoogleraar, maître de conférences, universitetslektor; Mikrobiom, microbiote, microbioom*). All of these rules are plain lists in [`config/taxonomy.yaml`](config/taxonomy.yaml) and [`config/sources.yaml`](config/sources.yaml) — edit them to tune the tracker, no programming needed.

The collector is deliberately polite: it identifies itself, obeys `robots.txt` (including `*` and `$` wildcard rules), waits between requests, uses each board's own RSS feeds, opens a posting page only once (then re-checks active ones weekly), and **does not try to get around bot protection**. If a board blocks the GitHub servers, that board is skipped and shown as failed in the footer; the rest still update.

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

## Postings in other languages

Postings that aren't in English (JREC-IN, and any non-English posting on the other boards) are machine-translated into English and marked **Translated from …** on the site, with the original title kept on the position's page. Only postings that already mention microbiome terms in their own language are translated, so translation stays quick. Terms and job titles in Japanese, Chinese, Korean and the main European languages are in [`config/taxonomy.yaml`](config/taxonomy.yaml).

- **Free, offline (default):** [Argos Translate](https://github.com/argosopentech/argos-translate) models run inside the GitHub Action. A model (~100 MB) is downloaded the first time a language is needed.
- **Better quality (optional):** create a free [DeepL API](https://www.deepl.com/pro-api) account and add its key as a repository secret named `DEEPL_API_KEY` (Settings → Secrets and variables → Actions). The free plan's 500,000 characters a month is far more than the tracker uses.

Translations are cached in `data/translations.json`, so each posting is translated once. If translation fails, the posting is kept in its original language.

## Visitor statistics (optional)

The site can count visits with [GoatCounter](https://www.goatcounter.com): free for non-commercial sites, no cookies (so no consent banner), no personal data. Each position page is counted separately under its title, so you can see which positions people open.

1. Sign up at goatcounter.com and choose a site code, e.g. `mfjobs` (your dashboard is then `https://mfjobs.goatcounter.com`).
2. Put that code between the quotes in [`docs/assets/analytics.js`](docs/assets/analytics.js): `const GOATCOUNTER_CODE = "mfjobs";`
3. Commit and push. Visits show up in your GoatCounter dashboard within a minute.

Leave the code empty to turn counting off. Visitors with ad or tracker blockers aren't counted, so treat the numbers as a lower bound. (GitHub's own **Insights → Traffic** page counts visits to the repository on github.com, not to the website.)

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
| Bioinformatics | the posting mentions bioinformatics, computational biology, analysis of sequencing/omics data, machine learning, data science or systems biology (also in German, French, Spanish, Japanese, Chinese and Korean); the detail page quotes the sentence |
| Multi-omics | the posting says multi-omics / integrative omics, **or** names two or more omics layers (metagenomics, metatranscriptomics, metaproteomics, metabolomics, genomics, transcriptomics, proteomics, epigenomics, spatial omics, 16S/amplicon); the layers found are listed on the detail page. Patterns are in `method_flags` in `config/taxonomy.yaml` |
| Teaching load | "2-2 teaching load", "3/3 load", "teaching load of two courses per semester" |
| Institution type (US) | the employer is matched to the U.S. Department of Education's IPEDS directory: Carnegie basic classification (R1, R2, doctoral/professional, master's and baccalaureate = **PUI**, medical school/center, special focus, two-year) and official HBCU, tribal, land-grant and medical-degree flags; **veterinary school** = the institution has Doctor of Veterinary Medicine graduates in IPEDS completions data (program code 51.2401). If the employer is listed as a department, the institution's name is looked for in the posting text. Ivy League and women's/historically women's colleges come from [`config/institution_lists.yaml`](config/institution_lists.yaml) |
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
