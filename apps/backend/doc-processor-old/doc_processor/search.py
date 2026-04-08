"""
Search sub-graph module — reusable RAG pipeline for law lookup.

Two use-cases:
1. **Interactive chat** — full graph with user_agent routing (search vs direct answer)
2. **Programmatic** — use ``search_law()`` from ``core.vector_db`` directly

This module exposes both:
- ``search_graph``: full interactive chat graph (START → user_agent → ... → END)
- ``search_only_graph``: query-only graph (START → search_query → search_db → search_eval → END)
"""

from pydantic import BaseModel, Field, ValidationError
from langchain_core.exceptions import OutputParserException

from langgraph.graph import StateGraph, START, END

from typing import Literal, Annotated

from doc_processor.llms import midm as llm
from doc_processor.prompts import get_prompts
from doc_processor.core.chat_utils import trim_chat_history
from doc_processor.core.vector_db import qdrant

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

user_agent_llm = llm.with_structured_output(UserAgentDecision, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError, OutputParserException), stop_after_attempt=3)
query_gen_llm = llm.with_structured_output(SearchQuery, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError, OutputParserException), stop_after_attempt=3)
search_eval_llm = llm.with_structured_output(SearchEval, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError, OutputParserException), stop_after_attempt=3)

###################################################################################################
# STATES
###################################################################################################

def _add_messages(existing: list[tuple[str, str]], new: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return existing + new


class ChatSearchState(BaseModel):
    """Full interactive search state (with chat history)."""
    chat_history: Annotated[list[tuple[str, str]], _add_messages] = Field(default_factory=list)
    search_description: str = ""
    search_query: str = ""
    search_results: str = ""
    search_retries: int = 0
    max_retries: int = 2
    past_queries: list[str] = Field(default_factory=list)
    should_retry: bool = False
    agent_response: str = ""


class SearchOnlyState(BaseModel):
    """Programmatic search state (no chat history, just description → results)."""
    search_description: str = ""
    search_query: str = ""
    search_results: str = ""
    search_retries: int = 0
    max_retries: int = 2
    past_queries: list[str] = Field(default_factory=list)
    should_retry: bool = False

###################################################################################################
# NODES
###################################################################################################

def user_agent_node(state: ChatSearchState):
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


def search_query_node(state: ChatSearchState | SearchOnlyState):
    """Generate a search query from the description."""
    messages = [
        ("system", prompts["search_query_gen"]),
        ("user", state.search_description),
    ]
    print(f"\n--- QUERY GEN ---")
    result = SearchQuery.model_validate(query_gen_llm.invoke(messages))
    print(f"  query: {result.query}")
    return {"search_query": result.query}


def search_db_node(state: ChatSearchState | SearchOnlyState):
    """Execute vector DB search."""
    print(f"\n--- DB SEARCH: '{state.search_query}' ---")
    docs_with_scores = qdrant.similarity_search_with_score(state.search_query, k=10)
    results_text = "\n\n---\n\n".join(doc.page_content for doc, _ in docs_with_scores)
    scores = ",".join(str(round(s, 4)) for _, s in docs_with_scores)
    print(f"  retrieved {len(docs_with_scores)} documents | scores: {scores}")
    return {"search_results": results_text, "past_queries": state.past_queries + [state.search_query]}


def search_eval_node(state: ChatSearchState | SearchOnlyState):
    """Evaluate if search results are sufficient."""
    # For ChatSearchState, use last user message; for SearchOnlyState, use description
    if isinstance(state, ChatSearchState) and state.chat_history:
        user_question = state.chat_history[-1][1]
    else:
        user_question = state.search_description

    past_queries_text = "\n".join(f"- {q}" for q in state.past_queries) if state.past_queries else "(없음)"
    messages = [
        ("system", prompts["search_eval"]),
        ("user", f"[사용자 질문]\n{user_question}\n\n[검색 쿼리]\n{state.search_query}\n\n"
                 f"[이전 시도 쿼리]\n{past_queries_text}\n\n[검색 결과]\n{state.search_results}"),
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


def answer_node(state: ChatSearchState):
    """Generate final answer using search results."""
    user_question = state.chat_history[-1][1] if state.chat_history else ""
    messages = [
        ("system", prompts["search_answer"]),
        ("user", f"[사용자 질문]\n{user_question}\n\n[검색 결과]\n{state.search_results}"),
    ]
    print(f"\n--- ANSWER GEN ---")
    response = llm.invoke(messages)
    print(f"  answer generated")
    return {"agent_response": response.content}

###################################################################################################
# ROUTING
###################################################################################################

def _route_user_agent(state: ChatSearchState) -> str:
    if state.search_description and not state.agent_response:
        return "search_query"
    return "respond"

def _route_search_eval(state: ChatSearchState | SearchOnlyState) -> str:
    if state.should_retry:
        return "retry"
    return "done"

###################################################################################################
# GRAPH 1: Full interactive chat search
###################################################################################################

_chat_builder = StateGraph(ChatSearchState)

_chat_builder.add_node("user_agent", user_agent_node)
_chat_builder.add_node("search_query", search_query_node)
_chat_builder.add_node("search_db", search_db_node)
_chat_builder.add_node("search_eval", search_eval_node)
_chat_builder.add_node("answer", answer_node)

_chat_builder.add_edge(START, "user_agent")
_chat_builder.add_conditional_edges("user_agent", _route_user_agent, {
    "search_query": "search_query",
    "respond": END,
})
_chat_builder.add_edge("search_query", "search_db")
_chat_builder.add_edge("search_db", "search_eval")
_chat_builder.add_conditional_edges("search_eval", _route_search_eval, {
    "retry": "search_db",
    "done": "answer",
})
_chat_builder.add_edge("answer", END)

search_graph = _chat_builder.compile()

###################################################################################################
# GRAPH 2: Search-only (no chat, just description → results)
###################################################################################################

_search_builder = StateGraph(SearchOnlyState)

_search_builder.add_node("search_query", search_query_node)
_search_builder.add_node("search_db", search_db_node)
_search_builder.add_node("search_eval", search_eval_node)

_search_builder.add_edge(START, "search_query")
_search_builder.add_edge("search_query", "search_db")
_search_builder.add_edge("search_db", "search_eval")
_search_builder.add_conditional_edges("search_eval", _route_search_eval, {
    "retry": "search_db",
    "done": END,
})

search_only_graph = _search_builder.compile()
