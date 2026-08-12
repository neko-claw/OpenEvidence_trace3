"""Replaceable infrastructure adapters for A5 ports.

Track 3 vendored subset: A4 adapter requires Track 1's retrieval package which
is not vendored (Track 3 has its own retrieval/ package). Import lazily via
``a5.adapters.a4_evidence_retriever`` when needed; the D-condition path uses
``A5EvidenceRetrieverAdapter`` from Track 3 (evaluation/adapters/a5_retriever.py)
and never imports this module's eager dependency.
"""

__all__ = ["A4EvidenceRetrieverAdapter"]


def __getattr__(name: str):
    if name == "A4EvidenceRetrieverAdapter":
        from a5.adapters.a4_evidence_retriever import A4EvidenceRetrieverAdapter
        return A4EvidenceRetrieverAdapter
    raise AttributeError(name)
