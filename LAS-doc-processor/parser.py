from pydantic import BaseModel, Field
from env_loader import load_env_SecretStr, load_env_str

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END

parser_llm = ChatOpenAI(
    base_url=load_env_str("PARSER_LLM_URL"),
    api_key=load_env_SecretStr("PARSER_LLM_KEY"),
    model=load_env_str("PARSER_LLM_MODEL", ""),
)

parser_llm.bind_tools(
    [
        
    ],
    tool_choice="required", strict=True)

