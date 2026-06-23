import pytest

from app.services.agent import MockAgent
from app.services.avatar_intent import parse_avatar_action_intent


@pytest.mark.anyio
async def test_mock_agent_general_question_is_not_miralink_only():
    response = await MockAgent().generate("今天晚饭吃什么", "sess_mock_open")

    assert "只能回答" not in response.reply_text
    assert "MiraLink 项目" not in response.reply_text
    assert "数字人技术" not in response.reply_text


@pytest.mark.anyio
async def test_mock_agent_identity_still_answers_miralink_avatar():
    response = await MockAgent().generate("你是谁", "sess_mock_identity")

    assert "MiraLink" in response.reply_text
    assert "数字人" in response.reply_text
    assert response.dialogue_act == "self_intro"


def test_avatar_intent_recognizes_happy_expression():
    command = parse_avatar_action_intent("做一个开心的表情")

    assert command is not None
    assert command.emotion == "happy"
    assert command.gesture == ""


def test_avatar_intent_recognizes_wave():
    command = parse_avatar_action_intent("你挥挥手")

    assert command is not None
    assert command.emotion == "happy"
    assert command.gesture == "gesture_greet"


def test_avatar_intent_recognizes_look_left():
    command = parse_avatar_action_intent("看左边")

    assert command is not None
    assert command.gaze_mode == "gaze_left"


def test_avatar_intent_recognizes_restore_neutral():
    command = parse_avatar_action_intent("恢复普通表情")

    assert command is not None
    assert command.emotion == "neutral"
    assert command.gaze_mode == "gaze_idle"


def test_avatar_intent_ignores_general_question():
    assert parse_avatar_action_intent("今天晚饭吃什么") is None
