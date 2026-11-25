"""照片参照换算与位点兼容性测试。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loancheck.geometry import (  # noqa: E402
    locations_compatible,
    photo_side_to_object,
    photo_vertical_to_object,
    resolve_location,
)
from loancheck.model import ObjectLocation, View  # noqa: E402


class GeometryTests(unittest.TestCase):
    def setUp(self):
        # 镜像照片：照片右轴落在物件左
        self.mirrored = View("Vm", "Lx", "left", "top", ["paper"])
        # 旋转 90° 照片：照片右轴落在物件上
        self.rotated = View("Vr", "Lx", "top", "left", ["paper"])
        # 缺水平参照
        self.missing = View("Vu", "Lx", None, "top", ["paper"])

    def test_mirrored_photo_right_is_object_left(self):
        self.assertEqual(photo_side_to_object(self.mirrored, "right"), "left")
        self.assertEqual(photo_side_to_object(self.mirrored, "left"), "right")

    def test_rotated_axes_swap_dimensions(self):
        self.assertEqual(photo_side_to_object(self.rotated, "right"), "top")
        self.assertEqual(photo_vertical_to_object(self.rotated, "bottom"), "left")

    def test_missing_reference_does_not_resolve(self):
        self.assertIsNone(photo_side_to_object(self.missing, "right"))
        location = ObjectLocation(frame="photo", side="right", margin=True,
                                  raw="photo right")
        resolved = resolve_location(location, self.missing)
        self.assertFalse(resolved.resolved)
        self.assertEqual(resolved.frame, "photo")

    def test_resolved_location_carries_view_id(self):
        location = ObjectLocation(frame="photo", side="right", margin=True,
                                  raw="photo right")
        resolved = resolve_location(location, self.mirrored)
        self.assertTrue(resolved.resolved)
        self.assertEqual(resolved.frame, "object")
        self.assertEqual(resolved.side, "left")
        self.assertEqual(resolved.reference_view, "Vm")

    def test_unresolved_locations_never_match(self):
        unresolved = ObjectLocation(frame="photo", side="right", resolved=False)
        anchor = ObjectLocation(frame="object", side="left", resolved=True)
        self.assertFalse(locations_compatible(unresolved, anchor))

    def test_partial_location_claims_are_compatible(self):
        # 只主张“上边”与主张“左上角”可指向同一处
        top_only = ObjectLocation(frame="object", vertical="top", margin=True)
        left_top = ObjectLocation(frame="object", side="left", vertical="top",
                                  margin=True)
        self.assertTrue(locations_compatible(top_only, left_top))
        # 左右主张冲突则不兼容
        right_top = ObjectLocation(frame="object", side="right", vertical="top",
                                   margin=True)
        self.assertFalse(locations_compatible(right_top, left_top))


if __name__ == "__main__":
    unittest.main()
