"use strict";

const state = {
  profile: null,
  profileName: "",
  verifyProfileText: "",
  verifyProfileFile: null,
  run: null,
  configFile: null,
  files: [],
  lastReport: null,
};

const byId = (id) => document.getElementById(id);

function showTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((panel) => panel.classList.toggle("active", panel.id === `panel-${name}`));
}

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => showTab(tab.dataset.tab)));

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function renderSearchResults(data) {
  const root = byId("search-results");
  if (!data.works.length) {
    root.innerHTML = '<div class="empty-state">No records found. Try a more specific or broader query.</div>';
    return;
  }
  root.innerHTML = data.works.map((work, index) => {
    const candidateUrl = work.landing_page || work.doi || work.openalex_id || "";
    const url = /^https?:\/\//i.test(candidateUrl) ? candidateUrl : "#";
    const meta = [work.year, work.type, work.venue, work.authors?.join(", ")].filter(Boolean).join(" · ");
    return `<article class="result-card">
      <div class="result-top">
        <a class="result-title" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(work.title || "Untitled record")}</a>
        <span class="candidate-tag">CANDIDATE · UNREVIEWED</span>
      </div>
      <p class="result-meta">${escapeHtml(meta || "Metadata not available")}${work.doi ? ` · DOI: ${escapeHtml(work.doi)}` : ""}</p>
      <div class="result-actions">
        <span class="muted">Review the source, methods, units, and applicability before relying on it.</span>
        <button class="button secondary add-evidence" type="button" data-index="${index}" ${state.profile ? "" : "disabled"}>Add candidate to profile</button>
      </div>
    </article>`;
  }).join("");
  root.querySelectorAll(".add-evidence").forEach((button) => button.addEventListener("click", () => {
    const work = data.works[Number(button.dataset.index)];
    addLiteratureCandidate(work);
  }));
}

byId("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = byId("search-query").value.trim();
  const status = byId("search-status");
  status.textContent = "Searching OpenAlex…";
  byId("search-results").innerHTML = "";
  try {
    const result = await postJson("/api/search", { query, limit: Number(byId("search-limit").value) });
    status.textContent = `${result.works.length} candidate record(s). Search retrieved ${result.retrieved_at_utc}.`;
    renderSearchResults(result);
  } catch (error) {
    status.textContent = error.message;
  }
});

function profileFromEditor() {
  try {
    const profile = JSON.parse(byId("profile-json").value);
    if (!profile || Array.isArray(profile) || typeof profile !== "object") throw new Error("Profile JSON root must be an object.");
    state.profile = profile;
    state.profileName = state.profileName || "edited-profile.json";
    byId("save-profile").disabled = false;
    renderQuestions();
    return true;
  } catch (error) {
    window.alert(`Profile JSON is invalid: ${error.message}`);
    return false;
  }
}

function renderQuestions() {
  const profile = state.profile;
  if (!profile) return;
  byId("profile-title").textContent = profile.title || profile.profile_id || "Research profile";
  byId("profile-name").textContent = state.profileName;
  const questions = profile.questions || [];
  const unresolvedCount = questions.filter((question) => question.status !== "resolved").length;
  byId("question-count").textContent = `${unresolvedCount} open`;
  const root = byId("questions-list");
  if (!questions.length) {
    root.className = "questions-list empty-state";
    root.textContent = "No open decisions are listed in this profile.";
    return;
  }
  root.className = "questions-list";
  root.innerHTML = questions.map((question, index) => `
    <article class="question-card">
      <div class="question-id">${escapeHtml(question.id || `Q-${index + 1}`)}</div>
      <h4>${escapeHtml(question.question || "Decision question missing")}</h4>
      <p>${escapeHtml(question.why || "")}</p>
      <div class="answer-row">
        <select data-question-status="${index}" aria-label="Decision status">
          <option value="unresolved" ${question.status !== "resolved" ? "selected" : ""}>Unresolved</option>
          <option value="resolved" ${question.status === "resolved" ? "selected" : ""}>Resolved</option>
        </select>
        <input data-question-answer="${index}" value="${escapeHtml(question.answer || "")}" placeholder="Record the decision and rationale">
      </div>
    </article>`).join("");
  root.querySelectorAll("[data-question-status]").forEach((control) => control.addEventListener("change", (event) => {
    const question = profile.questions[Number(event.target.dataset.questionStatus)];
    question.status = event.target.value;
    if (question.status === "resolved" && !question.answer) {
      question.answer = root.querySelector(`[data-question-answer="${event.target.dataset.questionStatus}"]`).value.trim();
      if (!question.answer) {
        question.status = "unresolved";
        event.target.value = "unresolved";
      }
    }
    updateProfileEditor();
  }));
  root.querySelectorAll("[data-question-answer]").forEach((control) => control.addEventListener("input", (event) => {
    profile.questions[Number(event.target.dataset.questionAnswer)].answer = event.target.value;
    updateProfileEditor();
  }));
}

