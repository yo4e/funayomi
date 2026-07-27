import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from funayomi.cache import LocalCache
from funayomi.errors import (
    DataContractError,
    DataUnavailableError,
)
from funayomi.normalize import SCHEMA_VERSION
from funayomi.repository import RaceRepository, date_range
from funayomi.turnmark import TurnmarkClient

from tests.helpers import raw_payload, raw_race


class LocalCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = LocalCache(self.root)
        self.day = date(2026, 5, 1)

    def test_raw_cache_records_sha256_and_metadata(self):
        payload = b'{"programs":{}}'
        digest = self.cache.write_raw(
            self.day,
            payload,
            {"provider": "turnmark", "source_url": "https://example.test/data"},
        )

        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())
        self.assertEqual(self.cache.read_raw(self.day), payload)
        metadata = self.cache.read_raw_metadata(self.day)
        self.assertEqual(metadata["provider"], "turnmark")
        self.assertEqual(metadata["source_url"], "https://example.test/data")
        self.assertEqual(metadata["sha256"], digest)
        self.assertNotIn("races", metadata)

    def test_raw_cache_refuses_missing_or_mismatched_sha_metadata(self):
        payload = b'{"programs":{}}'
        raw_path = self.cache.raw_path(self.day)
        raw_path.parent.mkdir(parents=True)
        raw_path.write_bytes(payload)

        with self.assertRaises(DataContractError):
            self.cache.read_raw(self.day)

        self.cache.raw_metadata_path(self.day).write_text(
            json.dumps({"sha256": "0" * 64}),
            encoding="utf-8",
        )
        with self.assertRaises(DataContractError):
            self.cache.read_raw(self.day)

    def test_existing_raw_cache_is_not_overwritten_without_replace(self):
        first = b'{"version":1}'
        second = b'{"version":2}'
        first_digest = self.cache.write_raw(
            self.day, first, {"marker": "first"}
        )

        returned = self.cache.write_raw(
            self.day, second, {"marker": "second"}, replace=False
        )

        self.assertEqual(returned, first_digest)
        self.assertEqual(self.cache.read_raw(self.day), first)
        self.assertEqual(self.cache.read_raw_metadata(self.day)["marker"], "first")

    def test_json_cache_is_canonical_and_round_trips(self):
        value = {"z": 1, "日本語": "値", "a": {"b": 2}}
        self.cache.write_normalized(self.day, value)

        serialized = self.cache.normalized_path(self.day).read_text("utf-8")
        self.assertEqual(serialized, '{"a":{"b":2},"z":1,"日本語":"値"}\n')
        self.assertEqual(self.cache.read_normalized(self.day), value)

    def test_non_object_cache_documents_are_rejected(self):
        metadata_path = self.cache.raw_metadata_path(self.day)
        metadata_path.parent.mkdir(parents=True)
        metadata_path.write_text("[]", encoding="utf-8")
        normalized_path = self.cache.normalized_path(self.day)
        normalized_path.parent.mkdir(parents=True)
        normalized_path.write_text("[]", encoding="utf-8")

        with self.assertRaises(DataContractError):
            self.cache.read_raw_metadata(self.day)
        with self.assertRaises(DataContractError):
            self.cache.read_normalized(self.day)


class TurnmarkClientTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = LocalCache(Path(self.temporary.name))
        self.day = date(2026, 5, 2)

    def test_fetch_uses_cache_without_refetch_and_refreshes_only_explicitly(self):
        payloads = [b'{"version":1}', b'{"version":2}']
        opener = Mock(side_effect=payloads)
        client = TurnmarkClient(
            self.cache,
            base_url="https://example.test/api/v1/",
            opener=opener,
        )

        first = client.fetch(self.day)
        cached = client.fetch(self.day)
        refreshed = client.fetch(self.day, refresh=True)

        self.assertEqual(first, payloads[0])
        self.assertEqual(cached, payloads[0])
        self.assertEqual(refreshed, payloads[1])
        self.assertEqual(opener.call_count, 2)
        request, timeout = opener.call_args_list[0].args
        self.assertEqual(
            request.full_url,
            "https://example.test/api/v1/2026/20260502.json",
        )
        self.assertEqual(timeout, 30.0)
        metadata = self.cache.read_raw_metadata(self.day)
        self.assertEqual(
            metadata["sha256"], hashlib.sha256(payloads[1]).hexdigest()
        )
        self.assertEqual(metadata["source_url"], request.full_url)
        self.assertIn("fetched_at", metadata)

    def test_offline_missing_cache_never_calls_opener(self):
        opener = Mock(side_effect=AssertionError("network must not be used"))
        client = TurnmarkClient(self.cache, opener=opener)

        with self.assertRaises(DataUnavailableError):
            client.fetch(self.day, offline=True)

        opener.assert_not_called()

    def test_offline_reads_existing_cache(self):
        payload = b'{"cached":true}'
        self.cache.write_raw(self.day, payload, {})
        opener = Mock(side_effect=AssertionError("network must not be used"))
        client = TurnmarkClient(self.cache, opener=opener)

        self.assertEqual(client.fetch(self.day, offline=True), payload)
        opener.assert_not_called()

    def test_invalid_json_is_rejected_without_poisoning_cache(self):
        client = TurnmarkClient(self.cache, opener=Mock(return_value=b"not-json"))

        with self.assertRaises(DataContractError):
            client.fetch(self.day)

        self.assertFalse(self.cache.has_raw(self.day))
        self.assertFalse(self.cache.raw_metadata_path(self.day).exists())

    def test_http_and_transport_failures_are_domain_errors(self):
        failures = (
            HTTPError(
                "https://example.test/missing.json",
                404,
                "Not Found",
                {},
                None,
            ),
            HTTPError(
                "https://example.test/error.json",
                503,
                "Unavailable",
                {},
                None,
            ),
            URLError("offline"),
            TimeoutError("timeout"),
        )
        for failure in failures:
            with self.subTest(failure=repr(failure)):
                client = TurnmarkClient(
                    self.cache,
                    opener=Mock(side_effect=failure),
                )
                with self.assertRaises(DataUnavailableError):
                    client.fetch(self.day)
                self.assertFalse(self.cache.has_raw(self.day))


class RaceRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = LocalCache(Path(self.temporary.name))
        self.day = date(2026, 5, 3)
        document = raw_payload(self.day, [raw_race(self.day)])
        self.payload = json.dumps(document, ensure_ascii=False).encode("utf-8")

    def test_normalized_cache_matches_raw_hash_and_avoids_renormalizing(self):
        opener = Mock(return_value=self.payload)
        client = TurnmarkClient(self.cache, opener=opener)
        client.decode = Mock(wraps=client.decode)
        repository = RaceRepository(self.cache, client)

        first = repository.races_on(self.day)
        second = repository.races_on(self.day)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertEqual(opener.call_count, 1)
        self.assertEqual(client.decode.call_count, 1)
        # 取得時検証はclass methodを通る。instanceのdecodeは初回正規化時
        # だけ呼ばれ、2回目は正規化キャッシュを直接読む。
        normalized = self.cache.read_normalized(self.day)
        self.assertEqual(
            normalized["source"]["sha256"],
            hashlib.sha256(self.payload).hexdigest(),
        )
        self.assertEqual(normalized["normalization"]["stadium_number"], 21)
        self.assertEqual(normalized["schema_version"], SCHEMA_VERSION)

    def test_replacing_raw_payload_invalidates_normalized_cache_by_hash(self):
        first_payload = self.payload
        second_document = raw_payload(
            self.day,
            [raw_race(self.day), raw_race(self.day, race_number=2)],
        )
        second_payload = json.dumps(second_document).encode("utf-8")
        client = TurnmarkClient(self.cache, opener=Mock(return_value=first_payload))
        repository = RaceRepository(self.cache, client)
        self.assertEqual(len(repository.races_on(self.day)), 1)

        self.cache.write_raw(
            self.day,
            second_payload,
            {"source_url": client.url_for(self.day)},
            replace=True,
        )
        races = repository.races_on(self.day, offline=True)

        self.assertEqual([race.identity.race_number for race in races], [1, 2])
        normalized = self.cache.read_normalized(self.day)
        self.assertEqual(
            normalized["source"]["sha256"],
            hashlib.sha256(second_payload).hexdigest(),
        )

    def test_date_range_is_inclusive_and_rejects_reverse_repository_range(self):
        self.assertEqual(
            list(date_range(date(2026, 5, 1), date(2026, 5, 3))),
            [date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3)],
        )
        repository = RaceRepository(self.cache)
        with self.assertRaises(ValueError):
            repository.races_between(
                date(2026, 5, 2), date(2026, 5, 1), offline=True
            )


if __name__ == "__main__":
    unittest.main()
