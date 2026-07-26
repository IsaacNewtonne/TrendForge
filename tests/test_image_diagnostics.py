import shutil
import unittest
import uuid
from pathlib import Path

from PIL import Image

from modules.image_diagnostics import analyze_image, is_video_ready_image


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

    def test_rejects_undersized_images_even_when_they_have_detail(self):
        path = self.root / "small_checker.png"
        image = Image.new("RGB", (640, 360))
        for y in range(360):
            for x in range(640):
                value = 245 if (x // 12 + y // 12) % 2 else 20
                image.putpixel((x, y), (value, 80, 255 - value))
        image.save(path)

        result = analyze_image(path)

        self.assertTrue(result["is_undersized"])
        self.assertFalse(is_video_ready_image(path))
