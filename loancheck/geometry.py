"""照片参照轴与物件方位的换算。

资料约定：``right_in_object`` 表示“照片正向的右轴落在物件自身的哪一方位”。
因此照片右侧对应的物件方位就是该字段本身；镜像（值为 left）时照片右即物件左，
旋转（值为 top/bottom）时照片右对应物件上/下。任一根轴缺失时，
对应维度不得强行换算，位点保持未解析。
"""
from __future__ import annotations

from typing import Optional

from .model import ObjectLocation, View

OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}

# 物件方位 -> 照片方位（正向轴）
_OBJECT_TO_PHOTO = {
    "right": "right",
    "left": "left",
    "top": "top",
    "bottom": "bottom",
}


def photo_side_to_object(view: View, photo_side: str) -> Optional[str]:
    """照片水平方位（left/right）换算为物件方位；缺水平参照返回 None。"""
    if view.right_in_object is None:
        return None
    # 照片右 -> 物件的 right_in_object；照片左与其相反
    if photo_side == "right":
        return view.right_in_object
    if photo_side == "left":
        return OPPOSITE[view.right_in_object]
    return None


def photo_vertical_to_object(view: View, photo_vertical: str) -> Optional[str]:
    """照片垂直方位（top/bottom）换算为物件方位；缺垂直参照返回 None。"""
    if view.top_in_object is None:
        return None
    if photo_vertical == "bottom":
        return view.top_in_object
    if photo_vertical == "top":
        return OPPOSITE[view.top_in_object]
    return None


def object_side_to_photo(view: View, object_side: str) -> Optional[str]:
    """物件方位换算回该照片中的水平方位，用于“同痕在旋转照片中的转述”。"""
    if view.right_in_object is None:
        return None
    if object_side == view.right_in_object:
        return "right"
    if object_side == OPPOSITE[view.right_in_object]:
        return "left"
    # 物件上/下缘在旋转 90° 的照片里落在垂直轴上，不属于水平换算
    return None


def resolve_location(location: ObjectLocation, view: Optional[View]) -> ObjectLocation:
    """把照片坐标位点换算成物件坐标。

    - 已经是物件坐标：原样返回。
    - 照片坐标且照片两根轴齐备：按轴换算，resolved=True。
    - 照片坐标但参照缺失：保留原照片方位，resolved=False，调用方不得据此配位点。
    """
    if location.frame != "photo":
        return location
    if view is None:
        return ObjectLocation(
            frame="photo",
            side=location.side,
            vertical=location.vertical,
            margin=location.margin,
            face=location.face,
            resolved=False,
            reference_view=location.reference_view,
            raw=location.raw,
        )
    object_side = photo_side_to_object(view, location.side) if location.side else None
    object_vertical = (
        photo_vertical_to_object(view, location.vertical) if location.vertical else None
    )
    # 旋转照片中，水平/垂直维度可能互换：某一维度无法在本轴表达时不丢信息，
    # 但只要任一原始维度缺参照，整体就标记为未完全解析。
    horizontal_resolvable = location.side is None or view.right_in_object is not None
    vertical_resolvable = location.vertical is None or view.top_in_object is not None
    fully_resolved = horizontal_resolvable and vertical_resolvable
    if not fully_resolved:
        return ObjectLocation(
            frame="photo",
            side=location.side,
            vertical=location.vertical,
            margin=location.margin,
            face=location.face,
            resolved=False,
            reference_view=view.id,
            raw=location.raw,
        )
    return ObjectLocation(
        frame="object",
        side=object_side,
        vertical=object_vertical,
        margin=location.margin,
        face=location.face,
        resolved=True,
        reference_view=view.id,
        raw=location.raw,
    )


def locations_compatible(candidate: ObjectLocation, anchor: ObjectLocation) -> bool:
    """判断两个位点是否可指向同一处。

    规则：
    - 任一为未解析照片位点，一律不得自动配同（缺参照不硬配）。
    - 物件坐标下逐维度比较，某一方维度为空表示该维度无主张，可兼容；
      双方都有主张时必须一致。
    - face（正/背面）双方都有主张时必须一致。
    """
    if not candidate.resolved or not anchor.resolved:
        return False
    if candidate.frame != anchor.frame:
        return False
    for attribute in ("side", "vertical", "face"):
        left = getattr(candidate, attribute)
        right = getattr(anchor, attribute)
        if left is not None and right is not None and left != right:
            return False
    # margin 仅记录“边沿类部位”这一事实，不参与位点冲突判定，
    # 具体哪条边由 side/vertical 决定
    return True


def same_object_position(left: ObjectLocation, right: ObjectLocation) -> bool:
    """严格同位点（用于“明确记录的新位置”判定）。"""
    if left.frame != right.frame or not left.resolved or not right.resolved:
        return False
    return left.key() == right.key()
