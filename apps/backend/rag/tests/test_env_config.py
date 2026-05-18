from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from rag_pipeline.generation.pipeline import RagPipeline
from rag_pipeline.generation.service import GenerationConfig
from rag_pipeline.graph.llm_cypher_planner import LlmCypherPlannerConfig
from rag_pipeline.query_parser.parser import QueryParserConfig


class EnvConfigTest(unittest.TestCase):
    def test_query_parser_inherits_openai_compat_url_from_llm_profile(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openai_compat",
                "LLM_MODEL": "nvidia/Gemma-4-26B-A4B-NVFP4",
                "LLM_URL": "http://spark.test/v1/chat/completions",
                "LLM_API_KEY": "spark-key",
            },
            clear=True,
        ):
            cfg = QueryParserConfig.from_env()

        self.assertEqual(cfg.provider, "openai_compat")
        self.assertEqual(cfg.model, "nvidia/Gemma-4-26B-A4B-NVFP4")
        self.assertEqual(cfg.url, "http://spark.test/v1/chat/completions")
        self.assertEqual(cfg.api_key, "spark-key")

    def test_query_parser_scoped_profile_overrides_global_llm_profile(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "gemini",
                "LLM_MODEL": "gemini-shared",
                "LLM_API_KEY": "shared-key",
                "QUERY_PARSER_LLM_PROVIDER": "openai_compat",
                "QUERY_PARSER_LLM_MODEL": "parser-model",
                "QUERY_PARSER_LLM_URL": "http://parser.test/v1/chat/completions",
                "QUERY_PARSER_LLM_API_KEY": "parser-key",
                "QUERY_PARSER_LLM_TIMEOUT": "7",
                "QUERY_PARSER_LLM_STRICT": "true",
            },
            clear=True,
        ):
            cfg = QueryParserConfig.from_env()

        self.assertEqual(cfg.provider, "openai_compat")
        self.assertEqual(cfg.model, "parser-model")
        self.assertEqual(cfg.url, "http://parser.test/v1/chat/completions")
        self.assertEqual(cfg.api_key, "parser-key")
        self.assertEqual(cfg.timeout, 7)
        self.assertTrue(cfg.strict_mode)

    def test_graph_llm_inherits_openai_compat_url_from_llm_profile(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openai_compat",
                "LLM_MODEL": "shared-model",
                "LLM_URL": "http://spark.test/v1/chat/completions",
                "LLM_API_KEY": "spark-key",
                "QUERY_PARSER_LLM_MODEL": "parser-model",
            },
            clear=True,
        ):
            cfg = LlmCypherPlannerConfig.from_env()

        self.assertEqual(cfg.provider, "openai_compat")
        self.assertEqual(cfg.model, "parser-model")
        self.assertEqual(cfg.url, "http://spark.test/v1/chat/completions")
        self.assertEqual(cfg.api_key, "spark-key")

    def test_generation_config_supports_llm_url_alias(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openai_compat",
                "LLM_MODEL": "answer-model",
                "LLM_URL": "http://answer.test/v1/chat/completions",
                "LLM_API_KEY": "answer-key",
            },
            clear=True,
        ):
            cfg = GenerationConfig.from_env()

        self.assertEqual(cfg.url, "http://answer.test/v1/chat/completions")
        self.assertEqual(cfg.model, "answer-model")
        self.assertEqual(cfg.api_key, "answer-key")

    def test_rag_pipeline_reads_scoped_embedding_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "QDRANT_URL": "http://qdrant.test",
                "QDRANT_COLLECTIONS": "law_article",
                "LLM_PROVIDER": "openai_compat",
                "LLM_MODEL": "answer-model",
                "LLM_URL": "http://answer.test/v1/chat/completions",
                "LLM_API_KEY": "answer-key",
                "EMBEDDING_PROVIDER": "openai_compat",
                "EMBEDDING_MODEL": "embedding-model",
                "EMBEDDING_API_KEY": "embedding-key",
                "EMBEDDING_BASE_URL": "http://embedding.test/v1",
                "EMBEDDING_DIMENSIONS": "768",
            },
            clear=True,
        ):
            pipeline = RagPipeline.from_env()

        try:
            self.assertEqual(pipeline._cfg.retrieval.embedding_provider, "openai_compat")
            self.assertEqual(pipeline._cfg.retrieval.embedding_model, "embedding-model")
            self.assertEqual(pipeline._cfg.retrieval.embedding_api_key, "embedding-key")
            self.assertEqual(pipeline._cfg.retrieval.embedding_api_base_url, "http://embedding.test/v1")
            self.assertEqual(pipeline._cfg.retrieval.embedding_dimensions, 768)
        finally:
            pipeline._executor.shutdown(wait=False)


if __name__ == "__main__":
    unittest.main()
