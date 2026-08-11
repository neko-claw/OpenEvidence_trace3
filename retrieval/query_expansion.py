"""中文医学查询扩展：把中文问题里的医学术语映射为英文，解决中问英库检索鸿沟

用法： expand_query("高血压患者为什么需要长期服药")
    -> "高血压患者为什么需要长期服药 hypertension blood pressure ..."
原句保留 + 英文术语追加，BM25 与向量都能受益。
"""
from __future__ import annotations

MEDICAL_TERMS: dict[str, str] = {
    # 高血压
    "高血压": "hypertension hypertensive",
    "血压": "blood pressure",
    "降压": "antihypertensive blood pressure lowering",
    "收缩压": "systolic blood pressure",
    "舒张压": "diastolic blood pressure",
    "动态血压": "ambulatory blood pressure monitoring",
    "诊室血压": "office blood pressure",
    "家庭血压": "home blood pressure",
    "白大衣高血压": "white coat hypertension",
    "靶器官": "target organ damage",
    "左心室肥厚": "left ventricular hypertrophy",
    "老年高血压": "elderly hypertension older adults",
    "妊娠高血压": "gestational hypertension",
    "盐敏感性": "salt sensitivity",
    "限钠": "sodium restriction salt reduction",
    "盐": "salt sodium",
    "利尿剂": "diuretic thiazide",
    "钙通道阻滞剂": "calcium channel blocker",
    "血管紧张素": "angiotensin ACE inhibitor ARB RAAS",
    "醛固酮": "aldosterone",
    "依从性": "adherence compliance medication",
    "联合用药": "combination therapy fixed-dose combination",
    "难治性高血压": "resistant hypertension",
    "血压目标": "blood pressure target goal",
    "血压变异": "blood pressure variability",
    # 血脂
    "血脂": "lipid lipids dyslipidemia",
    "胆固醇": "cholesterol",
    "低密度脂蛋白": "LDL low-density lipoprotein cholesterol",
    "高密度脂蛋白": "HDL high-density lipoprotein",
    "甘油三酯": "triglyceride hypertriglyceridemia",
    "他汀": "statin HMG-CoA reductase inhibitor",
    "依折麦布": "ezetimibe",
    "贝特": "fibrate",
    "降脂": "lipid lowering",
    "非他汀": "non-statin lipid lowering",
    "脂蛋白": "lipoprotein Lp(a) lipoprotein(a)",
    "家族性高胆固醇血症": "familial hypercholesterolemia",
    "动脉粥样硬化": "atherosclerosis atherosclerotic",
    "代谢综合征": "metabolic syndrome",
    "饮食干预": "dietary intervention diet",
    "地中海饮食": "mediterranean diet",
    "运动": "exercise physical activity",
    "减重": "weight loss obesity",
    # 结局与背景
    "心血管": "cardiovascular",
    "冠心病": "coronary artery disease coronary heart disease",
    "卒中": "stroke",
    "心肌梗死": "myocardial infarction",
    "心力衰竭": "heart failure",
    "肾脏": "renal kidney chronic kidney disease",
    "糖尿病": "diabetes mellitus",
    "临床结局": "clinical outcomes mortality",
    "随机对照": "randomized controlled trial RCT",
    "指南": "guideline consensus",
    "系统综述": "systematic review meta-analysis",
    "队列": "cohort study",
    "证据": "evidence",
    "风险": "risk factor",
}


def expand_query(question: str) -> str:
    """返回 原句 + 命中的英文术语（去重、拼接）"""
    terms = []
    for zh, en in MEDICAL_TERMS.items():
        if zh in question and en not in terms:
            terms.append(en)
    return (question + " " + " ".join(terms)).strip()
