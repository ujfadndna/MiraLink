from app.services.memory import get_memory


def main() -> None:
    session_id = "test_m7_memory_session"
    memory = get_memory()
    before = memory.load(session_id)
    state = memory.update_after_turn(session_id, "我叫小明 我喜欢咖啡", "好的，我记住了。", "happy")
    state = memory.update_after_turn(session_id, "我叫小明 我喜欢咖啡", "咖啡听起来不错。", "happy")

    checks = [
        state.closeness > before.closeness,
        "叫小明" in state.known_facts,
        "喜欢咖啡" in state.known_facts,
    ]
    if all(checks):
        print("PASS")
    else:
        print(f"FAIL closeness={state.closeness} facts={state.known_facts}")


if __name__ == "__main__":
    main()
