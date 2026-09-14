(function () {
  "use strict";

  const ranges = [
    [1, "Today"],
    [7, "Last 7 Days"],
    [14, "Last 14 Days"],
    [21, "Last 21 Days"],
    [30, "Last 30 Days"],
  ];

  function svgNode(name, attrs, text) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderChart(svg, data) {
    const labels = Array.isArray(data.labels) ? data.labels : [];
    if (!labels.length) return;

    const series = [
      { values: data.logbook || [], color: "#2563eb" },
      { values: data.work || [], color: "#10b981" },
      { values: data.evaluations || [], color: "#7c3aed" },
    ];
    const width = 720;
    const height = 245;
    const pad = { left: 42, right: 18, top: 18, bottom: 36 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const maxValue = Math.max(1, ...series.flatMap((item) => item.values.map((value) => Number(value) || 0)));
    const axisMax = Math.max(5, Math.ceil(maxValue / 5) * 5);
    const x = (index) => pad.left + (labels.length === 1 ? plotW / 2 : (plotW * index) / (labels.length - 1));
    const y = (value) => pad.top + plotH - (plotH * (Number(value) || 0)) / axisMax;

    svg.replaceChildren();
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.appendChild(svgNode("title", { id: "activity-chart-title" }, `${data.label || "Activity"} intern activity`));
    svg.appendChild(svgNode("desc", { id: "activity-chart-desc" }, "Counts for Daily OJT Logbook entries, Work submissions, and Official OJT Evaluation activity."));

    for (let step = 0; step <= 5; step += 1) {
      const value = (axisMax * step) / 5;
      const yy = y(value);
      svg.appendChild(svgNode("line", { x1: pad.left, y1: yy, x2: width - pad.right, y2: yy, stroke: "#dbe5f1", "stroke-width": 1 }));
      svg.appendChild(svgNode("text", { x: pad.left - 12, y: yy + 4, "text-anchor": "end", fill: "#64748b", "font-size": 11 }, String(Math.round(value))));
    }

    const labelStep = Math.max(1, Math.ceil(labels.length / 7));
    labels.forEach((label, index) => {
      if (index % labelStep !== 0 && index !== labels.length - 1) return;
      svg.appendChild(svgNode("text", { x: x(index), y: height - 9, "text-anchor": "middle", fill: "#64748b", "font-size": 10 }, label));
    });

    series.forEach((item) => {
      const points = labels.map((_, index) => `${x(index)},${y(item.values[index] || 0)}`).join(" ");
      if (labels.length > 1) {
        svg.appendChild(svgNode("polyline", { points, fill: "none", stroke: item.color, "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round" }));
      }
      labels.forEach((_, index) => {
        svg.appendChild(svgNode("circle", { cx: x(index), cy: y(item.values[index] || 0), r: 3.5, fill: item.color }));
      });
    });
  }

  async function loadRange(select, svg, days) {
    select.disabled = true;
    try {
      const response = await fetch(`/supervisor/dashboard/activity-chart?days=${encodeURIComponent(days)}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("Unable to load activity data.");
      const data = await response.json();
      renderChart(svg, data);
      select.value = String(data.days || days);
      try { window.sessionStorage.setItem("nexoraSupervisorActivityRange", select.value); } catch (error) {}
    } catch (error) {
      select.setAttribute("title", "Activity range could not be refreshed. The previously loaded chart remains visible.");
    } finally {
      select.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.location.pathname !== "/supervisor/dashboard") return;
    const select = document.querySelector('select[aria-label="Activity chart period"]');
    const svg = document.getElementById("supervisorActivityChart");
    if (!select || !svg) return;

    select.replaceChildren();
    ranges.forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = label;
      select.appendChild(option);
    });

    let initial = "7";
    try {
      const stored = window.sessionStorage.getItem("nexoraSupervisorActivityRange");
      if (stored && ranges.some(([value]) => String(value) === stored)) initial = stored;
    } catch (error) {}
    select.value = initial;
    select.addEventListener("change", () => loadRange(select, svg, Number(select.value) || 7));
    loadRange(select, svg, Number(initial) || 7);
  });
})();
