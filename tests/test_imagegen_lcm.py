import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from modules.imagegen import (
    configure_scheduler,
    image_generation_settings,
    install_torchvision_functional_tensor_shim,
    is_gtx_16_series_device,
    postprocess_generated_image,
    resolve_vae_torch_dtype,
)


class ImagegenLcmTests(unittest.TestCase):
    @patch("modules.imagegen.DPMSolverMultistepScheduler")
    def test_configured_dpm_scheduler_is_applied(self, scheduler_cls):
        original = SimpleNamespace(config={"name": "original"})
        replacement = SimpleNamespace(config={"name": "dpm"})
        scheduler_cls.from_config.return_value = replacement
        pipe = SimpleNamespace(scheduler=original)

        configure_scheduler(pipe, {"scheduler": "dpm_solver_multistep"})

        scheduler_cls.from_config.assert_called_once_with(original.config)
        self.assertIs(pipe.scheduler, replacement)

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

    def test_realesrgan_upscale_falls_back_when_model_missing(self):
        image = Image.new("RGB", (64, 36), (20, 80, 120))

        processed = postprocess_generated_image(
            image,
            {
                "upscale_to_output": True,
                "output_width": 128,
                "output_height": 72,
                "upscale_method": "realesrgan",
                "realesrgan_model_path": "models/upscalers/missing.pth",
            },
        )

        self.assertEqual(processed.size, (128, 72))

    def test_basic_sr_torchvision_shim_installs_old_import_path(self):
        install_torchvision_functional_tensor_shim()

        import torchvision.transforms.functional_tensor as functional_tensor

        self.assertTrue(hasattr(functional_tensor, "rgb_to_grayscale"))


if __name__ == "__main__":
    unittest.main()