function installProfile(profile, name) {
  state.profile = profile;
  state.profileName = name;
  byId("profile-json").value = JSON.stringify(profile, null, 2);
  byId("save-profile").disabled = false;
  renderQuestions();
  if (!byId("search-query").value && profile.research_question) {
    byId("search-query").value = profile.research_question;
  }
  document.querySelectorAll(".add-evidence").forEach((button) => { button.disabled = false; });
}

function updateProfileEditor() {
  byId("profile-json").value = JSON.stringify(state.profile, null, 2);
  const unresolvedCount = (state.profile.questions || []).filter((question) => question.status !== "resolved").length;
  byId("question-count").textContent = `${unresolvedCount} open`;
}

byId("profile-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    installProfile(JSON.parse(text), file.name);
  } catch (error) {
    window.alert(`Could not load profile JSON: ${error.message}`);
  }
});

byId("load-pilot").addEventListener("click", async () => {
  try {
    const response = await fetch("/api/pilot-profile");
    const profile = await response.json();
    if (!response.ok) throw new Error(profile.error || `Request failed (${response.status})`);
    installProfile(profile, "battery-estimation-pilot.json");
  } catch (error) {
    window.alert(`Could not load the battery pilot: ${error.message}`);
  }
});

byId("apply-profile").addEventListener("click", () => {
  if (!profileFromEditor()) return;
  state.profileName = state.profileName.replace(/\.json$/i, "") + "-edited.json";
  byId("profile-name").textContent = state.profileName;
});

byId("save-profile").addEventListener("click", () => {
  if (!profileFromEditor()) return;
  const blob = new Blob([`${JSON.stringify(state.profile, null, 2)}\n`], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = state.profileName || "research-profile.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
});

function addLiteratureCandidate(work) {
  if (!state.profile) return;
  const evidence = state.profile.evidence || (state.profile.evidence = []);
  const baseId = `LIT-${String(work.openalex_id || work.doi || work.title || "SOURCE").split("/").pop().replace(/[^A-Za-z0-9-]/g, "-").toUpperCase()}`;
  let id = baseId;
  let suffix = 2;
  while (evidence.some((item) => item.id === id)) id = `${baseId}-${suffix++}`;
  evidence.push({
    id,
    kind: "literature_candidate",
    reference: work.doi || work.landing_page || work.openalex_id || work.title,
    citation_metadata: {
      title: work.title,
      year: work.year,
      authors: work.authors,
      venue: work.venue,
      doi: work.doi,
      openalex_id: work.openalex_id,
      retrieved_from: "OpenAlex Works API",
    },
    claim: "Candidate source only; record and review the exact passage and applicability before using as evidence.",
    status: "candidate_unreviewed",
  });
  updateProfileEditor();
  byId("profile-name").textContent = `${state.profileName} · unsaved changes`;
}

byId("verify-profile-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  state.verifyProfileFile = file || null;
  state.verifyProfileText = file ? await file.text() : "";
  byId("verify-profile-name").textContent = file ? `${file.name} · ${file.size.toLocaleString()} bytes` : "No file selected";
  updateVerifyButton();
});

byId("run-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  state.run = null;
  if (file) {
    try {
      state.run = JSON.parse(await file.text());
      byId("run-name").textContent = `${file.name} · ${state.run.run_id || "run id missing"}`;
    } catch (error) {
      byId("run-name").textContent = `Invalid JSON: ${error.message}`;
    }
  } else {
    byId("run-name").textContent = "No file selected";
  }
  updateVerifyButton();
});

byId("config-file").addEventListener("change", (event) => {
  state.configFile = event.target.files[0] || null;
  byId("config-name").textContent = state.configFile
    ? `${state.configFile.name} · ${state.configFile.size.toLocaleString()} bytes`
    : "Needed to check config_sha256";
  updateVerifyButton();
});

byId("output-files").addEventListener("change", (event) => {
  state.files = Array.from(event.target.files || []);
  byId("output-names").textContent = state.files.length
    ? `${state.files.length} file(s): ${state.files.slice(0, 3).map((file) => file.webkitRelativePath || file.name).join(", ")}${state.files.length > 3 ? " …" : ""}`
    : "No files selected";
});

function updateVerifyButton() {
  byId("verify-button").disabled = !(state.verifyProfileText && state.run && state.configFile);
}

async function fileToBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return btoa(binary);
}

