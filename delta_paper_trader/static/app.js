const state = {
  catalog: [],
  status: null,
  chartSymbol: null,
  chart: null,  // TradingView Lightweight Chart instance
  candleSeries: null,  // Candlestick series
};

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
}

function parseSymbols(value) {
  return value
    .split(",")
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
}

function money(value, decimals = 2) {
  const number = Number(value || 0);
  return number.toLocaleString(undefined, { 
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals 
  });
}

function pnlClass(value) {
  const number = Number(value || 0);
  if (number > 0) return "positive-glow";
  if (number < 0) return "negative-glow";
  return "";
}

// ── Time Utilities ───────────────────────────────────────────────────────────
function toIST(isoString) {
  const date = new Date(isoString);
  return date.toLocaleString('en-IN', { 
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });
}

function unixToIST(unixTimestamp) {
  return toIST(new Date(unixTimestamp * 1000).toISOString());
}

// ── TradingView Lightweight Charts Utilities ─────────────────────────────────
function initChart() {
  if (!window.LightweightCharts) {
    console.warn("TradingView Lightweight Charts not loaded");
    return null;
  }

  const container = $("#market-chart-container");
  if (!container) return null;

  try {
    const chart = window.LightweightCharts.createChart(container, {
      layout: {
        background: { color: 'rgba(15, 23, 42, 0.25)' },
        textColor: '#e2e8f0',
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
      // grid: {
      //   hStyle: window.LightweightCharts.GridLineStyle.Dotted,
      //   vStyle: window.LightweightCharts.GridLineStyle.Dotted,
      //   hColor: 'rgba(255, 255, 255, 0.1)',
      //   vColor: 'rgba(255, 255, 255, 0.1)',
      // },
    });

    const candleSeries = chart.addSeries(window.LightweightCharts.CandlestickSeries,{
      upColor: '#10b981',
      downColor: '#f43f5e',
      borderUpColor: '#10b981',
      borderDownColor: '#f43f5e',
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    });

    state.chart = chart;
    state.candleSeries = candleSeries;

    // Handle window resize
    window.addEventListener('resize', () => {
      if (state.chart && container) {
        state.chart.applyOptions({
          width: container.clientWidth,
          height: container.clientHeight,
        });
      }
    });

    return { chart, candleSeries };
  } catch (error) {
    console.error("Failed to initialize TradingView chart:", error);
    return null;
  }
}

function updateChartWithCandles(candles) {
  if (!state.candleSeries) return;

  if (!candles || candles.length === 0) return;

  // Convert candles to chart format with IST timestamps
  const chartData = candles.map(candle => {
    const date = new Date(candle.start);
    const timestamp = Math.floor(date.getTime() / 1000);

    return {
      time: timestamp,
      open: parseFloat(candle.open),
      high: parseFloat(candle.high),
      low: parseFloat(candle.low),
      close: parseFloat(candle.close),
    };
  });

  state.candleSeries.setData(chartData);
  state.chart.timeScale().fitContent();
}

function renderCatalog() {
  const select = $("#strategy-type");
  const options = state.catalog
    .map((item) => `<option value="${item.code}">${item.name}</option>`)
    .join("");
  select.innerHTML = options;
  $("#backtest-strategy-type").innerHTML = options;
}

function updateAggregates() {
  const status = state.status;
  if (!status || !status.strategies) return;

  let totalPnL = 0;
  let totalFees = 0;
  let totalGST = 0;

  status.strategies.forEach(strat => {
    // Add position-level metrics
    strat.positions.forEach(pos => {
      totalPnL += Number(pos.net_pnl || 0);
      totalFees += Number(pos.fees_paid || 0);
      totalGST += Number(pos.gst_paid || 0);
    });
    
    // Fallback/Include past fills if there are no open positions
    // but pnl was realized
    strat.fills.forEach(fill => {
      // unrealized pnl is not in fills, but fees/GST are
      // We already sum fees/gst from positions (which is cumulative in broker)
    });
  });

  const pnlElement = $("#total-portfolio-pnl");
  pnlElement.textContent = `${totalPnL >= 0 ? "+" : ""}$${money(totalPnL)}`;
  pnlElement.className = totalPnL > 0 ? "text-success font-outfit" : totalPnL < 0 ? "text-danger font-outfit" : "font-outfit";

  $("#total-fees-gst").innerHTML = `$${money(totalFees + totalGST)} <small id="gst-breakdown">(GST: $${money(totalGST)})</small>`;
}

function renderStatus() {
  const status = state.status;
  
  // Status Indicator Dot & Label
  const dot = $("#status-dot");
  if (status.running) {
    dot.className = "pulse-dot active";
    $("#engine-status").textContent = "Running";
    $("#engine-status").className = "text-success";
  } else {
    dot.className = "pulse-dot inactive";
    $("#engine-status").textContent = "Stopped";
    $("#engine-status").className = "text-muted";
  }

  $("#started-at").textContent = status.started_at 
    ? new Date(status.started_at).toLocaleString() 
    : "Not running";

  // Hide/Show error banner
  const errBanner = $("#error-banner");
  if (status.last_error) {
    $("#last-error").textContent = status.last_error;
    errBanner.style.display = "flex";
  } else {
    errBanner.style.display = "none";
  }

  $("#fee-note").textContent = `Delta defaults: Taker ${status.fee_model.futures_taker_bps} bps, Maker ${status.fee_model.futures_maker_bps} bps. Paper fills use Taker + 18% GST.`;

  // Render strategies
  $("#strategies").innerHTML = status.strategies.length
    ? status.strategies.map(renderStrategy).join("")
    : `<div class="empty-state">
         <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="16"></line><line x1="8" y1="12" x2="16" y2="12"></line></svg>
         <h3>No strategies added yet</h3>
         <p class="muted">Fill out the configuration form to deploy your first paper trading strategy.</p>
       </div>`;

  updateAggregates();
  renderMarketChart();
}

function renderMarketChart() {
  const status = state.status;
  const select = $("#chart-symbol");
  
  if (!status || !select) return;

  // Initialize chart on first render
  if (!state.chart) {
    initChart();
  }

  const symbols = Array.from(new Set([
    ...Object.keys(status.closed_candles || {}),
    ...Object.keys(status.active_candles || {}),
    ...(status.strategies || []).flatMap((strategy) => strategy.symbols || []),
  ])).sort();

  if (!symbols.length) {
    select.innerHTML = "";
    return;
  }

  if (!state.chartSymbol || !symbols.includes(state.chartSymbol)) {
    state.chartSymbol = symbols[0];
  }

  select.innerHTML = symbols
    .map((symbol) => `<option value="${symbol}" ${symbol === state.chartSymbol ? "selected" : ""}>${symbol}</option>`)
    .join("");

  // Update chart with current candles
  const closed = (status.closed_candles || {})[state.chartSymbol] || [];
  const active = (status.active_candles || {})[state.chartSymbol];
  const candles = active ? [...closed, active] : closed;
  
  if (candles.length > 0 && state.candleSeries) {
    updateChartWithCandles(candles);
  }
}

function drawLineChart(canvas, points, label) {
  canvas.style.display = "block";
  if (!points.length) {
    drawEmptyChart(canvas, "No replay points");
    return;
  }

  const ctx = prepareCanvas(canvas);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const pad = { top: 18, right: 12, bottom: 24, left: 46 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const values = points.map((point) => Number(point.equity)).filter(Number.isFinite);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, max * 0.001, 1);
  const x = (index) => pad.left + (points.length === 1 ? plotWidth : (plotWidth / (points.length - 1)) * index);
  const y = (value) => pad.top + ((max - value) / range) * plotHeight;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(15, 23, 42, 0.25)";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(255, 255, 255, 0.055)";
  ctx.fillStyle = "#64748b";
  ctx.font = "11px Inter, sans-serif";
  ctx.textAlign = "right";
  for (let i = 0; i <= 3; i += 1) {
    const lineY = pad.top + (plotHeight / 3) * i;
    const value = max - (range / 3) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, lineY);
    ctx.lineTo(width - pad.right, lineY);
    ctx.stroke();
    ctx.fillText(money(value), pad.left - 6, lineY + 4);
  }

  ctx.strokeStyle = "#3b82f6";
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((point, index) => {
    const pointX = x(index);
    const pointY = y(Number(point.equity));
    if (index === 0) ctx.moveTo(pointX, pointY);
    else ctx.lineTo(pointX, pointY);
  });
  ctx.stroke();

  ctx.fillStyle = "#e2e8f0";
  ctx.font = "600 12px Outfit, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(label, pad.left, 15);
}

