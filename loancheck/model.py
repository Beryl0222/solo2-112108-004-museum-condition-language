"""领域数据结构。

所有结构只描述事实与核对结论，不做展示格式化，便于按借件批次复用、
被其他系统以 JSON 形式再次读取。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# 三个业务层面：作品本体、装裱、外箱
LAYER_BODY = "body"
LAYER_MOUNT = "mount"
LAYER_CASE = "case"

# 资料里的具体材质名到三个层面的归类
MATERIAL_LAYERS = {
    "paper": LAYER_BODY,
    "cloth": LAYER_BODY,
    "mount": LAYER_MOUNT,
    "crate": LAYER_CASE,
}

PHASE_IN = "in"
PHASE_MID = "mid"
PHASE_OUT = "out"

# 肯定程度
CERT_CONFIRMED = "confirmed"      # 明确陈述
CERT_UNCERTAIN = "uncertain"      # 不能断定/疑似
CERT_NEGATED = "negated"          # 明确否定（未见、非起翘）
CERT_REVIEW = "review"            # 复查动作及其结论


@dataclass(frozen=True)
class Loan:
    """一件借件及其声明层面与当前箱号（箱号不代表放行结论）。"""

    id: str
    label: str
    layers: list[str]
    case: str
    owner: str

    @property
    def body_material(self) -> Optional[str]:
        for material in self.layers:
            if MATERIAL_LAYERS.get(material) == LAYER_BODY:
                return material
        return None

    def has_layer(self, layer: str) -> bool:
        return any(MATERIAL_LAYERS.get(material) == layer for material in self.layers)


@dataclass(frozen=True)
class View:
    """一张照片的参照。轴信息为空表示该方向缺参照，不能硬配位点。"""

    id: str
    loan: str
    right_in_object: Optional[str]
    top_in_object: Optional[str]
    scope: list[str]

    @property
    def has_horizontal_reference(self) -> bool:
        return self.right_in_object is not None

    @property
    def has_full_reference(self) -> bool:
        return self.right_in_object is not None and self.top_in_object is not None


@dataclass(frozen=True)
class Report:
    """一条双语文字报告；同 id 的 revision 以高修订号为准。"""

    id: str
    loan: str
    phase: str
    author: str
    lang: str
    revision: int
    references: list[str]
    text: str


@dataclass(frozen=True)
class Handover:
    """一次两馆签字或拟箱记录。snapshot 是签字时所见的对象列表。"""

    id: str
    signer: str
    scope: str
    snapshot: list[str]
    action: str
    at: str

    @property
    def is_sealing(self) -> bool:
        # 资料中“已签封箱”才构成签字；拟合箱/拟改组只是计划
        return "签" in self.action and self.scope == "case"


@dataclass(frozen=True)
class ObjectLocation:
    """部位与朝向的结构化表达。

    frame:
      object —— 物件自身坐标（右缘、verso 等）
      photo  —— 照片坐标（照片右、right margin），需经参照换算
      unknown —— 文字未给可定位信息
    side/vertical：方位词（right/left/top/bottom）
    margin：是否为边沿类部位
    face：recto/verso
    resolved：photo 坐标是否已成功换算到物件坐标
    reference_view：换算所依据的照片号
    """

    frame: str
    side: Optional[str] = None
    vertical: Optional[str] = None
    margin: bool = False
    face: Optional[str] = None
    resolved: bool = True
    reference_view: Optional[str] = None
    raw: Optional[str] = None

    def key(self) -> tuple[Any, ...]:
        """用于位点合并的稳定键；未解析位点不得与已解析位点相等。"""
        return (
            self.frame,
            self.side,
            self.vertical,
            self.margin,
            self.face,
            self.resolved,
        )


@dataclass(frozen=True)
class Observation:
    """从一句话中抽取的一条原始观察，保留原文证据。"""

    report_id: str
    loan_id: str
    phase: str
    lang: str
    clause: str                         # 原文小句
    span: tuple[int, int]               # 小句在报告全文中的字符区间
    layer: Optional[str]                # body/mount/case，无法判定为 None
    family: str                         # 状态家族（fold/lift/scratch/...）
    certainty: str
    location: ObjectLocation
    count: Optional[int] = None
    view_refs: list[str] = field(default_factory=list)
    evidence_phrases: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)  # 如“可能是装裱投影”
    temporal: Optional[str] = None      # old/new/none
    review: bool = False
    note: Optional[str] = None


@dataclass
class RequiredView:
    """仍不能确定归属时，最少还需核对的视角或层面。"""

    need_code: str                      # 机器可读码
    description: str
    reason: str
    related_feature: str

    def key(self) -> tuple[Any, ...]:
        return (self.need_code, self.description)


@dataclass
class Feature:
    """多条观察归并后指向的同一件状况（旧痕/新变/排除项/分歧）。"""

    id: str
    loan_id: str
    layer: Optional[str]
    family: str
    status: str
    location_key: tuple[Any, ...]
    locations: list[ObjectLocation] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    distinct_sources: list[str] = field(default_factory=list)
    photos: list[str] = field(default_factory=list)
    quota: Optional[int] = None         # 笼统旧痕可吸收的条数
    used_quota: int = 0
    required_views: list[RequiredView] = field(default_factory=list)
    note: Optional[str] = None

    @property
    def blocks_release(self) -> bool:
        return self.status in {
            "new_pending",
            "disputed",
            "unresolved_located",
        }


@dataclass
class CoverageGap:
    """视角/层面覆盖缺口（提示性质，不直接等同于新增变化）。"""

    loan_id: str
    layer: str
    face: Optional[str]
    description: str


@dataclass
class LoanConclusion:
    """单件借件的核对结论。"""

    loan: Loan
    features: list[Feature] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    coverage_gaps: list[CoverageGap] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def blocking_features(self) -> list[Feature]:
        return [feature for feature in self.features if feature.blocks_release]


@dataclass
class CaseDecision:
    """一个实际可放行的封箱组合的核对结论。"""

    case_id: str
    loan_ids: list[str]
    releasable: bool
    reasons: list[str] = field(default_factory=list)
    blocking: list[dict[str, Any]] = field(default_factory=list)
    matched_handover: Optional[Handover] = None
    proposed_handovers: list[Handover] = field(default_factory=list)
    combination_signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.matched_handover is not None:
            data["matched_handover"] = asdict(self.matched_handover)
        data["proposed_handovers"] = [asdict(item) for item in self.proposed_handovers]
        return data


@dataclass
class BatchResult:
    """整批核对结果。"""

    conclusions: list[LoanConclusion]
    case_decisions: list[CaseDecision]
    data_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "loans": [
                {
                    "loan_id": conclusion.loan.id,
                    "label": conclusion.loan.label,
                    "case": conclusion.loan.case,
                    "features": [
                        {
                            "id": feature.id,
                            "layer": feature.layer,
                            "family": feature.family,
                            "status": feature.status,
                            "locations": [asdict(location) for location in feature.locations],
                            "observation_ids": feature.observation_ids,
                            "distinct_sources": feature.distinct_sources,
                            "photos": feature.photos,
                            "quota": feature.quota,
                            "used_quota": feature.used_quota,
                            "required_views": [asdict(need) for need in feature.required_views],
                            "note": feature.note,
                            "evidence": feature.evidence,
                        }
                        for feature in conclusion.features
                    ],
                    "coverage_gaps": [asdict(gap) for gap in conclusion.coverage_gaps],
                    "warnings": conclusion.warnings,
                }
                for conclusion in self.conclusions
            ],
            "cases": [decision.to_dict() for decision in self.case_decisions],
            "data_warnings": self.data_warnings,
        }
