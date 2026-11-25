"""旧痕/新增/排除/分歧核对引擎。

业务规则落地：
1. 多条描述可合并指向同一旧痕（跨语言、跨阶段）；一条笼统多部位记录可按
   有证据的位置拆开。
2. “边缘两处起翘”这类笼统计数只能吸收未定位的旧痕配额，不能抵消已明确
   记录的新位点。
3. 同一张照片的不同转述不是互相独立的确认；独立来源以报告（登记号）计。
4. 复查排除需要独立于原照片的来源（如背面/verso 复查）。
5. 照片缺参照时位点保持未解析，不得硬配；该变化必须补核。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .geometry import locations_compatible
from .model import (
    CERT_CONFIRMED,
    CERT_UNCERTAIN,
    CoverageGap,
    Feature,
    LAYER_BODY,
    LAYER_CASE,
    LAYER_MOUNT,
    Loan,
    LoanConclusion,
    MATERIAL_LAYERS,
    Observation,
    PHASE_IN,
    PHASE_MID,
    PHASE_OUT,
    RequiredView,
    View,
)
from .parser import NEGATIVE_COVERAGE_FAMILY, _positioned

# 特征状态
OLD_SIGNED = "old_signed"                 # 入场已签认的旧痕
OLD_RECORDED = "old_recorded"             # 入场有记录但未见签字
OLD_QUOTA = "old_quota"                   # 笼统旧痕配额（未定位计数）
REVIEW_EXCLUDED = "review_excluded"       # 复查排除（含投影/反光）
OPTICAL_EXCLUDED = "optical_excluded"
NEW_PENDING = "new_pending"               # 待确认的新痕（阻断放行）
NEW_CONFIRMED = "new_confirmed"           # 已确认新增且已完成复核（留痕，不阻断）
DISPUTED = "disputed"                     # 两馆仍有分歧（阻断）
UNRESOLVED_LOCATED = "unresolved_located" # 缺照片参照无法定位（阻断）
CASE_NOTE = "case_note"                   # 外箱层变化，未达本体
COVERAGE_NOTE = "coverage_note"           # 覆盖性陈述（未见新增）

OPTICAL_FAMILIES = {"shadow", "reflection"}
BLOCKING_STATUSES = {NEW_PENDING, DISPUTED, UNRESOLVED_LOCATED}


@dataclass
class _EntrySigning:
    signed_report_ids: set[str]
    warnings: list[str]


def entry_signed_reports(handovers) -> _EntrySigning:
    """入场记录 scope 的签字覆盖哪些报告登记号。"""
    warnings: list[str] = []
    signed: set[str] = set()
    for handover in handovers:
        if handover.scope == "record":
            signed.update(handover.snapshot)
    return _EntrySigning(signed_report_ids=signed, warnings=warnings)


def _evidence_entry(observation: Observation) -> dict:
    return {
        "report_id": observation.report_id,
        "phase": observation.phase,
        "lang": observation.lang,
        "clause": observation.clause,
        "span": list(observation.span),
        "certainty": observation.certainty,
        "temporal": observation.temporal,
        "view_refs": observation.view_refs,
        "alternatives": observation.alternatives,
        "note": observation.note,
    }


class _FeatureBuilder:
    def __init__(self, loan: Loan):
        self.loan = loan
        self._counter = 0
        self.features: list[Feature] = []

    def create(self, layer, family, status, location, observation) -> Feature:
        self._counter += 1
        feature = Feature(
            id=f"{self.loan.id}-F{self._counter}",
            loan_id=self.loan.id,
            layer=layer,
            family=family,
            status=status,
            location_key=location.key() if location else ("unknown",),
            locations=[location] if location else [],
        )
        self._attach(feature, observation)
        self.features.append(feature)
        return feature

    def _attach(self, feature: Feature, observation: Observation) -> None:
        feature.observation_ids.append(observation.report_id)
        feature.evidence.append(_evidence_entry(observation))
        for ref in observation.view_refs:
            if ref not in feature.photos:
                feature.photos.append(ref)
        location = observation.location
        if location and location.frame != "unknown":
            if not any(
                existing.key() == location.key() for existing in feature.locations
            ):
                feature.locations.append(location)
        # 独立来源按报告登记号计；同一报告（含其中不同小句/转述）只算一个来源
        if observation.report_id not in feature.distinct_sources:
            feature.distinct_sources.append(observation.report_id)


def _is_optical(observation: Observation) -> bool:
    return observation.family in OPTICAL_FAMILIES


def _damage_observations(observations: list[Observation]) -> list[Observation]:
    return [
        item
        for item in observations
        if item.family != NEGATIVE_COVERAGE_FAMILY and not _is_optical(item)
    ]


def _find_matching_feature(
    feature: Feature, observation: Observation
) -> Optional[Feature]:
    """同家族、同层面下寻找可合并的既有特征。"""
    if feature.family != observation.family:
        return None
    if feature.layer is not None and observation.layer is not None:
        if feature.layer != observation.layer:
            return None
    location = observation.location
    # 未解析位点不允许并入已解析特征（缺参照不硬配）
    if not location.resolved:
        return None
    for anchor in feature.locations:
        if not anchor.resolved:
            continue
        if locations_compatible(location, anchor):
            return feature
    return None


def _build_baseline(
    loan: Loan,
    in_observations: list[Observation],
    signing: _EntrySigning,
    builder: _FeatureBuilder,
) -> tuple[list[Feature], list[Feature]]:
    """入场记录 -> 已签认旧痕/笼统配额。"""
    resolved_features: list[Feature] = []
    quota_features: list[Feature] = []
    for observation in in_observations:
        if observation.family == NEGATIVE_COVERAGE_FAMILY or _is_optical(observation):
            continue
        signed = observation.report_id in signing.signed_report_ids
        status = OLD_SIGNED if signed else OLD_RECORDED
        if not _positioned(observation.location):
            # 未定位或仅有笼统“边缘/rim”主张：作为计数配额，
            # 只能吸收未定位描述，不能抵消明确新位点
            existing_quota = next(
                (feature for feature in quota_features
                 if feature.family == observation.family
                 and (feature.layer is None or observation.layer is None
                      or feature.layer == observation.layer)),
                None,
            )
            if existing_quota is not None:
                builder._attach(existing_quota, observation)
                continue
            feature = builder.create(
                observation.layer, observation.family, OLD_QUOTA,
                observation.location, observation,
            )
            feature.quota = observation.count or 1
            feature.used_quota = 0
            feature.note = (
                "入场笼统计数旧痕，只能吸收未定位的同类描述，"
                "不能抵消已明确记录的新位点"
            )
            quota_features.append(feature)
            continue
        # 同家族同层面同位点的入场描述先合并（含同一登记号的多份转述）
        merged = None
        for feature in resolved_features:
            merged = _find_matching_feature(feature, observation)
            if merged:
                break
        if merged is not None:
            builder._attach(merged, observation)
            if signed:
                merged.status = OLD_SIGNED
            continue
        feature = builder.create(
            observation.layer, observation.family, status,
            observation.location, observation,
        )
        resolved_features.append(feature)
    return resolved_features, quota_features


def _required_views_for(
    observation: Observation, loan: Loan, views: dict[str, View]
) -> list[RequiredView]:
    needs: list[RequiredView] = []
    location = observation.location
    if location.frame == "photo" and not location.resolved:
        needs.append(
            RequiredView(
                need_code="photo_reference",
                description=(
                    f"补一张带完整方向参照（right/top 轴）的照片，"
                    f"以确定 {location.raw or '照片所述部位'} 对应物件的哪一边"
                ),
                reason="原照片缺方向参照，照片右侧不能直接当作画作右缘",
                related_feature="",
            )
        )
    if observation.alternatives or observation.family in OPTICAL_FAMILIES:
        needs.append(
            RequiredView(
                need_code="verso_review",
                description="在同一物件位点补做背面（verso）/装裱层面复查",
                reason="需区分作品本体变化与装裱投影、反光等光学现象",
                related_feature="",
            )
        )
    if observation.certainty == CERT_UNCERTAIN and not needs:
        needs.append(
            RequiredView(
                need_code="second_source",
                description="由另一独立视角或另一登记来源复核该位点",
                reason="现有描述为疑似，单张照片的不同转述不构成独立确认",
                related_feature="",
            )
        )
    if observation.certainty == CERT_CONFIRMED and not needs:
        needs.append(
            RequiredView(
                need_code="independent_review",
                description="对该明确新位点安排保护人员独立复查并由两馆签字确认",
                reason="已明确记录的新位点不能被笼统旧痕计数抵消，需完成复核方可放行",
                related_feature="",
            )
        )
    return needs


def _normalize_layer(layer: Optional[str]) -> Optional[str]:
    """把资料原始材质名（crate/mount/paper/cloth）归一到三个业务层面。"""
    if layer is None:
        return None
    return MATERIAL_LAYERS.get(layer, layer)


def reconcile_loan(
    loan: Loan,
    observations: list[Observation],
    views: dict[str, View],
    signing: _EntrySigning,
) -> LoanConclusion:
    # 统一层面命名，避免 crate/case 一类原始值与业务层面常量不一致
    for observation in observations:
        object.__setattr__(observation, "layer", _normalize_layer(observation.layer))
    conclusion = LoanConclusion(loan=loan, observations=observations)
    builder = _FeatureBuilder(loan)
    mine = [item for item in observations if item.loan_id == loan.id]

    in_obs = [item for item in mine if item.phase == PHASE_IN]
    mid_obs = [item for item in mine if item.phase == PHASE_MID]
    out_obs = [item for item in mine if item.phase == PHASE_OUT]

    resolved_baseline, quota_baseline = _build_baseline(loan, in_obs, signing, builder)
    all_damage_features = list(resolved_baseline) + list(quota_baseline)

    # 展中清点：可用于消除歧义，并入同痕或单列旧痕
    for observation in _damage_observations(mid_obs):
        observation = _apply_photo_context(observation, mine, views)
        matched = None
        if observation.location.resolved and _positioned(observation.location):
            for feature in resolved_baseline:
                matched = _find_matching_feature(feature, observation)
                if matched:
                    break
        if matched is not None:
            builder._attach(matched, observation)
            continue
        feature = builder.create(
            observation.layer, observation.family, OLD_RECORDED,
            observation.location, observation,
        )
        if observation.location.resolved and _positioned(observation.location):
            resolved_baseline.append(feature)
        all_damage_features.append(feature)

    # 独立的复查排除证据（光学家族，review 或 confirmed）
    exclusion_sources: dict[str, list[Observation]] = {}
    for observation in mine:
        if _is_optical(observation) and observation.review:
            exclusion_sources.setdefault(observation.family, []).append(observation)

    # 退场观察
    for raw_observation in _damage_observations(out_obs):
        observation = _apply_photo_context(raw_observation, mine, views)
        location = observation.location

        # 1) 先尝试并入已定位旧痕（含 old 时间性主张的照片坐标旧痕）
        matched = None
        if location.resolved and _positioned(location):
            for feature in resolved_baseline:
                matched = _find_matching_feature(feature, observation)
                if matched:
                    break
        if matched is not None:
            builder._attach(matched, observation)
            matched.note = matched.note or "退场描述与入场旧痕同位，归并为同一旧痕"
            continue
        # 明确主张为旧痕、但照片坐标未能换算：作为未决旧痕留证，不硬配
        if observation.temporal == "old" and location.frame == "photo":
            feature = builder.create(
                observation.layer, observation.family,
                UNRESOLVED_LOCATED, location, observation,
            )
            feature.note = (
                "文字明确主张为旧痕，但照片缺参照/多照片语境无法定位，"
                "不得与入场旧折硬配，需补带方向参照的照片"
            )
            feature.required_views = _required_views_for(observation, loan, views)
            for need in feature.required_views:
                need.related_feature = feature.id
            continue

        # 2) 复查排除优先于配额：独立来源（如背面复查）证实为投影/反光，
        #    即使原观察位点未解析也成立，否则会被误当成新变化
        if _has_independent_exclusion(observation, exclusion_sources):
            exclusion_family = next(iter(exclusion_sources))
            feature = builder.create(
                LAYER_MOUNT,
                exclusion_family,
                REVIEW_EXCLUDED,
                location,
                observation,
            )
            for family_name, sources in exclusion_sources.items():
                for source in sources:
                    if source.report_id != observation.report_id:
                        builder._attach(feature, source)
            feature.note = "经独立复查排除：该位点为装裱投影/反光，非运输新增"
            continue

        # 3) 笼统旧痕配额：只吸收未定位/无明确位点主张的描述
        if not _positioned(location):
            quota = _consume_quota(quota_baseline, observation, builder)
            if quota is not None:
                continue

        # 4) 新变化判定
        if not location.resolved:
            feature = builder.create(
                observation.layer, observation.family,
                UNRESOLVED_LOCATED, location, observation,
            )
        elif observation.certainty == CERT_UNCERTAIN:
            feature = builder.create(
                observation.layer, observation.family,
                DISPUTED, location, observation,
            )
            feature.note = "新痕疑似且归属未定，两馆存在分歧"
        else:
            feature = builder.create(
                observation.layer, observation.family,
                NEW_PENDING, location, observation,
            )
            feature.note = "退场出现的明确新位点，笼统旧痕计数不得抵消"
        feature.required_views = _required_views_for(observation, loan, views)
        for need in feature.required_views:
            need.related_feature = feature.id

    # 光学排除特征（即使没有对应损伤候选，也独立留证给签字方看）
    for family_name, sources in exclusion_sources.items():
        already = [feature for feature in builder.features if feature.status == REVIEW_EXCLUDED]
        covered_reports = {report for feature in already for report in feature.observation_ids}
        for source in sources:
            if source.report_id in covered_reports:
                continue
            feature = builder.create(
                LAYER_MOUNT, family_name, OPTICAL_EXCLUDED,
                source.location, source,
            )
            feature.note = "装裱投影/反光的独立复查记录，非作品本体变化"

    # 覆盖性陈述（未见新增）
    for observation in mine:
        if observation.family == NEGATIVE_COVERAGE_FAMILY:
            feature = builder.create(
                observation.layer or LAYER_BODY,
                NEGATIVE_COVERAGE_FAMILY,
                COVERAGE_NOTE,
                observation.location,
                observation,
            )
            feature.note = observation.note

    # 外箱层损伤单列：未达本体则为 case_note
    for feature in builder.features:
        if feature.layer == LAYER_CASE and feature.status in {
            NEW_PENDING,
            DISPUTED,
            UNRESOLVED_LOCATED,
        }:
            # 若同批有本体未受影响的证据（coverage 或文字 note），降为 case_note
            if _case_damage_confined(feature, mine):
                feature.status = CASE_NOTE
                feature.note = "变化限于外箱层面，未达作品本体；仍需在收据上留痕"

    conclusion.features = builder.features
    conclusion.coverage_gaps = _coverage_gaps(loan, views)
    conclusion.warnings = _feature_warnings(builder.features)
    return conclusion


def _apply_photo_context(
    observation: Observation,
    all_observations: list[Observation],
    views: dict[str, View],
) -> Observation:
    """多照片小句的位点回退：按同报告其他小句的显式照片归属确定语境。

    例如 O1 同时引用 V12/V13，其中 V13 由同句显式号归属；不带号的
    “photo right”小句若在报告语境中能确定唯一照片，则按该照片参照换算，
    否则保持未解析（不硬配）。
    """
    location = observation.location
    if location.frame != "photo" or location.resolved:
        return observation
    candidates: set[str] = set()
    for sibling in all_observations:
        if sibling.report_id != observation.report_id:
            continue
        for ref in sibling.view_refs:
            candidates.add(ref)
    # 只在报告语境能收敛到单张可参照照片时回退
    resolvable = {ref for ref in candidates if views[ref].has_horizontal_reference}
    if len(resolvable) != 1:
        return observation
    view = views[next(iter(resolvable))]
    from .geometry import resolve_location
    resolved = resolve_location(location, view)
    return Observation(
        report_id=observation.report_id,
        loan_id=observation.loan_id,
        phase=observation.phase,
        lang=observation.lang,
        clause=observation.clause,
        span=observation.span,
        layer=observation.layer,
        family=observation.family,
        certainty=observation.certainty,
        location=resolved,
        count=observation.count,
        view_refs=list(dict.fromkeys(observation.view_refs + [view.id])),
        evidence_phrases=list(observation.evidence_phrases),
        alternatives=list(observation.alternatives),
        temporal=observation.temporal,
        review=observation.review,
        note=observation.note,
    )


def _consume_quota(
    quota_features: list[Feature],
    observation: Observation,
    builder: _FeatureBuilder,
) -> Optional[Feature]:
    for feature in quota_features:
        if feature.family != observation.family:
            continue
        if feature.layer is not None and observation.layer is not None:
            if feature.layer != observation.layer:
                continue
        if feature.quota is None or feature.used_quota >= feature.quota:
            continue
        builder._attach(feature, observation)
        feature.used_quota += 1
        feature.note = (feature.note or "") + "；退场笼统描述并入入场旧痕配额"
        return feature
    return None


def _has_independent_exclusion(
    observation: Observation,
    exclusion_sources: dict[str, list[Observation]],
) -> bool:
    """独立复查排除：排除证据必须来自不同于原观察的报告登记号，
    且不能只是同一张照片的另一份转述。

    同一张照片的不同转述不算独立确认；背面/verso 复查或另一视角才算。
    成立路径：
    1. 复查报告的位点与待判定位点可兼容（或任一方未给定位但确为复查动作）；
    2. 待判定观察带光学备选（alternatives），且另一报告给出了 verso/装裱
       层面的投影/反光复查结论——照片缺参照无法比对位点时以此为准。
    """
    for sources in exclusion_sources.values():
        for source in sources:
            if source.report_id == observation.report_id:
                continue
            shared_photos = set(source.view_refs) & set(observation.view_refs)
            if shared_photos:
                # 同照片转述不是独立确认；只有来源照片完全不重叠才采信
                continue
            if not source.location.resolved or not observation.location.resolved:
                if source.review:
                    return True
                continue
            if locations_compatible(source.location, observation.location):
                return True
            # 位点无法解析（含照片缺参照、文字未给定位）但原观察已声明
            # 光学备选，且独立来源做了装裱/背面复查
            if (
                (not observation.location.resolved
                 or observation.location.frame == "unknown")
                and observation.alternatives and source.review
            ):
                return True
    return False


def _case_damage_confined(feature: Feature, observations: list[Observation]) -> bool:
    """外箱变化是否有“未达本体”的证据。"""
    for observation in observations:
        if observation.family == NEGATIVE_COVERAGE_FAMILY:
            continue
        if "未达" in observation.clause or "does not reach" in observation.clause.lower():
            return True
    return False


def _coverage_gaps(loan: Loan, views: dict[str, View]) -> list[CoverageGap]:
    gaps: list[CoverageGap] = []
    loan_views = [view for view in views.values() if view.loan == loan.id]
    covered_layers = {scope for view in loan_views for scope in view.scope}
    covered_layers_mapped = {
        MATERIAL_LAYERS.get(scope, scope) for scope in covered_layers
    }
    for material in loan.layers:
        layer = MATERIAL_LAYERS.get(material, material)
        if layer not in covered_layers_mapped:
            gaps.append(
                CoverageGap(
                    loan_id=loan.id,
                    layer=layer,
                    face=None,
                    description=f"现有照片视角未覆盖{_layer_name(layer)}层面，建议补拍",
                )
            )
    return gaps


def _layer_name(layer: str) -> str:
    return {LAYER_BODY: "作品本体", LAYER_MOUNT: "装裱", LAYER_CASE: "外箱"}.get(
        layer, layer
    )


def _feature_warnings(features: list[Feature]) -> list[str]:
    warnings: list[str] = []
    for feature in features:
        if feature.status == UNRESOLVED_LOCATED:
            warnings.append(
                f"{feature.id}: 照片缺方向参照，位点未解析，不能与旧痕硬配"
            )
        if feature.status == DISPUTED:
            warnings.append(f"{feature.id}: 存在未决分歧，需两馆下次签字确认")
    return warnings


def distinct_photo_sources(feature: Feature) -> set[str]:
    """特征实际依赖的照片号集合（同一照片的多份转述只算一个视角）。"""
    return set(feature.photos)
