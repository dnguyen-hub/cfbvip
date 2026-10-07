from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .analysis import (
    ExpectedGainModel,
    fit_expected_gain_model,
    label_plays,
    score_plays,
)
from .cfbd import CfbdClient, CfbdError
from .report import build_report


def fetch_fbs_season(
    client: CfbdClient,
    *,
    season: int,
    through_week: int,
    refresh: bool = False,
    refresh_week: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch each FBS week once; team and opponent filtering happens locally."""
    plays: list[dict[str, Any]] = []
    for week in range(0, through_week + 1):
        print(f"Loading {season} Week {week}...", file=sys.stderr)
        plays.extend(
            client.get_plays(
                year=season,
                week=week,
                classification="fbs",
                refresh=refresh or week == refresh_week,
            )
        )
    return plays


def command_train(args: argparse.Namespace) -> int:
    client = CfbdClient(cache_dir=args.cache_dir)
    raw_plays: list[dict[str, Any]] = []
    for season in args.seasons:
        raw_plays.extend(
            fetch_fbs_season(
                client,
                season=season,
                through_week=args.through_week,
                refresh=args.refresh,
                refresh_week=args.refresh_week,
            )
        )

    labeled, exclusions = label_plays(raw_plays)
    model = fit_expected_gain_model(
        labeled,
        training_seasons=args.seasons,
        min_samples=args.min_samples,
    )
    model_path = model.save(args.model)
    print(f"Model: {model_path.resolve()}")
    print(f"Training plays: {len(labeled):,}")
    print(f"League +5 rate: {model.plus_five_prior:.1%}")
    print(f"Excluded plays: {sum(exclusions.values()):,}")
    return 0


def command_build(args: argparse.Namespace) -> int:
    model = ExpectedGainModel.load(args.model)
    client = CfbdClient(cache_dir=args.cache_dir)
    season_raw = fetch_fbs_season(
        client,
        season=args.season,
        through_week=args.through_week,
        refresh=args.refresh,
        refresh_week=args.refresh_week,
    )
    team_name = args.team.casefold()
    opponent_name = args.opponent.casefold()
    offense_raw = [
        play
        for play in season_raw
        if str(play.get("offense") or "").casefold() == team_name
    ]
    defense_raw = [
        play
        for play in season_raw
        if str(play.get("defense") or "").casefold() == opponent_name
    ]
    if not offense_raw:
        raise CfbdError(
            f"No offensive plays found for {args.team!r}. Check the CFBD team name and selected weeks."
        )
    if not defense_raw:
        raise CfbdError(
            f"No defensive plays found for {args.opponent!r}. Check the CFBD team name and selected weeks."
        )
    return write_report(args, model, offense_raw, defense_raw)


def command_demo(args: argparse.Namespace) -> int:
    baseline_raw, offense_raw, defense_raw = demo_plays()
    baseline, _ = label_plays(baseline_raw)
    model = fit_expected_gain_model(
        baseline,
        training_seasons=(2023, 2024),
        min_samples=10,
    )
    args.team = "Georgia Tech"
    args.opponent = "Example Opponent"
    args.season = 2025
    args.through_week = 6
    return write_report(args, model, offense_raw, defense_raw)


def write_report(
    args: argparse.Namespace,
    model: ExpectedGainModel,
    offense_raw: list[dict[str, Any]],
    defense_raw: list[dict[str, Any]],
) -> int:
    offense_labeled, offense_exclusions = label_plays(offense_raw)
    defense_labeled, defense_exclusions = label_plays(defense_raw)
    offense_scored = score_plays(offense_labeled, model)
    defense_scored = score_plays(defense_labeled, model)
    html_path, csv_path = build_report(
        team=args.team,
        opponent=args.opponent,
        season=args.season,
        through_week=args.through_week,
        model=model,
        offense_plays=offense_scored,
        defense_plays=defense_scored,
        offense_exclusions=offense_exclusions,
        defense_exclusions=defense_exclusions,
        output_path=args.output,
    )
    print(f"Report: {html_path.resolve()}")
    print(f"Data:   {csv_path.resolve()}")
    print(
        f"Qualifying snaps: {len(offense_scored):,} offense / "
        f"{len(defense_scored):,} defense"
    )
    return 0


def demo_plays() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    baseline: list[dict[str, Any]] = []
    offense: list[dict[str, Any]] = []
    defense: list[dict[str, Any]] = []
    configurations = [
        (1, 10, 64, "Rush", 4, 9, 7),
        (1, 10, 64, "Pass Reception", 6, 13, 10),
        (2, 5, 42, "Rush", 5, 11, 8),
        (2, 8, 70, "Pass Reception", 6, 15, 10),
        (3, 6, 35, "Pass Reception", 5, 12, 9),
        (3, 2, 55, "Rush", 3, 9, 7),
    ]
    counter = 0
    for down, distance, ytg, play_type, expected, offense_high, defense_high in configurations:
        for index in range(60):
            counter += 1
            baseline.append(
                _demo_play(
                    counter,
                    "Baseline Offense",
                    "Baseline Defense",
                    down,
                    distance,
                    ytg,
                    play_type,
                    expected + ((index % 5) - 2),
                )
            )
        for index in range(30):
            counter += 1
            offense.append(
                _demo_play(
                    counter,
                    "Georgia Tech",
                    "Defense",
                    down,
                    distance,
                    ytg,
                    play_type,
                    offense_high if index < 12 else expected - 1,
                )
            )
            defense.append(
                _demo_play(
                    counter + 1000,
                    "Opponent Offense",
                    "Example Opponent",
                    down,
                    distance,
                    ytg,
                    play_type,
                    defense_high if index < 9 else expected - 1,
                )
            )
    return baseline, offense, defense


def _demo_play(
    play_id: int,
    offense: str,
    defense: str,
    down: int,
    distance: int,
    yards_to_goal: int,
    play_type: str,
    yards_gained: int,
) -> dict[str, Any]:
    return {
        "id": str(play_id),
        "driveId": str(play_id // 10),
        "gameId": 1,
        "playNumber": play_id,
        "offense": offense,
        "defense": defense,
        "down": down,
        "distance": distance,
        "yardsToGoal": yards_to_goal,
        "yardsGained": yards_gained,
        "playType": play_type,
        "playText": "Runner gained yards" if "Rush" in play_type else "Pass complete",
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Train and run the CFB VIP yards-above-expected opportunity finder"
    )
    subparsers = root.add_subparsers(dest="command", required=True)

    train = subparsers.add_parser(
        "train",
        help="Train an expected-gain model from league-wide historical FBS plays",
    )
    train.add_argument("--seasons", type=int, nargs="+", required=True)
    train.add_argument("--through-week", type=int, default=16)
    train.add_argument("--model", type=Path, required=True)
    train.add_argument("--min-samples", type=int, default=50)
    train.add_argument("--cache-dir", type=Path, default=Path("var/cache"))
    train.add_argument("--refresh", action="store_true")
    train.add_argument("--refresh-week", type=int)
    train.set_defaults(func=command_train)

    build = subparsers.add_parser(
        "build",
        help="Build a matchup report with a previously trained expected-gain model",
    )
    build.add_argument("--season", type=int, required=True)
    build.add_argument("--through-week", type=int, default=16)
    build.add_argument("--model", type=Path, required=True)
    build.add_argument("--team", default="Georgia Tech")
    build.add_argument("--opponent", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--cache-dir", type=Path, default=Path("var/cache"))
    build.add_argument("--refresh", action="store_true")
    build.add_argument("--refresh-week", type=int)
    build.set_defaults(func=command_build)

    demo = subparsers.add_parser(
        "demo", help="Build a report from included offline demonstration data"
    )
    demo.add_argument("--output", type=Path, required=True)
    demo.set_defaults(func=command_demo)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.func(args)
    except (CfbdError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
