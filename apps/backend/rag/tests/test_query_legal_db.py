from __future__ import annotations

import unittest

from rag_pipeline.generation import GenerationConfig, RagPipeline, RagPipelineConfig
from rag_pipeline.retrieval import LAW_CONTEXT_OK, RetrievalConfig


class CustomScore:
    def __str__(self) -> str:
        return "custom-score"


class QueryLegalDbTest(unittest.TestCase):
    def test_query_legal_db_returns_tool_friendly_payload(self) -> None:
        pipeline = RagPipeline(
            RagPipelineConfig(
                retrieval=RetrievalConfig(
                    qdrant_url="http://qdrant.test",
                    qdrant_collections=["law_article"],
                    opensearch_url="",
                    opensearch_indices=[],
                ),
                generation=GenerationConfig(
                    url="http://llm.test/v1/chat/completions",
                    model="test-model",
                    api_key="test-key",
                ),
            )
        )

        def fake_retrieve(
            question: str,
            *,
            doc_types: list[str] | None,
            law_names: list[str] | None,
            intent: str | None = None,
            search_query: str | None = None,
            hypothetical_doc: str | None = None,
            trace=None,
            top_k: int | None = None,
        ):
            self.assertEqual(question, "clause text")
            self.assertEqual(doc_types, ["law"])
            self.assertEqual(law_names, ["근로기준법"])
            self.assertEqual(intent, "normative")
            self.assertEqual(search_query, "wage legal basis")
            self.assertEqual(hypothetical_doc, "hypothetical statute")
            self.assertEqual(top_k, 3)
            return (
                [
                    {
                        "rank": "1",
                        "source_id": "law-1",
                        "doc_type": "law",
                        "law_name": "근로기준법",
                        "article_no": "제43조",
                        "score": CustomScore(),
                        "snippet": "임금은 통화로 직접 근로자에게...",
                        "text": "임금은 통화로 직접 근로자에게 그 전액을 지급하여야 한다.",
                    }
                ],
                "[검색 컨텍스트]",
                LAW_CONTEXT_OK,
                True,
            )

        pipeline._retrieve = fake_retrieve  # type: ignore[method-assign]
        try:
            result = pipeline.query_legal_db(
                "clause text",
                doc_types=["law"],
                law_names=["근로기준법"],
                intent="normative",
                search_query="wage legal basis",
                hypothetical_doc="hypothetical statute",
                top_k=3,
            )
        finally:
            pipeline._executor.shutdown(wait=False)

        self.assertEqual(result["query"], "clause text")
        self.assertEqual(result["context_text"], "[검색 컨텍스트]")
        self.assertEqual(result["law_context_status"], LAW_CONTEXT_OK)
        self.assertTrue(result["law_context_added"])
        self.assertTrue(result["has_evidence"])
        self.assertEqual(result["document_count"], 1)
        self.assertEqual(result["filters"]["search_query"], "wage legal basis")
        self.assertTrue(result["filters"]["hypothetical_doc_used"])

        document = result["documents"][0]
        self.assertEqual(document["rank"], 1)
        self.assertEqual(document["source_id"], "law-1")
        self.assertEqual(document["score"], "custom-score")
        self.assertEqual(document["citation"], "근로기준법 제43조 (law-1)")
        self.assertEqual(result["citations"][0]["citation"], document["citation"])


if __name__ == "__main__":
    unittest.main()
