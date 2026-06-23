from __future__ import annotations

import asyncio

from app.routers import sensor_ws
from app.routers.sensor_clients import bind_sensor_ws, forward_avatar_anchors, unbind_sensor_ws
from app.services.sensor import BODY_TOUCH_ZONES, SensorReactionEngine


SENSITIVE_TOUCH_ZONES = {
    "chest",
    "waist",
    "left_thigh",
    "right_thigh",
    "left_calf",
    "right_calf",
    "left_foot",
    "right_foot",
}


class DummyWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


async def _test_feedback_forwarding() -> None:
    sensor = DummyWebSocket()
    avatar = DummyWebSocket()
    session_id = "test_jd_session"
    sensor_ws._avatar_ws_registry[session_id] = avatar

    calls: list[tuple[str, str]] = []

    async def fake_reaction(_avatar_ws, event: str, sid: str) -> None:
        calls.append((event, sid))

    original_reaction = sensor_ws._run_optional_sensor_reaction
    sensor_ws._run_optional_sensor_reaction = fake_reaction
    try:
        await sensor_ws._handle_sensor_event(
            sensor,
            {
                "type": "sensor.event",
                "session_id": session_id,
                "event": "shake",
                "zone": None,
                "value": {"strength": 0.9, "confidence": 1.0},
                "timestamp_ms": 1000,
            },
            "shake",
            session_id,
        )
        await asyncio.sleep(0)
    finally:
        sensor_ws._run_optional_sensor_reaction = original_reaction
        sensor_ws._avatar_ws_registry.pop(session_id, None)
        sensor_ws._engine._last_trigger.pop(session_id, None)
        sensor_ws._engine._last_forward.pop(session_id, None)

    assert avatar.sent, "avatar should receive sensor.feedback"
    feedback = avatar.sent[0]
    assert feedback["type"] == "sensor.feedback"
    assert feedback["event"] == "shake"
    assert feedback["emotion"] == "surprised"
    assert feedback["energy_delta"] > 0
    assert "vfx" in feedback["feedback_tags"]
    assert feedback["command"]["gesture"] == "gesture_emphasis"
    assert feedback["command"]["vfx_key"] == "shake_burst"
    assert feedback["command"]["interrupt_policy"] == "interrupt_reacting"

    assert sensor.sent, "sensor should receive sensor.ack"
    ack = sensor.sent[0]
    assert ack["type"] == "sensor.ack"
    assert ack["accepted"] is True
    assert ack["event"] == "shake"
    assert calls == [("shake", session_id)]


async def _test_swipe_value_zone_forwarding() -> None:
    sensor = DummyWebSocket()
    avatar = DummyWebSocket()
    session_id = "test_jd_swipe_zone"
    sensor_ws._avatar_ws_registry[session_id] = avatar

    try:
        await sensor_ws._handle_sensor_event(
            sensor,
            {
                "type": "sensor.event",
                "session_id": session_id,
                "event": "swipe",
                "value": {"zone": "chest", "direction": "right", "confidence": 1.0},
                "timestamp_ms": 0,
                "diagnostic": True,
            },
            "swipe",
            session_id,
        )
    finally:
        sensor_ws._avatar_ws_registry.pop(session_id, None)
        sensor_ws._engine._last_forward.pop(session_id, None)
        sensor_ws._engine._last_trigger.pop(session_id, None)

    assert sensor.sent[0]["accepted"] is True
    feedback = avatar.sent[0]
    assert feedback["event"] == "swipe"
    assert feedback["zone"] == "chest"
    assert feedback["command"]["pose_mode"] == "touch_chest_guard"
    assert feedback["command"]["sound_key"] == "boundary_tone"
    assert feedback["command"]["vfx_key"] == "subtle_spark"


