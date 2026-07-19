import json
import tempfile
import unittest
from pathlib import Path

from modules.checkpoints import CHECKPOINT_VERSION, CheckpointStore


class CheckpointStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="temp")
        self.root = Path(self.temp.name) / "checkpoints"

    def tearDown(self):
        self.temp.cleanup()

    def test_round_trip_uses_stable_topic_and_config_fingerprint(self):
        first = CheckpointStore("Artificial Intelligence", {"voice": "a"}, self.root)
        first.save("research", {"topic": "Artificial Intelligence", "raw_content": [1]})
        second = CheckpointStore("Artificial Intelligence", {"voice": "a"}, self.root)
        self.assertEqual(second.load("research")["raw_content"], [1])

        changed = CheckpointStore("Artificial Intelligence", {"voice": "b"}, self.root)
        self.assertIsNone(changed.load("research"))

    def test_asset_is_snapshotted_and_missing_snapshot_invalidates_stage(self):
        source = Path(self.temp.name) / "segment_000.wav"
        source.write_bytes(b"first audio")
        store = CheckpointStore("topic", {}, self.root)
        store.save("audio", {"audio_files": [{"path": str(source)}]})

        source.write_bytes(b"overwritten by another run")
        restored = store.load("audio")
        cached = Path(restored["audio_files"][0]["path"])
        self.assertNotEqual(cached, source)
        self.assertEqual(cached.read_bytes(), b"first audio")

        cached.unlink()
        self.assertIsNone(store.load("audio"))

    def test_corrupt_stage_json_is_ignored(self):
        store = CheckpointStore("topic", {}, self.root)
        store.save("script", {"script": {"segments": []}})
        (store.directory / "script.json").write_text("{broken", encoding="utf-8")
        self.assertIsNone(store.load("script"))

    def test_manifest_is_valid_json_after_each_save(self):
        store = CheckpointStore("topic", {}, self.root)
        store.save("research", {"value": 1})
        store.save("analysis", {"value": 2})
        manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["stages"]), {"research", "analysis"})

    def test_old_checkpoint_version_is_not_reused(self):
        store = CheckpointStore("topic", {}, self.root)
        store.save("research", {"value": "stale"})
        manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = CHECKPOINT_VERSION - 1
        store.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        refreshed = CheckpointStore("topic", {}, self.root)

        self.assertIsNone(refreshed.load("research"))
        self.assertEqual(refreshed.manifest["version"], CHECKPOINT_VERSION)


if __name__ == "__main__":
    unittest.main()
