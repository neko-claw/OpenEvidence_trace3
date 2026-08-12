from evaluation.run_a5 import parse_args


def test_run_a5_parser_keeps_unified_entrypoint_options(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["run_a5", "--a5-root", "E:/projects/OpenEvidence_MVP/OpenEvidence_trace1"],
    )
    args = parse_args()
    assert args.a5_root.endswith("OpenEvidence_trace1")
    assert args.seed == 0
    assert args.replicate == 1