async def _test_visual_left_hand_drives_anatomical_right_hand() -> None:
    sensor = DummyWebSocket()
    avatar = DummyWebSocket()
    session_id = "test_jd_visual_left_hand"
    sensor_ws._avatar_ws_registry[session_id] = avatar

    try:
        await sensor_ws._handle_sensor_event(
            sensor,
            {
                "type": "sensor.event",
                "session_id": session_id,
                "event": "tap_left_hand",
                "zone": "left_hand",
                "value": {
                    "zone": "left_hand",
                    "visual_zone": "left_hand",
                    "anatomical_zone": "right_hand",
                    "zone_basis": "screen_visual",
                    "confidence": 1.0,
                },
                "timestamp_ms": 0,
                "diagnostic": True,
            },
            "tap_left_hand",
            session_id,
        )
    finally:
        sensor_ws._avatar_ws_registry.pop(session_id, None)
        sensor_ws._engine._last_forward.pop(session_id, None)
        sensor_ws._engine._last_trigger.pop(session_id, None)

    assert sensor.sent[0]["accepted"] is True
    assert sensor.sent[0]["event"] == "tap_left_hand"
    feedback = avatar.sent[0]
    assert feedback["event"] == "tap_left_hand"
    assert feedback["zone"] == "left_hand"
    assert feedback["value"]["visual_zone"] == "left_hand"
    assert feedback["value"]["anatomical_zone"] == "right_hand"
    assert feedback["command"]["pose_mode"] == "touch_right_hand_ack"


async def _test_visual_right_hand_drives_anatomical_left_hand() -> None:
    sensor = DummyWebSocket()
    avatar = DummyWebSocket()
    session_id = "test_jd_visual_right_hand"
    sensor_ws._avatar_ws_registry[session_id] = avatar

    try:
        await sensor_ws._handle_sensor_event(
            sensor,
            {
                "type": "sensor.event",
                "session_id": session_id,
                "event": "tap_right_hand",
                "zone": "right_hand",
                "value": {
                    "zone": "right_hand",
                    "visual_zone": "right_hand",
                    "anatomical_zone": "left_hand",
                    "zone_basis": "screen_visual",
                    "confidence": 1.0,
                },
                "timestamp_ms": 0,
                "diagnostic": True,
            },
            "tap_right_hand",
            session_id,
        )
    finally:
        sensor_ws._avatar_ws_registry.pop(session_id, None)
        sensor_ws._engine._last_forward.pop(session_id, None)
        sensor_ws._engine._last_trigger.pop(session_id, None)

    assert sensor.sent[0]["accepted"] is True
    assert sensor.sent[0]["event"] == "tap_right_hand"
    feedback = avatar.sent[0]
    assert feedback["event"] == "tap_right_hand"
    assert feedback["zone"] == "right_hand"
    assert feedback["value"]["visual_zone"] == "right_hand"
    assert feedback["value"]["anatomical_zone"] == "left_hand"
    assert feedback["command"]["pose_mode"] == "touch_left_hand_ack"
    assert feedback["command"]["gaze_mode"] == "gaze_left_hand"


async def _test_visual_hold_and_swipe_use_anatomical_pose_zone() -> None:
    cases = [
        ("hold_right_hand", "right_hand", "left_hand", "touch_left_hand_hold", "gaze_left_hand"),
        ("hold_left_hand", "left_hand", "right_hand", "touch_right_hand_hold", "gaze_right_hand"),
        ("swipe", "right_forearm", "left_forearm", "touch_left_arm_ack", "gaze_sweep"),
        ("swipe", "left_forearm", "right_forearm", "touch_right_arm_ack", "gaze_sweep"),
    ]

    for index, (event, visual_zone, anatomical_zone, pose_mode, gaze_mode) in enumerate(cases):
        sensor = DummyWebSocket()
        avatar = DummyWebSocket()
        session_id = f"test_jd_visual_pose_{index}"
        sensor_ws._avatar_ws_registry[session_id] = avatar

        try:
            await sensor_ws._handle_sensor_event(
                sensor,
                {
                    "type": "sensor.event",
                    "session_id": session_id,
                    "event": event,
                    "zone": visual_zone,
                    "value": {
                        "zone": visual_zone,
                        "visual_zone": visual_zone,
                        "anatomical_zone": anatomical_zone,
                        "zone_basis": "screen_visual",
                        "direction": "right",
                        "confidence": 1.0,
                    },
                    "timestamp_ms": 0,
                    "diagnostic": True,
                },
                event,
                session_id,
            )
        finally:
            sensor_ws._avatar_ws_registry.pop(session_id, None)
            sensor_ws._engine._last_forward.pop(session_id, None)
            sensor_ws._engine._last_trigger.pop(session_id, None)

        assert sensor.sent[0]["accepted"] is True, event
        feedback = avatar.sent[0]
        assert feedback["zone"] == visual_zone
        assert feedback["value"]["visual_zone"] == visual_zone
        assert feedback["value"]["anatomical_zone"] == anatomical_zone
        assert feedback["command"]["pose_mode"] == pose_mode
        assert feedback["command"]["gaze_mode"] == gaze_mode


