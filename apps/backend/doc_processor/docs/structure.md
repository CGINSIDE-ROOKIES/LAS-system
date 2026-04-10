following is the recommneded project structure for langgraph projects

my_project/
├── .env                 # API keys and environment variables
├── langgraph.json       # Configuration for LangGraph Cloud/Studio
├── pyproject.toml       # or requirements.txt (dependencies)
├── src/
│   ├── __init__.py
│   ├── main.py          # Entry point (compiled graph)
│   ├── state.py         # Definition of the TypedDict State
│   ├── nodes/           # Individual step logic
│   │   ├── __init__.py
│   │   ├── chatbot.py   # LLM interaction node
│   │   └── tools.py     # Tool execution node
│   ├── tools/           # Custom tool definitions
│   │   └── search.py
│   └── utils/           # Helper functions (routing logic, etc.)
└── tests/               # Unit tests for nodes and graph flow
