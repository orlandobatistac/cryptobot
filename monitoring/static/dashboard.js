// Dashboard JavaScript for CryptoBot
// Improves interactivity and dashboard functionality

// Global variables
let lastUpdateTime = new Date();
let refreshInterval = 5000; // 5 seconds
let darkMode = true;
let chartInstance = null;
let metricsHistory = {
  balance: [],
  profit: [],
  times: [],
};

let detailedEvaluationsDataTable = null; // Variable para la instancia de DataTable

// Function to format numbers
function formatCurrency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

// Function to format percentages
function formatPercent(value) {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value / 100);
}

// Function to render the trade table
function renderTradeTable(trades) {
  if (!trades || trades.length === 0)
    return '<p class="text-secondary">No recent trades</p>';

  let html =
    '<table class="table table-dark table-striped"><thead><tr><th>Type</th><th>Price</th><th>Volume</th><th>Time</th><th>P/L</th></tr></thead><tbody>';

  for (const t of trades) {
    html += `<tr>
      <td>${
        t.type
          ? (t.type.toLowerCase() === "buy"
              ? '<span class="icon icon-trade">&#128200;</span> '
              : '<span class="icon icon-trade">&#128201;</span> ') +
            t.type.toUpperCase()
          : ""
      }</td>
      <td>${formatCurrency(Number(t.price))}</td>
      <td>${t.volume}</td>
      <td>${t.time ? t.time.replace("T", " ").slice(0, 19) : ""}</td>
      <td>${
        t.profit !== undefined
          ? t.profit >= 0
            ? `<span class='icon icon-profit'>&#x1F4B0;</span> <span class='text-success'>${formatCurrency(
                Number(t.profit)
              )}</span>`
            : `<span class='icon icon-loss'>&#x1F4B8;</span> <span class='text-danger'>${formatCurrency(
                Number(t.profit)
              )}</span>`
          : ""
      }</td>
    </tr>`;
  }

  html += "</tbody></table>";
  return html;
}