async def _test_diagnostic_feedback_skips_voice_reaction() -> None:
    sensor = DummyWebSocket()
    avatar = DummyWebSocket()
    session_id = "test_jd_diagnostic"
    sensor_ws._avatar_ws_registry[session_id] = avatar

    calls: list[tuple[str, str]] = []

    async def fake_reaction(_avatar_ws, event: str, sid: str) -> None:
        calls.append((event, sid))

    original_reaction = sensor_ws._run_optional_sensor_reaction
    sensor_ws._run_optional_sensor_reaction = fake_reaction
    try:
        await sensor_ws._handle_sensor_event(
            sensor,
            {
                "type": "sensor.event",
                "session_id": session_id,
                "event": "tap_head",
                "zone": "head",
                "diagnostic": True,
                "value": {"zone": "head", "confidence": 1.0, "diagnostic": True},
                "timestamp_ms": 1000,
            },
            "tap_head",
            session_id,
        )
        await asyncio.sleep(0)
    finally:
        sensor_ws._run_optional_sensor_reaction = original_reaction
        sensor_ws._avatar_ws_registry.pop(session_id, None)
        sensor_ws._engine._last_trigger.pop(session_id, None)
        sensor_ws._engine._last_forward.pop(session_id, None)

    assert sensor.sent[0]["type"] == "sensor.ack"
    assert sensor.sent[0]["accepted"] is True
    assert avatar.sent[0]["type"] == "sensor.feedback"
    assert avatar.sent[0]["event"] == "tap_head"
    assert calls == []


async def _test_tilt_rate_limit_and_no_score() -> None:
    sensor = DummyWebSocket()
    avatar = DummyWebSocket()
    session_id = "test_jd_tilt"
    sensor_ws._avatar_ws_registry[session_id] = avatar

    try:
        payload = {
            "type": "sensor.event",
            "session_id": session_id,
            "event": "tilt",
            "value": {"beta": 12.5, "gamma": -18.0, "confidence": 0.9},
            "timestamp_ms": 0,
        }
        await sensor_ws._handle_sensor_event(sensor, payload, "tilt", session_id)
        await sensor_ws._handle_sensor_event(sensor, payload, "tilt", session_id)
    finally:
        sensor_ws._avatar_ws_registry.pop(session_id, None)
        sensor_ws._engine._last_forward.pop(session_id, None)

    assert len(avatar.sent) == 1, "rate-limited tilt should not be forwarded"
    feedback = avatar.sent[0]
    assert feedback["event"] == "tilt"
    assert feedback["energy_delta"] == 0
    assert feedback["score_delta"] == 0
    assert feedback["command"]["gaze_mode"] == "gaze_follow"
    assert feedback["command"]["interrupt_policy"] == "nonblocking"

    assert sensor.sent[0]["accepted"] is True
    assert sensor.sent[1]["accepted"] is False
    assert sensor.sent[1]["reason"] == "rate_limited"
    assert sensor.sent[1]["retry_after_ms"] > 0


async def _test_avatar_anchors_forwarding() -> None:
    sensor = DummyWebSocket()
    session_id = "test_jd_anchors"
    payload = {
        "type": "avatar.anchors",
        "session_id": session_id,
        "anchors": {
            "head": {"x": 0.5, "y": 0.25, "r": 0.1, "visible": True},
            "left_hand": {"x": 0.25, "y": 0.65, "r": 0.12, "visible": True},
        },
        "timestamp_ms": 123456,
    }

    bind_sensor_ws(session_id, sensor)
    try:
        forwarded = await forward_avatar_anchors(payload)
    finally:
        unbind_sensor_ws(sensor, session_id)

    assert forwarded == 1
    assert sensor.sent == [payload]


async def _test_avatar_anchors_without_bound_sensor_is_noop() -> None:
    forwarded = await forward_avatar_anchors({
        "type": "avatar.anchors",
        "session_id": "test_no_sensor",
        "anchors": {"head": {"x": 0.5, "y": 0.2, "r": 0.1, "visible": True}},
        "timestamp_ms": 0,
    })

    assert forwarded == 0


