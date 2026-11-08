"use strict";

const $ = (selector) => document.querySelector(selector);
const csrf = $("[name=csrfmiddlewaretoken]").value;
const modelNames = { sequential: "Sequential", concurrent: "Concurrent" };
const strategyNames = {
  first_fit: "First fit", round_robin: "Round robin",
  least_connections: "Least connections", fastest_server: "Fastest server",
};
const descriptions = {
  first_fit: "Use the first server with enough capacity, ordered by server ID.",
  round_robin: "Take turns across servers, skipping any that cannot accept the next request.",
  least_connections: "Use the eligible server with the fewest running requests. Ties use server ID.",
  fastest_server: "Use the eligible server with the most CPU units per second. Ties use server ID.",
};
const modelDescriptions = {
  sequential: "One request runs on a server at a time, using its full CPU. This model passes the supplied validator.",
  concurrent: "Requests can run together when memory allows. They share CPU equally and keep their memory until they finish.",
};
const statusNames = { queued: "Queued", running: "Running", succeeded: "Completed", failed: "Failed" };
let editing = null;
let deleting = null;
let selectedRun = null;
let pollTimer = null;
let historyUrl = "/api/runs/";
let previousUrl = null;
let nextUrl = null;
let historySequence = 0;
let serverCount = 0;
let submitting = false;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function revealElement(node) {
  node.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
}

function notice(error) {
  $("#feedback").hidden = true;
  $("#notice").textContent = error instanceof Error ? error.message : String(error);
  $("#notice").hidden = false;
  $("#notice").focus({ preventScroll: true });
  revealElement($("#notice"));
}

function feedback(text) {
  $("#notice").hidden = true;
  $("#feedback").textContent = text;
  $("#feedback").hidden = false;
}

function errorText(body) {
  if (typeof body === "string") return body;
  if (Array.isArray(body)) return body.map(errorText).join(" ");
  if (body && typeof body === "object") {
    if (body.detail || body.error) return errorText(body.detail || body.error);
    return Object.entries(body).map(([key, value]) => `${key.replaceAll("_", " ")}: ${errorText(value)}`).join("\n");
  }
  return "The request could not be completed.";
}

async function api(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { ...options, headers: { "X-CSRFToken": csrf, ...options.headers } });
  } catch {
    throw new Error("Cannot reach the server. Check that the application is running, then try again.");
  }
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body ? errorText(body) : `The server returned HTTP ${response.status}. Please try again.`);
  if (body === null) throw new Error("The server returned an unexpected response. Refresh the page and try again.");
  return body;
}

function action(text, callback, danger = false) {
  const button = element("button", text, `secondary small${danger ? " danger" : ""}`);
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await callback(); } catch (error) { notice(error); }
    finally { button.disabled = false; }
  });
  return button;
}

function resetServer() {
  editing = null;
  $("#server-form").reset();
  $("#server-id").disabled = false;
  $("#server-form-title").textContent = "Add a server";
  $("#save-server").textContent = "Add server";
  $("#cancel-edit").hidden = true;
}

function updateReadiness() {
  $("#start-run").disabled = submitting || serverCount === 0;
  $("#start-run").textContent = submitting ? "Submitting…" : "Run simulation";
  $("#run-readiness").textContent = serverCount === 0
    ? "Add at least one server in step 1 before running."
    : "Every run is saved and validated before results are available.";
}

async function loadServers() {
  const servers = await api("/api/servers/");
  serverCount = servers.length;
  updateReadiness();
  $("#cluster-summary").replaceChildren(...[
    `${serverCount} ${serverCount === 1 ? "server" : "servers"}`,
    `${servers.reduce((sum, server) => sum + server.cpu_units_per_tick, 0)} CPU units / s`,
    `${servers.reduce((sum, server) => sum + server.mem_mb, 0).toLocaleString()} MB total memory`,
  ].map((text) => element("span", text)));
  $("#servers").replaceChildren();
  for (const server of servers) {
    const row = element("tr");
    for (const key of ["id", "cpu_units_per_tick", "mem_mb", "rate_limit_per_sec"]) row.append(element("td", server[key]));
    const controls = element("td");
    const buttons = element("div", undefined, "row-actions");
    buttons.append(action("Edit", () => {
      editing = server.id;
      for (const [key, value] of Object.entries(server)) $(`#server-form [name=${key}]`).value = value;
      $("#server-id").disabled = true;
      $("#server-form-title").textContent = `Edit server ${server.id}`;
      $("#save-server").textContent = "Save changes";
      $("#cancel-edit").hidden = false;
      revealElement($("#server-form"));
      $("#server-cpu").focus({ preventScroll: true });
    }));
    buttons.append(action("Delete", () => {
      deleting = server.id;
      $("#delete-description").textContent = `Remove ${server.id} from the cluster for future runs?`;
      $("#delete-dialog").showModal();
    }, true));
    controls.append(buttons);
    row.append(controls);
    $("#servers").append(row);
  }
  if (!servers.length) {
    const cell = element("td", "Your cluster is empty. Add a server below to get started.");
    cell.colSpan = 5;
    const row = element("tr");
    row.append(cell);
    $("#servers").append(row);
  }
}

