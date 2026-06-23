from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from app.schemas import RelationshipStateSchema
from app.services import memory as memory_module
from app.services.memory import RelationshipMemory


def _patched_datetime(now: datetime) -> Mock:
    mocked = Mock()
    mocked.now.return_value = now
    mocked.fromisoformat.side_effect = datetime.fromisoformat
    return mocked


def main() -> None:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "m9_memory.db"
            memory = RelationshipMemory(str(db_path))
            session_id = "test_m9_session"

            # 1. Daily greeting: first call greets, second call on same day does not.
            first_greet, first_text = memory.check_daily_greeting(session_id)
            second_greet, _ = memory.check_daily_greeting(session_id)
            assert first_greet is True and first_text
            assert second_greet is False

            # 2. Gap push: 26 hours since last_seen should trigger a non-empty message.
            past = datetime.now(timezone.utc) - timedelta(hours=26)
            state = memory.load(session_id)
            memory.save(state.model_copy(update={"last_seen_iso": past.isoformat()}))
            should_push, push_text = memory.check_gap_push(session_id)
            assert should_push is True and push_text

            # 3. Streak: simulate three consecutive interaction days.
            streak_session = "test_m9_streak_session"
            start = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
            for offset in range(3):
                with patch.object(memory_module, "datetime", _patched_datetime(start + timedelta(days=offset))):
                    state = memory.update_after_turn(
                        streak_session,
                        f"第 {offset + 1} 天",
                        "我在。",
                        "happy",
                    )
            assert state.streak_days == 3

            # 4. Unlock thresholds.
            assert memory.get_streak_unlock(3) is not None
            assert memory.get_streak_unlock(2) is None

            # 5. Closeness growth over five turns.
            close_session = "test_m9_closeness_session"
            before = memory.load(close_session).closeness
            for index in range(5):
                memory.update_after_turn(close_session, f"你好 {index}", "你好。", "happy")
            after = memory.load(close_session).closeness
            assert after - before >= 0.02

        print("PASS")
    except Exception as exc:
        print(f"FAIL: {exc}")


if __name__ == "__main__":
    main()
