from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def build_a5_workflow(a5_root: Path, retriever: Any, *, demo: bool = False) -> Any:
    """Build A5 with an injected retriever while preserving its Workflow FSM."""
    root = str(a5_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    from a5.adapters.default_safety_policy import (
        DefaultFailClosedSafetyPolicy,
        FixtureSafetyPolicy,
    )
    from a5.adapters.mock_claim_generator import MockClaimGenerator
    from a5.adapters.rule_based_claim_verifier import RuleBasedClaimVerifier
    from a5.agent.workflow import A5Workflow
    from a5.runtime_config import load_runtime_config

    config = load_runtime_config()
    return A5Workflow(
        retriever=retriever,
        claim_generator=MockClaimGenerator(),
        claim_verifier=RuleBasedClaimVerifier(
            config.gates.gate5,
            name=config.models.claim_verifier,
            textual_support_name=config.models.textual_support_evaluator,
        ),
        safety_policy=(
            FixtureSafetyPolicy(config.gates.gate0_version)
            if demo
            else DefaultFailClosedSafetyPolicy(config.gates.gate0_version)
        ),
        runtime_config=config,
    )
