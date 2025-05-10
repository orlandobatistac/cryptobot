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
  if (document.getElementById("balance-chart")) {
    new Chart(document.getElementById("balance-chart"), {
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

  if (document.getElementById("profit-chart")) {
    new Chart(document.getElementById("profit-chart"), {
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
        <h5 class="card-title"><span class="icon icon-logs">&#128203;</span>Latest Log Entries</h5>
        <pre class="mt-3">${data.logs}</pre>
      </div>
    </div>`;

    document.getElementById("logs-root").innerHTML = html;
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
