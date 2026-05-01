import shutil
import unittest
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

from modules.source_card import HEIGHT, WIDTH
from modules.source_frame import create_evidence_frame


class SourceFrameRenderTests(unittest.TestCase):
    def setUp(self):
        self.output_dir = Path("temp/test_source_frame") / f"{self._testMethodName}_{uuid.uuid4().hex}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_evidence_frame_wraps_raw_screenshot(self):
        raw = self.output_dir / "raw.png"
        framed = self.output_dir / "framed.png"
        image = Image.new("RGB", (1280, 900), (245, 247, 252))
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 90, 1180, 210), fill=(28, 42, 72))
        draw.text((120, 128), "Example report: AI adoption is accelerating", fill=(255, 255, 255))
        draw.rectangle((120, 280, 1160, 780), outline=(30, 151, 255), width=8)
        image.save(raw)

        create_evidence_frame(
            raw,
            framed,
            {
                "id": "seg_004",
                "source_name": "Example Research Lab",
                "source_url": "https://example.com/reports/artificial-intelligence-update",
                "source_title": "Example report shows AI adoption is moving fastest inside routine office workflows",
            },
        )

        output = Image.open(framed).convert("RGB")
        self.assertEqual(output.size, (WIDTH, HEIGHT))
        colors = output.resize((160, 90)).getcolors(maxcolors=1_000_000)
        self.assertIsNotNone(colors)
        self.assertGreater(len(colors or []), 120)


if __name__ == "__main__":
    unittest.main()
