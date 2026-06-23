"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const htmlPath = path.join(__dirname, "avatar_touch.html");
const html = fs.readFileSync(htmlPath, "utf8");
const scriptMatch = html.match(/<script>\s*([\s\S]*?)\s*<\/script>/);
if (!scriptMatch) throw new Error("avatar_touch.html script not found");

const BODY_TOUCH_ZONES = [
  "head",
  "face",
  "neck",
  "chest",
  "waist",
  "left_shoulder",
  "right_shoulder",
  "left_upper_arm",
  "right_upper_arm",
  "left_forearm",
  "right_forearm",
  "left_hand",
  "right_hand",
  "left_thigh",
  "right_thigh",
  "left_calf",
  "right_calf",
  "left_foot",
  "right_foot",
];

class FakeElement {
  constructor(id) {
    this.id = id;
    this.textContent = "";
    this.value = "";
    this.srcObject = null;
    this.videoWidth = 16;
    this.videoHeight = 9;
    this.rect = { left: 0, top: 0, width: 390, height: 844 };
    this.listeners = {};
    this.attributes = {};
    this.style = {};
    this.classList = {
      values: new Set(),
      toggle: (name, force) => {
        if (force) this.classList.values.add(name);
        else this.classList.values.delete(name);
      },
      add: (name) => this.classList.values.add(name),
      remove: (name) => this.classList.values.delete(name),
      contains: (name) => this.classList.values.has(name),
    };
  }

  addEventListener(type, callback) {
    this.listeners[type] = this.listeners[type] || [];
    this.listeners[type].push(callback);
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  contains(target) {
    return target === this;
  }

  getBoundingClientRect() {
    return this.rect;
  }

  play() {
    return Promise.resolve();
  }
}

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, new FakeElement(id));
  return elements.get(id);
}

const sent = [];
const sockets = [];
let now = 100000;
const context = {
  console,
  Date: class extends Date {
    constructor(...args) {
      super(...(args.length ? args : [now]));
    }
    static now() { return now; }
  },
  Math,
  Number,
  String,
  Boolean,
  Object,
  Array,
  JSON,
  URL,
  URLSearchParams,
  WebSocket: class {
    constructor() {
      this.readyState = 1;
      context.__lastWebSocket = this;
      sockets.push(this);
    }
    send(raw) { sent.push(JSON.parse(raw)); }
    close() {}
  },
  RTCPeerConnection: undefined,
  RTCIceCandidate: function() {},
  RTCSessionDescription: function(data) { return data; },
  MediaStream: function() {},
  setTimeout(callback) {
    context.__timers.push(callback);
    return context.__timers.length;
  },
  clearTimeout() {},
  setInterval() { return 1; },
  clearInterval() {},
  location: {
    protocol: "http:",
    hostname: "127.0.0.1",
    search: "",
  },
  window: {
    innerHeight: 844,
    PointerEvent: function PointerEvent() {},
    HERUNITY_SERVER_DEFAULTS: {
      iceTransportPolicy: "relay",
      iceServers: [
        {
          urls: ["turn:127.0.0.1:3478?transport=udp"],
          username: "u",
          credential: "p",
        },
      ],
    },
    localStorage: {
      store: { sc_session: "test-session", sc_ip: "127.0.0.1", sc_port: "8100", sc_signal_port: "8080" },
      getItem(key) { return this.store[key] || ""; },
      setItem(key, value) { this.store[key] = String(value); },
    },
    addEventListener() {},
  },
  navigator: {
    mediaDevices: {
      getUserMedia() {
        return Promise.resolve({
          getTracks() {
            return [{ stop() {} }];
          },
        });
      },
    },
  },
  document: {
    body: element("body"),
    getElementById: element,
    addEventListener() {},
  },
  __timers: [],
};
context.WebSocket.OPEN = 1;
context.window.window = context.window;
context.window.document = context.document;
context.window.location = context.location;
context.window.setTimeout = context.setTimeout;
context.window.clearTimeout = context.clearTimeout;
context.window.setInterval = context.setInterval;
context.window.clearInterval = context.clearInterval;
context.window.WebSocket = context.WebSocket;
context.window.navigator = context.navigator;
context.PointerEvent = context.window.PointerEvent;

