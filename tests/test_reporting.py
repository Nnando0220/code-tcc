"""Testes das interpretacoes publicadas no relatorio academico."""

import pandas as pd

from ._bootstrap import ROOT  # noqa: F401
from tcc_reddit.reporting.analysis import build_findings


def test_complete_collection_reports_completed_combinations():
    completeness = pd.DataFrame(
        [
            {
                "subreddit": "brasil",
                "sort_origin": sort,
                "completion_rate": 1.0,
            }
            for sort in ("top", "controversial", "hot", "new")
        ]
    )

    findings = build_findings(
        pd.DataFrame(),
        completeness,
        pd.DataFrame(),
        pd.DataFrame(),
        {},
    )
    finding = next(item for item in findings if item["title"] == "Completude da coleta")

    assert finding["value"] == "4 de 4"
    assert "nenhuma combinação ficou abaixo" in finding["interpretation"]
    assert "selected_posts menores que 100 não representam falha" in finding["interpretation"]
