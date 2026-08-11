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


if __name__ == "__main__":
    unittest.main()
