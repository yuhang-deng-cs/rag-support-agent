// Minimal, dependency-free client for the RAG Support Agent API.
"use strict";

const API = "/api/v1";
const TOKEN_KEY = "rsa.token";
const $ = (sel) => document.querySelector(sel);

const state = { token: null, user: null };

// ---- storage (may be unavailable in private mode) ---------------------------
function loadToken() {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function saveToken(token) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage unavailable: the session just won't survive a reload
  }
}

// ---- HTTP -------------------------------------------------------------------
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
  }
  const resp = await fetch(API + path, { ...options, headers });
  if (resp.status === 401 && state.token) { logout(); throw new Error("Session expired"); }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail;
    throw new Error(detail || `Request failed (${resp.status})`);
  }
  return resp.status === 204 ? null : resp.json();
}

// ---- auth -------------------------------------------------------------------
function showAuthError(message) {
  const el = $("#auth-error");
  el.textContent = message;
  el.hidden = !message;
}

async function authenticate(path, payload) {
  showAuthError("");
  try {
    const result = await api(path, { method: "POST", json: payload });
    state.token = result.access_token;
    state.user = result.user;
    saveToken(state.token);
    enterApp();
  } catch (err) {
    showAuthError(err.message);
  }
}

let emptyChat = null; // initial "ask a question" placeholder, restored on logout

function logout() {
  state.token = null;
  state.user = null;
  saveToken(null);
  // Never leave a previous user's conversation or workspace data on screen.
  emptyChat ??= $("#messages").innerHTML;
  $("#messages").innerHTML = emptyChat;
  $("#documents").replaceChildren();
  $("#tickets").replaceChildren();
  $("#invite-code").hidden = true;
  $("#question").value = "";
  $("#app-view").hidden = true;
  $("#logout").hidden = true;
  $("#whoami").hidden = true;
  $("#auth-view").hidden = false;
}

function bindAuth(config) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".auth-form").forEach((f) => { f.hidden = f.dataset.panel !== tab.dataset.tab; });
      showAuthError("");
    });
  });
  const formPayload = (form) => Object.fromEntries(new FormData(form).entries());
  $("#form-login").addEventListener("submit", (e) => { e.preventDefault(); void authenticate("/auth/login", formPayload(e.target)); });
  $("#form-signup").addEventListener("submit", (e) => { e.preventDefault(); void authenticate("/auth/signup", formPayload(e.target)); });
  $("#form-join").addEventListener("submit", (e) => { e.preventDefault(); void authenticate("/auth/join", formPayload(e.target)); });

  $("#signup-tab").hidden = !config.signup;
  $("#demo-box").hidden = !config.demo;
  document.querySelectorAll("[data-demo]").forEach((btn) => {
    btn.addEventListener("click", () => void authenticate("/auth/login", { username: btn.dataset.demo, password: "demo-password" }));
  });
  $("#logout").addEventListener("click", logout);
}

// ---- app ----------------------------------------------------------------------
function enterApp() {
  const { user } = state;
  $("#auth-view").hidden = true;
  $("#app-view").hidden = false;
  $("#logout").hidden = false;
  const who = $("#whoami");
  who.textContent = `${user.username} · ${user.role} · ${user.tenant_id}`;
  who.hidden = false;
  document.querySelectorAll(".admin-only").forEach((el) => { el.hidden = user.role !== "admin"; });
  void refreshDocuments();
  void refreshTickets();
  $("#question").focus();
}

function li(name, status, title) {
  const item = document.createElement("li");
  const label = document.createElement("span");
  label.className = "name";
  label.textContent = name;
  if (title) label.title = title;
  const badge = document.createElement("span");
  badge.className = `status ${status}`;
  badge.textContent = status;
  item.append(label, badge);
  return item;
}

let docPoll = null;
async function refreshDocuments() {
  const docs = await api("/documents").catch(() => []);
  const list = $("#documents");
  list.replaceChildren(...docs.map((d) => li(d.filename, d.status, d.error || `${d.chunk_count} chunks`)));
  if (!docs.length) list.append(Object.assign(document.createElement("li"), { textContent: "No documents yet", className: "muted" }));
  clearTimeout(docPoll);
  if (docs.some((d) => d.status === "queued" || d.status === "processing")) docPoll = setTimeout(refreshDocuments, 1500);
}

async function refreshTickets() {
  const tickets = await api("/tickets").catch(() => []);
  const list = $("#tickets");
  list.replaceChildren(...tickets.map((t) => li(t.question, t.status)));
  if (!tickets.length) list.append(Object.assign(document.createElement("li"), { textContent: "None", className: "muted" }));
}

// ---- chat -----------------------------------------------------------------------
function addMessage(role, text = "") {
  $(".empty")?.remove();
  const node = $("#tpl-message").content.firstElementChild.cloneNode(true);
  node.classList.add(role);
  node.querySelector(".bubble").textContent = text;
  $("#messages").append(node);
  node.scrollIntoView({ block: "end" });
  return node;
}

