"""OpenEvidence MVP —— 第一部分：数据集采集与标准化。

包含：
- sources/      各数据源连接器（PubMed / ClinicalTrials.gov / Europe PMC）
- guidelines.py 人工确认的权威指南清单（高血压 + 血脂）
- normalize.py  Evidence 标准化、去重、证据等级、主题标签、content_hash
- build_db.py   SQLite 入库 + DatasetManifest + 统计报告
- run_all.py    一键执行完整采集流程
"""
