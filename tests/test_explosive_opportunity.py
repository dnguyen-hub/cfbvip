import tempfile
import unittest
from pathlib import Path

from cfbvip.features.explosive_opportunity.analysis import (
    Exclusion,
    ExpectedGainModel,
    LabeledPlay,
    fit_expected_gain_model,
    label_play,
    label_plays,
    score_plays,
    summarize_matchup,
)
from cfbvip.features.explosive_opportunity.cfbd import CfbdClient


def play(**overrides):
    value = {
        "id": "1",
        "driveId": "drive-1",
        "gameId": 101,
        "playNumber": 1,
        "offense": "Georgia Tech",
        "defense": "Clemson",
        "down": 1,
        "distance": 10,
        "yardsToGoal": 65,
        "yardsGained": 10,
        "playType": "Rush",
        "playText": "Runner rushed for 10 yards",
    }
    value.update(overrides)
    return value


def labeled_many(count, **overrides):
    values = [play(id=str(index), playNumber=index, **overrides) for index in range(count)]
    labeled, exclusions = label_plays(values)
    assert not exclusions
    return labeled


class LabelTests(unittest.TestCase):
    def test_exactly_ten_still_counts_as_secondary_metric(self):
        result = label_play(play(yardsGained=10))
        self.assertIsInstance(result, LabeledPlay)
        self.assertTrue(result.productive_10_plus)

    def test_interception_is_not_productive(self):
        result = label_play(
            play(playType="Interception Return", playText="Pass intercepted", yardsGained=15)
        )
        self.assertIsInstance(result, LabeledPlay)
        self.assertTrue(result.turnover)
        self.assertFalse(result.productive_10_plus)

    def test_penalty_is_excluded(self):
        result = label_play(play(playText="PENALTY Georgia Tech holding"))
        self.assertEqual(result, Exclusion("penalty_or_no_play"))

    def test_inside_five_is_excluded_but_nine_is_allowed(self):
        self.assertEqual(
            label_play(play(yardsToGoal=4)), Exclusion("inside_opponent_5")
        )
        self.assertIsInstance(label_play(play(yardsToGoal=9)), LabeledPlay)

    def test_administrative_play_is_excluded(self):
        result = label_play(play(playType="Punt", playText="Punt 42 yards"))
        self.assertEqual(result, Exclusion("not_rush_or_pass"))


class ExpectedGainTests(unittest.TestCase):
    def test_plus_five_is_measured_against_expected_gain(self):
        baseline = labeled_many(60, yardsGained=5)
        model = fit_expected_gain_model(baseline, min_samples=20)
        target = label_play(play(yardsGained=11))
        self.assertIsInstance(target, LabeledPlay)
        scored = model.score(target)
        self.assertEqual(scored.expected_yards, 5)
        self.assertEqual(scored.yards_above_expected, 6)
        self.assertTrue(scored.productive_plus_five)

    def test_sparse_exact_context_backs_off_to_down_distance(self):
        baseline = labeled_many(20, yardsToGoal=85, yardsGained=4)
        baseline += labeled_many(20, yardsToGoal=65, yardsGained=6)
        model = fit_expected_gain_model(baseline, min_samples=30)
        target = baseline[0]
        expected, samples, level = model.expected_for(target)
        self.assertEqual(level, "down_distance")
        self.assertEqual(samples, 40)
        self.assertEqual(expected, 5)

    def test_model_round_trip(self):
        baseline = labeled_many(60, yardsGained=5)
        model = fit_expected_gain_model(
            baseline,
            training_seasons=(2023, 2024),
            min_samples=20,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "expected-gain.json"
            model.save(path)
            loaded = ExpectedGainModel.load(path)
        self.assertEqual(loaded.training_seasons, (2023, 2024))
        self.assertEqual(loaded.global_cell, model.global_cell)
        self.assertEqual(loaded.plus_five_prior, model.plus_five_prior)


class SummaryTests(unittest.TestCase):
    def test_summary_combines_offense_and_defense_plus_five_rates(self):
        baseline = labeled_many(60, yardsGained=5)
        model = fit_expected_gain_model(baseline, min_samples=20)
        offense = labeled_many(10, yardsGained=11)
        defense = labeled_many(
            10,
            offense="Opponent",
            defense="Clemson",
            yardsGained=4,
        )
        rows = summarize_matchup(
            score_plays(offense, model),
            score_plays(defense, model),
            plus_five_prior=model.plus_five_prior,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["offense_plus_five"], 10)
        self.assertEqual(rows[0]["defense_plus_five"], 0)
        self.assertEqual(rows[0]["confidence"], "Low")


class CfbdClientTests(unittest.TestCase):
    def test_fbs_classification_is_sent_in_one_week_request(self):
        client = CfbdClient(api_key="test")
        captured = {}

        def fake_get(path, *, params, refresh):
            captured.update(params)
            return []

        client._get = fake_get  # type: ignore[method-assign]
        client.get_plays(year=2025, week=1)
        self.assertEqual(captured["classification"], "fbs")
        self.assertNotIn("offense", captured)
        self.assertNotIn("defense", captured)


if __name__ == "__main__":
    unittest.main()

