import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import renderer


class FastExportRecoveryTests(unittest.TestCase):
    def test_nvenc_segment_failure_retries_with_cpu_and_keeps_cpu(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = str(Path(temp_dir) / "video.mp4")
            timeline = {
                "fast_export_segments": [
                    {"duration": 1.0},
                    {"duration": 1.0},
                ]
            }
            codecs = []

            def fake_render(
                ffmpeg_path,
                segment,
                index,
                duration,
                work_dir,
                cfg_video,
                codec,
                fps,
                width,
                height,
            ):
                codecs.append(codec)
                if codec == "h264_nvenc":
                    raise RuntimeError("simulated encoder failure")
                return Path(work_dir) / f"segment_{index:03d}.mp4"

            with (
                patch.object(renderer, "resolve_ffmpeg_path", return_value="ffmpeg"),
                patch.object(renderer, "load_output_config", return_value={"temp_directory": temp_dir}),
                patch.object(renderer, "choose_video_codec", return_value="h264_nvenc"),
                patch.object(renderer, "render_fast_segment", side_effect=fake_render),
                patch.object(renderer, "concat_media_files"),
            ):
                renderer.export_with_fast_ffmpeg(timeline, output_path, {"fps": 30})

            self.assertEqual(codecs, ["h264_nvenc", "libx264", "libx264"])


if __name__ == "__main__":
    unittest.main()