function renderReport(report) {
  state.lastReport = report;
  const root = byId("verify-report");
  const failed = report.verdict === "blocked";
  let html = `<article class="verdict-card">
    <div class="verdict-head">
      <h3 class="verdict-title ${failed ? "failed" : "passed"}">${failed ? "BLOCKED — evidence incomplete or checks failed" : "Configured checks passed"}</h3>
      <span class="report-id">${escapeHtml(report.run_id || "RUN")} · ${escapeHtml(report.profile_id || "")}</span>
    </div>`;
  const dimensions = report.dimensions || {};
  const invariants = dimensions.model_invariants || [];
  const artifacts = dimensions.artifact_integrity || [];
  const blockers = report.blockers || [];
  html += `<div class="report-block"><h4>Configured model invariants</h4>${invariants.map((item) => `<div class="report-line"><span class="check-status ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span><span><strong>${escapeHtml(item.id)}</strong> — ${escapeHtml(item.detail)}</span></div>`).join("") || '<div class="muted">No invariant checks recorded.</div>'}</div>`;
  html += `<div class="report-block"><h4>Evidence dimensions</h4>
    <div class="report-line"><span class="check-status ${escapeHtml(dimensions.recorded_run_reproducibility?.status || "not_assessed")}">${escapeHtml(dimensions.recorded_run_reproducibility?.status || "not assessed")}</span><span>Recorded-run reproducibility — ${escapeHtml(dimensions.recorded_run_reproducibility?.detail || "")}</span></div>
    <div class="report-line"><span class="check-status ${escapeHtml(dimensions.profile_conformance?.status || "not_assessed")}">${escapeHtml(dimensions.profile_conformance?.status || "not assessed")}</span><span>Profile decisions</span></div>
    <div class="report-line"><span class="check-status ${escapeHtml(dimensions.configuration_integrity?.status || "not_assessed")}">${escapeHtml(dimensions.configuration_integrity?.status || "not assessed")}</span><span>Configuration hash — ${escapeHtml(dimensions.configuration_integrity?.detail || "")}</span></div>
    <div class="report-line"><span class="check-status ${escapeHtml(dimensions.external_validation || "not_assessed")}">${escapeHtml(dimensions.external_validation || "not assessed")}</span><span>External validation</span></div>
    <div class="report-line"><span class="check-status not_assessed">not established</span><span>Scientific validity — not established by this app</span></div>
    ${artifacts.map((item) => `<div class="report-line"><span class="check-status ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span><span>Artifact ${escapeHtml(item.path || "")} — ${escapeHtml(item.detail)}</span></div>`).join("")}
    </div>`;
  if (blockers.length) {
    html += `<div class="report-block"><h4>Blockers (${blockers.length})</h4>${blockers.map((item) => `<div class="report-line blocker"><span>•</span><span>${escapeHtml(item)}</span></div>`).join("")}</div>`;
  }
  html += '<div class="report-block report-download"><button id="download-report" class="button secondary" type="button">Download audit report JSON</button></div>';
  html += "</article>";
  root.innerHTML = html;
  byId("download-report").addEventListener("click", () => {
    const blob = new Blob([`${JSON.stringify(state.lastReport, null, 2)}\n`], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${report.run_id || "run"}-assurance-report.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  });
}

byId("verify-button").addEventListener("click", async () => {
  const button = byId("verify-button");
  const status = byId("verify-status");
  button.disabled = true;
  status.textContent = "Verifying selected evidence locally…";
  byId("verify-report").innerHTML = "";
  try {
    const uploaded = [];
    const matchedOutputs = [];
    const outputs = state.run.outputs;
    if (!Array.isArray(outputs) || outputs.length === 0) {
      throw new Error("The run manifest must list output files to verify.");
    }
    const selected = state.files.map((file) => ({
      file,
      path: (file.webkitRelativePath || file.name).replaceAll("\\", "/"),
    }));
    for (const output of outputs) {
      const expectedPath = output.path.replaceAll("\\", "/");
      let candidates = selected.filter((item) => item.path === expectedPath);
      if (candidates.length === 0) {
        candidates = selected.filter((item) => item.path.endsWith(`/${expectedPath}`));
      }
      if (candidates.length !== 1) {
        throw new Error(`Could not uniquely match output file "${expectedPath}" in the selected folder.`);
      }
      matchedOutputs.push({ path: expectedPath, file: candidates[0].file });
    }
    const payloadBytes = matchedOutputs.reduce(
      (sum, item) => sum + item.file.size,
      state.configFile.size + state.verifyProfileFile.size,
    );
    if (payloadBytes > 17 * 1024 * 1024) {
      throw new Error("Selected profile, configuration, and outputs exceed the 17 MiB desktop upload limit.");
    }
    for (const item of matchedOutputs) {
      uploaded.push({ path: item.path, content_base64: await fileToBase64(item.file) });
    }
    const report = await postJson("/api/verify", {
      profile_base64: await fileToBase64(state.verifyProfileFile),
      run: state.run,
      config_base64: await fileToBase64(state.configFile),
      files: uploaded,
    });
    renderReport(report);
    status.textContent = "Verification report generated. The report is intentionally not a scientific-validity certificate.";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
    updateVerifyButton();
  }
});
