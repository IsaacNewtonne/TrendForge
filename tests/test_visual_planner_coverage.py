import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from modules.visual_planner import (
    complete_visual_plan_coverage,
    validate_visual_plan,
)


class VisualPlannerCoverageTests(unittest.TestCase):
    def test_validation_cap_never_drops_parent_segment_coverage(self):
        script = {
            "segments": [
                {"type": "fact", "text": f"Segment {index} narration."}
                for index in range(28)
            ]
        }
        raw_beats = [
            {
                "parent_segment_index": index,
                "narration": f"Segment {index} narration.",
                "visual_intent": "concept_art",
            }
            for index in range(28)
        ]

        result = validate_visual_plan(raw_beats, script, {"max_beats": 20})

        self.assertEqual(len(result), 28)

    def test_coverage_fallback_fills_indices_omitted_by_model(self):
        script = {
            "segments": [
                {"type": "fact", "text": f"Segment {index} narration."}
                for index in range(4)
            ]
        }
        initial = [
            {
                "parent_segment_index": 0,
                "narration": "Segment 0 narration.",
                "visual_intent": "concept_art",
            }
        ]
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"beats": [{"parent_segment_index": 1, '
                        '"visual_intent": "concept_art"}]}'
                    )
                )
            ]
        )
        client = Mock()
        client.chat.completions.create.return_value = response

        result = complete_visual_plan_coverage(
            initial,
            script,
            evidence=[{"title": "Evidence"}],
            client=client,
            model="local",
            options={},
            planner_cfg={
                "strict": True,
                "coverage_fallback": True,
                "coverage_batch_size": 8,
            },
        )

        self.assertEqual(
            {beat["parent_segment_index"] for beat in result},
            {0, 1, 2, 3},
        )


if __name__ == "__main__":
    unittest.main()