// Function to render the metrics section
function renderMetrics(data) {
  updateMetricsHistory(data);

  // Live Trading Metrics
  let apiStatusIcon =
    data.api_status === "ONLINE"
      ? '<span class="icon icon-server text-success">&#9989;</span>'
      : '<span class="icon icon-server text-danger">&#10060;</span>';

  let apiStatusText =
    data.api_status === "ONLINE"
      ? '<span class="text-success">ONLINE</span>'
      : '<span class="text-danger">ERROR</span>';

  let html = `
  <div class="section-title"><span class="icon icon-btc">&#128181;</span>Live Trading Metrics</div>
  <div class="row g-4">
    <div class="col-md-3">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-usd">&#36;</span>USD Balance</h5>
        <p class="card-text display-6">${formatCurrency(
          Number(data.usd_balance)
        )}</p>
        <div class="mini-chart" id="balance-chart"></div>
      </div></div>
    </div>
    <div class="col-md-3">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-profit">&#x1F4B0;</span>Total Profit</h5>
        <p class="card-text display-6">${formatCurrency(
          Number(data.live_trading.total_profit)
        )}</p>
        <div class="mini-chart" id="profit-chart"></div>
      </div></div>
    </div>
    <div class="col-md-3">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-trade">&#128200;</span>Unrealized P/L</h5>
        <p class="card-text display-6">${formatCurrency(
          Number(data.live_trading.pl_unrealized)
        )}</p>
      </div></div>
    </div>
    <div class="col-md-3">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-server"></span>API Status</h5>
        <p class="card-text display-6">${
          data.api_status === "ONLINE"
            ? '<span class="text-success animate-pulse">&#9989; ONLINE</span>'
            : '<span class="text-danger animate-pulse">&#10060; ERROR</span>'
        }</p>
      </div></div>
    </div>
  </div>
  <div class="row mt-4"><div class="col"><div class="card shadow"><div class="card-body">
    <h5 class="card-title"><span class="icon icon-trade">&#128200;</span>Current Position</h5>
    `;

  if (data.position) {
    html += `<table class="table table-dark table-striped">
      <tr><th>Type</th><td>${data.position.type || "auto"}</td></tr>
      <tr><th>Volume</th><td>${data.position.volume}</td></tr>
      <tr><th>Entry Price</th><td>${formatCurrency(
        Number(data.position.entry_price)
      )}</td></tr>
      <tr><th>P/L</th><td>${
        data.pl >= 0
          ? `<span class='icon icon-profit'>&#x1F4B0;</span> <span class='text-success'>${formatCurrency(
              Number(data.pl)
            )}</span>`
          : `<span class='icon icon-loss'>&#x1F4B8;</span> <span class='text-danger'>${formatCurrency(
              Number(data.pl)
            )}</span>`
      }</td></tr>
    </table>`;
  } else {
    html += `<p class="text-secondary">No open position</p>`;
  }

  html += `<div class="mt-3"><strong>Trades:</strong> ${
    data.live_trading.total_profit !== undefined
      ? data.live_trading.total_trades || 0
      : 0
  }</div>`;
  html += `<div class="mt-2"><strong>Win Rate:</strong> ${data.live_trading.win_rate}%</div>`;
  html += `<div class="mt-2"><strong>Uptime:</strong> ${formatUptime(
    data.live_trading.uptime
  )}</div>`;
  html += `<div class="mt-4 d-flex justify-content-between align-items-center">
            <strong>Last 5 Trades:</strong>
            <button class="refresh-button" onclick="fetchMetrics()" title="Refresh data">⟳</button>
           </div>`;
  html += renderTradeTable(data.live_trading.last_5_trades);
  html += `</div></div></div></div>`;

  // Live Paper Metrics
  html += `<div class="section-title"><span class="icon icon-paper">&#128196;</span>Paper Trading Metrics</div>
  <div class="row g-4">
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-usd">&#36;</span>USD Balance</h5>
        <p class="card-text display-6">${formatCurrency(
          Number(data.paper.balance)
        )}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-profit">&#x1F4B0;</span>Total Profit</h5>
        <p class="card-text display-6">${formatCurrency(
          Number(data.paper.total_profit)
        )}</p>
      </div></div>
    </div>
    <div class="col-md-4">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-trade">&#128200;</span>Unrealized P/L</h5>
        <p class="card-text display-6">${formatCurrency(
          Number(data.paper.pl_unrealized)
        )}</p>
      </div></div>
    </div>
  </div>
  <div class="row mt-4"><div class="col"><div class="card shadow"><div class="card-body">
    <h5 class="card-title"><span class="icon icon-trade">&#128200;</span>Current Position</h5>
    `;

  if (data.paper.open_position) {
    html += `<table class="table table-dark table-striped">
      <tr><th>Volume</th><td>${data.paper.open_position.volume}</td></tr>
      <tr><th>Entry Price</th><td>${formatCurrency(
        Number(data.paper.open_position.entry_price)
      )}</td></tr>
      <tr><th>P/L</th><td>${
        data.paper.pl_unrealized >= 0
          ? `<span class='icon icon-profit'>&#x1F4B0;</span> <span class='text-success'>${formatCurrency(
              Number(data.paper.pl_unrealized)
            )}</span>`
          : `<span class='icon icon-loss'>&#x1F4B8;</span> <span class='text-danger'>${formatCurrency(
              Number(data.paper.pl_unrealized)
            )}</span>`
      }</td></tr>
    </table>`;
  } else {
    html += `<p class="text-secondary">No open position</p>`;
  }

  html += `<div class="mt-3"><strong>Trades:</strong> ${
    data.paper.total_trades || 0
  }</div>`;
  html += `<div class="mt-2"><strong>Win Rate:</strong> ${data.paper.win_rate.toFixed(
    2
  )}%</div>`;
  html += `<div class="mt-2"><strong>Uptime:</strong> ${formatUptime(
    data.paper.uptime
  )}</div>`;
  html += `<div class=\"mt-4\"><strong>Last 5 Trades:</strong></div>`;
  html += renderTradeTable(data.paper.last_5_trades);
  html += `</div></div></div></div>`;

  // Server/Bot Metrics
  html += `<div class="section-title"><span class="icon icon-server">&#128187;</span>Server & Bot Status</div>
  <div class="row g-4">
    <div class="col-md-3">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-server">&#9200;</span>Uptime</h5>
        <p class="card-text display-6">${formatUptime(
          data.server.flask_uptime
        )}</p>
      </div></div>
    </div>
    <div class="col-md-3">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-server">&#9881;&#65039;</span>CPU</h5>
        <p class="card-text display-6">${data.server.cpu_percent}%</p>
        <div class="progress">
          <div class="progress-bar bg-info" role="progressbar" style="width: ${
            data.server.cpu_percent
          }%" 
               aria-valuenow="${
                 data.server.cpu_percent
               }" aria-valuemin="0" aria-valuemax="100"></div>
        </div>
      </div></div>
    </div>
    <div class="col-md-3">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-server">&#128190;</span>Memory</h5>
        <p class="card-text display-6">${data.server.ram_percent}%</p>
        <div class="progress">
          <div class="progress-bar bg-warning" role="progressbar" style="width: ${
            data.server.ram_percent
          }%" 
               aria-valuenow="${
                 data.server.ram_percent
               }" aria-valuemin="0" aria-valuemax="100"></div>
        </div>
      </div></div>
    </div>
    <div class="col-md-3">
      <div class="card shadow"><div class="card-body">
        <h5 class="card-title"><span class="icon icon-server">&#128190;</span>Disk</h5>
        <p class="card-text display-6">${data.server.disk_percent}%</p>
        <div class="progress">
          <div class="progress-bar bg-success" role="progressbar" style="width: ${
            data.server.disk_percent
          }%" 
               aria-valuenow="${
                 data.server.disk_percent
               }" aria-valuemin="0" aria-valuemax="100"></div>
        </div>
      </div></div>
    </div>
  </div>
  <div class="row mt-4"><div class="col"><div class="card shadow"><div class="card-body">
    <h5 class="card-title"><span class="icon icon-server">&#128187;</span>System</h5>
    <p class="card-text">${data.server.platform}</p>
    <div class="mt-2"><strong>Bot Status:</strong> <span class="badge bg-success">Running</span></div>
    <div class="mt-2"><strong>Last Update:</strong> <span id="lastUpdate">${formatLastUpdate()}</span></div>
  </div></div></div></div>`;

  document.getElementById("metrics-root").innerHTML = html;
  document.getElementById("now").textContent = data.now;

  // Initialize mini charts after the DOM is ready
  setTimeout(() => {
    renderMiniCharts();
  }, 100);
}