function highlightRun() {
  for (const row of $("#runs").children) row.classList.toggle("selected", row.dataset.runId === selectedRun);
}

async function loadHistory(url = historyUrl) {
  const sequence = ++historySequence;
  const data = await api(url);
  if (sequence !== historySequence) return;
  historyUrl = url;
  previousUrl = data.previous;
  nextUrl = data.next;
  $("#previous-page").disabled = !previousUrl;
  $("#next-page").disabled = !nextUrl;
  $("#history-count").textContent = `${data.count} saved ${data.count === 1 ? "run" : "runs"}. Select View to inspect inputs, results, and the trace.`;
  $("#runs").replaceChildren();
  for (const run of data.results) {
    const row = element("tr");
    row.dataset.runId = run.id;
    const shortId = element("td", run.id.slice(0, 8));
    shortId.title = run.id;
    row.append(shortId, element("td", new Date(run.created_at).toLocaleString()),
      element("td", modelNames[run.mode]), element("td", strategyNames[run.strategy]));
    const status = element("td");
    status.append(element("span", statusNames[run.status], `status ${run.status}`));
    const controls = element("td");
    controls.append(action("View", () => selectRun(run.id, true)));
    row.append(status, controls);
    $("#runs").append(row);
  }
  highlightRun();
  if (!data.results.length) {
    const row = element("tr");
    const cell = element("td", "No saved runs yet. Try the sample requests in step 2.");
    cell.colSpan = 6;
    row.append(cell);
    $("#runs").append(row);
  }
}

function renderResults(run) {
  $("#results").hidden = false;
  $("#run-identity").textContent = `${modelNames[run.mode]} · ${strategyNames[run.strategy]} · Run ${run.id.slice(0, 8)} · ${new Date(run.created_at).toLocaleString()}`;
  $("#run-badge").textContent = statusNames[run.status];
  $("#run-badge").className = `status ${run.status}`;
  $("#run-status").textContent = {
    queued: "Waiting for a worker. This run is saved; you can find it in history later.",
    running: "Running the simulation and validating CPU, memory, start budgets, and request lifecycles.",
    succeeded: "Completed and validated. Your results and trace are ready.",
    failed: `This run could not complete. ${run.error}`,
  }[run.status];
  $("#snapshots").textContent = JSON.stringify({ servers: run.server_snapshot, requests: run.request_snapshot }, null, 2);
  const ready = run.status === "succeeded";
  $("#download-trace").hidden = !ready;
  $("#download-trace").href = `/api/runs/${run.id}/trace/`;
  $("#result-details").hidden = !ready;
  $("#validation-status").textContent = ready
    ? (run.validation.original === "passed"
      ? "Passed both the supplied sequential validator and independent replay."
      : "Passed independent replay for shared CPU. The supplied validator only supports sequential runs.")
    : "Results become available only after validation succeeds. Use Refresh run if automatic updates are interrupted.";
  if (!ready) return;
  const summary = run.summary;
  const origin = Math.min(...summary.outcomes.map((outcome) => outcome.arrival));
  const elapsed = summary.end_tick - origin;
  const duration = Math.max(1, elapsed);
  $("#metrics").replaceChildren();
  for (const [label, value, help] of [
    ["Requests", summary.total_requests, "All requests in the uploaded CSV"],
    ["Completed", summary.finished, "Requests that finished successfully"],
    ["Dropped", summary.dropped, "Requests whose memory exceeds every server"],
    ["Average wait", summary.avg_wait_ticks === null ? "—" : `${summary.avg_wait_ticks.toFixed(2)} s`, "Time in the queue, excluding dropped requests"],
    ["P95 wait", summary.p95_wait_ticks === null ? "—" : `${summary.p95_wait_ticks} s`, "95% of started requests waited this long or less"],
    ["Duration", `${elapsed} s`, "Time from the first arrival to the last event"],
  ]) {
    const metric = element("div", undefined, "metric");
    metric.title = help;
    metric.append(element("strong", value), element("span", label));
    $("#metrics").append(metric);
  }
  $("#drop-explanation").hidden = summary.dropped === 0;
  $("#drop-explanation").textContent = `${summary.dropped} requests were dropped at arrival because their memory exceeded every server. Increase a server’s memory for a future run to make those requests feasible.`;
  $("#server-metrics").replaceChildren();
  for (const server of summary.per_server) {
    const row = element("tr");
    for (const value of [server.server_id, server.finished, server.work_units,
      `${(server.cpu_utilization * 100).toFixed(1)}%`, server.throughput_per_tick.toFixed(3)]) row.append(element("td", value));
    $("#server-metrics").append(row);
  }
  $("#timeline-window").textContent = `Time window: ${origin}–${summary.end_tick} s`;
  $("#timeline").replaceChildren();
  for (const outcome of summary.outcomes) {
    const row = element("tr");
    row.append(element("td", outcome.request_id), element("td", outcome.server_id ?? "—"));
    const cell = element("td");
    if (outcome.start !== null) {
      const track = element("div", undefined, "track");
      for (const [start, end, color] of [[outcome.arrival, outcome.start, "wait"], [outcome.start, outcome.finish, "execution"]]) {
        if (end <= start) continue;
        const bar = element("span", undefined, `bar ${color}`);
        bar.style.left = `${100 * (start - origin) / duration}%`;
        bar.style.width = `${100 * (end - start) / duration}%`;
        track.append(bar);
      }
      cell.append(track);
    } else cell.append(element("span", "Dropped at arrival", "status failed"));
    row.append(cell);
    for (const value of [outcome.arrival, outcome.start ?? "—", outcome.finish ?? "—",
      outcome.start === null ? "—" : outcome.start - outcome.arrival]) row.append(element("td", value));
    $("#timeline").append(row);
  }
}

