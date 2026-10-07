from __future__ import annotations

import csv
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis import (
    ExpectedGainModel,
    ScoredPlay,
    overall_summary,
    summarize_matchup,
)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _yards(value: float, *, signed: bool = False) -> str:
    return f"{value:+.1f}" if signed else f"{value:.1f}"


def _esc(value: Any) -> str:
    return html.escape(str(value))


def build_report(
    *,
    team: str,
    opponent: str,
    season: int,
    through_week: int,
    model: ExpectedGainModel,
    offense_plays: list[ScoredPlay],
    defense_plays: list[ScoredPlay],
    offense_exclusions: dict[str, int],
    defense_exclusions: dict[str, int],
    output_path: str | Path,
) -> tuple[Path, Path]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = summarize_matchup(
        offense_plays,
        defense_plays,
        plus_five_prior=model.plus_five_prior,
    )
    own = overall_summary(offense_plays)
    allowed = overall_summary(defense_plays)

    actionable = [
        row
        for row in rows
        if row["offense_attempts"] >= 20 and row["defense_attempts"] >= 20
    ]
    exploratory = [
        row
        for row in rows
        if row not in actionable
        and row["offense_attempts"] >= 5
        and row["defense_attempts"] >= 5
    ]
    displayed = (actionable + exploratory)[:20]

    csv_path = output.with_suffix(".csv")
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")

    cards = "".join(
        _card(index, row, opponent) for index, row in enumerate(displayed, 1)
    )
    if not cards:
        cards = '<div class="empty">No matchup cells have at least five plays on both sides yet.</div>'

    exclusion_rows = "".join(
        f"<tr><td>{_esc(reason.replace('_', ' ').title())}</td>"
        f"<td>{offense_exclusions.get(reason, 0)}</td>"
        f"<td>{defense_exclusions.get(reason, 0)}</td></tr>"
        for reason in sorted(set(offense_exclusions) | set(defense_exclusions))
    )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    training_seasons = ", ".join(str(year) for year in model.training_seasons)

    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(team)} vs {_esc(opponent)} — Explosive Opportunity Finder</title>
