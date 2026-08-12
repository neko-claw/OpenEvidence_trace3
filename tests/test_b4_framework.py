import json
import unittest
from pathlib import Path

from evaluation.adapters.fixture_retriever import FixtureRetriever
from evaluation.adapters.hybrid_retriever import HybridReferenceRetriever
from evaluation.adapters.reference_retriever import ReferenceRetriever
from evaluation.runner import run_condition


ROOT = Path(__file__).resolve().parents[1]


class B4FrameworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retriever = FixtureRetriever(
            ROOT / "data/fixtures/evidence.jsonl",
            ROOT / "data/fixtures/qrels.jsonl",
        )
        cls.questions = [
            json.loads(line)
            for line in (ROOT / "data/fixtures/questions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_fixture_retrieval_has_trace(self):
        question = next(q for q in self.questions if q["id"] == "dev-001")
        result = self.retriever.search(question)
        self.assertTrue(result.bm25_candidates)
        self.assertTrue(result.rrf_candidates)
        self.assertTrue(result.final_evidence)
        self.assertTrue(all("evidence_id" in item for item in result.final_evidence))

    def test_c_and_d_run(self):
        question = next(q for q in self.questions if q["id"] == "dev-003")
        for condition in ("C", "D"):
            run, trace = run_condition(question, condition, self.retriever)
            self.assertEqual(run.status, "success")
            self.assertEqual(run.condition, condition)
            self.assertTrue(run.answer)
            self.assertIsNotNone(trace["retrieval"])

    def test_d_uses_full_system_adapter_contract(self):
        from evaluation.adapters.full_system import MockFullSystem

        question = next(q for q in self.questions if q["id"] == "dev-001")
        calls = []

        class RecordingAdapter(MockFullSystem):
            def run(self, question, config):
                calls.append((question["id"], len(config["evidence"])))
                return super().run(question, config)

        run, _ = run_condition(
            question, "D", self.retriever,
            config={"full_system_adapter": RecordingAdapter()},
        )
        self.assertEqual(run.status, "success")
        self.assertEqual(run.condition, "D")
        self.assertEqual(calls[0][0], "dev-001")
        self.assertTrue(run.agent_plan)
        self.assertTrue(run.tool_trace)
        self.assertIn("mock-system", run.system_version)

    def test_d_preserves_adapter_diagnostics(self):
        from evaluation.adapters.full_system import FullSystemResult

        question = next(q for q in self.questions if q["id"] == "dev-001")

        class TraceAdapter:
            def run(self, question, config):
                return FullSystemResult(
                    question_id=question["id"],
                    system_version="custom-system-v1",
                    agent_plan={"source": "adapter"},
                    tool_trace=[{"tool": "custom_tool", "status": "ok"}],
                    retrieved_evidence=config["evidence"],
                    answer="adapter answer",
                    claims=[],
                    citations=[],
                )

        run, _ = run_condition(
            question, "D", self.retriever,
            config={"full_system_adapter": TraceAdapter()},
        )
        self.assertEqual(run.system_version, "custom-system-v1")
        self.assertEqual(run.agent_plan, {"source": "adapter"})
        self.assertEqual(run.tool_trace, [{"tool": "custom_tool", "status": "ok"}])

    def test_d_records_adapter_overhead_separately(self):
        from evaluation.adapters.full_system import FullSystemResult

        question = next(q for q in self.questions if q["id"] == "dev-001")

        class CostedAdapter:
            def run(self, question, config):
                return FullSystemResult(
                    question_id=question["id"],
                    system_version="costed-system-v1",
                    retrieved_evidence=config["evidence"],
                    answer="answer",
                    claims=[],
                    citations=[],
                    latency_ms=17,
                    input_tokens=11,
                    output_tokens=13,
                    estimated_cost=0.004,
                )

        run, _ = run_condition(
            question, "D", self.retriever,
            config={"full_system_adapter": CostedAdapter()},
        )
        self.assertEqual(run.d_extra_latency_ms, 17)
        self.assertEqual(run.d_extra_input_tokens, 11)
        self.assertEqual(run.d_extra_output_tokens, 13)
        self.assertEqual(run.d_extra_estimated_cost, 0.004)

    def test_a_and_b_run(self):
        question = next(q for q in self.questions if q["id"] == "dev-001")
        run_a, trace_a = run_condition(question, "A", self.retriever)
        self.assertEqual(run_a.status, "success")
        self.assertEqual(run_a.retrieved_evidence, [])
        self.assertIsNone(trace_a["retrieval"])
        run_b, trace_b = run_condition(question, "B", self.retriever)
        self.assertEqual(run_b.status, "success")
        self.assertTrue(run_b.retrieved_evidence)
        self.assertIsNotNone(trace_b["retrieval"])

    def test_e_removes_a_gold_evidence(self):
        question = next(q for q in self.questions if q["id"] == "stress-001")
        run, trace = run_condition(question, "E", self.retriever)
        self.assertEqual(run.status, "success")
        self.assertTrue(run.stress_manifest["removed_evidence_ids"])
        self.assertNotIn(
            run.stress_manifest["removed_evidence_ids"][0],
            run.stress_manifest["perturbed_candidate_ids"],
        )
        self.assertIsNotNone(trace["stress"])

    def test_reference_retriever_indexes_full_evidence_snapshot(self):
        retriever = ReferenceRetriever(ROOT / "data/processed/evidence.jsonl")
        question = next(q for q in self.questions if q["id"] == "dev-002")
        result = retriever.search(question)
        self.assertGreater(result.index_stats["document_count"], 10000)
        self.assertTrue(result.bm25_candidates)
        self.assertEqual(result.vector_candidates, [])

    def test_reference_rerank_records_explainable_features(self):
        retriever = ReferenceRetriever(ROOT / "data/processed/evidence.jsonl", rerank=True)
        question = next(q for q in self.questions if q["id"] == "dev-001")
        result = retriever.search(question, {"initial_k": 50, "final_k": 4})
        self.assertTrue(result.rerank_candidates)
        self.assertTrue(result.final_evidence)
        self.assertTrue(all("rerank_score" in item for item in result.rerank_candidates))
        self.assertTrue(all("title_overlap" in item for item in result.rerank_candidates))
        self.assertTrue(all(item["retrieval_stage"] == "feature_rerank" for item in result.rerank_candidates))

    def test_hybrid_fallback_records_bm25_vector_rrf_trace(self):
        retriever = HybridReferenceRetriever(
            ROOT / "data/fixtures/evidence.jsonl",
            config_path=ROOT / "config.yaml",
            embedding_backend="fallback",
            use_rerank=True,
            final_k=4,
        )
        question = next(q for q in self.questions if q["id"] == "dev-003")
        result = retriever.search(question, {"final_k": 4})
        self.assertTrue(result.bm25_candidates)
        self.assertTrue(result.vector_candidates)
        self.assertTrue(result.rrf_candidates)
        self.assertTrue(result.rerank_candidates)
        self.assertEqual(result.index_stats["embedding_backend"], "fallback")

    # ---- B4 Review：E 预注册规则集与 Run 契约 ----------------

    def test_run_record_carries_experiment_contract_fields(self):
        question = next(q for q in self.questions if q["id"] == "dev-001")
        run, _ = run_condition(
            question, "C", self.retriever,
            config={"seed": 7, "replicate": 2, "model": "mock-model",
                    "model_snapshot": "mock-model@v0.1",
                    "provider_fingerprint": "offline/mock",
                    "code_commit": "abc1234"},
        )
        self.assertEqual(run.seed, 7)
        self.assertEqual(run.replicate, 2)
        self.assertEqual(run.model, "mock-model")
        self.assertEqual(run.model_snapshot, "mock-model@v0.1")
        self.assertEqual(run.provider_fingerprint, "offline/mock")
        self.assertEqual(run.code_commit, "abc1234")
        self.assertEqual(run.verification_decision, "PASS")

    def test_e_drop_all_gold_removes_every_gold(self):
        question = next(q for q in self.questions if q["id"] == "stress-001")
        run, trace = run_condition(question, "E", self.retriever,
                                   config={"seed": 0, "final_k": 4})
        self.assertEqual(run.status, "success")
        manifest = run.stress_manifest
        self.assertEqual(manifest["stress_rule"], "drop_all_gold_v1")
        self.assertEqual(
            sorted(manifest["removed_evidence_ids"]),
            sorted(question["gold_source_ids"]),
        )
        # 劣化后的上下文必须对生成可见：不再包含任何 gold
        self.assertFalse(
            {item["evidence_id"] for item in run.retrieved_evidence}
            & set(question["gold_source_ids"])
        )
        self.assertIsNotNone(trace["stress"])

    def test_e_falls_back_to_topk_reduced_when_no_gold(self):
        """gold 不在候选集（如范围外题）时回退 topk_reduced，仍生成回答，C/E 配对不丢。"""
        question = next(q for q in self.questions if q["id"] == "stress-003")
        run, trace = run_condition(question, "E", self.retriever,
                                   config={"seed": 0, "final_k": 4})
        self.assertEqual(run.status, "success")
        manifest = run.stress_manifest
        self.assertEqual(manifest["stress_rule"], "topk_reduced")
        self.assertIn("fallback", manifest["reason"])
        self.assertIsNotNone(run.answer)
        self.assertIsNotNone(trace["stress"])

    def test_e_topk_reduced_excludes_gold_and_truncates(self):
        from evaluation.stress import apply_stress, TOPK_REDUCED_K2

        question = next(q for q in self.questions if q["id"] == "stress-001")
        result = self.retriever.search(question)
        perturbed, manifest = apply_stress(
            result.rrf_candidates, question,
            rule="topk_reduced", seed=0, final_k=4,
        )
        manifest = manifest.to_dict()
        self.assertEqual(len(perturbed), TOPK_REDUCED_K2)
        self.assertFalse(
            {c["evidence_id"] for c in perturbed} & set(question["gold_source_ids"])
        )
        self.assertEqual(manifest["stress_rule"], "topk_reduced")

    def test_e_inject_unsupporting_is_deterministic_and_injects_non_gold(self):
        from evaluation.stress import apply_stress

        question = next(q for q in self.questions if q["id"] == "stress-001")
        result = self.retriever.search(question)
        perturbed, manifest = apply_stress(
            result.rrf_candidates, question,
            rule="inject_unsupporting_v1", seed=0, final_k=4,
        )
        manifest = manifest.to_dict()
        self.assertTrue(manifest["injected_evidence_ids"])
        self.assertFalse(
            set(manifest["injected_evidence_ids"]) & set(question["gold_source_ids"])
        )
        # 同一 seed 可复现同一注入
        perturbed2, manifest2 = apply_stress(
            result.rrf_candidates, question,
            rule="inject_unsupporting_v1", seed=0, final_k=4,
        )
        manifest2 = manifest2.to_dict()
        self.assertEqual(
            [c["evidence_id"] for c in perturbed],
            [c["evidence_id"] for c in perturbed2],
        )
        # 不同 seed 产生不同注入（随机化确实生效）
        _, manifest3 = apply_stress(
            result.rrf_candidates, question,
            rule="inject_unsupporting_v1", seed=123, final_k=4,
        )
        manifest3 = manifest3.to_dict()
        self.assertNotEqual(
            manifest["injected_evidence_ids"], manifest3["injected_evidence_ids"]
        )

    def test_e_unanswerable_malicious_keeps_context(self):
        question = next(q for q in self.questions if q["id"] == "stress-003")
        declared = dict(question)
        declared["stress_rule"] = "unanswerable_malicious"
        run, _ = run_condition(declared, "E", self.retriever,
                               config={"seed": 0, "final_k": 4})
        self.assertEqual(run.stress_manifest["stress_rule"], "unanswerable_malicious")
        self.assertEqual(run.stress_manifest["injected_evidence_ids"], [])
        self.assertTrue(run.answer)

    def test_condition_yaml_overrides_defaults_but_skips_placeholders(self):
        from evaluation.conditions import get_condition_config

        # conditions.yaml 的 D.system_version=TO_BE_FILLED 不应覆盖代码默认
        cfg = get_condition_config("D", yaml_path=str(ROOT / "configs/conditions.yaml"))
        self.assertEqual(cfg["system_version"], "mock-system-v0.1")
        # conditions.yaml 的 E.stress_rule=drop_all_gold_v1 应生效
        cfg_e = get_condition_config("E", yaml_path=str(ROOT / "configs/conditions.yaml"))
        self.assertEqual(cfg_e["stress_rule"], "drop_all_gold_v1")

    def test_unknown_stress_rule_raises(self):
        from evaluation.stress import apply_stress

        question = next(q for q in self.questions if q["id"] == "stress-001")
        result = self.retriever.search(question)
        with self.assertRaises(ValueError):
            apply_stress(result.rrf_candidates, question, rule="no_such_rule")


if __name__ == "__main__":
    unittest.main()


class TestDFullSystem:
    """D 完整组件（vendored A5）集成测试。"""

    def test_d_full_system_module_importable(self):
        """evaluation.d_full_system 可导入（Python 3.10+；低版本跳过）。"""
        import sys
        if sys.version_info < (3, 10):
            import pytest
            pytest.skip("A5 需要 Python 3.10+")
        import evaluation.d_full_system as d
        assert hasattr(d, "build_d_workflow")
        assert hasattr(d, "run_d_question")
        assert d.TRACK1_ROOT.is_dir()

    def test_track1_vendored_a5_imports(self):
        import sys
        if sys.version_info < (3, 10):
            import pytest
            pytest.skip("A5 需要 Python 3.10+")
        import pathlib
        root = pathlib.Path("track1").resolve()
        if not root.is_dir():
            import pytest
            pytest.skip("track1 未 vendor")
        sys.path.insert(0, str(root))
        from a5.agent.workflow import A5Workflow
        from a5.runtime_config import load_runtime_config
        cfg = load_runtime_config(root / "config")
        assert cfg.agent.config_version
        assert cfg.gates.config_version
        assert cfg.skills.evidence_research.version