async function selectRun(id, reveal = false) {
  selectedRun = id;
  clearTimeout(pollTimer);
  const run = await api(`/api/runs/${id}/`);
  if (selectedRun !== id) return;
  renderResults(run);
  highlightRun();
  if (reveal) {
    $("#results").focus({ preventScroll: true });
    revealElement($("#results"));
  }
  if (["queued", "running"].includes(run.status)) {
    pollTimer = setTimeout(() => selectRun(id).then(() => loadHistory()).catch(notice), 1200);
  }
}

$("#server-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#save-server").disabled = true;
  $("#notice").hidden = true;
  const serverId = editing;
  try {
    const data = Object.fromEntries(new FormData(event.currentTarget));
    delete data.csrfmiddlewaretoken;
    for (const key of ["cpu_units_per_tick", "mem_mb", "rate_limit_per_sec"]) data[key] = Number(data[key]);
    await api(serverId ? `/api/servers/${encodeURIComponent(serverId)}/` : "/api/servers/", {
      method: serverId ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
    });
    resetServer();
    await loadServers();
    feedback(`Server ${serverId || data.id} ${serverId ? "updated" : "added"}. New runs will use this configuration.`);
  } catch (error) { notice(error); }
  finally { $("#save-server").disabled = false; }
});

$("#confirm-delete").addEventListener("click", async () => {
  const id = deleting;
  if (id === null) return;
  $("#confirm-delete").disabled = true;
  try {
    await api(`/api/servers/${encodeURIComponent(id)}/`, { method: "DELETE" });
    if (editing === id) resetServer();
    await loadServers();
    feedback(`Server ${id} deleted. Saved runs retain their original inputs.`);
  } catch (error) { notice(error); }
  finally {
    $("#delete-dialog").close();
    $("#confirm-delete").disabled = false;
  }
});
$("#cancel-delete").addEventListener("click", () => $("#delete-dialog").close());
$("#delete-dialog").addEventListener("close", () => { deleting = null; });

$("#requests-file").addEventListener("change", () => {
  const file = $("#requests-file").files[0];
  $("#file-status").textContent = file ? `${file.name} · ${file.size.toLocaleString()} bytes` : "Choose a file or use the sample.";
});
$("#use-sample").addEventListener("click", async () => {
  $("#use-sample").disabled = true;
  try {
    const response = await fetch($("#sample-download").href);
    if (!response.ok) throw new Error("Could not load the sample CSV. Try the download link or upload your own file.");
    const transfer = new DataTransfer();
    transfer.items.add(new File([await response.blob()], "requests.csv", { type: "text/csv" }));
    $("#requests-file").files = transfer.files;
    $("#requests-file").dispatchEvent(new Event("change", { bubbles: true }));
    feedback("Sample requests are ready. Choose an execution model and strategy, then run the simulation.");
  } catch (error) { notice(error); }
  finally { $("#use-sample").disabled = false; }
});

$("#run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  submitting = true;
  updateReadiness();
  $("#notice").hidden = true;
  $("#feedback").hidden = true;
  try {
    const run = await api("/api/runs/", { method: "POST", body: new FormData(event.currentTarget) });
    await loadHistory("/api/runs/");
    await selectRun(run.id, true);
  } catch (error) { notice(error); }
  finally { submitting = false; updateReadiness(); }
});
$("#cancel-edit").addEventListener("click", resetServer);
$("#refresh-servers").addEventListener("click", () => loadServers().catch(notice));
$("#refresh-history").addEventListener("click", () => loadHistory().catch(notice));
$("#refresh-run").addEventListener("click", () => { if (selectedRun) selectRun(selectedRun).then(() => loadHistory()).catch(notice); });
$("#previous-page").addEventListener("click", () => { if (previousUrl) loadHistory(previousUrl).catch(notice); });
$("#next-page").addEventListener("click", () => { if (nextUrl) loadHistory(nextUrl).catch(notice); });
$("#run-strategy").addEventListener("change", (event) => { $("#strategy-description").textContent = descriptions[event.target.value]; });
$("#run-mode").addEventListener("change", (event) => { $("#model-description").textContent = modelDescriptions[event.target.value]; });
$("#strategy-description").textContent = descriptions.first_fit;
$("#model-description").textContent = modelDescriptions.sequential;
Promise.all([loadServers(), loadHistory()]).catch(notice);
