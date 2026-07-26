import shutil
import unittest
import uuid
from pathlib import Path

from PIL import Image

from modules.image_diagnostics import analyze_image


class ImageDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("temp/test_image_diagnostics") / uuid.uuid4().hex
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_single_extreme_pixel_does_not_report_maximum_contrast(self):
        path = self.root / "mostly_flat.png"
        image = Image.new("RGB", (240, 135), (120, 120, 120))
        image.putpixel((0, 0), (0, 0, 0))
        image.putpixel((1, 0), (255, 255, 255))
        image.save(path)

        result = analyze_image(path)

        self.assertEqual(result["contrast_metric"], "p95_minus_p05_luminance")
        self.assertLess(result["contrast"], 1)
