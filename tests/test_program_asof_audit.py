import unittest
from datetime import date, datetime, timezone

from scripts.audit_program_asof import (
    PROPOSED_FEATURES,
    source_set_fingerprint,
    summarize_capture_vs_close,
    summarize_feature_completeness,
    summarize_timestamp_evidence,
)
from tests.helpers import make_race


class ProgramAsOfAuditTests(unittest.TestCase):
    def test_feature_completeness_counts_missing_and_non_numeric_values(self):
        race = make_race(date(2026, 1, 1))
        racers = {
            entry: {
                **values,
                **{field: 1.0 for field in PROPOSED_FEATURES},
                "entry_number": entry,
            }
            for entry, values in race.program.racers.items()
        }
        racers[1]["weight"] = None
        racers[2]["weight"] = "52.0"
        complete = race.__class__(
            identity=race.identity,
            program=race.program.__class__(
                race_fields=race.program.race_fields,
                racers=racers,
            ),
            preview=race.preview,
            odds=race.odds,
            outcome=race.outcome,
            issues=race.issues,
            source_sha256=race.source_sha256,
        )

        result = summarize_feature_completeness([complete])

        self.assertEqual(result["races_with_six_entries"], 1)
        self.assertEqual(result["fields"]["weight"]["missing_or_null"], 1)
        self.assertEqual(result["fields"]["weight"]["non_numeric"], 1)
        self.assertEqual(result["fields"]["local_win_rate"]["missing_or_null"], 0)

    def test_provider_timestamp_does_not_treat_closed_at_as_observation(self):
        result = summarize_timestamp_evidence(
            [
                {
                    "closed_at": "2026-01-01 12:00:00",
                    "observed_at": "2026-01-01T10:00:00+09:00",
                    "racers": {
                        "1": {"entry_number": 1, "updated_at": "timestamp"}
                    },
                },
                {"closed_at": "2026-01-01 13:00:00", "racers": {}},
            ]
        )

        self.assertEqual(result["observed_at"], 1)
        self.assertEqual(result["racers.updated_at"], 1)
        self.assertNotIn("closed_at", result)

    def test_capture_comparison_treats_naive_close_as_japan_time(self):
        result = summarize_capture_vs_close(
            [
                (
                    {"closed_at": "2026-01-01 12:00:00"},
                    datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc),
                ),
                (
                    {"closed_at": "invalid"},
                    datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc),
                ),
            ],
        )

        self.assertEqual(result["comparable_races"], 1)
        self.assertEqual(result["captured_after_close"], 1)
        self.assertEqual(result["unparseable_close"], 1)

    def test_source_set_fingerprint_is_order_independent_but_date_sensitive(self):
        first = source_set_fingerprint(
            [
                {"date": "2026-01-02", "sha256": "b"},
                {"date": "2026-01-01", "sha256": "a"},
            ]
        )
        second = source_set_fingerprint(
            [
                {"date": "2026-01-01", "sha256": "a"},
                {"date": "2026-01-02", "sha256": "b"},
            ]
        )
        changed = source_set_fingerprint(
            [
                {"date": "2026-01-01", "sha256": "a"},
                {"date": "2026-01-03", "sha256": "b"},
            ]
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)


if __name__ == "__main__":
    unittest.main()