function renderStrategy(strategy) {
  const positions = strategy.positions.length
    ? `<div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Avg Entry</th>
              <th>Watermark</th>
              <th>Fees</th>
              <th>GST (18%)</th>
              <th class="text-right">Net PnL</th>
            </tr>
          </thead>
          <tbody>${strategy.positions.map(renderPosition).join("")}</tbody>
        </table>
       </div>`
    : `<p class="muted-info">No active positions currently held.</p>`;

  const fills = strategy.fills.length
    ? `<div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Price</th>
              <th>Fee</th>
              <th>GST</th>
              <th>Realized</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>${strategy.fills.slice(-5).reverse().map(renderFill).join("")}</tbody>
        </table>
       </div>`
    : `<p class="muted-info">No execution logs captured.</p>`;

  const latestCandle = (state.status.active_candles || {})[strategy.symbols[0]];
  const candleText = latestCandle
    ? `<span class="candle-stat">Open <strong>${money(latestCandle.open)}</strong></span> 
       <span class="candle-stat">High <strong>${money(latestCandle.high)}</strong></span> 
       <span class="candle-stat">Low <strong>${money(latestCandle.low)}</strong></span> 
       <span class="candle-stat">Close <strong>${money(latestCandle.close)}</strong></span>`
    : `<span class="pulse-text">Waiting for Delta Exchange live feeds...</span>`;

  // Risk parameters info string
  const slText = Number(strategy.sl_pct) > 0 ? `${strategy.sl_pct}%` : "None";
  const targetText = Number(strategy.target_pct) > 0 ? `${strategy.target_pct}%` : "None";
  const trailingSLText = Number(strategy.trailing_sl_pct) > 0 ? `${strategy.trailing_sl_pct}%` : "None";

  return `<article class="strategy-card">
    <div class="strategy-head">
      <div>
        <div class="strategy-title-row">
          <h3>${strategy.name}</h3>
          <span class="badge ${strategy.enabled ? 'badge-success' : 'badge-secondary'}">${strategy.enabled ? 'Active' : 'Disabled'}</span>
        </div>
        <p class="strategy-meta">${strategy.strategy_type.toUpperCase()} · ${strategy.symbols.join(", ")} · Signal: <span class="signal-tag">${strategy.last_signal}</span></p>
      </div>
      <div class="controls">
        <button class="btn-sm ${strategy.enabled ? 'btn-warn' : 'btn-primary'}" data-toggle="${strategy.id}">
          ${strategy.enabled ? 'Pause' : 'Activate'}
        </button>
        <button class="btn-sm btn-danger-outline" data-delete="${strategy.id}">Delete</button>
      </div>
    </div>

    <!-- Risk config status badges -->
    <div class="risk-bar">
      <span class="risk-item">Stop Loss: <strong>${slText}</strong></span>
      <span class="risk-item">Profit Target: <strong>${targetText}</strong></span>
      <span class="risk-item">Trailing Stop: <strong>${trailingSLText}</strong></span>
    </div>

    <div class="metrics">
      <div class="metric">
        <span>Capital Allocation</span>
        <strong>$${money(strategy.capital)}</strong>
      </div>
      <div class="metric">
        <span>Current Equity</span>
        <strong>$${money(strategy.equity)}</strong>
      </div>
      <div class="metric">
        <span>Cash Balance</span>
        <strong>$${money(strategy.cash)}</strong>
      </div>
      <div class="metric">
        <span>Quotes Read</span>
        <strong>${strategy.quote_count}</strong>
      </div>
      <div class="metric">
        <span>Fee rate</span>
        <strong>${strategy.fee_bps} bps</strong>
      </div>
    </div>

    <div class="live-candles">
      <div class="candle-head">
        <span class="pulse-dot active tiny"></span>
        <span>Active 1m Candle (${strategy.symbols[0]}):</span>
      </div>
      <div class="candle-metrics">${candleText}</div>
    </div>

    <h4 class="table-title">Position Status</h4>
    ${positions}
    
    <h4 class="table-title">Execution Logs (Fills)</h4>
    ${fills}
  </article>`;
}

