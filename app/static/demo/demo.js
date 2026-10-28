// Marg.ai web demo (s14): the same pipeline as WhatsApp, with a live trace of every step.
// Vanilla JS, no build step. Messages are JSON; a voice note goes as base64. Turns arrive on
// the /demo/events stream (SSE); while it's down, the page polls instead.
"use strict";

const POLL_MS = 2000; // only while the live stream is down
const MAX_WAIT_MS = 120000; // two minutes
const MAX_RECORDING_MS = 60000;
const PHOTO_MAX_SIDE = 1024; // the page sends a JPEG of at most 1024 px (DEMO_MAX_IMAGE_BYTES)
const PHOTO_QUALITY = 0.82;
const OUTCOME_ICONS = { ok: "✓", degraded: "◐", failed: "✗", skipped: "–" };
const ERROR_TEXT = {
  rate_limited: "Too many messages for now. Please try again later.",
  daily_budget_reached: "The demo has reached today's limit. Please try again tomorrow, or watch the video.",
  bad_origin: "This page must be opened from its own address.",
  no_session: "Your session expired. Reloading…",
  invalid_message: "That message couldn't be sent.",
};

const messages = document.getElementById("messages");
const composer = document.getElementById("composer");
const textInput = document.getElementById("text");
const micButton = document.getElementById("mic");
const micNote = document.getElementById("mic-note");
const photoButton = document.getElementById("photo");
const photoFile = document.getElementById("photo-file");
const banner = document.getElementById("banner");
const trace = document.getElementById("trace");
const traceSummary = document.getElementById("trace-summary");
const live = document.getElementById("live");

let busy = false;
let recorder = null;
let recordingTimer = null;
let streamOpen = false;
let tracedTurnId = null; // the turn the trace panel shows; its later steps keep updating it
const waiters = new Map(); // message id → { mine, resolve, deadline }
const repliedTurns = new Set(); // a turn's reply is shown once, however often it arrives

function showBanner(text) {
  banner.textContent = text;
  banner.hidden = !text;
}

function addBubble(who, text) {
  const item = document.createElement("li");
  item.className = `bubble ${who}`;
  if (text) {
    const body = document.createElement("span");
    body.textContent = text;
    item.appendChild(body);
  }
  messages.appendChild(item);
  messages.scrollTop = messages.scrollHeight;
  return item;
}

function setState(bubble, text) {
  let state = bubble.querySelector(".state");
  if (!state) {
    state = document.createElement("span");
    state.className = "state";
    bubble.appendChild(state);
  }
  state.textContent = text;
}

