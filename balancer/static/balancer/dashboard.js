"use strict";

const $ = (selector) => document.querySelector(selector);
const csrf = $("[name=csrfmiddlewaretoken]").value;
let editing = null;
let selectedRun = null;
let pollTimer = null;
let historyUrl = "/api/runs/";
let previousUrl = null;
let nextUrl = null;
const descriptions = {
  first_fit: "Choose the first eligible server by ID.",
  round_robin: "Rotate through eligible servers in a stable order.",
  least_connections: "Choose the eligible server with the fewest active requests. Ties use server ID.",
  fastest_server: "Choose the eligible server with the highest CPU capacity. Ties use server ID.",
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function notice(error) {
  $("#notice").textContent = error instanceof Error ? error.message : String(error);
  $("#notice").hidden = false;
}

async function api(url, options = {}) {
  const headers = { "X-CSRFToken": csrf, ...options.headers };
  const response = await fetch(url, { ...options, headers });
  if (response.status === 204) return null;
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || body.error || JSON.stringify(body));
  return body;
}

function action(text, callback, danger = false) {
  const button = element("button", text, `secondary small${danger ? " danger" : ""}`);
  button.type = "button";
  button.addEventListener("click", () => Promise.resolve().then(callback).catch(notice));
  return button;
}

function resetServer() {
  editing = null;
  $("#server-form").reset();
  $("#server-form [name=id]").disabled = false;
  $("#server-form-title").textContent = "Add server";
  $("#save-server").textContent = "Add server";
  $("#cancel-edit").hidden = true;
}

async function loadServers() {
  const servers = await api("/api/servers/");
  $("#server-count").textContent = `${servers.length} servers`;
  $("#servers").replaceChildren();
  for (const server of servers) {
    const row = element("tr");
    for (const key of ["id", "cpu_units_per_tick", "mem_mb", "rate_limit_per_sec"]) {
      row.append(element("td", server[key]));
    }
    const controls = element("td");
    const buttons = element("div", undefined, "row-actions");
    buttons.append(action("Edit", () => {
      editing = server.id;
      for (const [key, value] of Object.entries(server)) {
        $(`#server-form [name=${key}]`).value = value;
      }
      $("#server-form [name=id]").disabled = true;
      $("#server-form-title").textContent = `Edit ${server.id}`;
      $("#save-server").textContent = "Save changes";
      $("#cancel-edit").hidden = false;
      $("#server-form [name=cpu_units_per_tick]").focus();
    }));
    buttons.append(action("Delete", async () => {
      await api(`/api/servers/${encodeURIComponent(server.id)}/`, { method: "DELETE" });
      if (editing === server.id) resetServer();
      await loadServers();
    }, true));
    controls.append(buttons);
    row.append(controls);
    $("#servers").append(row);
  }
  if (!servers.length) {
    const cell = element("td", "No servers yet. Add a server to run simulations.");
    cell.colSpan = 5;
    const row = element("tr");
    row.append(cell);
    $("#servers").append(row);
  }
}

async function loadHistory(url = historyUrl) {
  const data = await api(url);
  historyUrl = url;
  previousUrl = data.previous;
  nextUrl = data.next;
  $("#previous-page").disabled = !previousUrl;
  $("#next-page").disabled = !nextUrl;
  $("#runs").replaceChildren();
  for (const run of data.results) {
    const row = element("tr");
    row.append(element("td", new Date(run.created_at).toLocaleString()), element("td", run.mode),
      element("td", run.strategy.replaceAll("_", " ")));
    const status = element("td");
    status.append(element("span", run.status, `status ${run.status}`));
    const controls = element("td");
    controls.append(action("View", () => selectRun(run.id)));
    row.append(status, controls);
    $("#runs").append(row);
  }
  if (!data.results.length) {
    const row = element("tr");
    const cell = element("td", "No runs yet. Upload a CSV to start.");
    cell.colSpan = 5;
    row.append(cell);
    $("#runs").append(row);
  }
}