function renderPosition(position) {
  // Determine if high/low watermark is relevant
  let watermarkText = "-";
  if (position.side === "long" && Number(position.highest_price) > 0) {
    watermarkText = `<span class="badge badge-watermark">H: $${money(position.highest_price, 1)}</span>`;
  } else if (position.side === "short" && Number(position.lowest_price) > 0) {
    watermarkText = `<span class="badge badge-watermark">L: $${money(position.lowest_price, 1)}</span>`;
  }

  const sideBadge = position.side === "long" 
    ? `<span class="badge badge-success-outline">LONG</span>` 
    : position.side === "short"
    ? `<span class="badge badge-danger-outline">SHORT</span>`
    : `<span class="badge badge-secondary-outline">FLAT</span>`;

  return `<tr>
    <td><strong>${position.symbol}</strong></td>
    <td>${sideBadge}</td>
    <td>${position.quantity}</td>
    <td class="font-mono">$${money(position.avg_entry)}</td>
    <td>${watermarkText}</td>
    <td class="font-mono">$${money(position.fees_paid)}</td>
    <td class="font-mono">$${money(position.gst_paid)}</td>
    <td class="font-mono text-right ${pnlClass(position.net_pnl)}">${Number(position.net_pnl) >= 0 ? "+" : ""}$${money(position.net_pnl)}</td>
  </tr>`;
}

