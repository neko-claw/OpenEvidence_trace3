"""证据相关性过滤：强词/弱词白名单 + 排除词黑名单

规则：
- 标题命中 ≥1 强词 → 保留
- 标题命中 ≥2 弱词 → 保留
- 命中排除词（如 pulmonary hypertension / Fontan 等无关主题）→ 剔除
"""
from __future__ import annotations

# 强相关词：标题命中其一即保留（高血压/血脂核心术语）
STRONG = [
    "hypertension", "hypertensive", "antihypertensive", "blood pressure",
    "essential hypertension", "systolic", "diastolic",
    "ldl", "ldl-c", "cholesterol", "statin", "statins", "lipid", "lipids",
    "dyslipidemia", "dyslipidaemia", "triglyceride", "hypercholesterolemia",
    "hypercholesterolaemia", "hyperlipidemia", "pcsk9", "lipoprotein",
    "血压", "降压", "高血压", "血脂", "胆固醇", "他汀",
]

# 弱相关词：需命中 ≥2 个才保留（泛心血管词，单独出现不足以证明主题相关）
WEAK = [
    "cardiovascular", "coronary", "atherosclero", "atherogenic", "sodium",
    "diet", "dietary", "exercise", "dash", "salt", "obesity", "overweight",
    "heart failure", "stroke", "myocardial", "renal", "kidney", "vascular",
]

# 排除词：命中即剔除（无关主题，尤其肺动脉高压各变体）
EXCLUDE = [
    "pulmonary hypertension", "pulmonary arterial hypertension", "portopulmonary",
    "pulmonary veno-occlusive", "pulmonary embolism",
    "intracranial hypertension", "idiopathic intracranial", "portal hypertension",
    "ocular hypertension", "intraocular pressure",
    "meningococcal", "fontan", "combat sport", "methamphetamine",
    "anesthesia", "anaesthesia", "cataract", "glaucoma", "dental", "periodontal",
    "veterinary", "canine", "equine",
]


def is_relevant(title: str, text: str = "") -> tuple[bool, str]:
    """返回 (是否相关, 理由)"""
    hay = (title or "").lower()
    full = (title + " " + text[:500]).lower()

    for bad in EXCLUDE:
        if bad in full:
            return False, f"命中排除词: {bad}"

    strong_hits = [w for w in STRONG if w in hay]
    if strong_hits:
        return True, f"强词命中: {','.join(strong_hits[:3])}"
    weak_hits = [w for w in WEAK if w in hay]
    if len(weak_hits) >= 2:
        return True, f"弱词命中×{len(weak_hits)}: {','.join(weak_hits[:3])}"
    return False, f"无关键词命中 (强0 弱{len(weak_hits)})"