async function startSession() {
  const response = await fetch("/demo/session", { credentials: "same-origin" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showBanner(ERROR_TEXT[body.error] || "The demo couldn't start. Please reload.");
    return;
  }
  addBubble("bot", "Namaste! Type Hi (or send a voice note) to begin.");
  openStream();
}

async function send(payload, label, previewUrl) {
  if (busy) return;
  busy = true;
  showBanner("");
  const mine = addBubble("you", label);
  if (previewUrl) {
    // Shown from the visitor's own browser only; the server never serves a photo back.
    const preview = document.createElement("img");
    preview.src = previewUrl;
    preview.alt = "Your photo";
    mine.appendChild(preview);
  }
  setState(mine, "sending…");
  try {
    const response = await fetch("/demo/messages", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (response.status === 401) {
      showBanner(ERROR_TEXT.no_session);
      setTimeout(() => window.location.reload(), 1200);
      return;
    }
    if (response.status !== 202) {
      setState(mine, "not sent");
      showBanner(ERROR_TEXT[body.error] || "That message couldn't be sent.");
      return;
    }
    setState(mine, "processing…");
    await follow(body.message_id, mine);
  } finally {
    busy = false;
  }
}

function openStream() {
  if (!window.EventSource) return; // polling only
  const stream = new EventSource("/demo/events");
  stream.addEventListener("open", () => {
    streamOpen = true;
    live.hidden = true;
  });
  stream.addEventListener("error", () => {
    streamOpen = false; // EventSource reconnects by itself; polling covers the gap
    live.hidden = waiters.size === 0;
  });
  stream.addEventListener("turn", (event) => handleTurn(JSON.parse(event.data)));
}

// A turn arrived (stream or poll), whole: render it again; repeats and replays are harmless.
function handleTurn(turn) {
  const waiting = turn.message_ids.filter((id) => waiters.has(id));
  const isCard = turn.message_ids.length === 0 && turn.route === "khoj_card";
  if (waiting.length || turn.turn_id === tracedTurnId) {
    tracedTurnId = turn.turn_id;
    renderTrace(turn);
  } else if (!isCard || turn.replay) {
    return; // an earlier turn of this visitor's, from before this page was opened
  }
  const done = turn.parts.length > 0 && turn.status !== "processing";
  if (!done || repliedTurns.has(turn.turn_id)) return;
  repliedTurns.add(turn.turn_id);
  for (const id of waiting) {
    const waiter = waiters.get(id);
    waiters.delete(id);
    setState(waiter.mine, "");
    waiter.resolve();
  }
  renderReply(turn);
}

function follow(messageId, mine) {
  return new Promise((resolve) => {
    waiters.set(messageId, { mine, resolve, deadline: Date.now() + MAX_WAIT_MS });
    pollWhileStreamIsDown(messageId);
  });
}

async function pollWhileStreamIsDown(messageId) {
  while (waiters.has(messageId)) {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    const waiter = waiters.get(messageId);
    if (!waiter) return;
    if (Date.now() > waiter.deadline) {
      waiters.delete(messageId);
      setState(waiter.mine, "no reply yet");
      waiter.resolve();
      return;
    }
    if (streamOpen) continue;
    const response = await fetch(`/demo/messages/${encodeURIComponent(messageId)}`, {
      credentials: "same-origin",
    });
    if (!response.ok) continue;
    const view = await response.json();
    if (view.turn) handleTurn({ ...view.turn, replay: false });
  }
}

function renderReply(turn) {
  let bubble = null;
  for (const part of turn.parts) {
    if (part.kind === "audio" && part.audio_url) {
      bubble = bubble || addBubble("bot", "");
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.src = part.audio_url;
      bubble.appendChild(audio);
      continue;
    }
    if (part.kind === "image" && part.image_url) {
      const card = addBubble("bot", "");
      const image = document.createElement("img");
      image.src = part.image_url;
      image.alt = part.text || "Khoj card";
      card.appendChild(image);
      if (part.text) {
        const caption = document.createElement("span");
        caption.textContent = part.text;
        card.appendChild(caption);
      }
      const download = document.createElement("a");
      download.href = part.image_url;
      download.download = "khoj-card.jpg";
      download.textContent = "Download";
      card.appendChild(download);
      continue;
    }
    bubble = addBubble("bot", part.text || "");
    if (part.buttons && part.buttons.length) {
      const row = document.createElement("div");
      row.className = "buttons";
      for (const button of part.buttons) {
        const tap = document.createElement("button");
        tap.type = "button";
        tap.className = "reply";
        tap.textContent = button.title;
        tap.addEventListener("click", () => send({ button_id: button.id }, button.title));
        row.appendChild(tap);
      }
      bubble.appendChild(row);
    }
  }
}

function renderTrace(turn) {
  trace.replaceChildren();
  let totalMs = 0;
  let cost = 0;
  for (const step of turn.steps) {
    totalMs += step.duration_ms;
    cost += Number(step.cost_usd || 0);
    const row = document.createElement("li");
    const icon = document.createElement("span");
    icon.className = `outcome-${step.outcome}`;
    icon.textContent = OUTCOME_ICONS[step.outcome] || "?";
    icon.title = step.outcome;
    const name = document.createElement("span");
    name.textContent = step.model ? `${step.step} · ${step.model}` : step.step;
    const time = document.createElement("span");
    time.textContent = `${step.duration_ms} ms`;
    row.append(icon, name, time);
    if (step.detail) {
      const detail = document.createElement("span");
      detail.className = "detail";
      detail.textContent = step.detail;
      row.appendChild(detail);
    }
    trace.appendChild(row);
  }
  const route = turn.route ? ` · ${turn.route}` : "";
  traceSummary.textContent = `${(totalMs / 1000).toFixed(1)} s · $${cost.toFixed(4)}${route}`;
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = textInput.value.trim();
  if (!text) return;
  textInput.value = "";
  send({ text }, text);
});

function pickMimeType() {
  const options = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
  return options.find((type) => window.MediaRecorder && MediaRecorder.isTypeSupported(type));
}

async function toggleRecording() {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
    return;
  }
  const mimeType = pickMimeType();
  if (!mimeType || !navigator.mediaDevices) {
    micNote.textContent = "Voice notes aren't supported in this browser; you can still type.";
    micNote.hidden = false;
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    micNote.textContent = "Microphone permission was denied; you can still type.";
    micNote.hidden = false;
    return;
  }
  const chunks = [];
  recorder = new MediaRecorder(stream, { mimeType });
  recorder.addEventListener("dataavailable", (event) => chunks.push(event.data));
  recorder.addEventListener("stop", async () => {
    clearTimeout(recordingTimer);
    stream.getTracks().forEach((track) => track.stop());
    micButton.setAttribute("aria-pressed", "false");
    micNote.hidden = true;
    const blob = new Blob(chunks, { type: mimeType });
    const base64 = await blobToBase64(blob);
    send({ audio_base64: base64, audio_type: mimeType.split(";")[0] }, "🎤 voice note");
  });
  recorder.start();
  micButton.setAttribute("aria-pressed", "true");
  micNote.textContent = "Recording… tap 🎤 again to send (60 s at most).";
  micNote.hidden = false;
  recordingTimer = setTimeout(() => recorder && recorder.stop(), MAX_RECORDING_MS);
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

micButton.addEventListener("click", toggleRecording);

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => resolve({ image, url });
    image.onerror = () => reject(new Error("unreadable image"));
    image.src = url;
  });
}

async function shrinkToJpeg(file) {
  const { image, url } = await loadImage(file);
  const scale = Math.min(1, PHOTO_MAX_SIDE / Math.max(image.width, image.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(image.width * scale);
  canvas.height = Math.round(image.height * scale);
  canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", PHOTO_QUALITY));
  return { blob, url };
}

photoButton.addEventListener("click", () => photoFile.click());

photoFile.addEventListener("change", async () => {
  const file = photoFile.files && photoFile.files[0];
  photoFile.value = "";
  if (!file) return;
  try {
    const { blob, url } = await shrinkToJpeg(file);
    const base64 = await blobToBase64(blob);
    send({ image_base64: base64, image_type: "image/jpeg" }, "📷 photo", url);
  } catch (error) {
    showBanner("That photo couldn't be read. Please try another one.");
  }
});

document.getElementById("reset").addEventListener("click", async () => {
  if (!window.confirm("Delete everything about this conversation and start again?")) return;
  await fetch("/demo/reset", { method: "POST", credentials: "same-origin" });
  window.location.reload();
});

startSession();