function renderFill(fill) {
  const sideBadge = fill.side === "buy" 
    ? `<span class="badge badge-success-outline tiny">BUY</span>` 
    : `<span class="badge badge-danger-outline tiny">SELL</span>`;

  const realizedText = Number(fill.realized_pnl) !== 0
    ? `<span class="${pnlClass(fill.realized_pnl)}">${Number(fill.realized_pnl) >= 0 ? "+" : ""}$${money(fill.realized_pnl)}</span>`
    : `<span class="muted">-</span>`;

  return `<tr>
    <td class="text-muted">${new Date(fill.timestamp).toLocaleTimeString()}</td>
    <td><strong>${fill.symbol}</strong></td>
    <td>${sideBadge}</td>
    <td>${fill.quantity}</td>
    <td class="font-mono">$${money(fill.price)}</td>
    <td class="font-mono">$${money(fill.fee)}</td>
    <td class="font-mono">$${money(fill.gst || 0)}</td>
    <td class="font-mono">${realizedText}</td>
    <td class="text-muted small-text">${fill.reason}</td>
  </tr>`;
}

async function refresh() {
  try {
    state.status = await api("/api/status");
    renderStatus();
  } catch (error) {
    $("#last-error").textContent = `Sync Error: ${error.message}`;
    $("#error-banner").style.display = "flex";
  }
}

async function load() {
  state.catalog = await api("/api/strategy-catalog");
  renderCatalog();
  
  // Initialize TradingView chart
  initChart();
  
  await refresh();
}

$("#start-btn").addEventListener("click", async () => {
  try {
    await api("/api/engine/start", { method: "POST", body: "{}" });
    await refresh();
  } catch (error) {
    alert(`Failed to start engine: ${error.message}`);
  }
});

$("#stop-btn").addEventListener("click", async () => {
  try {
    await api("/api/engine/stop", { method: "POST" });
    await refresh();
  } catch (error) {
    alert(`Failed to stop engine: ${error.message}`);
  }
});

$("#refresh-btn").addEventListener("click", refresh);

$("#chart-symbol").addEventListener("change", (event) => {
  state.chartSymbol = event.target.value;
  renderMarketChart();
});

$("#strategy-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  let params = {};
  try {
    params = JSON.parse(form.get("params") || "{}");
  } catch (error) {
    alert(`Hyperparameters JSON is invalid: ${error.message}`);
    return;
  }
  
  try {
    await api("/api/strategies", {
      method: "POST",
      body: JSON.stringify({
        name: form.get("name"),
        strategy_type: form.get("strategy_type"),
        symbols: parseSymbols(form.get("symbols")),
        capital: form.get("capital"),
        quantity: form.get("quantity"),
        max_position: form.get("max_position"),
        fee_bps: form.get("fee_bps"),
        sl_pct: form.get("sl_pct") || "0",
        target_pct: form.get("target_pct") || "0",
        trailing_sl_pct: form.get("trailing_sl_pct") || "0",
        params,
      }),
    });
    await refresh();
    // Scroll strategies panel into view
    $(".live-panel").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    alert(`Failed to add strategy: ${error.message}`);
  }
});

