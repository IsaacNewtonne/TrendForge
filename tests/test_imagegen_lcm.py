import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from modules.imagegen import (
    configure_scheduler,
    image_generation_settings,
    install_torchvision_functional_tensor_shim,
    is_gtx_16_series_device,
    load_configured_vae,
    output_dimensions,
    postprocess_generated_image,
    refine_generated_image,
    resolve_vae_torch_dtype,
    validate_image_size,
)


class ImagegenLcmTests(unittest.TestCase):
    @patch("modules.imagegen.DEISMultistepScheduler")
    def test_configured_deis_scheduler_is_applied(self, scheduler_cls):
        original = SimpleNamespace(config={"name": "original"})
        replacement = SimpleNamespace(config={"name": "deis"})
        scheduler_cls.from_config.return_value = replacement
        pipe = SimpleNamespace(scheduler=original)

        configure_scheduler(pipe, {"scheduler": "deis_multistep"})

        scheduler_cls.from_config.assert_called_once_with(original.config)
        self.assertIs(pipe.scheduler, replacement)

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

    @patch("modules.imagegen.AutoencoderKL")
    def test_dedicated_vae_is_loaded_with_final_dtype(self, vae_cls):
        expected = object()
        vae_cls.from_pretrained.return_value = expected

        loaded = load_configured_vae(
            {"vae_id": "madebyollin/sdxl-vae-fp16-fix"},
            "float16",
        )

        self.assertIs(loaded, expected)
        vae_cls.from_pretrained.assert_called_once_with(
            "madebyollin/sdxl-vae-fp16-fix",
            torch_dtype="float16",
            use_safetensors=True,
        )

    def test_disabled_detail_pass_returns_original_image(self):
        image = Image.new("RGB", (64, 64), "navy")

        result = refine_generated_image(
            image,
            "prompt",
            "negative",
            {"detail_pass": {"enabled": False}},
            object(),
        )

        self.assertIs(result, image)

    @patch("modules.imagegen.AutoPipelineForImage2Image")
    def test_failed_detail_pass_returns_original_image(self, pipeline_cls):
        image = Image.new("RGB", (64, 64), "navy")
        pipeline_cls.from_pipe.side_effect = RuntimeError("out of memory")

        with patch("modules.imagegen._detail_pipeline", None):
            result = refine_generated_image(
                image,
                "prompt",
                "negative",
                {"detail_pass": {"enabled": True}},
                object(),
            )

        self.assertIs(result, image)

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

    def test_configured_generation_size_is_not_clamped(self):
        self.assertEqual(
            validate_image_size({"width": 1152, "height": 896}),
            (1152, 896),
        )

    def test_two_x_upscale_uses_generation_dimensions(self):
        cfg = {
            "width": 1152,
            "height": 896,
            "upscale_scale": 2,
            "upscale_to_output": True,
        }
        image = Image.new("RGB", (1152, 896), (20, 80, 120))

        self.assertEqual(output_dimensions(cfg), (2304, 1792))
        self.assertEqual(postprocess_generated_image(image, cfg).size, (2304, 1792))

    def test_native_resolution_mode_rejects_lower_resolution_output(self):
        image = Image.new("RGB", (1024, 576), (20, 80, 120))

        with self.assertRaisesRegex(RuntimeError, "Refusing to upscale"):
            postprocess_generated_image(
                image,
                {
                    "width": 1920,
                    "height": 1080,
                    "require_native_resolution": True,
                    "upscale_to_output": False,
                },
            )

    def test_basic_sr_torchvision_shim_installs_old_import_path(self):
        install_torchvision_functional_tensor_shim()

        import torchvision.transforms.functional_tensor as functional_tensor

        self.assertTrue(hasattr(functional_tensor, "rgb_to_grayscale"))


if __name__ == "__main__":
    unittest.main()