async def _test_imu_events_are_accepted() -> None:
    events = {
        "shake": {"accel_magnitude": 38.0, "net_magnitude": 28.2, "confidence": 1.0},
        "tilt": {"alpha": 5.0, "beta": 12.0, "gamma": -8.0, "confidence": 0.9},
        "pickup": {"beta": 72.0, "gamma": 3.0, "confidence": 0.9},
        "putdown": {"beta": 8.0, "gamma": 2.0, "confidence": 0.9},
        "near_ear": {"beta": 78.0, "gamma": 4.0, "confidence": 0.85},
        "walking": {"z_samples": [7.8, 9.4, 7.9, 9.5], "confidence": 0.8},
    }

    async def fake_reaction(_avatar_ws, event: str, sid: str) -> None:
        return None

    original_reaction = sensor_ws._run_optional_sensor_reaction
    sensor_ws._run_optional_sensor_reaction = fake_reaction
    try:
        for event, value in events.items():
            sensor = DummyWebSocket()
            avatar = DummyWebSocket()
            session_id = f"test_jd_imu_{event}"
            sensor_ws._avatar_ws_registry[session_id] = avatar
            try:
                await sensor_ws._handle_sensor_event(
                    sensor,
                    {
                        "type": "sensor.event",
                        "session_id": session_id,
                        "event": event,
                        "value": value,
                        "timestamp_ms": 0,
                    },
                    event,
                    session_id,
                )
            finally:
                sensor_ws._avatar_ws_registry.pop(session_id, None)
                sensor_ws._engine._last_forward.pop(session_id, None)
                sensor_ws._engine._last_trigger.pop(session_id, None)

            assert sensor.sent, f"{event} should receive sensor.ack"
            assert sensor.sent[0]["type"] == "sensor.ack"
            assert sensor.sent[0]["accepted"] is True
            assert sensor.sent[0]["event"] == event
            assert avatar.sent, f"{event} should forward sensor.feedback"
            assert avatar.sent[0]["event"] == event
    finally:
        sensor_ws._run_optional_sensor_reaction = original_reaction


async def _test_unknown_event_is_rejected() -> None:
    sensor = DummyWebSocket()
    session_id = "test_jd_unknown"
    await sensor_ws._handle_sensor_event(
        sensor,
        {
            "type": "sensor.event",
            "session_id": session_id,
            "event": "unknown_input",
            "timestamp_ms": 0,
        },
        "unknown_input",
        session_id,
    )

    assert sensor.sent == [{
        "type": "sensor.ack",
        "session_id": session_id,
        "event": "unknown_input",
        "accepted": False,
        "latency_ms": 0,
        "reason": "unknown event: unknown_input",
    }]


def _test_mapping() -> None:
    engine = SensorReactionEngine()
    expected_events = {
        "shake",
        "tilt",
        "tap",
        "swipe",
        "wave",
        "pickup",
        "near_ear",
        "walking",
        "dark",
        "reset",
    }
    for zone in BODY_TOUCH_ZONES:
        expected_events.add(f"tap_{zone}")
        expected_events.add(f"hold_{zone}")

    for event in expected_events:
        spec = engine.feedback_for(event)
        assert spec is not None, f"missing feedback mapping for {event}"
        assert spec.event in expected_events
        assert spec.emotion
        assert spec.feedback_tags
        assert spec.command.state
        assert spec.command.emotion
        assert spec.command.pose_mode
        assert spec.command.duration_sec >= 0
        assert spec.command.interrupt_policy

    assert engine.feedback_for("click").event == "tap"
    assert engine.feedback_for("tap_cheek").event == "tap_face"
    assert engine.feedback_for("tap_hand").event == "tap_hand"
    assert engine.feedback_for("hold_hand").event == "hold_hand"
    assert engine.feedback_for("swipe_left").event == "swipe"
    assert engine.feedback_for("hold").event == "hold_hand"
    assert engine.feedback_for("tilt").score_delta == 0
    assert engine.feedback_for("walking").score_delta == 0
    assert engine.feedback_for("tap_not_a_zone") is None
    assert engine.feedback_for("not_a_real_event") is None

    for zone in BODY_TOUCH_ZONES:
        assert engine.feedback_for(f"tap_{zone}").should_voice is False
        assert engine.feedback_for(f"hold_{zone}").should_voice is False


