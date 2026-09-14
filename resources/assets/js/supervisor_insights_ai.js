(function () {
  "use strict";

  const sectionLabels = [
    ["overall", "OVERALL INTERPRETATION"],
    ["happened", "WHAT HAPPENED"],
    ["improve", "WHAT TO IMPROVE"],
    ["feedback", "FEEDBACK SIGNAL"],
    ["next", "NEXT FOCUS"],
  ];

  function setSection(root, name, value) {
    const node = root.querySelector(`[data-ai-section="${name}"]`);
    if (node) {
      node.textContent = value || "Not enough evidence is available for this part of the explanation.";
    }
  }

  function parseAnswer(root, answer, evidence) {
    const text = String(answer || "").replace(/\r/g, "").trim();
    const found = [];

    sectionLabels.forEach(([key, label]) => {
      const index = text.toUpperCase().indexOf(`${label}:`);
      if (index >= 0) found.push({ key, label, index });
    });

    found.sort((a, b) => a.index - b.index);
    if (!found.length) {
      setSection(root, "overall", text);
      setSection(root, "happened", "Use the evidence cards above for the current measured results.");
      setSection(root, "improve", "Prioritize the lowest-supported evidence area without changing or replacing the Official OJT Evaluation.");
      setSection(root, "feedback", evidence.feedback_evidence ? "Use the Feedback Analysis panel for the current model signals." : "No supervisor feedback evidence is available yet.");
      setSection(root, "next", "Review the current evidence and follow the existing ML recommendation where Work data is available.");
      return;
    }

    const values = {};
    found.forEach((entry, index) => {
      const start = entry.index + entry.label.length + 1;
      const end = index + 1 < found.length ? found[index + 1].index : text.length;
      values[entry.key] = text.slice(start, end).trim().replace(/^[-•]\s*/, "");
    });
    sectionLabels.forEach(([key]) => setSection(root, key, values[key]));
  }

  function evidenceHash(value) {
    const text = JSON.stringify(value);
    let hash = 0;
    for (let index = 0; index < text.length; index += 1) {
      hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0;
    }
    return String(hash);
  }

  function hasEvidence(evidence) {
    return Boolean(
      evidence.work_evidence ||
      evidence.feedback_evidence ||
      Number(evidence.daily_rated_days || 0) > 0 ||
      Number(evidence.logbook_total || 0) > 0 ||
      Number(evidence.attendance_hours || 0) > 0 ||
      evidence.official_status
    );
  }

  function buildPrompt(evidence) {
    return [
      "Explain this intern's Nexora evidence to a supervisor using only the JSON below.",
      "Keep OJT Hours, Daily Performance, Logbook, Work, feedback ML, and Official Evaluation separate. Do not invent trends, causes, missing Work, behavior, or feedback details. Do not calculate an overall OJT grade. Official Evaluation is manual and must never be replaced by ML or AI.",
      "Return exactly five concise labeled sections:",
      "OVERALL INTERPRETATION:",
      "WHAT HAPPENED:",
      "WHAT TO IMPROVE:",
      "FEEDBACK SIGNAL:",
      "NEXT FOCUS:",
      `Data: ${JSON.stringify(evidence)}`,
    ].join("\n");
  }

  async function runAnalysis(root) {
    if (!root || root.dataset.aiInitialized === "true") return;
    root.dataset.aiInitialized = "true";

    const status = root.querySelector("[data-ai-status]");
    const items = root.querySelector("[data-ai-items]");
    const evidenceNode = root.querySelector("[data-supervisor-insights-ai-evidence]");
    if (!status || !items || !evidenceNode) return;

    let evidence;
    try {
      evidence = JSON.parse(evidenceNode.textContent || "{}");
    } catch (error) {
      status.textContent = "Nexora AI could not read the current evidence. The evidence cards above are unaffected.";
      items.hidden = true;
      return;
    }

    if (!hasEvidence(evidence)) {
      status.textContent = "Not enough evidence is available for an AI explanation yet.";
      items.hidden = true;
      return;
    }

    const cacheKey = `nxSupervisorInsightAi:${root.dataset.classroomId || "0"}:${root.dataset.studentId || "0"}:${evidenceHash(evidence)}`;
    try {
      const cached = window.sessionStorage.getItem(cacheKey);
      if (cached) {
        parseAnswer(root, cached, evidence);
        status.textContent = "AI explanation generated from the current evidence.";
        items.hidden = false;
        return;
      }
    } catch (error) {}

    status.textContent = "Analyzing the current evidence…";
    items.hidden = true;

    try {
      const response = await fetch(root.dataset.aiEndpoint || "/assistant/ask", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": root.dataset.csrfToken || "",
        },
        body: JSON.stringify({ question: buildPrompt(evidence) }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "AI request failed.");
      if (!data.available || !data.answer) {
        status.textContent = "Nexora AI is not enabled on this server yet. The existing evidence and ML recommendation remain available.";
        return;
      }

      parseAnswer(root, data.answer, evidence);
      status.textContent = "AI explanation generated from the current evidence.";
      items.hidden = false;
      try {
        window.sessionStorage.setItem(cacheKey, data.answer);
      } catch (error) {}
    } catch (error) {
      status.textContent = "Nexora AI explanation is temporarily unavailable. The existing evidence and ML recommendation are unaffected.";
      items.hidden = true;
    }
  }

  function init(scope) {
    const root = scope || document;
    const candidates = [];
    if (root.matches && root.matches("[data-supervisor-insights-ai]")) candidates.push(root);
    if (root.querySelectorAll) {
      root.querySelectorAll("[data-supervisor-insights-ai]").forEach((node) => candidates.push(node));
    }
    candidates.forEach(runAnalysis);
  }

  window.initSupervisorInsightsAi = init;
  document.addEventListener("DOMContentLoaded", () => init(document));
})();