<style>
:root{{--navy:#003057;--gold:#b3a369;--cream:#f7f4eb;--ink:#17202a;--muted:#68717b;--line:#ded9cb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--cream);color:var(--ink);font:15px/1.45 Inter,ui-sans-serif,system-ui,sans-serif}}
header{{background:var(--navy);color:#fff;padding:38px 24px 76px}}.wrap{{width:min(1120px,calc(100% - 32px));margin:0 auto}}
.kicker{{color:#e6d99b;font-size:12px;font-weight:800;letter-spacing:.15em;text-transform:uppercase}}h1{{font-size:clamp(30px,5vw,54px);line-height:1.05;margin:10px 0 12px}}header p{{color:#d8e2e9;max-width:820px}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:-44px}}.stat,.opportunity,.quality,.note{{background:#fff;border:1px solid var(--line);border-radius:16px}}
.stat{{padding:21px;box-shadow:0 10px 35px #001a2c18}}.stat span{{display:block;color:var(--muted);font-size:12px;font-weight:700;text-transform:uppercase}}.stat strong{{display:block;color:var(--navy);font-size:32px}}.stat small,.meta{{color:var(--muted)}}
main{{padding:32px 0 64px}}h2{{color:var(--navy)}}.opportunities{{display:grid;gap:9px}}.opportunity{{display:grid;grid-template-columns:44px 1fr auto;align-items:center;gap:15px;padding:15px 18px}}
.rank{{display:grid;place-items:center;height:36px;width:36px;border-radius:50%;background:#efe9d8;color:var(--navy);font-weight:900}}.eyebrow{{color:#827648;font-size:11px;font-weight:800;letter-spacing:.09em;text-transform:uppercase}}h3{{margin:3px 0 4px;font-size:17px}}
.score{{min-width:170px;text-align:right}}.score strong{{display:block;color:var(--navy);font-size:25px}}.score span{{display:block;color:var(--muted);font-size:11px}}.confidence{{display:inline-block;border-radius:999px;padding:3px 8px;font-size:10px;font-style:normal;font-weight:800;text-transform:uppercase}}.high{{background:#dff3e8;color:#14603a}}.medium{{background:#fff0c9;color:#765514}}.low{{background:#f5dfdf;color:#873333}}
.note,.quality{{padding:18px;margin-top:16px}}.note{{border-left:5px solid var(--gold)}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;border-bottom:1px solid #eee9dc;padding:9px 7px}}th{{color:var(--muted);font-size:11px;text-transform:uppercase}}footer{{color:var(--muted);font-size:12px;margin-top:30px}}.empty{{background:#fff;padding:24px;border:1px solid var(--line);border-radius:16px;color:var(--muted)}}
@media(max-width:820px){{.stats{{grid-template-columns:1fr 1fr}}.opportunity{{grid-template-columns:36px 1fr}}.score{{grid-column:2;text-align:left}}}}@media(max-width:520px){{.stats{{grid-template-columns:1fr}}}}
</style></head><body>
<header><div class="wrap"><div class="kicker">CFB VIP · Explosive Opportunity Finder</div><h1>{_esc(team)} vs {_esc(opponent)}</h1><p>{season} regular season through Week {through_week}. The primary outcome is a valid play gaining at least five yards more than expected for its down, distance, field zone, and run/pass family.</p></div></header>
<div class="wrap stats">
<div class="stat"><span>{_esc(team)} +5 rate</span><strong>{_pct(own['plus_five_rate'])}</strong><small>{own['plus_five']} of {own['attempts']} qualifying snaps</small></div>
<div class="stat"><span>{_esc(opponent)} +5 allowed</span><strong>{_pct(allowed['plus_five_rate'])}</strong><small>{allowed['plus_five']} of {allowed['attempts']} qualifying snaps</small></div>
<div class="stat"><span>GT average YAE</span><strong>{_yards(own['yards_above_expected'], signed=True)}</strong><small>yards above expected per qualifying snap</small></div>
<div class="stat"><span>GT traditional 10+</span><strong>{_pct(own['ten_plus_rate'])}</strong><small>retained as a comparison metric</small></div>
</div>
<main class="wrap"><div class="kicker" style="color:#827648">Ranked situations</div><h2>Top contextual opportunities</h2><section class="opportunities">{cards}</section>
<section class="note"><strong>Interpretation:</strong> the large percentage estimates the chance of beating contextual expected gain by at least five yards. Expected yards come from FBS seasons {_esc(training_seasons or 'not recorded')}. Actionable cells have at least 20 observations on both sides; lower-sample situations follow with a confidence label.</section>
<section class="quality"><h2>Data-quality exclusions</h2><table><thead><tr><th>Reason</th><th>GT offense</th><th>{_esc(opponent)} defense</th></tr></thead><tbody>{exclusion_rows or '<tr><td colspan="3">None</td></tr>'}</tbody></table></section>
<footer>Generated {generated}. Model league +5 prior: {_pct(model.plus_five_prior)}. Source: CollegeFootballData. Review data and compliance requirements before operational use.</footer></main></body></html>"""
    output.write_text(document, encoding="utf-8")
    return output, csv_path


def _card(index: int, row: dict[str, Any], opponent: str) -> str:
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(row["down"], "th")
    return (
        f'<article class="opportunity"><div class="rank">{index}</div><div>'
        f'<div class="eyebrow">{_esc(row["family"])} · {_esc(row["field_zone"])}</div>'
        f'<h3>{_esc(row["distance"])} on {row["down"]}{suffix} down · '
        f'{_yards(row["expected_yards"])} expected yards</h3>'
        f'<div class="meta">GT +5: {_pct(row["offense_plus_five_rate"])} '
        f'({row["offense_plus_five"]}/{row["offense_attempts"]}) · '
        f'{_esc(opponent)} +5 allowed: {_pct(row["defense_plus_five_rate"])} '
        f'({row["defense_plus_five"]}/{row["defense_attempts"]}) · '
        f'Matchup average: {_yards(row["matchup_avg_yae"], signed=True)} YAE · '
        f'Traditional 10+: {_pct(row["offense_10_plus_rate"])}</div></div>'
        f'<div class="score"><strong>{_pct(row["opportunity_rate"])}</strong>'
        f'<span>chance of expected +5</span>'
        f'<em class="confidence {row["confidence"].lower()}">'
        f'{_esc(row["confidence"])} confidence</em></div></article>'
    )