def _test_body_touch_command_policy() -> None:
    engine = SensorReactionEngine()

    for zone in (
        "left_shoulder",
        "right_shoulder",
        "left_upper_arm",
        "right_upper_arm",
        "left_forearm",
        "right_forearm",
        "left_hand",
        "right_hand",
    ):
        for prefix in ("tap", "hold"):
            spec = engine.feedback_for(f"{prefix}_{zone}")
            assert spec is not None
            assert spec.command.gesture == "", f"{prefix}_{zone} should not use a generic gesture"
            assert "gesture" not in spec.feedback_tags

    assert engine.feedback_for("tap_hand").event == "tap_hand"
    assert engine.feedback_for("tap_hand").command.gesture == ""
    assert engine.feedback_for("hold_hand").event == "hold_hand"
    assert engine.feedback_for("hold_hand").command.gesture == ""
    contextual = engine.feedback_for_event("tap_hand", zone="left_hand", value={"anatomical_zone": "right_hand"})
    assert contextual is not None
    assert contextual.event == "tap_left_hand"
    assert contextual.command.pose_mode == "touch_right_hand_ack"


def _test_zone_aware_swipe_mapping() -> None:
    engine = SensorReactionEngine()

    legacy = engine.feedback_for_event("swipe")
    assert legacy is not None
    assert legacy.event == "swipe"
    assert legacy.command.pose_mode == "swipe_shift"
    assert legacy.command.sound_key == "swipe_tone"

    expected = {
        "chest": ("touch_chest_guard", "boundary_tone", "subtle_spark"),
        "waist": ("touch_waist_guard", "boundary_tone", "subtle_spark"),
        "left_thigh": ("touch_left_leg_step", "step_tone", "subtle_spark"),
        "right_thigh": ("touch_right_leg_step", "step_tone", "subtle_spark"),
        "left_calf": ("touch_left_leg_step", "step_tone", "subtle_spark"),
        "right_calf": ("touch_right_leg_step", "step_tone", "subtle_spark"),
        "left_foot": ("touch_left_foot_step", "step_tone", "subtle_spark"),
        "right_foot": ("touch_right_foot_step", "step_tone", "subtle_spark"),
        "right_shoulder": ("touch_right_shoulder_ack", "soft_tone", "affinity_spark"),
        "right_upper_arm": ("touch_right_arm_ack", "soft_tone", "affinity_spark"),
        "right_forearm": ("touch_right_arm_ack", "soft_tone", "affinity_spark"),
        "right_hand": ("touch_right_hand_ack", "soft_tone", "affinity_spark"),
        "head": ("touch_head_recoil", "tap_tone", "pink_spark"),
        "face": ("touch_face_flinch", "tap_tone", "pink_spark"),
        "neck": ("touch_neck_shy", "tap_tone", "pink_spark"),
    }
    for zone, (pose, sound, vfx) in expected.items():
        spec = engine.feedback_for_event("swipe_right", zone=zone)
        assert spec is not None
        assert spec.event == "swipe"
        assert spec.should_voice is False
        assert spec.command.pose_mode == pose, zone
        assert spec.command.sound_key == sound, zone
        assert spec.command.vfx_key == vfx, zone
        if zone.endswith(("shoulder", "arm", "forearm", "hand", "thigh", "calf", "foot")):
            assert spec.command.gesture == "", zone


def main() -> None:
    _test_mapping()
    _test_body_touch_command_policy()
    _test_zone_aware_swipe_mapping()
    asyncio.run(_test_feedback_forwarding())
    asyncio.run(_test_swipe_value_zone_forwarding())
    asyncio.run(_test_visual_left_hand_drives_anatomical_right_hand())
    asyncio.run(_test_visual_right_hand_drives_anatomical_left_hand())
    asyncio.run(_test_visual_hold_and_swipe_use_anatomical_pose_zone())
    asyncio.run(_test_diagnostic_feedback_skips_voice_reaction())
    asyncio.run(_test_tilt_rate_limit_and_no_score())
    asyncio.run(_test_avatar_anchors_forwarding())
    asyncio.run(_test_avatar_anchors_without_bound_sensor_is_noop())
    asyncio.run(_test_imu_events_are_accepted())
    asyncio.run(_test_unknown_event_is_rejected())
    print("PASS")


if __name__ == "__main__":
    main()