// Render "[1]" citation markers as superscripts without using innerHTML on model output.
function renderAnswer(bubble, text) {
  bubble.replaceChildren();
  for (const part of text.split(/(\[\d+\])/)) {
    if (/^\[\d+\]$/.test(part)) {
      const sup = document.createElement("span");
      sup.className = "cite";
      sup.textContent = part;
      bubble.append(sup);
    } else if (part) {
      bubble.append(document.createTextNode(part));
    }
  }
}

function renderSources(container, sources) {
  container.replaceChildren(...sources.map((s) => {
    const details = document.createElement("details");
    details.className = "source";
    const summary = document.createElement("summary");
    summary.textContent = `[${s.id}] ${s.filename}${s.heading ? ` › ${s.heading}` : ""} · score ${s.score.toFixed(2)}`;
    const snippet = document.createElement("p");
    snippet.textContent = s.snippet;
    details.append(summary, snippet);
    return details;
  }));
}

function addMeta(msg, text) {
  const span = document.createElement("span");
  span.textContent = text;
  msg.querySelector(".meta").append(span);
}

function addEscalate(msg, question) {
  const btn = document.createElement("button");
  btn.className = "ghost";
  btn.textContent = "Escalate to a human";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      await api("/tickets", { method: "POST", json: { question } });
      btn.textContent = "Escalated ✓";
      void refreshTickets();
    } catch (err) {
      btn.textContent = err.message;
    }
  });
  msg.querySelector(".meta").append(btn);
}

async function* readSse(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const fields = {};
      for (const line of block.split("\n")) {
        const sep = line.indexOf(": ");
        if (sep > 0) fields[line.slice(0, sep)] = line.slice(sep + 2);
      }
      if (fields.event) yield { name: fields.event, data: JSON.parse(fields.data || "{}") };
    }
  }
}

async function ask(question) {
  addMessage("user", question);
  const msg = addMessage("bot");
  const bubble = msg.querySelector(".bubble");
  bubble.classList.add("typing");
  let answer = "";
  try {
    const resp = await fetch(`${API}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}` },
      body: JSON.stringify({ question }),
    });
    if (resp.status === 401) { logout(); return; }
    if (!resp.ok) throw new Error(`Request failed (${resp.status})`);
    for await (const event of readSse(resp)) {
      if (event.name === "sources") renderSources(msg.querySelector(".sources"), event.data.sources);
      if (event.name === "context") {
        const { original_tokens: before, pruned_tokens: after, saved_ratio: saved } = event.data;
        addMeta(msg, `context pruned ${before} → ${after} tokens (−${Math.round(saved * 100)}%)`);
      }
      if (event.name === "token") { answer += event.data.text; renderAnswer(bubble, answer); }
      if (event.name === "error") throw new Error(event.data.message);
      if (event.name === "done" && !event.data.answerable) addEscalate(msg, question);
      msg.scrollIntoView({ block: "end" });
    }
  } catch (err) {
    bubble.textContent = `⚠ ${err.message}`;
  } finally {
    bubble.classList.remove("typing");
  }
}

function bindApp() {
  $("#ask-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#question");
    const question = input.value.trim();
    if (!question) return;
    input.value = "";
    $("#ask-btn").disabled = true;
    await ask(question);
    $("#ask-btn").disabled = false;
    input.focus();
  });

  $("#upload-input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    try {
      await api("/documents", { method: "POST", body });
    } catch (err) {
      alert(err.message);
    }
    e.target.value = "";
    void refreshDocuments();
  });

  $("#invite-btn").addEventListener("click", async () => {
    const out = $("#invite-code");
    try {
      const invite = await api("/invites", { method: "POST", json: { role: "member" } });
      out.textContent = invite.code;
    } catch (err) {
      out.textContent = err.message;
    }
    out.hidden = false;
  });
}

// ---- boot -------------------------------------------------------------------------
async function boot() {
  const [config, health] = await Promise.all([
    fetch(`${API}/config`).then((r) => r.json()).catch(() => ({ demo: false, signup: true })),
    fetch(`${API}/health`).then((r) => r.json()).catch(() => null),
  ]);
  if (health) {
    const badge = $("#rls-badge");
    const enforced = health.row_level_security === "enforced";
    badge.textContent = enforced ? "RLS enforced" : `RLS ${health.row_level_security}`;
    badge.className = `badge ${enforced ? "ok" : "warn"}`;
    badge.title = `database: ${health.database} · embeddings: ${health.embedding_provider} · llm: ${health.llm_provider}`;
    badge.hidden = false;
  }
  emptyChat = $("#messages").innerHTML;
  bindAuth(config);
  bindApp();

  state.token = loadToken();
  if (state.token) {
    try {
      state.user = await api("/auth/me");
      enterApp();
      return;
    } catch { /* fall through to login */ }
  }
  logout();
}

void boot();