function renderResults(run) {
  $("#results").hidden = false;
  $("#run-status").textContent = `${run.mode} / ${run.strategy.replaceAll("_", " ")} · ${run.status}${run.error ? `: ${run.error}` : ""}`;
  $("#snapshots").textContent = JSON.stringify({ servers: run.server_snapshot, requests: run.request_snapshot }, null, 2);
  const ready = run.status === "succeeded";
  $("#download-trace").hidden = !ready;
  $("#download-trace").href = `/api/runs/${run.id}/trace/`;
  $("#metrics").replaceChildren();
  $("#timeline").replaceChildren();
  $("#server-metrics").replaceChildren();
  $("#validation-status").textContent = ready
    ? `Replay validation: passed. Original validator: ${run.validation.original === "passed" ? "passed" : "not applicable to concurrent execution"}.`
    : "Results become available after simulation and trace validation finish.";
  if (!ready) return;
  const summary = run.summary;
  for (const [label, value] of [["Requests", summary.total_requests], ["Finished", summary.finished],
    ["Dropped", summary.dropped], ["Average wait", summary.avg_wait_ticks === null ? "—" : `${summary.avg_wait_ticks.toFixed(2)} ticks`],
    ["P95 wait", summary.p95_wait_ticks === null ? "—" : `${summary.p95_wait_ticks} ticks`]]) {
    const metric = element("div", undefined, "metric");
    metric.append(element("strong", value), element("span", label));
    $("#metrics").append(metric);
  }
  for (const server of summary.per_server) {
    const row = element("tr");
    for (const value of [server.server_id, server.finished, server.work_units,
      `${(server.cpu_utilization * 100).toFixed(1)}%`, server.throughput_per_tick.toFixed(3)]) {
      row.append(element("td", value));
    }
    $("#server-metrics").append(row);
  }
  const origin = Math.min(...summary.outcomes.map((outcome) => outcome.arrival));
  const duration = Math.max(1, summary.end_tick - origin);
  for (const outcome of summary.outcomes) {
    const row = element("tr");
    row.append(element("td", outcome.request_id), element("td", outcome.server_id ?? "Dropped"));
    const cell = element("td");
    if (outcome.start !== null) {
      const track = element("div", undefined, "track");
      for (const [start, end, color] of [[outcome.arrival, outcome.start, "wait"],
        [outcome.start, outcome.finish, "execution"]]) {
        if (end <= start) continue;
        const bar = element("span", undefined, `bar ${color}`);
        bar.style.left = `${100 * (start - origin) / duration}%`;
        bar.style.width = `${100 * (end - start) / duration}%`;
        track.append(bar);
      }
      cell.append(track);
    } else cell.textContent = "Memory exceeds every server";
    row.append(cell, element("td", `${outcome.arrival} / ${outcome.start ?? "—"} / ${outcome.finish ?? "—"}`));
    $("#timeline").append(row);
  }
}

async function selectRun(id) {
  selectedRun = id;
  clearTimeout(pollTimer);
  const run = await api(`/api/runs/${id}/`);
  if (selectedRun !== id) return;
  renderResults(run);
  if (["queued", "running"].includes(run.status)) {
    pollTimer = setTimeout(() => selectRun(id).then(() => loadHistory()).catch(notice), 1200);
  }
}

$("#server-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#save-server").disabled = true;
  $("#notice").hidden = true;
  try {
    const form = new FormData(event.currentTarget);
    const data = Object.fromEntries(form);
    delete data.csrfmiddlewaretoken;
    for (const key of ["cpu_units_per_tick", "mem_mb", "rate_limit_per_sec"]) data[key] = Number(data[key]);
    await api(editing ? `/api/servers/${encodeURIComponent(editing)}/` : "/api/servers/", {
      method: editing ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
    });
    resetServer();
    await loadServers();
  } catch (error) { notice(error); }
  finally { $("#save-server").disabled = false; }
});

$("#run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#start-run").disabled = true;
  $("#notice").hidden = true;
  try {
    const run = await api("/api/runs/", { method: "POST", body: new FormData(event.currentTarget) });
    await loadHistory("/api/runs/");
    await selectRun(run.id);
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { notice(error); }
  finally { $("#start-run").disabled = false; }
});
$("#cancel-edit").addEventListener("click", resetServer);
$("#refresh-history").addEventListener("click", () => loadHistory().catch(notice));
$("#previous-page").addEventListener("click", () => { if (previousUrl) loadHistory(previousUrl).catch(notice); });
$("#next-page").addEventListener("click", () => { if (nextUrl) loadHistory(nextUrl).catch(notice); });
$("[name=strategy]").addEventListener("change", (event) => {
  $("#strategy-description").textContent = descriptions[event.target.value];
});
$("#strategy-description").textContent = descriptions.first_fit;
Promise.all([loadServers(), loadHistory()]).catch(notice);
