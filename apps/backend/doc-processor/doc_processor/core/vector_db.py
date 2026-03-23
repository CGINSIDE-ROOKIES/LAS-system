from langchain_community.embeddings import OpenVINOEmbeddings
from langchain_qdrant import QdrantVectorStore, RetrievalMode

from doc_processor.core.env_loader import load_env_str

###################################################################################################
# EMBEDDINGS
###################################################################################################

_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

ov_embeddings = OpenVINOEmbeddings(
    model_name_or_path=_EMBED_MODEL,
    model_kwargs={"device": "GPU"},
    encode_kwargs={"mean_pooling": True, "normalize_embeddings": True},
)

###################################################################################################
# QDRANT
###################################################################################################

_QDRANT_URL = load_env_str("QDRANT_URL", default="http://cg-rookies:6333")
_COLLECTION = load_env_str("QDRANT_COLLECTION", default="law_article")

qdrant = QdrantVectorStore.from_existing_collection(
    embedding=ov_embeddings,
    collection_name=_COLLECTION,
    url=_QDRANT_URL,
    retrieval_mode=RetrievalMode.DENSE,
    content_payload_key="text",
    vector_name="body",
)

###################################################################################################
# HELPERS
###################################################################################################

def search_law(query: str, k: int = 3, max_chars: int = 900) -> str:
    """Search the law vector DB and return truncated results.

    Designed to fit within the 4K context budget of the dev model.
    Returns concatenated document texts, each truncated to ``max_chars // k``.
    """
    docs_with_scores = qdrant.similarity_search_with_score(query, k=k)
    per_doc_limit = max_chars // max(len(docs_with_scores), 1)

    parts: list[str] = []
    for doc, score in docs_with_scores:
        text = doc.page_content[:per_doc_limit]
        if len(doc.page_content) > per_doc_limit:
            text += "..."
        parts.append(text)
        print(f"  [search_law] score={score:.4f} | {text[:80]}...")

    return "\n\n---\n\n".join(parts)
