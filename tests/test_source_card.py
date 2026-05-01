import shutil
import unittest
import uuid
from pathlib import Path

from PIL import Image

from modules.source_card import HEIGHT, WIDTH, create_source_card


class SourceCardRenderTests(unittest.TestCase):
    def setUp(self):
        self.output_dir = Path("temp/test_source_card") / f"{self._testMethodName}_{uuid.uuid4().hex}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_modern_source_card_renders_video_frame(self):
        output = self.output_dir / "source_card.png"
        create_source_card(
            {
                "source_name": "Example Research Lab",
                "source_url": "https://example.com/reports/artificial-intelligence-update",
                "source_title": "Example report shows AI adoption is moving fastest inside routine office workflows",
                "claim": "Evidence-backed claim with verified source context and concise key takeaway.",
            },
            output,
        )

        image = Image.open(output).convert("RGB")
        self.assertEqual(image.size, (WIDTH, HEIGHT))

        thumbnail = image.resize((160, 90))
        colors = thumbnail.getcolors(maxcolors=1_000_000)
        self.assertIsNotNone(colors)
        self.assertGreater(len(colors or []), 80)


if __name__ == "__main__":
    unittest.main()
