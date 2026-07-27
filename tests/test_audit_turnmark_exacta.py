import hashlib
import json
import tempfile
import unittest
from datetime import date
from itertools import permutations
from pathlib import Path

from scripts.audit_turnmark_exacta import (
    DEFAULT_SOURCE_COMMIT,
    format_text,
    run_audit,
)


def complete_exacta_odds(default=10.0):
    return {
        str(first): {
            str(second): default
            for second in range(1, 7)
            if second != first
        }
        for first in range(1, 7)
    }


def racers(place_sources=None):
    place_sources = place_sources or {
        entry: str(entry) for entry in range(1, 7)
    }
    values = {}
    for entry in range(1, 7):
        source = place_sources[entry]
        place = int(source) if source.isdigit() else None
        values[str(entry)] = {
            "entry_number": entry,
            "number": 1000 + entry,
            "name": f"選手{entry}",
            "place_number_source": source,
            "place_number": place,
        }
    return values


def race(
    *,
    race_number=1,
    odds=None,
    result_racers=None,
    payouts=None,
):
    return {
        "date": "2026-01-01",
        "stadium_number": 21,
        "race_number": race_number,
        "title": "テスト開催",
        "day_number": 1,
        "day_number_source": "初日",
        "racers": {
            str(entry): {
                "entry_number": entry,
                "number": 1000 + entry,
                "name": f"選手{entry}",
            }
            for entry in range(1, 7)
        },
        "odds": {
            "exacta": odds if odds is not None else complete_exacta_odds()
        },
        "result": {
            "racers": result_racers if result_racers is not None else racers(),
            "payouts": {
                "exacta": (
                    payouts
                    if payouts is not None
                    else [{"combination": "1-2", "amount": 1000}]
                )
            },
        },
    }


def payload(races):
    return {
        "programs": {
            "stadiums": {
                "21": {
                    "stadium_number": 21,
                    "races": {
                        str(item["race_number"]): item for item in races
                    },
                }
            }
        }
    }


