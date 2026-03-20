from pydantic import BaseModel, Field, ValidationError

from langgraph.graph import StateGraph, START, END

from typing import Literal, Annotated

from doc_processor.llms import midm as llm_sm
from doc_processor.llms import midm as llm_bg
from doc_processor.prompts import get_prompts
from doc_processor.core.chat_utils import trim_chat_history

prompts = get_prompts()

###################################################################################################
# STRUCTURED OUTPUT FORMS
###################################################################################################

class UserAgentDecision(BaseModel):
    reasoning: str = Field(description="판단 이유 한줄. 여기를 먼저 채워넣으세요!")
    action: Literal["search", "answer"] = Field(description="다음 행동")
    message: str = Field(description="검색 에이전트에 전달할 설명 또는 사용자에게 보낼 답변")

class SearchQuery(BaseModel):
    reasoning: str = Field(description="이 쿼리를 선택한 이유 한줄. 여기를 먼저 채워넣으세요!")
    query: str = Field(description="검색 쿼리")

class SearchEval(BaseModel):
    reasoning: str = Field(description="판단 이유 한줄. 여기를 먼저 채워넣으세요!")
    verdict: Literal["sufficient", "retry"] = Field(description="검색 결과 평가")
    retry_query: str = Field(default="", description="재시도 쿼리")

###################################################################################################
# LLM INSTANCES
###################################################################################################

user_agent_llm = llm_bg.with_structured_output(UserAgentDecision, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError), stop_after_attempt=3)
query_gen_llm = llm_sm.with_structured_output(SearchQuery, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError), stop_after_attempt=3)
search_eval_llm = llm_sm.with_structured_output(SearchEval, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError), stop_after_attempt=3)

###################################################################################################
# STATE
###################################################################################################

def add_messages(existing: list[tuple[str, str]], new: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return existing + new

class AgentState(BaseModel):
    chat_history: Annotated[list[tuple[str, str]], add_messages] = Field(default_factory=list)
    search_description: str = ""
    search_query: str = ""
    search_results: str = ""
    search_retries: int = 0
    max_retries: int = 2
    past_queries: list[str] = Field(default_factory=list)
    should_retry: bool = False
    agent_response: str = ""

###################################################################################################
# VECTOR DB SETUP (from query_intel)
###################################################################################################

from langchain_community.embeddings import OpenVINOEmbeddings
from langchain_qdrant import QdrantVectorStore, RetrievalMode

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
    collection_name="law_body_only",
    url="http://cg-rookies:6333",
    retrieval_mode=RetrievalMode.DENSE,
    content_payload_key="text"
)

###################################################################################################
# NODES
###################################################################################################

def user_agent_node(state: AgentState):
    """Analyze user message, decide: search DB or answer directly."""
    messages = [
        ("system", prompts["search_user_agent"]),
        *trim_chat_history(state.chat_history, prompts["search_user_agent"]),
    ]
    print(f"\n--- USER AGENT ---")
    decision = UserAgentDecision.model_validate(user_agent_llm.invoke(messages))
    print(f"  action: {decision.action} | reasoning: {decision.reasoning}")

    if decision.action == "search":
        return {"search_description": decision.message}
    else:
        return {"agent_response": decision.message}


def search_query_node(state: AgentState):
    """Generate a search query from the description."""
    messages = [
        ("system", prompts["search_query_gen"]),
        ("user", state.search_description),
    ]
    print(f"\n--- QUERY GEN ---")
    result = SearchQuery.model_validate(query_gen_llm.invoke(messages))
    print(f"  query: {result.query}")
    return {"search_query": result.query}


def search_db_node(state: AgentState):
    """Execute vector DB search."""
    print(f"\n--- DB SEARCH: '{state.search_query}' ---")
    docs_with_scores = qdrant.similarity_search_with_score(state.search_query, k=10)
    results_text = "\n\n---\n\n".join(doc.page_content for doc, _ in docs_with_scores)
    print(f"  retrieved {len(docs_with_scores)} documents | scores: {",".join([str(s) for _, s in docs_with_scores])}")
    return {"search_results": results_text, "past_queries": state.past_queries + [state.search_query]}


def search_eval_node(state: AgentState):
    """Evaluate if search results are sufficient."""
    user_question = state.chat_history[-1][1] if state.chat_history else ""
    past_queries_text = "\n".join(f"- {q}" for q in state.past_queries) if state.past_queries else "(없음)"
    messages = [
        ("system", prompts["search_eval"]),
        ("user", f"[사용자 질문]\n{user_question}\n\n[검색 쿼리]\n{state.search_query}\n\n[이전 시도 쿼리]\n{past_queries_text}\n\n[검색 결과]\n{state.search_results}"),
    ]
    print(f"\n--- SEARCH EVAL ---")
    evaluation = SearchEval.model_validate(search_eval_llm.invoke(messages))
    print(f"  verdict: {evaluation.verdict} | reasoning: {evaluation.reasoning}")

    if evaluation.verdict == "retry" and state.search_retries < state.max_retries:
        return {
            "search_query": evaluation.retry_query,
            "search_retries": state.search_retries + 1,
            "should_retry": True,
        }
    return {"should_retry": False}


def answer_node(state: AgentState):
    """Generate final answer using search results."""
    user_question = state.chat_history[-1][1] if state.chat_history else ""
    messages = [
        ("system", prompts["search_answer"]),
        ("user", f"[사용자 질문]\n{user_question}\n\n[검색 결과]\n{state.search_results}"),
    ]
    print(f"\n--- ANSWER GEN ---")
    response = llm_bg.invoke(messages)
    print(f"  answer generated")
    return {"agent_response": response.content}

###################################################################################################
# ROUTING
###################################################################################################

def route_user_agent(state: AgentState) -> str:
    if state.search_description and not state.agent_response:
        return "search_query"
    return "respond"

def route_search_eval(state: AgentState) -> str:
    if state.should_retry:
        return "retry"
    return "answer"

###################################################################################################
# GRAPH
###################################################################################################

graph_builder = StateGraph(AgentState)

graph_builder.add_node("user_agent", user_agent_node)
graph_builder.add_node("search_query", search_query_node)
graph_builder.add_node("search_db", search_db_node)
graph_builder.add_node("search_eval", search_eval_node)
graph_builder.add_node("answer", answer_node)

graph_builder.add_edge(START, "user_agent")
graph_builder.add_conditional_edges("user_agent", route_user_agent, {
    "search_query": "search_query",
    "respond": END,
})
graph_builder.add_edge("search_query", "search_db")
graph_builder.add_edge("search_db", "search_eval")
graph_builder.add_conditional_edges("search_eval", route_search_eval, {
    "retry": "search_db",
    "answer": "answer",
})
graph_builder.add_edge("answer", END)

search_graph = graph_builder.compile()

###################################################################################################
# MAIN LOOP
###################################################################################################

if __name__ == "__main__":
    state = {"chat_history": []}

    print("commands: 'quit', 'clear'\n")

    while True:
        user_input = input("질문: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if user_input.lower() in ("clear", "reset", "cls"):
            state = {"chat_history": []}
            print("대화 기록이 초기화되었습니다.\n")
            continue
        if not user_input:
            continue

        state["chat_history"].append(("user", user_input))

        result = search_graph.invoke(state)

        response = result["agent_response"]
        print(f"\n답변: {response}\n")

        # carry forward chat history + assistant response, reset transient state
        state = {
            "chat_history": result["chat_history"] + [("assistant", response)],
        }