$("#history-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const symbol = form.get("symbol").toUpperCase();
  const resolution = form.get("resolution");
  const limit = form.get("limit");

  try {
    const result = await api(`/api/candles/history?symbol=${symbol}&resolution=${resolution}&limit=${limit}`, {
      method: "GET",
    });

    if (!result.candles || result.candles.length === 0) {
      $("#history-result").innerHTML = `<p class="muted">No candles fetched for ${symbol}</p>`;
      return;
    }

    // Display result
    $("#history-result").innerHTML = `
      <p class="success"><strong>${result.candles.length} candles</strong> fetched for ${symbol}</p>
      <div style="max-height: 200px; overflow-y: auto; font-size: 11px;">
        <table style="width: 100%; border-collapse: collapse;">
          <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
            <th style="text-align: left; padding: 4px;">Time (IST)</th>
            <th style="text-align: right; padding: 4px;">O</th>
            <th style="text-align: right; padding: 4px;">H</th>
            <th style="text-align: right; padding: 4px;">L</th>
            <th style="text-align: right; padding: 4px;">C</th>
          </tr>
          ${result.candles.slice(-10).reverse().map(c => `
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
              <td style="padding: 4px;">${toIST(c.start)}</td>
              <td style="text-align: right; padding: 4px;">${money(c.open, 2)}</td>
              <td style="text-align: right; padding: 4px;">${money(c.high, 2)}</td>
              <td style="text-align: right; padding: 4px;">${money(c.low, 2)}</td>
              <td style="text-align: right; padding: 4px;">${money(c.close, 2)}</td>
            </tr>
          `).join('')}
        </table>
      </div>
      <p class="success" style="margin-top: 8px; font-size: 11px;">Copy the JSON below to use in backtest:</p>
      <textarea readonly rows="3" style="width: 100%; font-size: 10px; background: rgba(15,23,42,0.4); color: #e2e8f0; border: 1px solid rgba(255,255,255,0.1); padding: 4px; border-radius: 4px;">${JSON.stringify(result.candles)}</textarea>
    `;

    // Also populate backtest form with the candles
    $("#backtest-form textarea[name='candles']").value = JSON.stringify(result.candles);

  } catch (error) {
    alert(`Failed to fetch historical candles: ${error.message}`);
  }
});

$("#backtest-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  let params = {};
  let candles = [];
  try {
    params = JSON.parse(form.get("params") || "{}");
    candles = JSON.parse(form.get("candles") || "[]");
  } catch (error) {
    alert(`Backtest JSON is invalid: ${error.message}`);
    return;
  }

  try {
    const result = await api("/api/backtest", {
      method: "POST",
      body: JSON.stringify({
        strategy_type: form.get("strategy_type"),
        quantity: form.get("quantity"),
        params,
        candles,
      }),
    });
    renderBacktestResult(result);
  } catch (error) {
    alert(`Backtest failed: ${error.message}`);
  }
});

function renderBacktestResult(result) {
  const summary = result.summary || {};
  $("#backtest-result").innerHTML = [
    ["Final Equity", `$${money(summary.final_equity)}`],
    ["Return", `${Number(summary.total_return_pct || 0).toFixed(2)}%`],
    ["Max DD", `${Number(summary.max_drawdown || 0).toFixed(2)}%`],
    ["Fills", summary.fills || "0"],
  ].map(([label, value]) => `
    <div class="backtest-metric">
      <span>${label}</span>
      <strong>${value}</strong>
    </div>
  `).join("");
  drawLineChart($("#backtest-chart"), result.equity_curve || [], "Replay equity");
}

$("#strategies").addEventListener("click", async (event) => {
  const toggleBtn = event.target.closest("[data-toggle]");
  const deleteBtn = event.target.closest("[data-delete]");

  if (toggleBtn) {
    const toggleId = toggleBtn.dataset.toggle;
    try {
      const strategy = state.status.strategies.find((item) => item.id === toggleId);
      await api(`/api/strategies/${toggleId}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !strategy.enabled }),
      });
      await refresh();
    } catch (error) {
      alert(`Failed to toggle strategy: ${error.message}`);
    }
  }

  if (deleteBtn) {
    const deleteId = deleteBtn.dataset.delete;
    if (confirm("Are you sure you want to delete this strategy configuration?")) {
      try {
        await api(`/api/strategies/${deleteId}`, { method: "DELETE" });
        await refresh();
      } catch (error) {
        alert(`Failed to delete strategy: ${error.message}`);
      }
    }
  }
});

// Refresh every 3 seconds for live streaming updates
setInterval(refresh, 3000);
load().catch((error) => {
  $("#last-error").textContent = `Initialization Error: ${error.message}`;
  $("#error-banner").style.display = "flex";
});