vm.createContext(context);
new vm.Script(scriptMatch[1], { filename: htmlPath }).runInContext(context);

function markInteractionReady() {
  context.video.srcObject = { ready: true };
  context.videoReady = true;
  context.pcConnected = true;
  context.sensorBound = true;
  context.sessionId = "test-session";
  context.currentConfig.session = "test-session";
  if (context.sensorWs) context.sensorWs.readyState = context.WebSocket.OPEN;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function lastSent() {
  assert(sent.length > 0, "no WebSocket payload was sent");
  return sent[sent.length - 1];
}

function setLiveAnchors() {
  const positions = {
    head: [0.5, 0.10, 0.045],
    face: [0.5, 0.20, 0.045],
    neck: [0.5, 0.30, 0.035],
    chest: [0.5, 0.42, 0.060],
    waist: [0.5, 0.55, 0.055],
    left_shoulder: [0.32, 0.36, 0.040],
    right_shoulder: [0.68, 0.36, 0.040],
    left_upper_arm: [0.24, 0.48, 0.040],
    right_upper_arm: [0.76, 0.48, 0.040],
    left_forearm: [0.20, 0.61, 0.040],
    right_forearm: [0.80, 0.61, 0.040],
    left_hand: [0.18, 0.74, 0.045],
    right_hand: [0.82, 0.74, 0.045],
    left_thigh: [0.42, 0.70, 0.040],
    right_thigh: [0.58, 0.70, 0.040],
    left_calf: [0.40, 0.83, 0.040],
    right_calf: [0.60, 0.83, 0.040],
    left_foot: [0.36, 0.94, 0.040],
    right_foot: [0.64, 0.94, 0.040],
  };
  const anchors = {};
  BODY_TOUCH_ZONES.forEach((zone) => {
    const [x, y, r] = positions[zone];
    anchors[zone] = {
      x,
      y,
      r,
      visible: true,
      side: zone.indexOf("left_") === 0 ? "left" : zone.indexOf("right_") === 0 ? "right" : "center",
      body_group: zone.replace(/^left_/, "").replace(/^right_/, ""),
    };
  });
  context.applyAnchors({ anchors });
  return anchors;
}

function setMirroredLiveAnchors() {
  const anchors = {};
  BODY_TOUCH_ZONES.forEach((zone) => {
    anchors[zone] = {
      x: 0.5,
      y: 0.5,
      r: 0.03,
      visible: false,
      side: zone.indexOf("left_") === 0 ? "left" : zone.indexOf("right_") === 0 ? "right" : "center",
      body_group: zone.replace(/^left_/, "").replace(/^right_/, ""),
    };
  });
  Object.assign(anchors, {
    head: { x: 0.5, y: 0.16, r: 0.06, visible: true, side: "center", body_group: "head" },
    face: { x: 0.5, y: 0.25, r: 0.06, visible: true, side: "center", body_group: "face" },
    chest: { x: 0.5, y: 0.45, r: 0.08, visible: true, side: "center", body_group: "chest" },
    right_forearm: { x: 0.20, y: 0.60, r: 0.035, visible: true, side: "right", body_group: "forearm" },
    left_forearm: { x: 0.80, y: 0.60, r: 0.035, visible: true, side: "left", body_group: "forearm" },
    right_hand: { x: 0.24, y: 0.70, r: 0.035, visible: true, side: "right", body_group: "hand" },
    left_hand: { x: 0.76, y: 0.70, r: 0.035, visible: true, side: "left", body_group: "hand" },
  });
  context.applyAnchors({ anchors });
  return anchors;
}

function clientFromVideoPoint(point) {
  const metrics = context.videoFitMetrics();
  return {
    x: metrics.rect.left + metrics.offsetX + point.x * metrics.contentW,
    y: metrics.rect.top + metrics.offsetY + point.y * metrics.contentH,
  };
}

function tapZone(zone, anchors) {
  const pt = clientFromVideoPoint(anchors[zone]);
  const before = sent.length;
  context.startAvatarTouch(pt.x, pt.y, true);
  now += 120;
  context.finishAvatarTouch(pt.x, pt.y);
  const payload = lastSent();
  assert(sent.length === before + 1, `${zone} tap should send exactly one event`);
  assert(payload.event === `tap_${zone}`, `${zone} tap event mismatch: ${payload.event}`);
  assert(payload.zone === zone, `${zone} tap zone mismatch`);
  assert(payload.value.zone === zone, `${zone} value zone mismatch`);
  assert(payload.value.anchors_live === true, `${zone} should use live anchors`);
}

function tapPoint(point) {
  const pt = clientFromVideoPoint(point);
  const before = sent.length;
  context.startAvatarTouch(pt.x, pt.y, true);
  now += 120;
  context.finishAvatarTouch(pt.x, pt.y);
  assert(sent.length === before + 1, `tap at ${JSON.stringify(point)} should send exactly one event`);
  return lastSent();
}

function holdPoint(point) {
  const pt = clientFromVideoPoint(point);
  const before = sent.length;
  context.startAvatarTouch(pt.x, pt.y, true);
  const timer = context.__timers.pop();
  assert(typeof timer === "function", `hold timer missing for ${JSON.stringify(point)}`);
  now += 820;
  timer();
  assert(sent.length === before + 1, `hold at ${JSON.stringify(point)} should send exactly one event`);
  const payload = lastSent();
  context.cancelActiveTouch();
  return payload;
}

function swipePoint(point) {
  const pt = clientFromVideoPoint(point);
  const before = sent.length;
  context.startAvatarTouch(pt.x, pt.y, true);
  now += 180;
  context.finishAvatarTouch(pt.x + 70, pt.y);
  assert(sent.length === before + 1, `swipe at ${JSON.stringify(point)} should send exactly one event`);
  return lastSent();
}

function holdZone(zone, anchors) {
  const pt = clientFromVideoPoint(anchors[zone]);
  const before = sent.length;
  context.startAvatarTouch(pt.x, pt.y, true);
  const timer = context.__timers.pop();
  assert(typeof timer === "function", `${zone} hold timer missing`);
  now += 820;
  timer();
  const payload = lastSent();
  assert(sent.length === before + 1, `${zone} hold should send exactly one event`);
  assert(payload.event === `hold_${zone}`, `${zone} hold event mismatch: ${payload.event}`);
  assert(payload.zone === zone, `${zone} hold zone mismatch`);
  context.cancelActiveTouch();
}

function swipeZone(zone, anchors) {
  const pt = clientFromVideoPoint(anchors[zone]);
  const before = sent.length;
  context.startAvatarTouch(pt.x, pt.y, true);
  now += 180;
  context.finishAvatarTouch(pt.x + 70, pt.y);
  const payload = lastSent();
  assert(sent.length === before + 1, `${zone} swipe should send exactly one event`);
  assert(payload.event === "swipe", `${zone} swipe event mismatch: ${payload.event}`);
  assert(payload.zone === zone, `${zone} swipe zone mismatch`);
  assert(payload.value.direction === "right", `${zone} swipe direction mismatch`);
}

assert(!/id=["']zone-head["']|class=["'][^"']*\bzone\b/.test(html), "avatar_touch should not render visible touch zones");
assert(/id=["']call-panel["']/.test(html), "avatar_touch should render call panel");
assert(/id=["']call-toggle["'][^>]*>\s*开始\s*<\/button>/.test(html), "call toggle should show 开始");
assert(/id=["']unity-video["']/.test(html), "avatar_touch should render #unity-video");
assert(/\bvar\s+videoPc\b/.test(html), "avatar_touch script should expose videoPc");
assert(/\bvar\s+callWs\b/.test(html), "avatar_touch script should expose callWs");
assert(!/id=["']t["']|id=["']s["']|Say something|>\s*Send\s*</.test(html), "avatar_touch should not render old text input UI");
assert(new Function(scriptMatch[1]), "avatar_touch script should compile");
markInteractionReady();

assert(context.effectiveIcePolicy() === "relay", "server defaults should set relay ICE policy");
assert(context.hasConfiguredTurnServer() === true, "server defaults should provide TURN for relay ICE");
assert(context.configuredIceServers()[0].urls[0].startsWith("turn:"), "configured ICE should use injected TURN defaults");

context.window.localStorage.store.sc_ice_policy = "all";
assert(context.effectiveIcePolicy() === "all", "local ICE policy should override server default");
delete context.window.localStorage.store.sc_ice_policy;

BODY_TOUCH_ZONES.forEach((zone) => tapZone(zone, setLiveAnchors()));
BODY_TOUCH_ZONES.forEach((zone) => holdZone(zone, setLiveAnchors()));
BODY_TOUCH_ZONES.forEach((zone) => swipeZone(zone, setLiveAnchors()));

setMirroredLiveAnchors();
let payload = tapPoint({ x: 0.24, y: 0.70 });
assert(payload.event === "tap_left_hand", `visual left hand should send tap_left_hand, got ${payload.event}`);
assert(payload.zone === "left_hand", "visual left hand top-level zone mismatch");
assert(payload.value.zone === "left_hand", "visual left hand value zone mismatch");
assert(payload.value.visual_zone === "left_hand", "visual left hand visual_zone mismatch");
assert(payload.value.anatomical_zone === "right_hand", "visual left hand should target anatomical right_hand");
assert(payload.value.zone_basis === "screen_visual", "visual left hand zone_basis mismatch");

payload = tapPoint({ x: 0.76, y: 0.70 });
assert(payload.event === "tap_right_hand", `visual right hand should send tap_right_hand, got ${payload.event}`);
assert(payload.value.visual_zone === "right_hand", "visual right hand visual_zone mismatch");
assert(payload.value.anatomical_zone === "left_hand", "visual right hand should target anatomical left_hand");

payload = holdPoint({ x: 0.76, y: 0.70 });
assert(payload.event === "hold_right_hand", `visual right hand hold should send hold_right_hand, got ${payload.event}`);
assert(payload.value.visual_zone === "right_hand", "visual right hand hold visual_zone mismatch");
assert(payload.value.anatomical_zone === "left_hand", "visual right hand hold should target anatomical left_hand");

payload = swipePoint({ x: 0.76, y: 0.70 });
assert(payload.event === "swipe", `visual right hand swipe should send swipe, got ${payload.event}`);
assert(payload.zone === "right_hand", "visual right hand swipe top-level zone mismatch");
assert(payload.value.visual_zone === "right_hand", "visual right hand swipe visual_zone mismatch");
assert(payload.value.anatomical_zone === "left_hand", "visual right hand swipe should target anatomical left_hand");

payload = tapPoint({ x: 0.80, y: 0.60 });
assert(payload.event === "tap_right_forearm", `visual right forearm should send tap_right_forearm, got ${payload.event}`);
assert(payload.value.visual_zone === "right_forearm", "visual right forearm visual_zone mismatch");
assert(payload.value.anatomical_zone === "left_forearm", "visual right forearm should target anatomical left_forearm");

payload = holdPoint({ x: 0.20, y: 0.60 });
assert(payload.event === "hold_left_forearm", `visual left forearm should send hold_left_forearm, got ${payload.event}`);
assert(payload.value.visual_zone === "left_forearm", "visual left forearm visual_zone mismatch");
assert(payload.value.anatomical_zone === "right_forearm", "visual left forearm should target anatomical right_forearm");

payload = swipePoint({ x: 0.20, y: 0.60 });
assert(payload.event === "swipe", `visual left forearm swipe should send swipe, got ${payload.event}`);
assert(payload.zone === "left_forearm", "visual left forearm swipe top-level zone mismatch");
assert(payload.value.visual_zone === "left_forearm", "visual left forearm swipe visual_zone mismatch");
assert(payload.value.anatomical_zone === "right_forearm", "visual left forearm swipe should target anatomical right_forearm");

const leftFallback = context.hitTest(context.fallbackAnchors().left_hand);
assert(leftFallback.zone === "left_hand", "fallback visual left hand zone mismatch");
assert(leftFallback.anatomical_zone === "right_hand", "fallback visual left hand anatomical mismatch");
const rightFallback = context.hitTest(context.fallbackAnchors().right_hand);
assert(rightFallback.zone === "right_hand", "fallback visual right hand zone mismatch");
assert(rightFallback.anatomical_zone === "left_hand", "fallback visual right hand anatomical mismatch");

setLiveAnchors();
context.anchors.left_hand.visible = false;
context.anchors.right_hand.visible = false;
payload = tapPoint({ x: 0.22, y: 0.73 });
assert(payload.event === "tap_left_hand", `hidden live hand should fall back to visual left hand, got ${payload.event}`);
assert(payload.value.anatomical_zone === "right_hand", "hidden live fallback should preserve visual-left anatomical right_hand");
assert(payload.value.anchors_live === false, "hidden live fallback hit should be marked as fallback");

context.anchorsUpdatedAt = 0;
const fallbackZones = BODY_TOUCH_ZONES.filter((zone) => context.fallbackAnchors()[zone]);
assert(fallbackZones.length === BODY_TOUCH_ZONES.length, "fallback anchors should cover every body zone");
fallbackZones.forEach((zone) => {
  const hit = context.hitTest(context.fallbackAnchors()[zone]);
  assert(hit && hit.zone === zone, `fallback hit mismatch for ${zone}`);
});

assert(/object-fit:\s*contain/.test(html), "avatar_touch video should use contain to avoid cropping the avatar");

const fit = context.videoFitMetrics();
assert(fit.contentW <= fit.rect.width + 0.01, "contain metrics should not crop width");
assert(fit.contentH <= fit.rect.height + 0.01, "contain metrics should not crop height");
assert(fit.offsetY > 0, "wide phone viewport should letterbox vertically instead of cropping");

const center = context.videoPointFromClient(195, 422);
assert(Math.abs(center.x - 0.5) < 0.02, "contain x conversion should stay centered");
assert(Math.abs(center.y - 0.5) < 0.02, "contain y conversion should stay centered");

element("unity-video").rect = { left: 0, top: 0, width: 1280, height: 720 };
context.window.innerHeight = 720;
let wideFit = context.videoFitMetrics();
assert(wideFit.offsetX === 0, "landscape 16:9 should not pillarbox");
assert(wideFit.offsetY === 0, "landscape 16:9 should not letterbox");
let wideCenter = context.videoPointFromClient(640, 360);
assert(Math.abs(wideCenter.x - 0.5) < 0.01, "landscape contain x conversion should stay centered");
assert(Math.abs(wideCenter.y - 0.5) < 0.01, "landscape contain y conversion should stay centered");

element("unity-video").rect = { left: 0, top: 0, width: 390, height: 844 };
context.window.innerHeight = 844;

const drawerBefore = context.configOpen;
context.onPointerDown({ pointerType: "touch", pointerId: 1, isPrimary: true, button: 0, clientX: 20, clientY: 100, target: element("stage"), preventDefault() {} });
context.onPointerDown({ pointerType: "touch", pointerId: 2, isPrimary: false, button: 0, clientX: 40, clientY: 100, target: element("stage"), preventDefault() {} });
context.onPointerDown({ pointerType: "touch", pointerId: 3, isPrimary: false, button: 0, clientX: 60, clientY: 100, target: element("stage"), preventDefault() {} });
const timer = context.__timers.pop();
assert(typeof timer === "function", "three-finger pointer timer missing");
timer();
assert(context.configOpen !== drawerBefore || context.debugVisible === true, "three-finger pointer mode should toggle debug/drawer");

setLiveAnchors();
context.video.srcObject = { ready: true };
context.videoReady = true;
context.pcConnected = true;
context.sensorBound = false;
context.sessionId = "";
context.currentConfig.session = "";
context.window.localStorage.store.sc_session = "";
context.pendingFirstTouchEvent = null;
const queuedBefore = sent.length;
let queuePt = clientFromVideoPoint({ x: 0.5, y: 0.15 });
context.startAvatarTouch(queuePt.x, queuePt.y, true);
now += 120;
context.finishAvatarTouch(queuePt.x, queuePt.y);
assert(sent.length === queuedBefore + 1, "first touch should only request sensor.bind while session is not bound");
assert(lastSent().type === "sensor.bind", "first touch should request sensor.bind before readiness");
assert(context.pendingFirstTouchEvent && /^tap_/.test(context.pendingFirstTouchEvent.event), "queued first touch should keep a tap payload");
const queuedEvent = context.pendingFirstTouchEvent.event;
context.sensorWs.onmessage({ data: JSON.stringify({ type: "sensor.bound", session_id: "test-session" }) });
assert(sent.length === queuedBefore + 2, "sensor.bound should flush queued first touch");
assert(lastSent().event === queuedEvent, "flushed first touch event mismatch");
assert(context.pendingFirstTouchEvent === null, "queued first touch should clear after flush");

context.sensorBound = false;
context.sessionId = "";
context.currentConfig.session = "";
context.window.localStorage.store.sc_session = "";
context.pendingFirstTouchEvent = null;
const dropBefore = sent.length;
queuePt = clientFromVideoPoint({ x: 0.5, y: 0.15 });
context.startAvatarTouch(queuePt.x, queuePt.y, true);
now += 120;
context.finishAvatarTouch(queuePt.x, queuePt.y);
assert(sent.length === dropBefore + 1, "queued touch should only request sensor.bind before readiness");
assert(lastSent().type === "sensor.bind", "queued touch should request sensor.bind before timeout");
const dropTimer = context.__timers.pop();
assert(typeof dropTimer === "function", "first-touch timeout timer missing");
dropTimer();
assert(context.pendingFirstTouchEvent === null, "first-touch timeout should clear pending event");
context.sensorWs.onmessage({ data: JSON.stringify({ type: "sensor.bound", session_id: "test-session" }) });
assert(sent.length === dropBefore + 1, "timed-out first touch should not flush later");

context.callConnecting = true;
context.callReady = false;
context.setCallUi("connecting", "");
context.currentConfig.session = "test-session";
context.window.localStorage.store.sc_session = "test-session";
const callBefore = sent.length;
context.openCallSocket();
const callSocket = sockets[sockets.length - 1];
callSocket.onopen();
assert(sent.length === callBefore + 1, "call socket open should send call.start");
assert(lastSent().type === "call.start", "call.start payload type mismatch");
assert(lastSent().session_id === "test-session", "call.start should include current session");
assert(context.callState === "connecting", "call UI should stay connecting before call.started");
context.onCallMessage({ data: JSON.stringify({ type: "call.started", session_id: "test-session" }) });
assert(context.callReady === true, "call.started should mark callReady");
assert(context.callState === "listening", "call.started should switch UI to listening");

console.log("PASS");
