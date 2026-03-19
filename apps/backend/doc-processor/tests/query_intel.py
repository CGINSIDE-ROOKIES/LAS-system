from openvino import Core

from langgraph.graph import StateGraph, END
from langchain_community.embeddings import OpenVINOEmbeddings
from langchain_qdrant import QdrantVectorStore, RetrievalMode

from pydantic import BaseModel, Field, ValidationError

core = Core()
devices = core.available_devices

print(f"Detected devices: {devices}")

for device in devices:
    device_name = core.get_property(device, "FULL_DEVICE_NAME")
    print(f"- {device}: {device_name}")

model_name = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
model_kwargs = {"device": "GPU"}
encode_kwargs = {"mean_pooling": True, "normalize_embeddings": True}

ov_embeddings = OpenVINOEmbeddings(
    model_name_or_path=model_name,
    model_kwargs=model_kwargs,
    encode_kwargs=encode_kwargs,
)

qdrant = QdrantVectorStore.from_existing_collection(
    embedding=ov_embeddings,
    collection_name="Labor_law_v2_clean_for_import",
    url="http://cg-rookies:6333",
    retrieval_mode=RetrievalMode.DENSE,
    content_payload_key="text"
)

#################################################################################

class QueryState(BaseModel):
    question: str = Field()
    question_result: list | None = None


def query_node(state: QueryState):
    print("-- searching...")
    query = state.question
    result = qdrant.similarity_search(
        query, k=3
    )
    return {"question_result": result}

query_graph_builder = StateGraph(QueryState)

query_graph_builder.add_node("query_node", query_node)
query_graph_builder.set_entry_point("query_node")
query_graph_builder.add_edge("query_node", END)

query_graph = query_graph_builder.compile()

if __name__ == "__main__":
    result = query_graph.invoke(
        {"question": "해고"}
    )
    print(result)
