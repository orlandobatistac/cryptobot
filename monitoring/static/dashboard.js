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
    <div class="card shadow">
      <div class="card-body">
        <h5 class="card-title d-flex justify-content-between align-items-center">
          <span><span class="icon icon-logs">&#128203;</span>Latest Log Entries</span>
          <button id="toggle-eval-logs" class="btn btn-sm btn-outline-info">Show Only [EVAL] Logs</button>
        </h5>
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
    const response = await fetch("/api/strategy_evaluations_detailed");
    if (!response.ok) {
      console.error(
        `HTTP error! status: ${response.status}`,
        await response.text()
      );
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    displayDetailedEvaluations(data); // PASA EL OBJETO COMPLETO
  } catch (error) {
    console.error("Error fetching detailed evaluations:", error);
    const container = document.getElementById("detailed-evaluations-container");
    if (container) {
      container.innerHTML =
        "<p>Error loading strategy evaluations. Check the console for details.</p>";
    }
  }
}

function formatCountdown(seconds) {
  if (seconds < 0) return "00:00:00";

  // For daily evaluations, we need days, hours, minutes, seconds
  const d = Math.floor(seconds / 86400); // Days (86400 = 24*60*60)
  const h = Math.floor((seconds % 86400) / 3600)
    .toString()
    .padStart(2, "0");
  const m = Math.floor((seconds % 3600) / 60)
    .toString()
    .padStart(2, "0");
  const s = Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0");

  // Show days only if there are days remaining
  if (d > 0) {
    return `${d}d ${h}:${m}:${s}`;
  } else {
    return `${h}:${m}:${s}`;
  }
}

