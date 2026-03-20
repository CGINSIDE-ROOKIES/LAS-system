import os
from dotenv import load_dotenv
from pydantic import SecretStr
from langchain_core.utils.utils import convert_to_secret_str

load_dotenv()

def load_env_SecretStr(env_name: str) -> SecretStr:
    env = os.getenv(env_name)
    assert isinstance(env, str), f"env {env_name} not found."
    return convert_to_secret_str(env)

def load_env_str(env_name: str, default: str = "") -> str:
    env = os.getenv(env_name)
    if not env:
        return default
    return env

if __name__ == "__main__":
    pass