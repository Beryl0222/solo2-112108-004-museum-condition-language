"""双语文字报告解析器。

输出的每条观察都带原文小句与字符区间作为证据。解析只依据词表与规则，
不做跨材质的同义词硬等同；照片坐标位点交由 geometry 按照片参照换算，
参照缺失时保持未解析状态。

关键规则：
- 小句内显式照片号优先；没有显式号时才回退到报告 references。
- 多照片报告按小句归属：含显式号的小句用该号，无显式号的小句继承同报告
  单照片语境；无法确定时标记未解析，绝不猜测。
- 否定分为“现象不存在”（coverage_none）与“范围未达”（现象仍记录）。
- 光学现象（投影/反光）只生成一条独立观察，不再与主损伤重复留证。
- 报告级复查动作会传递给同报告的光学观察（“翻看了背面，…来自装裱投影”）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import lexicon
from .geometry import resolve_location
from .model import (
    CERT_CONFIRMED,
    CERT_NEGATED,
    CERT_REVIEW,
    CERT_UNCERTAIN,
    MATERIAL_LAYERS,
    Observation,
    ObjectLocation,
    Report,
    View,
)

NEGATIVE_COVERAGE_FAMILY = "coverage_none"
LAYER_MOUNT_DEFAULT = "mount"


@dataclass
class ParseResult:
    observations: list[Observation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def split_clauses(text: str, lang: str) -> list[tuple[str, int, int]]:
    """切分为小句，返回 (小句文本, 起始偏移, 结束偏移)。"""
    if lang == "zh":
        pieces = re.split(r"(。|；|，|,|;)", text)
        separators = "。；，,;"
    else:
        protected = text.replace("e.g.", "e__g__").replace("i.e.", "i__e__")
        # 句点/分号/逗号后若有空格则切分；行尾句点也切分
        pieces = re.split(r"(?<=[.;,;])(?:\s+|$)", protected)
        separators = ""
    clauses: list[tuple[str, int, int]] = []
    cursor = 0
    for piece in pieces:
        if piece is None or piece in separators:
            if piece in separators:
                cursor += len(piece)
            continue
        real = piece.replace("e__g__", "e.g.").replace("i__e__", "i.e.")
        index = text.find(real, cursor)
        if index < 0:
            continue
        end = index + len(real)
        stripped = real.strip().strip("。；;，,")
        if stripped:
            offset = index + (len(real) - len(real.lstrip()))
            clauses.append((stripped, offset, offset + len(stripped)))
        cursor = end
    return clauses


def _detect_layer(clause: str, lang: str) -> Optional[str]:
    for layer, pattern_zh, pattern_en in lexicon.LAYER_RES:
        pattern = pattern_zh if lang == "zh" else pattern_en
        if pattern.search(clause):
            return layer
    return None


def _detect_face(clause: str, lang: str) -> Optional[str]:
    for face, pattern_zh, pattern_en in lexicon.FACE_RES:
        pattern = pattern_zh if lang == "zh" else pattern_en
        if pattern.search(clause):
            return face
    return None


def _detect_certainty(clause: str, lang: str) -> tuple[str, list[str]]:
    phrases: list[str] = []
    level = CERT_CONFIRMED
    priority = {CERT_REVIEW: 3, CERT_NEGATED: 2, CERT_UNCERTAIN: 1, CERT_CONFIRMED: 0}
    for candidate, pattern_zh, pattern_en in lexicon.CERTAINTY_RES:
        pattern = pattern_zh if lang == "zh" else pattern_en
        match = pattern.search(clause)
        if match:
            phrases.append(match.group(0))
            if priority[candidate] > priority[level]:
                level = candidate
    return level, phrases


def _detect_temporal(clause: str, lang: str) -> tuple[Optional[str], list[str]]:
    phrases: list[str] = []
    found: Optional[str] = None
    for temporal, pattern_zh, pattern_en in lexicon.TEMPORAL_RES:
        pattern = pattern_zh if lang == "zh" else pattern_en
        match = pattern.search(clause)
        if match:
            phrases.append(match.group(0))
            found = temporal
    return found, phrases


def _detect_count(clause: str, lang: str) -> Optional[int]:
    match = lexicon.COUNT_RE.search(clause)
    if not match:
        return None
    if match.group("num"):
        return int(match.group("num"))
    zh = match.group("zh")
    if zh:
        return lexicon.COUNT_ZH.get(zh, 1)
    en = match.group("en")
    if en:
        return lexicon.COUNT_EN_WORDS.get(en.lower(), 1)
    return None


def _find_locations(clause: str, lang: str) -> list[ObjectLocation]:
    """找出小句内全部部位描述，先照片坐标后物件坐标，先复合角点后单维。"""
    found: list[ObjectLocation] = []
    claimed: list[tuple[int, int]] = []

    def take(pattern: re.Pattern, frame: str, side, vertical, margin):
        for match in pattern.finditer(clause):
            if any(not (match.end() <= start or match.start() >= end)
                   for start, end in claimed):
                continue
            claimed.append((match.start(), match.end()))
            found.append(ObjectLocation(
                frame=frame, side=side, vertical=vertical,
                margin=margin, raw=match.group(0),
            ))

    for side, vertical, zh_pattern, en_pattern in lexicon.PHOTO_LOCATION_PATTERNS:
        pattern = re.compile(zh_pattern if lang == "zh" else en_pattern, re.IGNORECASE)
        take(pattern, "photo", side, vertical, margin=True)
    if lang == "en":
        for match in lexicon.ENGLISH_BARE_MARGIN.finditer(clause):
            if any(not (match.end() <= start or match.start() >= end)
                   for start, end in claimed):
                continue
            claimed.append((match.start(), match.end()))
            word = match.group(1).lower()
            side = word if word in ("left", "right") else None
            vertical = word if word in ("top", "bottom") else None
            found.append(ObjectLocation(
                frame="photo", side=side, vertical=vertical,
                margin=True, raw=match.group(0),
            ))
    for side, vertical, margin, zh_pattern, en_pattern in lexicon.OBJECT_LOCATION_PATTERNS:
        pattern = re.compile(zh_pattern if lang == "zh" else en_pattern, re.IGNORECASE)
        take(pattern, "object", side, vertical, margin)
    found.sort(key=lambda item: clause.find(item.raw or ""))
    return found


def _clause_view_refs(
    clause: str, report: Report, views: dict[str, View]
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    explicit = lexicon.VIEW_ID_RE.findall(clause)
    refs = [ref for ref in explicit if ref in views]
    for ref in explicit:
        if ref not in views:
            warnings.append(f"{report.id}: 小句提到不存在的照片号 {ref}")
    if refs:
        return refs, warnings
    # 无显式号：报告只引用一张照片时可继承；多张则不猜测
    report_refs = [ref for ref in report.references if ref in views]
    if len(report_refs) == 1:
        return report_refs, warnings
    return report_refs, warnings  # 多张时调用方按 unresolved 处理


def _layer_from_views(refs: list[str], views: dict[str, View]) -> Optional[str]:
    layers = set()
    for ref in refs:
        view = views[ref]
        for scope in view.scope:
            layers.add(MATERIAL_LAYERS.get(scope, scope))
    if len(layers) == 1:
        return next(iter(layers))
    return None


def _is_generic_rim(location: ObjectLocation) -> bool:
    """只有“边缘/rim/margin”而无左右上下主张：属于笼统位点，走配额。"""
    return (
        location.margin
        and location.side is None
        and location.vertical is None
        and location.frame != "unknown"
    )


def _positioned(location: ObjectLocation) -> bool:
    if location.frame == "unknown":
        return False
    if _is_generic_rim(location):
        return False
    return True


def _resolve_with_views(
    location: ObjectLocation, refs: list[str], views: dict[str, View]
) -> ObjectLocation:
    if location.frame != "photo" or not refs or len(refs) != 1:
        if location.frame == "photo" and len(refs) != 1:
            return ObjectLocation(**{**location.__dict__, "resolved": False})
        return location
    return resolve_location(location, views[refs[0]])


def _make_observation(
    report: Report, clause: str, span: tuple[int, int], layer: Optional[str],
    family: str, certainty: str, location: ObjectLocation, count: Optional[int],
    view_refs: list[str], evidence: list[str], alternatives: list[str],
    temporal: Optional[str], review: bool, note: Optional[str],
) -> Observation:
    return Observation(
        report_id=report.id, loan_id=report.loan, phase=report.phase,
        lang=report.lang, clause=clause, span=span, layer=layer, family=family,
        certainty=certainty, location=location, count=count,
        view_refs=list(view_refs), evidence_phrases=evidence,
        alternatives=alternatives, temporal=temporal, review=review, note=note,
    )


def parse_reports(
    reports: list[Report], views: dict[str, View],
    body_materials: dict[str, Optional[str]],
) -> ParseResult:
    """解析整批报告；同 id 高 revision 覆盖低 revision。"""
    latest: dict[str, Report] = {}
    for report in reports:
        previous = latest.get(report.id)
        if previous is None or report.revision >= previous.revision:
            latest[report.id] = report

    combined = ParseResult()
    for report in sorted(latest.values(), key=lambda item: (item.loan, item.phase, item.id)):
        parsed = _parse_with_material(report, views, body_materials.get(report.loan))
        combined.observations.extend(parsed.observations)
        combined.warnings.extend(parsed.warnings)
    return combined


def parse_report(
    report: Report, views: dict[str, View], material: Optional[str] = None
) -> ParseResult:
    return _parse_with_material(report, views, material)


def _parse_with_material(
    report: Report, views: dict[str, View], material: Optional[str]
) -> ParseResult:
    result = ParseResult()
    clauses = split_clauses(report.text, report.lang)
    # 报告级复查：任何小句出现复查动作，整份报告的光学/排除观察都标 review
    report_review = any(
        _detect_certainty(clause, report.lang)[0] == CERT_REVIEW
        for clause, _, _ in clauses
    )
    continuation_notes: list[str] = []
    # 报告级光学备选词（如“could be a mount shadow”）及各自所在小句的照片
    # 语境：同报告的损伤观察只在共享照片语境时携带该备选，
    # 供复查排除链使用。先做全文预扫描，避免备选词出现在损伤小句之后时
    # 传播不到。
    optical_term_refs: dict[str, set[str]] = {}
    for pre_clause, _, _ in clauses:
        pre_layer = _detect_layer(pre_clause, report.lang)
        pre_refs, _ = _clause_view_refs(pre_clause, report, views)
        for hit in lexicon.find_family(pre_clause, report.lang, pre_layer, material):
            if not hit.rule.is_damage:
                optical_term_refs.setdefault(hit.term, set()).update(pre_refs)

    for clause, start, end in clauses:
        span = (start, end)
        certainty, certainty_phrases = _detect_certainty(clause, report.lang)
        temporal, temporal_phrases = _detect_temporal(clause, report.lang)
        face = _detect_face(clause, report.lang)
        explicit_layer = _detect_layer(clause, report.lang)
        refs, ref_warnings = _clause_view_refs(clause, report, views)
        result.warnings.extend(ref_warnings)
        view_layer = _layer_from_views(refs, views)
        layer = explicit_layer or view_layer
        locations = _find_locations(clause, report.lang)
        if face:
            locations = [
                ObjectLocation(**{**location.__dict__, "face": face})
                for location in locations
            ]
        count = _detect_count(clause, report.lang)
        confinement = lexicon.CONFINEMENT_RE.search(clause)
        hits = lexicon.find_family(clause, report.lang, layer, material)
        # 否定覆盖陈述（“No new marks...”）中的通用词不构成具体损伤家族，
        # 仅在确无任何严格命中时才放宽材质重检；重检命中只用于判断是否为
        # “对具体家族的否定”，不重新加入损伤集合
        relaxed_hits: list = []
        if not hits and certainty == CERT_NEGATED and not confinement:
            relaxed_hits = lexicon.find_family(clause, report.lang, layer, None)
        evidence = certainty_phrases + temporal_phrases
        clause_review = report_review or certainty == CERT_REVIEW
        optical = [hit for hit in hits if not hit.rule.is_damage]
        damage_hits = [hit for hit in hits if hit.rule.is_damage]
        strict_damage = bool(damage_hits)
        generic_only = bool(damage_hits) and all(
            hit.rule.generic for hit in damage_hits
        )
        # 否定句中的损伤词只表达“未见该现象”，不构成损伤观察；
        # 但“未达本体”一类范围否定不擦除现象本身
        if certainty == CERT_NEGATED and not confinement:
            damage_hits = []
        had_damage_word = strict_damage or any(
            hit.rule.is_damage for hit in relaxed_hits
        )
        if not damage_hits and not optical:
            # 否定覆盖：严格无命中，或只命中 marks/spots 一类通用词
            is_coverage_negation = (
                certainty == CERT_NEGATED
                and not confinement
                and (not strict_damage or generic_only)
            )
            if is_coverage_negation:
                location = locations[0] if locations else ObjectLocation(
                    frame="unknown", face=face,
                )
                result.observations.append(_make_observation(
                    report, clause, span, layer, NEGATIVE_COVERAGE_FAMILY,
                    CERT_NEGATED, _resolve_with_views(location, refs, views),
                    count, refs, evidence, [], temporal, clause_review,
                    "未见新增的覆盖性陈述",
                ))
            elif clause_review or len(clause) <= 60 or had_damage_word:
                # 复查附言、补充从句（如旋转照片中的同痕转述）或
                # “position not certain”一类说明，不单独成观察，
                # 留待并入同报告其他证据
                continuation_notes.append(clause)
            else:
                result.warnings.append(
                    f"{report.id}: 小句未识别出状态家族：{clause}"
                )
            continue

        # 范围未达（“does not reach artwork/未达本体”）：现象本身仍需记录
        effective_certainty = certainty
        if confinement:
            effective_certainty = (
                CERT_CONFIRMED if certainty == CERT_NEGATED else certainty
            )

        alternative_terms = [hit.term for hit in optical]

        # 纯光学陈述：只生成一条光学观察
        if not damage_hits:
            layer = layer or LAYER_MOUNT_DEFAULT
            location = locations[0] if locations else ObjectLocation(
                frame="unknown", face=face,
            )
            resolved = _resolve_with_views(location, refs, views)
            optical_certainty = (
                CERT_CONFIRMED if clause_review else CERT_UNCERTAIN
            )
            result.observations.append(_make_observation(
                report, clause, span, LAYER_MOUNT_DEFAULT,
                optical[0].rule.family, optical_certainty, resolved, 1, refs,
                evidence + [optical[0].term], [], temporal, clause_review,
                "装裱投影/反光观察（复查结论）" if clause_review
                else "光学现象备选证据",
            ))
            continue

        # 否定且无位点的损伤陈述（如“非起翘”）：不作为独立损伤，并入证据备注
        if effective_certainty == CERT_NEGATED and not _positioned(
            locations[0] if locations else ObjectLocation(frame="unknown")
        ):
            continuation_notes.append(clause)
            continue

        primary = damage_hits[0]
        split_locations = locations or [ObjectLocation(frame="unknown", face=face)]
        # 光学备选只对疑似/未确定的损伤观察挂接：已确认的旧痕或明确损伤
        # 不携带其他部位的投影/反光备选，避免污染旧痕证据
        shared_refs = set(refs)
        if effective_certainty == CERT_UNCERTAIN:
            all_alternatives = list(alternative_terms)
            for term, term_refs in optical_term_refs.items():
                if term in all_alternatives:
                    continue
                if shared_refs and term_refs & shared_refs:
                    all_alternatives.append(term)
        else:
            all_alternatives = list(alternative_terms)
        for index, location in enumerate(split_locations):
            resolved = _resolve_with_views(location, refs, views)
            note = None
            if len(split_locations) > 1:
                note = (
                    f"由一条多部位记录按证据拆出，第 {index + 1}/"
                    f"{len(split_locations)} 处"
                )
            if continuation_notes:
                note = (note + "；" if note else "") + (
                    "同报告复查附言：" + " / ".join(continuation_notes)
                )
            result.observations.append(_make_observation(
                report, clause, span, layer, primary.rule.family,
                effective_certainty, resolved,
                count if len(split_locations) == 1 else 1,
                refs, evidence + [primary.term], all_alternatives,
                temporal, clause_review, note,
            ))

        # 光学备选只在确有光学词且本句不是复查结论时留一条独立证据
        if optical and not clause_review:
            location = locations[0] if locations else ObjectLocation(
                frame="unknown", face=face,
            )
            result.observations.append(_make_observation(
                report, clause, span, LAYER_MOUNT_DEFAULT,
                optical[0].rule.family, CERT_UNCERTAIN,
                _resolve_with_views(location, refs, views),
                1, refs, evidence + [optical[0].term], [], temporal, False,
                "光学现象备选证据",
            ))
    return result
