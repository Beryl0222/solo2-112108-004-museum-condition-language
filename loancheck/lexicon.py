"""双语词表与同义术语映射。

关键约束：同义术语只在特定材质/层面下对应（例如 line 在纸本/织物本体语境
归入折痕家族，在装裱投影语境不是损伤）。词表全部显式声明适用范围，
解析器按材质过滤，不做跨材质的硬等同。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# --- 层面词 ---------------------------------------------------------------

# 顺序即优先级：先具体后笼统
LAYER_PATTERNS = [
    # (层面, 中文正则, 英文正则)
    ("case", r"外箱|箱体|箱面|箱", r"\bcase\b|\bcrate\b|\bbox\b"),
    ("mount", r"装裱|装框|裱框|画框|镜框|框边|框|裱",
     r"\bmount(?:ing|ed)?\b|\bframe[ds]?\b|\bmat\b"),
    ("body", r"本体|画作|织物|画心|纸本|纸面|画面",
     r"\bartwork\b|\btextile\b|\bpainting\b|\bpaper\b|\bsupport\b"),
]

FACE_PATTERNS = [
    ("verso", r"背面|反面|背", r"\bverso\b|\breverse\b|\bon the back\b"),
    ("recto", r"正面", r"\brecto\b|\bfront\b"),
]

# --- 状态家族 -------------------------------------------------------------

@dataclass(frozen=True)
class FamilyRule:
    family: str
    zh_terms: tuple[str, ...]
    en_patterns: tuple[str, ...]
    layers: tuple[str, ...]          # 允许出现的层面
    materials: tuple[str, ...] = ()  # 空 = 不限制具体材质
    is_damage: bool = True
    generic: bool = False            # 通用状况词（marks/spots），否定句按覆盖处理
    note: str = ""


# 顺序敏感：先匹配更具体的家族（raised line 先按起翘处理）
FAMILY_RULES: list[FamilyRule] = [
    FamilyRule(
        family="lift",
        zh_terms=("起翘", "翘起", "翘边", "翘"),
        en_patterns=(r"\brais(?:ed|ing)\b", r"\blifts?\b", r"\blifting\b", r"\braise[sd]?\b"),
        layers=("body", "mount"),
        materials=("paper", "cloth", "mount"),
        note="起翘可发生在本体或装裱，层面由部位词决定",
    ),
    FamilyRule(
        family="fold",
        zh_terms=("折痕", "折线", "浅折", "旧痕", "痕迹", "折"),
        en_patterns=(r"\bcreases?\b", r"\bfolds?\b", r"\bfaint line\b", r"\blines?\b"),
        layers=("body",),
        materials=("paper", "cloth"),
        note="line 仅在纸本/织物本体语境与 crease/fold 同义",
    ),
    FamilyRule(
        family="scratch",
        zh_terms=("划痕", "划伤", "刮痕"),
        en_patterns=(r"\bscratch(?:es|ed)?\b", r"\bscrape[sd]?\b"),
        layers=("body", "case"),
        materials=("paper", "cloth", "crate"),
    ),
    FamilyRule(
        family="stain",
        zh_terms=("灰斑", "污斑", "斑点", "污渍", "斑"),
        en_patterns=(r"\bdiscoloration\b", r"\bstains?\b", r"\bspots?\b",
                     r"\bmarks?\b"),
        layers=("body", "mount"),
        materials=("paper", "cloth", "mount"),
        generic=True,
        note="marks/spots 为通用状况词，否定句中按覆盖陈述处理",
    ),
    FamilyRule(
        family="tear",
        zh_terms=("撕裂", "裂口", "破裂", "裂"),
        en_patterns=(r"\btears?\b", r"\btorn\b", r"\brips?\b"),
        layers=("body",),
        materials=("paper", "cloth"),
    ),
    # 光学现象不是损伤家族，单独成类，供“复查排除”使用
    FamilyRule(
        family="shadow",
        zh_terms=("投影", "阴影", "影"),
        en_patterns=(r"\bshadows?\b",),
        layers=("mount", "body"),
        materials=("paper", "cloth", "mount"),
        is_damage=False,
        note="装裱投影属光学现象，不得记为新增损伤",
    ),
    FamilyRule(
        family="reflection",
        zh_terms=("反光",),
        en_patterns=(r"\breflections?\b", r"\bglare\b"),
        layers=("mount", "body"),
        materials=("paper", "cloth", "mount"),
        is_damage=False,
    ),
]

# --- 肯定程度与时间性 ------------------------------------------------------

CERTAINTY_RULES = [
    # (级别, 中文正则, 英文正则)
    ("review", r"复查|复核|翻看|反向看|经核对|确认排除|排除了|经检查|检查了",
     r"\bruled? out\b|\bre-?examined\b|\breview(?:ed)?\b|\bchecked\b|\bconfirmed\b"),
    ("negated", r"未见|没有|无|非|不是|未达|不涉及",
     r"\bno new\b|\bnot a\b|\bwithout\b"),
    ("uncertain", r"看似|看着像|看起来|疑似|不能排除|可能|或许|不确定|无法确定|未能确定|位置不明确|存疑|not certain",
     r"\blooks?\b|\bseems?\b|\bappears?\b|\bcould be\b|\bmay be\b|\bmight\b|\bpossibly\b|\bperhaps\b|"
     r"\bnot certain\b|\buncertain\b|\bcannot rule out\b|\bdiscernible\b"),
]

# “未达本体/does not reach”否定的是波及范围，不是现象本身，单独识别
CONFINEMENT_RE = re.compile(r"未达|不涉及|does not reach|doesn't reach", re.IGNORECASE)

TEMPORAL_RULES = [
    ("old", r"旧|原有|原来就有|较早|原先|素来",
     r"\bold\b|\bpre-?existing\b|\bremains?\b|\bremained\b|\bearlier\b"),
    ("new", r"新增|新起|新出现|又起|又一|新",
     r"\bnew\b|\bsecond\b|\badditional\b|\banother\b"),
]

# --- 部位与朝向 -----------------------------------------------------------

# 物件自身坐标
OBJECT_LOCATION_PATTERNS = [
    # (side, vertical, 是否边沿, 中文, 英文)
    ("left", "top", True, r"左上(?:角|部|外沿|沿)?", r"\bupper[- ]left\b|\btop[- ]left\b"),
    ("right", "top", True, r"右上(?:角|部|外沿|沿)?", r"\bupper[- ]right\b|\btop[- ]right\b"),
    ("left", "bottom", True, r"左下(?:角|部|外沿|沿)?", r"\blower[- ]left\b|\bbottom[- ]left\b"),
    ("right", "bottom", True, r"右下(?:角|部|外沿|沿)?", r"\blower[- ]right\b|\bbottom[- ]right\b"),
    # 注意：英文裸写的 right/left margin 归照片坐标（见 ENGLISH_BARE_MARGIN），
    # 物件坐标只接受 edge/rim/border 或带 object/artwork 限定的 margin
    ("left", None, True, r"左缘|左边沿|左沿",
     r"\bleft (?:edge|rim|border)\b|\bobject left margin\b|\bartwork left margin\b"),
    ("right", None, True, r"右缘|右边沿|右沿",
     r"\bright (?:edge|rim|border)\b|\bobject right margin\b|\bartwork right margin\b"),
    (None, "top", True, r"上缘|上边沿|上沿",
     r"\bupper edge\b|\btop edge\b|\bobject top margin\b"),
    (None, "bottom", True, r"下缘|下边沿|下沿",
     r"\blower edge\b|\bbottom edge\b|\bobject bottom margin\b"),
    ("left", None, False, r"左边|左侧|左部", r"\bon the left\b|\bleft side\b"),
    ("right", None, False, r"右边|右侧|右部", r"\bon the right\b|\bright side\b"),
    (None, "top", False, r"上边|上方|上部", r"\bupper (?:part|area)\b|\btop area\b"),
    (None, "bottom", False, r"下边|下方|下部", r"\blower (?:part|area)\b|\bbottom area\b"),
    # 物件坐标的通用 margin 仅在带 object/artwork 限定词时成立
    (None, None, True, r"外沿|边缘|边沿|沿",
     r"\b(?:rim|edge|border)\b|\b(?:object|artwork) margin\b"),
]

# 照片坐标（带 photo/image/照片/图 限定，或英文表格裸写的 right margin）
PHOTO_LOCATION_PATTERNS = [
    ("left", "top", r"照片左上|图左上|相片左上", r"\bphoto(?:graph)? upper[- ]left\b|\bimage upper[- ]left\b"),
    ("right", "top", r"照片右上|图右上", r"\bphoto(?:graph)? upper[- ]right\b"),
    ("left", "bottom", r"照片左下|图左下", r"\bphoto(?:graph)? lower[- ]left\b"),
    ("right", "bottom", r"照片右下|图右下", r"\bphoto(?:graph)? lower[- ]right\b"),
    ("left", None, r"照片左(?:边|侧|缘)?|图左|照相左", r"\bphoto(?:graph)? left\b|\bimage left\b|\bleft of (?:the )?(?:photo|image|view)\b"),
    ("right", None, r"照片右(?:边|侧|缘)?|图右|照相右", r"\bphoto(?:graph)? right\b|\bimage right\b|\bright of (?:the )?(?:photo|image|view)\b"),
    (None, "top", r"照片上(?:边|侧|缘)?|图上", r"\bphoto(?:graph)? top\b|\bimage top\b"),
    (None, "bottom", r"照片下(?:边|侧|缘)?|图下", r"\bphoto(?:graph)? bottom\b|\bimage bottom\b"),
]

# 英文表格裸写 right margin 等：按业务约定视为照片坐标，不得直接当作画作右缘
ENGLISH_BARE_MARGIN = re.compile(r"\b(right|left|top|bottom) margin\b", re.IGNORECASE)

VIEW_ID_RE = re.compile(r"\bV\d+\b")
COUNT_ZH = {"两": 2, "三": 3, "四": 4, "一": 1}
COUNT_EN_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4}
COUNT_RE = re.compile(
    r"(?P<zh>两|三|四|一)?\s*处"
    r"|(?P<num>\d+)\s*(?:处|lifts?|marks?|lines?|creases?)"
    r"|\b(?P<en>one|two|three|four)\b\s+(?:minor\s+)?(?:lifts?|marks?|lines?|creases?|spots?)",
    re.IGNORECASE,
)


def _bilingual(table: list[tuple]) -> list[tuple]:
    """双语规则表：每行除末尾两个正则外其余字段原样保留，中英正则分别编译。"""
    result = []
    for item in table:
        head, pattern_zh, pattern_en = item[:-2], item[-2], item[-1]
        result.append((
            *head,
            re.compile(pattern_zh, re.IGNORECASE),
            re.compile(pattern_en, re.IGNORECASE),
        ))
    return result


LAYER_RES = _bilingual(LAYER_PATTERNS)
FACE_RES = _bilingual(FACE_PATTERNS)
CERTAINTY_RES = _bilingual(CERTAINTY_RULES)
TEMPORAL_RES = _bilingual(TEMPORAL_RULES)


def _family_term_match(rule: FamilyRule, lang: str, clause: str) -> Optional[tuple[str, int, int]]:
    """返回命中的原文片段及其字符区间；无命中返回 None。"""
    if lang == "zh":
        for term in sorted(rule.zh_terms, key=len, reverse=True):
            index = clause.find(term)
            if index >= 0:
                return term, index, index + len(term)
        return None
    for pattern in rule.en_patterns:
        match = re.search(pattern, clause, re.IGNORECASE)
        if match:
            return match.group(0), match.start(), match.end()
    return None


def find_family(clause: str, lang: str, layer: str | None, material: str | None) -> list[FamilyHit]:
    """在材质/层面约束下找出小句中全部命中的状态家族。

    同一句话可能同时出现损伤词与光学词（“看着像起翘，不能排除反光”），
    因此返回列表，由解析器按肯定程度区分主陈述与备选假设。
    """
    hits: list[FamilyHit] = []
    for rule in FAMILY_RULES:
        hit = _family_term_match(rule, lang, clause)
        if hit is None:
            continue
        if layer is not None and rule.layers and layer not in rule.layers:
            continue
        if material and rule.materials and material not in rule.materials:
            continue
        term, start, end = hit
        hits.append(FamilyHit(rule=rule, term=term, span=(start, end)))
    return hits


@dataclass(frozen=True)
class FamilyHit:
    rule: FamilyRule
    term: str
    span: tuple[int, int]