def write_day(root, races):
    day = date(2026, 1, 1)
    raw_path = (
        root
        / "raw"
        / "turnmark"
        / "2026"
        / "20260101.json"
    )
    raw_path.parent.mkdir(parents=True)
    raw = json.dumps(
        payload(races),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    raw_path.write_bytes(raw)
    metadata = {
        "provider": "turnmark",
        "source_url": (
            "https://turnmark.github.io/api/v1/2026/20260101.json"
        ),
        "fetched_at": "2026-07-24T00:00:00+00:00",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    raw_path.with_suffix(".metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    return day


class ExactaAuditTests(unittest.TestCase):
    def test_clean_race_has_30_keys_and_both_eligibility_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = write_day(root, [race()])

            result = run_audit(root, start=day, end=day)

        self.assertEqual(result["scope"]["races"], 1)
        self.assertEqual(
            result["scope"]["source_repository_commit"],
            DEFAULT_SOURCE_COMMIT,
        )
        self.assertEqual(
            result["canonical_keys"]["canonical_30_key_races"], 1
        )
        self.assertEqual(result["odds"]["positive"], 30)
        self.assertEqual(
            result["eligibility"]["probability_training_eligible"], 1
        )
        self.assertEqual(
            result["eligibility"]["economic_settlement_eligible"], 1
        )
        self.assertTrue(result["meeting_blocks"]["reconstructable"])
        self.assertEqual(result["meeting_blocks"]["inferred_blocks"], 1)
        self.assertEqual(result["gate_a"]["recommendation"], "CONDITIONAL_GO")

    def test_absent_boat_and_other_zero_odds_are_separated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            odds = complete_exacta_odds()
            absent_keys = {
                (first, second)
                for first, second in permutations(range(1, 7), 2)
                if 6 in (first, second)
            }
            for first, second in absent_keys:
                odds[str(first)][str(second)] = 0
            odds["5"]["4"] = 0
            result_racers = racers(
                {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "欠"}
            )
            day = write_day(
                root,
                [race(odds=odds, result_racers=result_racers)],
            )

            result = run_audit(root, start=day, end=day)

        self.assertEqual(result["odds"]["zero"], 11)
        self.assertEqual(
            result["odds"]["zero_explained_by_absent_boats"], 10
        )
        self.assertEqual(result["odds"]["unattributed_zero_values"], 1)
        self.assertEqual(
            result["eligibility"]["economic_predecision_eligible"], 0
        )

    def test_fl_mismatch_is_auditable_and_refund_combinations_are_derived(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_racers = racers(
                {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "F"}
            )
            day = write_day(
                root,
                [
                    race(
                        result_racers=result_racers,
                        payouts=[
                            {"combination": "1-2", "amount": 500}
                        ],
                    )
                ],
            )

            result = run_audit(root, start=day, end=day)

        comparison = result["winning_odds_vs_payout"]
        refunds = result["exceptions_and_refunds"]
        self.assertEqual(comparison["mismatches"], 1)
        self.assertEqual(comparison["mismatches_with_fl"], 1)
        self.assertEqual(comparison["mismatches_without_fl"], 0)
        self.assertEqual(refunds["fl_races"], 1)
        self.assertEqual(refunds["derived_refund_combinations"], 10)
        self.assertEqual(refunds["direct_refund_fields_seen"], [])
        self.assertEqual(
            result["eligibility"]["economic_settlement_eligible"], 1
        )
        self.assertEqual(
            result["eligibility"]["probability_training_eligible"], 0
        )

    def test_lower_place_tie_is_exacta_clean_when_top_two_are_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_racers = racers(
                {1: "1", 2: "2", 3: "3", 4: "4", 5: "4", 6: "6"}
            )
            day = write_day(
                root,
                [race(result_racers=result_racers)],
            )

            result = run_audit(root, start=day, end=day)

        eligibility = result["eligibility"]
        self.assertEqual(eligibility["probability_training_eligible"], 1)
        self.assertEqual(eligibility["strict_full_order_clean_reference"], 0)
        self.assertEqual(
            eligibility["exacta_clean_not_strict_full_order"], 1
        )
        self.assertEqual(
            eligibility["exacta_clean_not_strict_examples"][0]["reason"],
            "lower_place_tie_does_not_affect_unique_top_two",
        )

    def test_missing_extra_null_and_multiple_payout_are_blockers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            odds = complete_exacta_odds()
            del odds["1"]["2"]
            odds["1"]["1"] = 9.0
            odds["1"]["3"] = None
            odds["2"]["3"] = "12.0"
            day = write_day(
                root,
                [
                    race(
                        odds=odds,
                        payouts=[
                            {"combination": "1-2", "amount": 1000},
                            {"combination": "1-3", "amount": 2000},
                        ],
                    )
                ],
            )

            result = run_audit(root, start=day, end=day)

        self.assertEqual(result["canonical_keys"]["missing_keys"], 1)
        self.assertEqual(result["canonical_keys"]["extra_keys"], 1)
        self.assertEqual(result["odds"]["null"], 1)
        self.assertEqual(result["odds"]["invalid_type"], 1)
        self.assertEqual(
            result["payouts_and_results"]["multiple_payout_races"], 1
        )
        self.assertEqual(result["gate_a"]["recommendation"], "NO_GO")
        self.assertGreater(result["gate_a"]["integrity_blocker_count"], 0)

    def test_non_establishment_and_top_two_dead_heat_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_racers = racers(
                {1: "1", 2: "1", 3: "2", 4: "3", 5: "4", 6: "5"}
            )
            day = write_day(
                root,
                [race(result_racers=result_racers, payouts=[])],
            )

            result = run_audit(root, start=day, end=day)

        payouts = result["payouts_and_results"]
        self.assertEqual(payouts["no_payout_races"], 1)
        self.assertEqual(payouts["top_two_dead_heat_races"], 1)
        self.assertEqual(result["gate_a"]["recommendation"], "NO_GO")
        self.assertEqual(
            result["eligibility"]["economic_settlement_eligible"], 0
        )

    def test_sha_mismatch_is_reported_and_blocks_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = write_day(root, [race()])
            raw_path = (
                root
                / "raw"
                / "turnmark"
                / "2026"
                / "20260101.json"
            )
            raw_path.write_bytes(raw_path.read_bytes() + b" ")

            result = run_audit(root, start=day, end=day)

        self.assertEqual(
            result["cache_integrity"]["sha_mismatch_days"],
            ["2026-01-01"],
        )
        self.assertEqual(result["scope"]["verified_cached_days"], 0)
        self.assertEqual(result["gate_a"]["recommendation"], "NO_GO")

    def test_text_output_records_fingerprint_and_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = write_day(root, [race()])
            result = run_audit(root, start=day, end=day)

        output = format_text(result)

        self.assertIn(result["fingerprints"]["raw_manifest_sha256"], output)
        self.assertIn("Gate A: CONDITIONAL_GO", output)
        self.assertIn("probability training 1", output)


if __name__ == "__main__":
    unittest.main()
