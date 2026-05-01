import unittest
from types import SimpleNamespace

from modules.imagegen import image_generation_settings, is_gtx_16_series_device, resolve_vae_torch_dtype


class ImagegenLcmTests(unittest.TestCase):
    def test_lcm_settings_are_used_only_when_pipeline_enabled(self):
        pipe = SimpleNamespace(_trendforge_lcm_enabled=True)

        steps, guidance = image_generation_settings(
            {
                "steps": 10,
                "guidance_scale": 6.0,
                "lcm_steps": 4,
                "lcm_guidance_scale": 1.0,
            },
            pipe,
        )

        self.assertEqual(steps, 4)
        self.assertEqual(guidance, 1.0)

    def test_standard_settings_remain_fallback_when_lcm_not_loaded(self):
        pipe = SimpleNamespace(_trendforge_lcm_enabled=False)

        steps, guidance = image_generation_settings(
            {
                "steps": 10,
                "guidance_scale": 6.0,
                "lcm_steps": 4,
                "lcm_guidance_scale": 1.0,
            },
            pipe,
        )

        self.assertEqual(steps, 10)
        self.assertEqual(guidance, 6.0)

    def test_gtx_16_series_detection_matches_common_device_names(self):
        self.assertTrue(is_gtx_16_series_device("NVIDIA GeForce GTX 1650 Ti with Max-Q Design"))
        self.assertTrue(is_gtx_16_series_device("GeForce GTX 1660 SUPER"))
        self.assertFalse(is_gtx_16_series_device("NVIDIA GeForce RTX 3060"))
        self.assertFalse(is_gtx_16_series_device("NVIDIA GeForce GTX 1080 Ti"))

    def test_vae_auto_uses_pipeline_dtype(self):
        self.assertEqual(resolve_vae_torch_dtype("auto", "fp16", "cuda", "float16"), "float16")


if __name__ == "__main__":
    unittest.main()
