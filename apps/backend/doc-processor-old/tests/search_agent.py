from doc_processor.search import search_graph

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
