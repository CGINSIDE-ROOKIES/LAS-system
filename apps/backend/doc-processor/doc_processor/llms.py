from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

from pydantic import SecretStr

from doc_processor.core.env_loader import load_env_SecretStr, load_env_str


midm = ChatOpenAI(
    base_url=load_env_str("MIDM_LLM_URL"),
    api_key=SecretStr(""),
    model="jinkyeongk/Midm-2.0-Base-Instruct-AWQ",
)

gpt_5_nano = ChatOpenAI(
    api_key=load_env_SecretStr("OPENAI_API_KEY"),
    model="gpt-5-nano",
)

"""
Gemini 3.1 Flash Lite
RPM: 15
TPM: 250k
RPD: 500
"""
gemini_flash_lite = ChatGoogleGenerativeAI(
    api_key=load_env_SecretStr("GEMINI_API_KEY"),
    model="gemini-3.1-flash-lite-preview",
    temperature=0.7,
    max_retries=2
)