function displayDetailedEvaluations(data) {
  const container = document.getElementById("detailed-evaluations-container");
  if (!container) {
    console.error("#detailed-evaluations-container not found.");
    return;
  }
  // --- New: Status and countdown header ---
  let html = `<div class="section-title"><span class="icon icon-eval">&#128202;</span>STRATEGY EVALUATIONS</div>`;
  html += `<div class="row g-4 mb-3">
    <div class="col-md-6">      <div class="card shadow-sm mb-2">
        <div class="card-body d-flex flex-column flex-md-row align-items-md-center justify-content-between gap-2">
          <div><b>Live Trading Status:</b> <span id="status-live-trading" class="badge bg-info"></span></div>
          <div><b>Next daily evaluation in:</b> <span id="countdown-live-trading" class="fw-bold"></span></div>
        </div>
      </div>
    </div>
    <div class="col-md-6">
      <div class="card shadow-sm mb-2">
        <div class="card-body d-flex flex-column flex-md-row align-items-md-center justify-content-between gap-2">
          <div><b>Paper Trading Status:</b> <span id="status-live-paper" class="badge bg-info"></span></div>
          <div><b>Next daily evaluation in:</b> <span id="countdown-live-paper" class="fw-bold"></span></div>
        </div>
      </div>
    </div>
  </div>`;
  html += `  <div class="card shadow mb-4">
    <div class="card-body">      <h5 class="card-title">
        <span><span class="icon icon-eval">&#128202;</span>Recent Strategy Evaluations</span>
      </h5>
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
  </div>`;
  container.innerHTML = html;
  // --- Fill status and countdown ---
  const now = data.now;
  const statusInfo = data.status_info;
  // Almacenar la diferencia entre el tiempo del servidor y el cliente
  const serverClientTimeDiff = now - Math.floor(Date.now() / 1000);

  // Variable para controlar las actualizaciones automáticas
  if (!window._lastAutoUpdateTime) {
    window._lastAutoUpdateTime = {};
  }
  function updateCountdowns() {
    [
      {
        bot: "live_trading",
        statusId: "status-live-trading",
        countdownId: "countdown-live-trading",
      },
      {
        bot: "live_paper",
        statusId: "status-live-paper",
        countdownId: "countdown-live-paper",
      },
    ].forEach(({ bot, statusId, countdownId }) => {
      const status = statusInfo[bot]?.status || "Unknown";
      const nextEval = statusInfo[bot]?.next_evaluation_ts || now;

      // Calculate remaining time, adjusting for server-client time difference
      const clientNowSeconds = Math.floor(Date.now() / 1000);
      const adjustedClientTime = clientNowSeconds + serverClientTimeDiff;
      const seconds = Math.max(0, Math.floor(nextEval - adjustedClientTime));

      // If countdown reaches 0, schedule data refresh
      if (seconds <= 1) {
        const currentTime = Date.now();
        // Avoid too frequent updates (maximum once every 5 seconds per bot)
        if (
          !window._lastAutoUpdateTime[bot] ||
          currentTime - window._lastAutoUpdateTime[bot] > 5000
        ) {
          // Wait 2 seconds to give time for the evaluation to complete, then update
          setTimeout(() => {
            console.log(
              `Updating evaluation data for ${bot} after countdown reached 0`
            );
            fetchDetailedEvaluations();
            window._lastAutoUpdateTime[bot] = currentTime + 2000;
          }, 2000);
        }
      }

      const statusElem = document.getElementById(statusId);
      const countdownElem = document.getElementById(countdownId);

      if (statusElem) statusElem.textContent = status;
      if (countdownElem) countdownElem.textContent = formatCountdown(seconds);
    });
  }
  updateCountdowns();
  if (window._evalCountdownInterval)
    clearInterval(window._evalCountdownInterval);
  window._evalCountdownInterval = setInterval(updateCountdowns, 1000);

  // ...existing code for table rendering...
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
  const evaluations = data.evaluations;
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
      bot === "live_trading" ? "Live Trading" : "Paper Trading"
    }</b>`;
    headerCell.className = "table-primary";
    headerCell.style.backgroundColor = "#ff5733";
    headerCell.style.color = "#000000";
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

        // Destacar visualmente las evaluaciones más recientes (primera de cada bot)
        if (idx === 0) {
          row.classList.add("new-evaluation");
          row.style.backgroundColor = "#1d432d";
          // Animación simple para destacar nuevas evaluaciones
          setTimeout(() => {
            // Usar una transición CSS para un cambio de color suave
            row.style.transition = "background-color 3s ease-out";
            row.style.backgroundColor = "";
          }, 500);
        }

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

// Badge for decision (BUY/SELL/HOLD)
function badgeForDecision(decision) {
  if (!decision) return "<span class='badge bg-secondary'>N/A</span>";
  const d = decision.toLowerCase();
  if (d === "buy") return "<span class='badge bg-success'>BUY</span>";
  if (d === "sell") return "<span class='badge bg-danger'>SELL</span>";
  if (d === "hold") return "<span class='badge bg-secondary'>HOLD</span>";
  return `<span class='badge bg-secondary'>${decision.toUpperCase()}</span>`;
}

// Helper to render a collapsible JSON cell for table rows
function collapsibleJsonCell(obj, id) {
  if (!obj) return '<span class="text-secondary">N/A</span>';
  let jsonStr = "";
  try {
    jsonStr = JSON.stringify(obj, null, 2);
  } catch (e) {
    jsonStr = String(obj);
  }
  return `
    <button class="btn btn-sm btn-outline-secondary" type="button" data-bs-toggle="collapse" data-bs-target="#${id}" aria-expanded="false" aria-controls="${id}">
      View
    </button>
    <div class="collapse mt-1" id="${id}">
      <pre class="bg-dark text-light p-2 rounded small" style="max-height:200px;overflow:auto;">${jsonStr}</pre>
    </div>
  `;
}

// Llama a las funciones cuando la página cargue (para compatibilidad con código anterior)
// Este bloque se mantiene por compatibilidad pero se está usando initApp() como punto principal
document.addEventListener("DOMContentLoaded", () => {
  // No hacemos nada aquí ya que initApp() se encarga de inicializar todo
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

  // Get logs and strategy evaluations
  await fetchLogs();
  await fetchDetailedEvaluations();

  // Set up periodic updates
  setInterval(() => {
    fetchMetrics();
  }, refreshInterval);

  setInterval(() => {
    fetchLogs();
  }, refreshInterval * 2);

  // Update strategy evaluations every 5 seconds to keep countdown accurate
  setInterval(() => {
    fetchDetailedEvaluations();
  }, refreshInterval);
}

// Start the application when the DOM is ready
document.addEventListener("DOMContentLoaded", initApp);