// Function to format uptime
function formatUptime(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

// Function to format the last update
function formatLastUpdate() {
  return `${Math.floor((new Date() - lastUpdateTime) / 1000)} seconds ago`;
}

// Update metrics history
function updateMetricsHistory(data) {
  const now = new Date();

  // Limit history to last 20 entries
  if (metricsHistory.times.length >= 20) {
    metricsHistory.times.shift();
    metricsHistory.balance.shift();
    metricsHistory.profit.shift();
  }

  metricsHistory.times.push(now);
  metricsHistory.balance.push(data.usd_balance);
  metricsHistory.profit.push(data.live_trading.total_profit);

  lastUpdateTime = now;
}

// Render mini charts
function renderMiniCharts() {
  const balanceChartElem = document.getElementById("balance-chart");
  if (balanceChartElem && balanceChartElem.getContext) {
    new Chart(balanceChartElem, {
      type: "line",
      data: {
        labels: metricsHistory.times.map((t) => t.toLocaleTimeString()),
        datasets: [
          {
            label: "Balance",
            data: metricsHistory.balance,
            borderColor: "#7fd7ff",
            tension: 0.4,
            pointRadius: 0,
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          x: { display: false },
          y: { display: false },
        },
        maintainAspectRatio: false,
        height: 50,
      },
    });
  }

  const profitChartElem = document.getElementById("profit-chart");
  if (profitChartElem && profitChartElem.getContext) {
    new Chart(profitChartElem, {
      type: "line",
      data: {
        labels: metricsHistory.times.map((t) => t.toLocaleTimeString()),
        datasets: [
          {
            label: "Profit",
            data: metricsHistory.profit,
            borderColor: "#4ade80",
            tension: 0.4,
            pointRadius: 0,
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          x: { display: false },
          y: { display: false },
        },
        maintainAspectRatio: false,
        height: 50,
      },
    });
  }
}

// Function to fetch and display logs
async function fetchLogs() {
  try {
    const res = await fetch("/logs");
    const data = await res.json();

    let html = `
    <div class="section-title"><span class="icon icon-logs">&#128203;</span>System Logs</div>
    <div class="mb-2">
      <button id="toggle-eval-logs" class="btn btn-outline-info btn-sm">Show Only [EVAL] Logs</button>
    </div>
    <div class="card shadow">
      <div class="card-body">
        <h5 class="card-title"><span class="icon icon-logs">&#128203;</span>Latest Log Entries</h5>
        <pre class="mt-3" id="system-logs-pre">${data.logs
          .split("\n")
          .slice(-10)
          .join("\n")}</pre>
      </div>
    </div>`;

    document.getElementById("logs-root").innerHTML = html;

    // Add filter logic
    const btn = document.getElementById("toggle-eval-logs");
    const pre = document.getElementById("system-logs-pre");
    let showingEval = false;
    let allLogs = data.logs;
    // Solo mostrar las últimas 10 líneas por defecto
    let last10Logs = allLogs.split("\n").slice(-10).join("\n");
    pre.textContent = last10Logs;
    btn.onclick = function () {
      if (!showingEval) {
        // Mostrar solo las últimas 10 líneas que contienen [EVAL]
        const evalLines = allLogs
          .split("\n")
          .filter((line) => line.includes("[EVAL]"));
        const last10Eval = evalLines.slice(-10);
        const filtered = last10Eval
          .map(
            (line) =>
              `<span style='background:#222;color:#4ade80;font-weight:bold;'>${line}</span>`
          )
          .join("\n");
        pre.innerHTML =
          filtered || '<span class="text-warning">No [EVAL] logs found.</span>';
        btn.textContent = "Show All Logs";
        showingEval = true;
      } else {
        pre.textContent = last10Logs;
        btn.textContent = "Show Only [EVAL] Logs";
        showingEval = false;
      }
    };
  } catch (error) {
    console.error("Error fetching logs:", error);
  }
}

// Function to fetch metrics
async function fetchMetrics() {
  try {
    const res = await fetch("/metrics");
    const data = await res.json();
    renderMetrics(data);

    // Update the last update time
    const updateInterval = setInterval(() => {
      const updateElem = document.getElementById("lastUpdate");
      if (updateElem) {
        updateElem.textContent = formatLastUpdate();
      }
    }, 1000);

    return data;
  } catch (error) {
    console.error("Error fetching metrics:", error);
    return null;
  }
}

// --- DETAILED STRATEGY EVALUATIONS ---
async function fetchDetailedEvaluations() {
  try {
    const response = await fetch("/api/strategy_evaluations_detailed"); // Podrías añadir ?limit=50
    if (!response.ok) {
      console.error(
        `HTTP error! status: ${response.status}`,
        await response.text()
      );
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const evaluations = await response.json();
    displayDetailedEvaluations(evaluations);
  } catch (error) {
    console.error("Error fetching detailed evaluations:", error);
    const container = document.getElementById("detailed-evaluations-container");
    if (container) {
      container.innerHTML =
        "<p>Error al cargar los detalles de evaluación. Ver la consola para más detalles.</p>";
    }
  }
}

function formatJsonForDisplay(jsonData) {
  if (jsonData === null || jsonData === undefined) {
    return "N/A";
  }
  if (typeof jsonData === "object") {
    // Si hay un error de parseo, mostrarlo
    if (jsonData.error && jsonData.raw_value) {
      return `Error: ${jsonData.error}. Raw: <pre>${jsonData.raw_value}</pre>`;
    }
    if (jsonData.error) {
      return `Error: ${jsonData.error}`;
    }

    let html = '<ul style="margin: 0; padding-left: 15px; font-size: 0.9em;">';
    for (const key in jsonData) {
      if (jsonData.hasOwnProperty(key)) {
        let value = jsonData[key];
        if (typeof value === "object" && value !== null) {
          // Para sub-objetos, podrías simplemente convertirlos a string o formatearlos más
          value = JSON.stringify(value, null, 2);
          html += `<li><strong>${key}:</strong> <pre style="margin: 2px 0; white-space: pre-wrap; word-break: break-all;">${value}</pre></li>`;
        } else {
          html += `<li><strong>${key}:</strong> ${value}</li>`;
        }
      }
    }
    html += "</ul>";
    if (Object.keys(jsonData).length === 0) {
      return "Vacío";
    }
    return html;
  }
  return jsonData;
}

function badgeForDecision(decision) {
  if (!decision) return '<span class="badge bg-secondary">N/A</span>';
  const d = decision.toLowerCase();
  if (d === "buy") return '<span class="badge bg-success">BUY</span>';
  if (d === "sell") return '<span class="badge bg-danger">SELL</span>';
  if (d === "hold") return '<span class="badge bg-secondary">HOLD</span>';
  return `<span class="badge bg-info">${decision}</span>`;
}

function collapsibleJsonCell(jsonData, idPrefix) {
  if (
    !jsonData ||
    (typeof jsonData === "object" && Object.keys(jsonData).length === 0)
  ) {
    return '<span class="text-muted">Vacío</span>';
  }
  const uid = idPrefix + "_" + Math.random().toString(36).substr(2, 6);
  let short = "";
  let full = "";
  if (typeof jsonData === "object") {
    short =
      Object.keys(jsonData)
        .slice(0, 2)
        .map(
          (k) =>
            `<strong>${k}</strong>: ${
              typeof jsonData[k] === "object"
                ? JSON.stringify(jsonData[k])
                : jsonData[k]
            }`
        )
        .join(", ") + (Object.keys(jsonData).length > 2 ? ", ..." : "");
    full = `<pre class='bg-dark text-light p-2 rounded' style='max-height:300px;overflow:auto;'>${JSON.stringify(
      jsonData,
      null,
      2
    )}</pre>`;
  } else {
    short = String(jsonData);
    full = `<pre class='bg-dark text-light p-2 rounded'>${jsonData}</pre>`;
  }
  return `
    <span>${short} <a href="#" class="text-info" data-bs-toggle="collapse" data-bs-target="#${uid}" aria-expanded="false" aria-controls="${uid}">[+]</a></span>
    <div class="collapse mt-1" id="${uid}">${full}</div>
  `;
}

function displayDetailedEvaluations(evaluations) {
  const container = document.getElementById("detailed-evaluations-container");
  if (!container) {
    console.error("#detailed-evaluations-container not found.");
    return;
  }
  // Card wrapper and section title
  let html = `
    <div class="section-title"><span class="icon icon-eval">&#128202;</span>STRATEGY EVALUATIONS</div>
    <div class="row g-4">
      <div class="col-12">
        <div class="card shadow mb-4">
          <div class="card-body">
            <h5 class="card-title"><span class="icon icon-eval">&#128202;</span>Recent Strategy Evaluations</h5>
            <div class="table-responsive">
              <table class="table table-dark table-striped" id="detailed-evaluations-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Decision</th>
                    <th>Price</th>
                    <th>Reason</th>
                    <th>Indicators</th>
                    <th>Conditions</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
  container.innerHTML = html;
  const tableBody = document.querySelector("#detailed-evaluations-table tbody");
  if (!tableBody) {
    console.error("#detailed-evaluations-table tbody not found.");
    return;
  }
  if (detailedEvaluationsDataTable) {
    detailedEvaluationsDataTable.destroy();
    detailedEvaluationsDataTable = null;
  }
  tableBody.innerHTML = "";
  if (!evaluations || evaluations.length === 0) {
    const row = tableBody.insertRow();
    const cell = row.insertCell();
    cell.colSpan = 7;
    cell.textContent = "No detailed evaluation data available.";
    cell.style.textAlign = "center";
    return;
  }
  // Separate by bot
  const bots = ["live_trading", "live_paper"];
  bots.forEach((bot) => {
    // Section header
    const headerRow = tableBody.insertRow();
    const headerCell = headerRow.insertCell();
    headerCell.colSpan = 7;
    headerCell.innerHTML = `<b>Bot: ${
      bot === "live_trading" ? "Live Trading" : "Live Paper"
    }</b>`;
    headerCell.className = "table-primary";
    headerCell.style.backgroundColor = "#ff5733"; // Cambia el color de fondo a un naranja más visible
    headerCell.style.color = "#000000"; // Cambia el color de las letras a negro para contraste
    // Evaluation rows
    const botEvals = evaluations.filter((e) => e.bot_name === bot);
    if (botEvals.length === 0) {
      const row = tableBody.insertRow();
      const cell = row.insertCell();
      cell.colSpan = 7;
      cell.textContent = "No recent evaluations.";
      cell.style.textAlign = "center";
    } else {
      botEvals.forEach((evaluation, idx) => {
        const row = tableBody.insertRow();
        row.classList.add("align-middle");
        // Timestamp
        row.insertCell().textContent = evaluation.timestamp || "N/A";
        // Decision with badge
        row.insertCell().innerHTML = badgeForDecision(evaluation.decision);
        // Price
        row.insertCell().textContent =
          evaluation.price_at_evaluation !== null &&
          evaluation.price_at_evaluation !== undefined
            ? Number(evaluation.price_at_evaluation).toFixed(2)
            : "N/A";
        // Reason with tooltip
        const reasonCell = row.insertCell();
        reasonCell.innerHTML = `<span data-bs-toggle="tooltip" data-bs-placement="top" title="${
          evaluation.reason || ""
        }">${(evaluation.reason || "").slice(0, 40)}${
          evaluation.reason && evaluation.reason.length > 40 ? "..." : ""
        }</span>`;
        // Indicators (collapsible)
        const indicatorsCell = row.insertCell();
        indicatorsCell.innerHTML = collapsibleJsonCell(
          evaluation.indicators_state,
          bot + "_ind" + idx
        );
        // Conditions (collapsible)
        const conditionsCell = row.insertCell();
        conditionsCell.innerHTML = collapsibleJsonCell(
          evaluation.strategy_conditions,
          bot + "_cond" + idx
        );
        // Notes with tooltip
        const notesCell = row.insertCell();
        notesCell.innerHTML = `<span data-bs-toggle="tooltip" data-bs-placement="top" title="${
          evaluation.notes || ""
        }">${(evaluation.notes || "").slice(0, 30)}${
          evaluation.notes && evaluation.notes.length > 30 ? "..." : ""
        }</span>`;
      });
    }
  });
  // Enable Bootstrap tooltips
  setTimeout(() => {
    var tooltipTriggerList = [].slice.call(
      document.querySelectorAll('[data-bs-toggle="tooltip"]')
    );
    tooltipTriggerList.map(function (tooltipTriggerEl) {
      return new bootstrap.Tooltip(tooltipTriggerEl);
    });
  }, 300);
}

// Llama a las funciones cuando la página cargue
document.addEventListener("DOMContentLoaded", () => {
  fetchMetrics();
  fetchLogs();
  // fetchBtcChartData(); // Comentado para evitar error de función no definida
  fetchDetailedEvaluations(); // Añadir la nueva función

  setInterval(fetchMetrics, 10000); // cada 10s
  setInterval(fetchLogs, 30000); // cada 30s
  // No es necesario refrescar el gráfico de BTC tan frecuentemente a menos que cambie mucho
  // setInterval(fetchBtcChartData, 60000 * 5); // cada 5 minutos
  setInterval(fetchDetailedEvaluations, 60000 * 2); // cada 2 minutos
});

// Function to toggle between dark and light theme
function toggleTheme() {
  darkMode = !darkMode;

  if (darkMode) {
    document.documentElement.setAttribute("data-theme", "dark");
    document.querySelector(".theme-toggle").innerHTML = "&#9788;"; // ☀
  } else {
    document.documentElement.setAttribute("data-theme", "light");
    document.querySelector(".theme-toggle").innerHTML = "&#9790;"; // ☾
  }

  localStorage.setItem("theme", darkMode ? "dark" : "light");
}

// Initialize the application
async function initApp() {
  // Load preferred theme
  const savedTheme = localStorage.getItem("theme") || "dark";
  darkMode = savedTheme === "dark";
  document.documentElement.setAttribute("data-theme", savedTheme);

  // Get initial data
  const data = await fetchMetrics();
  if (!data) return;

  // Get logs
  await fetchLogs();

  // Set up periodic updates
  setInterval(() => {
    fetchMetrics();
  }, refreshInterval);

  setInterval(() => {
    fetchLogs();
  }, refreshInterval * 2);
}

// Start the application when the DOM is ready
document.addEventListener("DOMContentLoaded", initApp);
