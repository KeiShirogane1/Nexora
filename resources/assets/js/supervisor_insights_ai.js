(function () {
  "use strict";

  if (window.__nexoraSupervisorInsightsUiLoaded) return;
  window.__nexoraSupervisorInsightsUiLoaded = true;

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

  function formatNumber(value, suffix) {
    const number = Number(value);
    if (!Number.isFinite(number)) return null;
    const text = Number.isInteger(number) ? String(number) : number.toFixed(1);
    return `${text}${suffix || ""}`;
  }

  function renderEvidenceFallback(root, evidence) {
    const overall = ["Live AI could not complete the response, so Nexora is summarizing the current evidence directly."];
    const happened = [];
    const improve = [];
    const next = [];

    const dailyAverage = formatNumber(evidence.daily_average, "%");
    const dailyRatedDays = formatNumber(evidence.daily_rated_days, "");
    const attendanceHours = formatNumber(evidence.attendance_hours, " hours");
    const requiredHours = formatNumber(evidence.required_hours, " hours");
    const workAverage = formatNumber(evidence.work_average, "%");
    const workReviewed = formatNumber(evidence.work_reviewed, "");
    const workTotal = formatNumber(evidence.work_total, "");
    const logbookTotal = formatNumber(evidence.logbook_total, "");
    const logbookApproved = formatNumber(evidence.logbook_approved, "");

    if (dailyAverage) {
      overall.push(`The supervisor-entered Daily Performance average is ${dailyAverage}${dailyRatedDays ? ` across ${dailyRatedDays} rated day(s)` : ""}.`);
    }
    if (workAverage) {
      overall.push(`The current Work average is ${workAverage}.`);
    } else if (workTotal && Number(evidence.work_total || 0) > 0) {
      overall.push("Work items exist, but Work analytics do not currently have a numeric Work score.");
    }
    if (evidence.official_status) {
      overall.push(`The Official OJT Evaluation status is ${String(evidence.official_status)} and remains separate from these analytics.`);
    }

    if (attendanceHours) {
      happened.push(`Recorded OJT time is ${attendanceHours}${requiredHours ? ` out of ${requiredHours} required` : ""}.`);
    }
    if (logbookTotal) {
      happened.push(`The Daily Logbook contains ${logbookTotal} entr${Number(evidence.logbook_total) === 1 ? "y" : "ies"}${logbookApproved ? `, with ${logbookApproved} approved` : ""}.`);
    }
    if (workReviewed && workTotal) {
      happened.push(`Work evidence shows ${workReviewed} reviewed item(s) out of ${workTotal} assigned.`);
    }

    if (Number(evidence.daily_rated_days || 0) > 0 && Number(evidence.work_total || 0) > 0 && !evidence.work_evidence) {
      improve.push("Daily Performance is already rated, while Work analytics still have no numeric score. Confirm that the intended Work is linked to the rated Daily OJT day before relying on Work analytics.");
      next.push("Check the Daily OJT day and its Related Assigned Work link");
    }
    if (Number(evidence.work_total || 0) > Number(evidence.work_reviewed || 0)) {
      next.push("Review remaining Work evidence when it becomes available");
    }
    if (Number(evidence.daily_rated_days || 0) > 0) {
      next.push("Use the supervisor-entered Daily Performance rating as the day-level OJT score");
    }
    next.push("Keep the Official OJT Evaluation separate from Daily Performance and Work analytics");

    let feedback = "No supervisor feedback evidence is available yet.";
    if (evidence.feedback_evidence) {
      const parts = [];
      if (evidence.sentiment) parts.push(`sentiment: ${evidence.sentiment}`);
      if (evidence.competency) parts.push(`competency: ${evidence.competency}`);
      const confidence = formatNumber(evidence.confidence, "");
      if (confidence) parts.push(`confidence: ${confidence}`);
      feedback = parts.length
        ? `Current feedback-model signals show ${parts.join("; ")}.`
        : "Feedback evidence is available; use the Feedback Analysis panel for the current model signals.";
    }

    setSection(root, "overall", overall.join(" "));
    setSection(root, "happened", happened.join(" ") || "Use the evidence cards above for the current measured results.");
    setSection(root, "improve", improve.join(" ") || "Use the current supervisor-entered evidence to choose the next improvement area without combining separate OJT dimensions into one grade.");
    setSection(root, "feedback", feedback);
    setSection(root, "next", next.slice(0, 4).join("; "));
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

    const cacheKey = `nxSupervisorInsightAi:v2:${root.dataset.classroomId || "0"}:${root.dataset.studentId || "0"}:${evidenceHash(evidence)}`;
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
        renderEvidenceFallback(root, evidence);
        status.textContent = "Live AI is not enabled on this server, so Nexora is showing a direct summary of the current evidence.";
        items.hidden = false;
        return;
      }

      parseAnswer(root, data.answer, evidence);
      status.textContent = "AI explanation generated from the current evidence.";
      items.hidden = false;
      try {
        window.sessionStorage.setItem(cacheKey, data.answer);
      } catch (error) {}
    } catch (error) {
      renderEvidenceFallback(root, evidence);
      status.textContent = "Live AI could not complete the response, so Nexora is showing a direct summary of the current evidence.";
      items.hidden = false;
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

  function rememberAssignedInsightsTarget(trigger) {
    const modal = document.getElementById("assignedInsightsModal");
    if (!modal || !trigger) return;
    modal.dataset.overallInsightsUrl = trigger.dataset.overallUrl || "";
    modal.dataset.individualInsightsUrl = trigger.dataset.individualUrl || "";
    modal.dataset.initialInsightsView = trigger.dataset.insightsView || "overall";
  }

  function parseExportTarget(url, individual) {
    const text = String(url || "");
    const match = individual
      ? text.match(/\/supervisor\/classes\/(\d+)\/insights\/(\d+)/)
      : text.match(/\/supervisor\/classes\/(\d+)\/(?:performance|ml-insights|insights)/);
    if (!match) return null;
    if (individual) {
      return {
        csv: `/supervisor/classes/${match[1]}/insights/${match[2]}/export.csv`,
        pdf: `/supervisor/classes/${match[1]}/insights/${match[2]}/export.pdf`,
      };
    }
    return {
      csv: `/supervisor/classes/${match[1]}/insights/export.csv`,
      pdf: `/supervisor/classes/${match[1]}/insights/export.pdf`,
    };
  }

  function ensureExportLink(container, kind, href, primary) {
    if (!container) return null;
    let link = container.querySelector(`[data-nexora-insights-export="${kind}"]`);
    if (!link) {
      link = document.createElement("a");
      link.dataset.nexoraInsightsExport = kind;
      container.appendChild(link);
    }
    link.href = href;
    link.textContent = kind === "pdf" ? "Export PDF" : "Export CSV";
    link.className = primary ? "btn btn-sm btn-primary" : "btn btn-sm btn-outline-primary";
    return link;
  }

  function configureStandaloneInsightsControls() {
    const path = window.location.pathname;
    const overallMatch = path.match(/^\/supervisor\/classes\/(\d+)\/(?:performance|ml-insights|insights)\/?$/);
    if (overallMatch) {
      const controls = document.querySelector("body.supervisor-insights-page .supervisor-insights-view-tabs .ms-auto");
      if (controls) {
        controls.querySelectorAll("a").forEach((link) => {
          const href = link.getAttribute("href") || "";
          const label = (link.textContent || "").trim().toLowerCase();
          if (label === "reports" || /\/reports(?:$|\?)/.test(href)) link.remove();
        });
        const classId = overallMatch[1];
        const existingCsv = Array.from(controls.querySelectorAll("a")).find((link) => /export csv/i.test(link.textContent || ""));
        if (existingCsv) {
          existingCsv.dataset.nexoraInsightsExport = "csv";
          existingCsv.href = `/supervisor/classes/${classId}/insights/export.csv`;
          existingCsv.textContent = "Export CSV";
          existingCsv.className = "btn btn-sm btn-outline-primary";
        } else {
          ensureExportLink(controls, "csv", `/supervisor/classes/${classId}/insights/export.csv`, false);
        }
        ensureExportLink(controls, "pdf", `/supervisor/classes/${classId}/insights/export.pdf`, false);
      }
    }

    const individualMatch = path.match(/^\/supervisor\/classes\/(\d+)\/insights\/(\d+)\/?$/);
    if (individualMatch) {
      const actions = document.querySelector("main .nexora-page > .d-flex.flex-wrap.align-items-start.justify-content-between.gap-3.mb-4 > .d-flex.flex-wrap.gap-2");
      if (actions) {
        actions.querySelectorAll("a").forEach((link) => {
          const href = link.getAttribute("href") || "";
          const label = (link.textContent || "").trim().toLowerCase();
          if (label === "work report" || /\/reports\/\d+/.test(href)) link.remove();
        });
        const classId = individualMatch[1];
        const studentId = individualMatch[2];
        ensureExportLink(actions, "csv", `/supervisor/classes/${classId}/insights/${studentId}/export.csv`, false);
        ensureExportLink(actions, "pdf", `/supervisor/classes/${classId}/insights/${studentId}/export.pdf`, false);
      }
    }

    const reports = document.getElementById("assignedInsightsReportsLink");
    if (reports) reports.remove();
  }

  function updateAssignedInsightsExports() {
    const modal = document.getElementById("assignedInsightsModal");
    const csvLink = document.getElementById("assignedInsightsExportLink");
    if (!modal || !csvLink) return;

    const individualTab = document.getElementById("assignedInsightsIndividualTab");
    const individual = individualTab && individualTab.getAttribute("aria-selected") === "true";
    const target = parseExportTarget(
      individual ? modal.dataset.individualInsightsUrl : modal.dataset.overallInsightsUrl,
      individual,
    );
    if (!target) return;

    csvLink.href = target.csv;
    csvLink.textContent = "Export CSV";
    csvLink.className = "btn btn-sm btn-outline-primary";

    let pdfLink = document.getElementById("assignedInsightsPdfLink");
    if (!pdfLink) {
      pdfLink = document.createElement("a");
      pdfLink.id = "assignedInsightsPdfLink";
      pdfLink.className = "btn btn-sm btn-outline-primary";
      pdfLink.textContent = "Export PDF";
      csvLink.insertAdjacentElement("afterend", pdfLink);
    }
    pdfLink.href = target.pdf;
  }

  window.initSupervisorInsightsAi = init;

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-insights-modal-open]");
    if (trigger) {
      rememberAssignedInsightsTarget(trigger);
      window.setTimeout(updateAssignedInsightsExports, 0);
      return;
    }
    if (event.target.closest("#assignedInsightsOverallTab, #assignedInsightsIndividualTab")) {
      window.setTimeout(updateAssignedInsightsExports, 0);
    }
  }, true);

  document.addEventListener("DOMContentLoaded", () => {
    configureStandaloneInsightsControls();
    init(document);
    updateAssignedInsightsExports();
  });
})();
