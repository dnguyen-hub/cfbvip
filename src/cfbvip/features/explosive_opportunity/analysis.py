from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


PASS_MARKERS = ("pass", "sack", "interception")
RUSH_MARKERS = ("rush",)
ADMIN_MARKERS = (
    "kickoff",
    "punt",
    "field goal",
    "extra point",
    "timeout",
    "end period",
    "end of",
    "coin toss",
    "two-point",
)
MODEL_VERSION = 1


@dataclass(frozen=True)
class LabeledPlay:
    offense: str
    defense: str
    down: int
    distance: int
    yards_to_goal: int
    yards_gained: int
    family: str
    distance_bucket: str
    field_zone: str
    productive_10_plus: bool
    turnover: bool
    game_id: int | None
    drive_id: str
    play_number: int | None
    play_id: str
    play_text: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation for a future web API."""
        return asdict(self)


@dataclass(frozen=True)
class ScoredPlay:
    play: LabeledPlay
    expected_yards: float
    expectation_samples: int
    expectation_level: str
    yards_above_expected: float
    productive_plus_five: bool

    def to_dict(self) -> dict[str, Any]:
        value = self.play.to_dict()
        value.update(
            {
                "expected_yards": self.expected_yards,
                "expectation_samples": self.expectation_samples,
                "expectation_level": self.expectation_level,
                "yards_above_expected": self.yards_above_expected,
                "productive_plus_five": self.productive_plus_five,
            }
        )
        return value


@dataclass(frozen=True)
class Exclusion:
    reason: str


@dataclass(frozen=True)
class ExpectedGainCell:
    expected_yards: float
    samples: int


@dataclass
class ExpectedGainModel:
    """Hierarchical expected-yards lookup trained from historical FBS plays."""

    exact: dict[str, ExpectedGainCell]
    fallback: dict[str, ExpectedGainCell]
    family: dict[str, ExpectedGainCell]
    global_cell: ExpectedGainCell
    plus_five_prior: float
    training_seasons: tuple[int, ...] = ()
    min_samples: int = 50

    @staticmethod
    def _key(parts: tuple[Any, ...]) -> str:
        return "|".join(str(part) for part in parts)

    def expected_for(self, play: LabeledPlay) -> tuple[float, int, str]:
        exact_key = self._key(
            (
                play.down,
                play.distance_bucket,
                play.field_zone,
                play.family,
            )
        )
        cell = self.exact.get(exact_key)
        if cell and cell.samples >= self.min_samples:
            return cell.expected_yards, cell.samples, "exact"

        fallback_key = self._key((play.down, play.distance_bucket, play.family))
        cell = self.fallback.get(fallback_key)
        if cell and cell.samples >= self.min_samples:
            return cell.expected_yards, cell.samples, "down_distance"

        cell = self.family.get(play.family)
        if cell:
            return cell.expected_yards, cell.samples, "play_family"
        return self.global_cell.expected_yards, self.global_cell.samples, "global"

    def score(self, play: LabeledPlay, threshold: float = 5.0) -> ScoredPlay:
        expected, samples, level = self.expected_for(play)
        yards_above_expected = play.yards_gained - expected
        return ScoredPlay(
            play=play,
            expected_yards=expected,
            expectation_samples=samples,
            expectation_level=level,
            yards_above_expected=yards_above_expected,
            productive_plus_five=(
                yards_above_expected >= threshold and not play.turnover
            ),
        )

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": MODEL_VERSION,
            "training_seasons": list(self.training_seasons),
            "min_samples": self.min_samples,
            "plus_five_prior": self.plus_five_prior,
            "global": asdict(self.global_cell),
            "exact": {key: asdict(value) for key, value in self.exact.items()},
            "fallback": {
                key: asdict(value) for key, value in self.fallback.items()
            },
            "family": {key: asdict(value) for key, value in self.family.items()},
        }
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return destination

    @classmethod
    def load(cls, path: str | Path) -> ExpectedGainModel:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("version") != MODEL_VERSION:
            raise ValueError(
                f"Unsupported expected-gain model version: {payload.get('version')}"
            )

        def cells(values: dict[str, dict[str, Any]]) -> dict[str, ExpectedGainCell]:
            return {key: ExpectedGainCell(**value) for key, value in values.items()}

        return cls(
            exact=cells(payload["exact"]),
            fallback=cells(payload["fallback"]),
            family=cells(payload["family"]),
            global_cell=ExpectedGainCell(**payload["global"]),
            plus_five_prior=float(payload["plus_five_prior"]),
            training_seasons=tuple(int(year) for year in payload["training_seasons"]),
            min_samples=int(payload["min_samples"]),
        )


def _text(play: dict[str, Any]) -> str:
    return str(play.get("playText") or play.get("play_text") or "")


def classify_family(play: dict[str, Any]) -> str | None:
    play_type = str(play.get("playType") or play.get("play_type") or "").lower()
    play_text = _text(play).lower()

    if any(marker in play_type for marker in ADMIN_MARKERS):
        return None
    if any(marker in play_type for marker in PASS_MARKERS):
        return "Pass"
    if any(marker in play_type for marker in RUSH_MARKERS):
        return "Rush"
    if re.search(r"\bpass(?:es|ed)?\b|\bsacked\b|\bintercept", play_text):
        return "Pass"
    if re.search(r"\brun(?:s)?\b|\brush(?:es|ed)?\b", play_text):
        return "Rush"
    return None


def distance_bucket(distance: int) -> str:
    if distance <= 3:
        return "Short (1–3)"
    if distance <= 6:
        return "Medium (4–6)"
    if distance <= 10:
        return "Long (7–10)"
    return "Extra long (11+)"


def field_zone(yards_to_goal: int) -> str:
    if yards_to_goal >= 81:
        return "Backed up"
    if yards_to_goal >= 51:
        return "Own territory"
    if yards_to_goal >= 21:
        return "Plus territory"
    return "Red zone"


def label_play(play: dict[str, Any]) -> LabeledPlay | Exclusion:
    text = _text(play)
    text_lower = text.lower()
    play_type = str(play.get("playType") or play.get("play_type") or "")
    type_lower = play_type.lower()

    if "penalty" in text_lower or "no play" in text_lower or "penalty" in type_lower:
        return Exclusion("penalty_or_no_play")

    family = classify_family(play)
    if family is None:
        return Exclusion("not_rush_or_pass")

    try:
        down = int(play.get("down"))
        distance = int(play.get("distance"))
        yards_to_goal = int(play.get("yardsToGoal", play.get("yards_to_goal")))
        yards_gained = int(play.get("yardsGained", play.get("yards_gained")))
    except (TypeError, ValueError):
        return Exclusion("missing_situation")

    if down not in (1, 2, 3, 4) or distance < 0:
        return Exclusion("invalid_situation")
    if yards_to_goal < 5:
        return Exclusion("inside_opponent_5")

    turnover = "intercept" in text_lower or "interception" in type_lower
    if "fumble" in text_lower and ("lost" in text_lower or "turnover" in text_lower):
        turnover = True

    play_number = play.get("playNumber", play.get("play_number"))
    try:
        parsed_play_number = int(play_number) if play_number is not None else None
    except (TypeError, ValueError):
        parsed_play_number = None

    return LabeledPlay(
        offense=str(play.get("offense") or "Unknown"),
        defense=str(play.get("defense") or "Unknown"),
        down=down,
        distance=distance,
        yards_to_goal=yards_to_goal,
        yards_gained=yards_gained,
        family=family,
        distance_bucket=distance_bucket(distance),
        field_zone=field_zone(yards_to_goal),
        productive_10_plus=yards_gained >= 10 and not turnover,
        turnover=turnover,
        game_id=play.get("gameId", play.get("game_id")),
        drive_id=str(play.get("driveId", play.get("drive_id")) or ""),
        play_number=parsed_play_number,
        play_id=str(play.get("id") or ""),
        play_text=text,
    )


def label_plays(
    raw_plays: Iterable[dict[str, Any]],
) -> tuple[list[LabeledPlay], dict[str, int]]:
    labeled: list[LabeledPlay] = []
    exclusions: dict[str, int] = defaultdict(int)
    for raw in raw_plays:
        result = label_play(raw)
        if isinstance(result, Exclusion):
            exclusions[result.reason] += 1
        else:
            labeled.append(result)
    return labeled, dict(sorted(exclusions.items()))


def _fit_cells(
    plays: Iterable[LabeledPlay],
    key_function: Any,
) -> dict[str, ExpectedGainCell]:
    totals: dict[str, list[float]] = defaultdict(list)
    for play in plays:
        totals[ExpectedGainModel._key(key_function(play))].append(play.yards_gained)
    return {
        key: ExpectedGainCell(expected_yards=sum(values) / len(values), samples=len(values))
        for key, values in totals.items()
    }


def fit_expected_gain_model(
    plays: list[LabeledPlay],
    *,
    training_seasons: Iterable[int] = (),
    min_samples: int = 50,
) -> ExpectedGainModel:
    if not plays:
        raise ValueError("Cannot fit expected gain model without qualifying plays")

    exact = _fit_cells(
        plays,
        lambda play: (
            play.down,
            play.distance_bucket,
            play.field_zone,
            play.family,
        ),
    )
    fallback = _fit_cells(
        plays,
        lambda play: (play.down, play.distance_bucket, play.family),
    )
    family = _fit_cells(plays, lambda play: (play.family,))
    # Family lookup is intentionally keyed by its human-readable value.
    family = {key.split("|", 1)[0]: value for key, value in family.items()}
    global_cell = ExpectedGainCell(
        expected_yards=sum(play.yards_gained for play in plays) / len(plays),
        samples=len(plays),
    )
    model = ExpectedGainModel(
        exact=exact,
        fallback=fallback,
        family=family,
        global_cell=global_cell,
        plus_five_prior=0.20,
        training_seasons=tuple(sorted(set(int(year) for year in training_seasons))),
        min_samples=min_samples,
    )
    scored = [model.score(play) for play in plays]
    model.plus_five_prior = sum(play.productive_plus_five for play in scored) / len(scored)
    return model


def score_plays(
    plays: Iterable[LabeledPlay],
    model: ExpectedGainModel,
    *,
    threshold: float = 5.0,
) -> list[ScoredPlay]:
    return [model.score(play, threshold=threshold) for play in plays]


def smoothed_rate(
    successes: int,
    attempts: int,
    prior: float,
    strength: int = 20,
) -> float:
    return (successes + prior * strength) / (attempts + strength)


def confidence(attempts_a: int, attempts_b: int) -> str:
    minimum = min(attempts_a, attempts_b)
    if minimum >= 50:
        return "High"
    if minimum >= 20:
        return "Medium"
    return "Low"


def wilson_interval(successes: int, attempts: int, z: float = 1.96) -> tuple[float, float]:
    if attempts == 0:
        return (0.0, 1.0)
    probability = successes / attempts
    denominator = 1 + z * z / attempts
    center = (probability + z * z / (2 * attempts)) / denominator
    margin = (
        z
        * math.sqrt(
            (probability * (1 - probability) + z * z / (4 * attempts)) / attempts
        )
        / denominator
    )
    return (max(0.0, center - margin), min(1.0, center + margin))


def summarize_matchup(
    offense_plays: list[ScoredPlay],
    defense_plays: list[ScoredPlay],
    *,
    plus_five_prior: float,
) -> list[dict[str, Any]]:
    def group(plays: list[ScoredPlay]) -> dict[tuple[Any, ...], list[ScoredPlay]]:
        grouped: dict[tuple[Any, ...], list[ScoredPlay]] = defaultdict(list)
        for scored in plays:
            play = scored.play
            key = (play.down, play.distance_bucket, play.field_zone, play.family)
            grouped[key].append(scored)
        return grouped

    offense_groups = group(offense_plays)
    defense_groups = group(defense_plays)
    rows: list[dict[str, Any]] = []
    for key in sorted(set(offense_groups) | set(defense_groups)):
        own = offense_groups.get(key, [])
        allowed = defense_groups.get(key, [])
        own_plus_five = sum(play.productive_plus_five for play in own)
        allowed_plus_five = sum(play.productive_plus_five for play in allowed)
        own_rate = smoothed_rate(own_plus_five, len(own), plus_five_prior)
        allowed_rate = smoothed_rate(allowed_plus_five, len(allowed), plus_five_prior)
        low_a, high_a = wilson_interval(own_plus_five, len(own))
        low_b, high_b = wilson_interval(allowed_plus_five, len(allowed))
        combined = own + allowed
        rows.append(
            {
                "down": key[0],
                "distance": key[1],
                "field_zone": key[2],
                "family": key[3],
                "expected_yards": (
                    sum(play.expected_yards for play in combined) / len(combined)
                    if combined
                    else 0.0
                ),
                "offense_plus_five": own_plus_five,
                "offense_attempts": len(own),
                "offense_plus_five_rate": own_plus_five / len(own) if own else 0.0,
                "offense_avg_yae": (
                    sum(play.yards_above_expected for play in own) / len(own)
                    if own
                    else 0.0
                ),
                "defense_plus_five": allowed_plus_five,
                "defense_attempts": len(allowed),
                "defense_plus_five_rate": (
                    allowed_plus_five / len(allowed) if allowed else 0.0
                ),
                "defense_avg_yae": (
                    sum(play.yards_above_expected for play in allowed) / len(allowed)
                    if allowed
                    else 0.0
                ),
                "offense_10_plus_rate": (
                    sum(play.play.productive_10_plus for play in own) / len(own)
                    if own
                    else 0.0
                ),
                "defense_10_plus_rate": (
                    sum(play.play.productive_10_plus for play in allowed) / len(allowed)
                    if allowed
                    else 0.0
                ),
                "opportunity_rate": (own_rate + allowed_rate) / 2,
                "matchup_avg_yae": (
                    (
                        sum(play.yards_above_expected for play in own) / len(own)
                        + sum(play.yards_above_expected for play in allowed) / len(allowed)
                    )
                    / 2
                    if own and allowed
                    else 0.0
                ),
                "confidence": confidence(len(own), len(allowed)),
                "uncertainty_width": ((high_a - low_a) + (high_b - low_b)) / 2,
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["opportunity_rate"],
            row["matchup_avg_yae"],
            min(row["offense_attempts"], row["defense_attempts"]),
        ),
        reverse=True,
    )


def overall_summary(plays: list[ScoredPlay]) -> dict[str, Any]:
    attempts = len(plays)
    plus_five = sum(play.productive_plus_five for play in plays)
    ten_plus = sum(play.play.productive_10_plus for play in plays)
    return {
        "plus_five": plus_five,
        "plus_five_rate": plus_five / attempts if attempts else 0.0,
        "ten_plus": ten_plus,
        "ten_plus_rate": ten_plus / attempts if attempts else 0.0,
        "attempts": attempts,
        "expected_yards": (
            sum(play.expected_yards for play in plays) / attempts if attempts else 0.0
        ),
        "actual_yards": (
            sum(play.play.yards_gained for play in plays) / attempts if attempts else 0.0
        ),
        "yards_above_expected": (
            sum(play.yards_above_expected for play in plays) / attempts
            if attempts
            else 0.0
        ),
    }

