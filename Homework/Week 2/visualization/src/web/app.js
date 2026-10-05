"use strict";

const graphElement = document.getElementById("graph");
const linksElement = document.getElementById("links");
const contentElement = document.getElementById("content");
const errorElement = document.getElementById("error");
const resultsElement = document.getElementById("search-results");
let graphData = null;
let selectedCompany = null;
let requestNumber = 0;

async function readJson(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "The request could not be completed.");
  }
  return data;
}

function showError(message) {
  graphData = null;
  contentElement.hidden = true;
  resultsElement.hidden = true;
  errorElement.textContent = message;
  errorElement.hidden = false;
}

function clearError() {
  errorElement.hidden = true;
  errorElement.textContent = "";
}

async function selectSector(sectorId, company = null) {
  const current = ++requestNumber;
  try {
    const data = await readJson(`/api/graph?focus=${encodeURIComponent(sectorId)}`);
    if (current !== requestNumber) return;
    graphData = data;
    selectedCompany = company;
    clearError();
    contentElement.hidden = false;
    resultsElement.hidden = true;
    draw();
  } catch (error) {
    if (current === requestNumber) showError(error.message);
  }
}

function makeText(tag, content, className = "") {
  const item = document.createElement(tag);
  item.textContent = content;
  if (className) item.className = className;
  return item;
}

function renderInspector() {
  const selected = graphData.selected;
  const node = graphData.nodes.find((item) => item.id === selected.id);
  document.getElementById("sector-id").textContent = `Sector ${selected.id}${node ? " · theme slice" : ""}`;
  document.getElementById("sector-title").textContent = node ? node.label : selected.name;
  document.getElementById("sector-name").textContent = node ? selected.name : selected.family;
  const examples = document.getElementById("examples");
  examples.replaceChildren(...selected.example_tickers.map((ticker) => makeText("span", ticker)));
  document.getElementById("listing-count").textContent = `${selected.listing_count} listed securities in this category; counts include share classes and other instruments.`;

  const companyBox = document.getElementById("company-selection");
  companyBox.hidden = !selectedCompany;
  if (selectedCompany) {
    const name = makeText("strong", `${selectedCompany.ticker} · ${selectedCompany.name}`);
    const note = makeText("span", "Classified in this sector. No company-level relationship is asserted by this map.");
    companyBox.replaceChildren(name, note);
  } else {
    companyBox.replaceChildren();
  }

  const connections = document.getElementById("connections");
  const active = graphData.edges.filter((edge) => edge.active);
  connections.replaceChildren(...active.map((edge) => {
    const outward = edge.source === selected.id;
    const otherId = outward ? edge.target : edge.source;
    const other = graphData.nodes.find((item) => item.id === otherId);
    const row = document.createElement("li");
    row.append(makeText("strong", `${outward ? "To" : "From"} ${other.label}`));
    row.append(makeText("span", `${edge.role} · conceptual`));
    return row;
  }));
  document.getElementById("outside-theme").hidden = Boolean(node);
}

function svgElement(tag, attributes) {
  const item = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) item.setAttribute(name, String(value));
  return item;
}

