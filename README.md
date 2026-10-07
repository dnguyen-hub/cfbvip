# CFB VIP

An internal college-football decision-support platform in development. The long-term goal is a staff-facing website containing focused tools for game planning, practice planning, roster evaluation, and situational analysis.

## Explosive Opportunity Finder

The first feature finds situations where Georgia Tech is most likely to gain **at least five yards more than expected**.

For every qualifying rush or pass:

```text
yards above expected = actual yards gained - contextual expected yards
```

A play is marked as a contextual explosive opportunity when:

```text
yards above expected >= 5
```

Expected gain is learned from historical FBS plays with the same:

- Down
- Distance bucket
- Field zone
- Run/pass family

If an exact situation has fewer than the configured minimum number of plays, the model automatically backs off to down/distance/run-pass, then run/pass, then the league average. The traditional 10+ yard result remains in the report as a comparison metric.

## Why the API usage stays small

The tool requests an entire FBS week once and caches it locally. It then filters Georgia Tech and the selected opponent from that local file.

For example, training on two 17-week seasons uses approximately 34 calls. Building the report season uses another 17 calls the first time. Re-running against the cache uses zero calls.

Live play-by-play is not required. Practice and game-planning reports can be produced from completed historical weeks.

## Project layout

```text
src/cfbvip/features/explosive_opportunity/
  analysis.py  # play labeling, expected-gain model, matchup scoring
  cfbd.py      # CollegeFootballData client and local caching
  report.py    # HTML and CSV report generation
  cli.py       # train/build/demo commands
run_explosivity.py  # zero-install runner used by the commands below
tests/
  test_explosive_opportunity.py
var/
  cache/       # API responses; ignored by Git
  models/      # trained expected-gain models; ignored by Git
  reports/     # generated HTML and CSV reports; ignored by Git
```

## Run it

All commands below should be run from the `cfbvip` repository root.

### 1. Open a terminal in the repository

```bash
cd "/Users/dereknguyen/Documents/School/VIP/cfbvip"
```

### 2. Optional: create a local Python environment

Python 3.10 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On future terminal sessions, reactivate it with:

```bash
source .venv/bin/activate
```

No packages need to be installed for the direct runner used below.

### 3. Configure CollegeFootballData

Rotate any API key previously shared in chat. Set the replacement key locally—never paste it into the repository:

```bash
export CFBD_API_KEY='your-rotated-key'
```

The key is only required when a requested week is not already cached.

### 4. Train an expected-gain model

This example trains on the completed 2023 and 2024 seasons:

```bash
python3 run_explosivity.py train \
  --seasons 2023 2024 \
  --through-week 16 \
  --model var/models/expected-gain-2023-2024.json
```

The first run downloads each FBS week once. Later runs reuse `var/cache`.

### 5. Build a matchup report

```bash
python3 run_explosivity.py build \
  --season 2025 \
  --through-week 16 \
  --model var/models/expected-gain-2023-2024.json \
  --team "Georgia Tech" \
  --opponent "Clemson" \
  --output var/reports/gt-vs-clemson-2025.html
```

The command generates:

```text
var/reports/gt-vs-clemson-2025.html
var/reports/gt-vs-clemson-2025.csv
```

On macOS, open the report with:

```bash
open var/reports/gt-vs-clemson-2025.html
```

### 6. Update during a season

Set `--through-week` to the latest completed week. Weeks already cached do not make another request:

```bash
python3 run_explosivity.py build \
  --season 2026 \
  --through-week 6 \
  --model var/models/expected-gain-2023-2024.json \
  --team "Georgia Tech" \
  --opponent "Clemson" \
  --output var/reports/gt-vs-clemson-2026.html
```

If Week 6 was previously downloaded before its games finished, refresh only that week:

```bash
python3 run_explosivity.py build \
  --season 2026 \
  --through-week 6 \
  --refresh-week 6 \
  --model var/models/expected-gain-2023-2024.json \
  --team "Georgia Tech" \
  --opponent "Clemson" \
  --output var/reports/gt-vs-clemson-2026.html
```

Use `--refresh` only when every requested week intentionally needs to be downloaded again.

### 7. Run the offline demonstration first

This requires no API key or network connection:

```bash
python3 run_explosivity.py demo --output var/reports/demo.html
open var/reports/demo.html
```

This is the fastest sanity check because it needs neither an API key nor downloaded data.

### 8. Run the tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

### 9. Check for an exposed API key before committing

```bash
python3 scripts/check_secrets.py
```

The same check runs automatically on GitHub pushes and pull requests. The real
key must stay in the `CFBD_API_KEY` environment variable. `.env`, downloaded
API responses, trained models, and generated reports are excluded by
`.gitignore`.

### Optional: install the short command

If you prefer `cfbvip-explosive` instead of `python3 run_explosivity.py`, install the repository in editable mode:

```bash
python3 -m pip install -e .
cfbvip-explosive demo --output var/reports/demo.html
```

## Report fields

The primary report and CSV include:

- Contextual expected yards
- Georgia Tech's rate of beating expectation by 5+ yards
- Opponent's rate of allowing expectation to be beaten by 5+ yards
- Average yards above expected
- Combined matchup opportunity probability
- Traditional 10+ yard rates
- Sample size and confidence
- Data-quality exclusion counts

## Public-data limitations

Public play-by-play supplies the situation and outcome, but usually not formation, personnel, motion, concept, coverage, front, pressure, or why execution failed. The next meaningful upgrade is an internal tagged-film export containing those fields and a video link.

## Website roadmap

1. Wrap the feature service in a web API.
2. Store normalized plays, teams, reports, and model versions in a database.
3. Build a shared frontend shell for multiple football tools.
4. Add staff authentication and role-based access.
5. Integrate internal tagged data and film links.
6. Add practice-priority and approved in-game views.