function renderGraph() {
  const width = graphElement.clientWidth;
  const narrow = width < 520;
  const height = narrow ? 566 : 434;
  const boxWidth = narrow ? Math.min(145, (width - 45) / 2) : Math.min(158, (width - 65) / 3);
  const boxHeight = narrow ? 90 : 78;
  const left = narrow ? 12 : 0;
  const middle = narrow ? width - boxWidth - 12 : (width - boxWidth) / 2;
  const right = width - boxWidth;
  const positions = narrow ? {
    "05": [left, 18], "32": [middle, 18], "11": [left, 146], "33": [middle, 146],
    "12": [left, 288], "19": [middle, 288], "47": [(width - boxWidth) / 2, 474]
  } : {
    "05": [left, 24], "11": [middle, 24], "12": [middle, 126], "19": [middle, 228],
    "32": [left, 330], "33": [middle, 330], "47": [right, 174]
  };
  graphElement.style.height = `${height}px`;
  linksElement.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const defs = svgElement("defs", {});
  for (const active of [true, false]) {
    const marker = svgElement("marker", {
      id: active ? "arrow-active" : "arrow-muted", viewBox: "0 0 10 10", refX: 8, refY: 5,
      markerWidth: 5, markerHeight: 5, orient: "auto-start-reverse"
    });
    marker.append(svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: active ? "var(--accent)" : "var(--line)" }));
    defs.append(marker);
  }
  linksElement.replaceChildren(defs);
  const activeIds = new Set([graphData.selected.id]);
  graphData.edges.filter((edge) => edge.active).forEach((edge) => { activeIds.add(edge.source); activeIds.add(edge.target); });

  graphData.edges.forEach((edge) => {
    const a = positions[edge.source];
    const b = positions[edge.target];
    let path;
    if (narrow) {
      if (edge.target !== "47") {
        path = `M${a[0] + boxWidth / 2},${a[1] + boxHeight} L${b[0] + boxWidth / 2},${b[1] - 4}`;
      } else if (edge.source === "11" || edge.source === "33") {
        const fromLeft = edge.source === "11";
        const startX = fromLeft ? a[0] : a[0] + boxWidth;
        const outerX = fromLeft ? 3 : width - 3;
        const endX = fromLeft ? b[0] - 4 : b[0] + boxWidth + 4;
        path = `M${startX},${a[1] + boxHeight / 2} L${outerX},${a[1] + boxHeight / 2} L${outerX},${b[1] + boxHeight / 2} L${endX},${b[1] + boxHeight / 2}`;
      } else {
        const startX = a[0] + boxWidth / 2;
        const endX = b[0] + (edge.source === "12" ? boxWidth * .25 : boxWidth * .75);
        path = `M${startX},${a[1] + boxHeight} C${startX},${a[1] + boxHeight + 55} ${endX},${b[1] - 54} ${endX},${b[1] - 4}`;
      }
    } else {
      const startX = a[0] + boxWidth;
      const endX = b[0] - 4;
      const startY = a[1] + boxHeight / 2;
      const endY = b[1] + boxHeight / 2;
      const bendX = (startX + endX) / 2;
      path = `M${startX},${startY} C${bendX},${startY} ${bendX},${endY} ${endX},${endY}`;
    }
    linksElement.append(svgElement("path", {
      d: path, fill: "none", stroke: edge.active ? "var(--accent)" : "var(--line)",
      "stroke-width": edge.active ? 2.3 : 1.2,
      "marker-end": `url(#${edge.active ? "arrow-active" : "arrow-muted"})`
    }));
  });

  graphElement.querySelectorAll(".graph-node").forEach((item) => item.remove());
  graphData.nodes.forEach((node) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "graph-node";
    button.setAttribute("aria-pressed", String(node.id === graphData.selected.id));
    button.setAttribute("aria-label", `Sector ${node.id}, ${node.label}`);
    button.classList.toggle("dim", !activeIds.has(node.id));
    button.style.left = `${positions[node.id][0]}px`;
    button.style.top = `${positions[node.id][1]}px`;
    button.style.width = `${boxWidth}px`;
    button.style.height = `${boxHeight}px`;
    button.append(makeText("span", node.id), makeText("strong", node.label));
    button.addEventListener("click", () => selectSector(node.id));
    graphElement.append(button);
  });
}

function draw() {
  if (!graphData) return;
  renderInspector();
  renderGraph();
}

document.getElementById("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = document.getElementById("search-input").value.trim();
  if (!query) return;
  try {
    const hits = await readJson(`/api/search?q=${encodeURIComponent(query)}&limit=10`);
    clearError();
    resultsElement.replaceChildren();
    if (hits.length === 0) {
      resultsElement.append(makeText("p", "No matching listing in this workbook.", "search-empty"));
    } else {
      hits.forEach((hit) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "search-result";
        button.append(makeText("strong", hit.ticker), makeText("span", hit.name), makeText("em", `Sector ${hit.sector_id}`));
        button.addEventListener("click", () => selectSector(hit.sector_id, hit));
        resultsElement.append(button);
      });
    }
    resultsElement.hidden = false;
  } catch (error) {
    showError(error.message);
  }
});

new ResizeObserver(() => { if (graphData) renderGraph(); }).observe(graphElement);
selectSector("47");
