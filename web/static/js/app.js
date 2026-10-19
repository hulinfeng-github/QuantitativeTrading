/**
 * A股主板量化系统前端核心交互引擎
 * 支持：实时行情轮询、全市场扫描、K线与RSRS指标Canvas图表渲染、通知配置与自选管理
 */

// 当前活跃标签
let activeTab = 'screener';
let pollTimer = null;

// 初始化
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  fetchStatus();
  fetchWatchlist();
  fetchScanResults();
  loadConfig();
  
  // 盘中定时轮询（每10秒刷新自选股实时行情与状态）
  pollTimer = setInterval(() => {
    fetchStatus();
    if (activeTab === 'watchlist') {
      fetchWatchlist();
    }
    if (activeTab === 't0') {
      fetchT0Monitor();
    }
  }, 10000);
});

// 标签切换
function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.style.display = 'none');
      
      btn.classList.add('active');
      activeTab = btn.getAttribute('data-tab');
      const targetPane = document.getElementById(`pane-${activeTab}`);
      if (targetPane) {
        targetPane.style.display = 'block';
      }

      if (activeTab === 'watchlist') fetchWatchlist();
      if (activeTab === 't0') fetchT0Monitor();
      if (activeTab === 'screener') fetchScanResults();
      if (activeTab === 'signals') fetchSignalsHistory();
      if (activeTab === 'review') fetchReviewData();
    });
  });
}

// 1. 获取系统运行状态
async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    
    const marketEl = document.getElementById('marketStatusText');
    const dotEl = document.getElementById('marketDot');
    
    if (data.is_trading_time) {
      marketEl.textContent = '盘中交易时段 (实时监控中)';
      dotEl.className = 'dot live';
    } else {
      marketEl.textContent = '非交易时段 (待机)';
      dotEl.className = 'dot idle';
    }

    // 扫描状态更新
    if (data.scan_status) {
      const scanBtn = document.getElementById('btnStartScan');
      const scanNotice = document.getElementById('scanNotice');
      if (data.scan_status.is_scanning) {
        scanBtn.disabled = true;
        scanBtn.textContent = '⏳ ' + data.scan_status.message;
        if (scanNotice) scanNotice.textContent = data.scan_status.message;
      } else {
        scanBtn.disabled = false;
        scanBtn.textContent = '🚀 立即全市场主板智能选股';
        if (data.scan_status.last_scan_time && scanNotice) {
          scanNotice.textContent = `上次扫描: ${data.scan_status.last_scan_time} (${data.scan_status.message})`;
        }
      }
    }
  } catch (e) {
    console.error('获取系统状态失败:', e);
  }
}

// 2. 获取并展示全市场主板选股结果
async function fetchScanResults() {
  try {
    const res = await fetch('/api/scan/results');
    const data = await res.json();
    renderScreenerCards(data.results || []);
  } catch (e) {
    console.error('获取选股结果失败:', e);
  }
}

function renderScreenerCards(list) {
  const container = document.getElementById('screenerContainer');
  if (!list || list.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1/-1; text-align: center; padding: 60px 20px; color: var(--text-muted);">
        <p style="font-size: 16px; margin-bottom: 12px;">今日尚未执行全市场扫描</p>
        <p style="font-size: 13px;">点击右上角「立即全市场主板智能选股」按钮，系统将自动基于修正RSRS与多周期均线模型筛选高质量标的。</p>
      </div>`;
    return;
  }

  container.innerHTML = list.map(item => {
    const isBuy = item.signal_type === 'BUY';
    const cardClass = isBuy ? 'stock-card card-buy' : 'stock-card';
    const badgeClass = isBuy ? 'badge-tag badge-buy' : 'badge-tag badge-watch';
    const changeClass = item.change_pct >= 0 ? 'bull' : 'bear';
    const levels = item.trade_levels || {};

    const reasonsHtml = (item.reasons || []).map(r => `<li>${r}</li>`).join('');
    const mainCost = item.main_cost || item.price;
    const biasToMain = item.bias_to_main !== undefined ? item.bias_to_main : 0;
    const controlStatus = item.control_status || '吸筹蓄势';
    let statusBadgeClass = 'badge-neutral';
    if (controlStatus.includes('起爆')) statusBadgeClass = 'badge-bull';
    else if (controlStatus.includes('派发')) statusBadgeClass = 'badge-bear';
    else if (controlStatus.includes('主升')) statusBadgeClass = 'badge-gold';

    return `
      <div class="${cardClass}">
        <div class="stock-card-header">
          <div class="stock-name-box">
            <h3>${item.name} <span class="stock-code">${item.symbol}</span></h3>
            <span class="${badgeClass}">${item.signal_desc} (${item.score}分)</span>
          </div>
          <div class="stock-price-box">
            <div class="stock-price ${changeClass}">${item.price.toFixed(2)}</div>
            <div class="stock-change ${changeClass}">${item.change_pct >= 0 ? '+' : ''}${item.change_pct.toFixed(2)}%</div>
          </div>
        </div>

        <!-- 🏦 主力持仓成本与控盘透视 -->
        <div style="background: rgba(14, 165, 233, 0.08); border: 1px solid rgba(14, 165, 233, 0.2); border-radius: 6px; padding: 6px 10px; margin-bottom: 10px; font-size: 11px; display: flex; justify-content: space-between; align-items: center;">
          <span>🏦 主力成本: <strong style="color:var(--color-gold); font-size:12px;">${mainCost.toFixed(2)}元</strong> <small style="color:${biasToMain >= 0 ? 'var(--color-bull)' : 'var(--color-bear)'};">(${biasToMain >= 0 ? '+' : ''}${biasToMain}%)</small></span>
          <span class="badge ${statusBadgeClass}" style="font-size:10px;">${controlStatus}</span>
        </div>

        <div class="metrics-row">
          <div class="metric-item">
            <span>修正RSRS</span>
            <span style="color: #38bdf8;">${item.rsrs_norm}</span>
          </div>
          <div class="metric-item">
            <span>R²拟合优度</span>
            <span>${item.rsrs_r2}</span>
          </div>
          <div class="metric-item">
            <span>成交量比</span>
            <span>${item.vol_ratio}x</span>
          </div>
          <div class="metric-item">
            <span>ATR波动</span>
            <span>${item.atr}</span>
          </div>
        </div>

        <div class="trade-levels-box">
          <div>建议止损: <strong style="color: #ef4444;">${levels.initial_stop || 0}元 (-${levels.stop_pct || 0}%)</strong></div>
          <div>目标止盈: <strong style="color: #10b981;">${levels.target_price || 0}元 (+${levels.reward_pct || 0}%)</strong></div>
        </div>

        <ul class="reasons-list">
          ${reasonsHtml}
        </ul>

        <div style="display: flex; gap: 8px; margin-top: auto; padding-top: 8px;">
          <button class="btn btn-outline" style="flex: 1; padding: 6px;" onclick="addStockToWatch('${item.symbol}', ${item.price})">+ 加入自选监控</button>
          <button class="btn btn-outline" style="padding: 6px 12px;" onclick="quickDiagnose('${item.symbol}')">深度诊断</button>
        </div>
      </div>
    `;
  }).join('');
}

// 触发全市场主板选股
async function triggerScan() {
  const btn = document.getElementById('btnStartScan');
  btn.disabled = true;
  btn.textContent = '🚀 正在初始化全市场扫描...';
  try {
    await fetch('/api/scan/start', { method: 'POST' });
    // 轮询检查扫描进度
    const checkInterval = setInterval(async () => {
      const res = await fetch('/api/status');
      const data = await res.json();
      if (!data.scan_status.is_scanning) {
        clearInterval(checkInterval);
        fetchScanResults();
        fetchStatus();
      } else {
        btn.textContent = `⏳ ${data.scan_status.message}`;
      }
    }, 2000);
  } catch (e) {
    alert('触发扫描失败: ' + e);
    btn.disabled = false;
  }
}

// 3. 自选股监控池管理
async function fetchWatchlist() {
  try {
    const res = await fetch('/api/watchlist');
    const list = await res.json();
    renderWatchlistTable(list);
  } catch (e) {
    console.error('获取自选股失败:', e);
  }
}

function renderWatchlistTable(list) {
  const tbody = document.getElementById('watchlistTbody');
  if (!list || list.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 40px; color: var(--text-dim);">自选股池为空，请在上方输入主板股票代码添加</td></tr>`;
    return;
  }

  tbody.innerHTML = list.map(item => {
    const changeClass = item.change_pct >= 0 ? 'bull' : 'bear';
    const profitClass = item.profit_pct >= 0 ? 'bull' : 'bear';
    const profitText = item.entry_price > 0 ? `${item.profit_pct >= 0 ? '+' : ''}${item.profit_pct}%` : '--';
    const profitAmountText = item.shares > 0 && item.entry_price > 0 ? `${item.profit_amount >= 0 ? '+' : ''}${item.profit_amount.toFixed(0)}元` : '--';
    const mainCost = item.main_cost || item.price;
    const biasToMain = item.bias_to_main !== undefined ? item.bias_to_main : 0;
    const controlStatus = item.control_status || '洗盘蓄势';
    let statusBadgeClass = 'badge-neutral';
    if (controlStatus.includes('起爆')) statusBadgeClass = 'badge-bull';
    else if (controlStatus.includes('派发')) statusBadgeClass = 'badge-bear';
    else if (controlStatus.includes('主升')) statusBadgeClass = 'badge-gold';

    return `
      <tr>
        <td>
          <strong>${item.name}</strong>
          <span style="font-size:11px; color:var(--text-dim); display:block;">${item.symbol}</span>
        </td>
        <td style="font-family:monospace; font-weight:700;" class="${changeClass}">${item.price.toFixed(2)}</td>
        <td style="font-weight:600;" class="${changeClass}">${item.change_pct >= 0 ? '+' : ''}${item.change_pct.toFixed(2)}%</td>
        <td style="font-family:monospace;">${item.entry_price > 0 ? item.entry_price.toFixed(2) + '元' : '未设成本'}</td>
        <td style="font-family:monospace;">
          <strong style="color:var(--color-gold); font-size:13px;">${mainCost.toFixed(2)}元</strong>
          <span style="font-size:11px; display:block; color:${biasToMain >= 0 ? 'var(--color-bull)' : 'var(--color-bear)'};">${biasToMain >= 0 ? '+' : ''}${biasToMain}%</span>
        </td>
        <td><span class="badge ${statusBadgeClass}" style="font-size:11px;">${controlStatus}</span></td>
        <td style="font-family:monospace;">${item.shares > 0 ? item.shares + ' 股' : '<span style="color:var(--text-dim);">仅观察</span>'}</td>
        <td style="font-family:monospace; font-weight:700;" class="${profitClass}">
          ${profitText}
          <div style="font-size:11px; font-weight:400; opacity:0.85;">${profitAmountText}</div>
        </td>
        <td>
          <span style="font-size:12px; color:var(--text-muted);">${(item.turnover / 100000000).toFixed(2)} 亿</span>
        </td>
        <td>
          <button class="btn btn-outline" style="padding: 4px 8px; font-size:12px; margin-right:4px;" onclick="editWatchStock('${item.symbol}', ${item.entry_price}, ${item.shares})">✏️ 修改</button>
          <button class="btn btn-outline" style="padding: 4px 8px; font-size:12px; margin-right:4px;" onclick="quickDiagnose('${item.symbol}')">诊断</button>
          <button class="btn btn-danger" style="padding: 4px 8px; font-size:12px;" onclick="deleteWatch('${item.symbol}')">移除</button>
        </td>
      </tr>
    `;
  }).join('');
}

function editWatchStock(symbol, entryPrice, shares) {
  const input = document.getElementById('inputAddCode');
  const priceInput = document.getElementById('inputAddEntryPrice');
  const sharesInput = document.getElementById('inputAddShares');
  input.value = symbol;
  priceInput.value = entryPrice > 0 ? entryPrice : '';
  sharesInput.value = shares > 0 ? shares : '';
  priceInput.focus();
  input.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function addWatchlistStock() {
  const input = document.getElementById('inputAddCode');
  const priceInput = document.getElementById('inputAddEntryPrice');
  const sharesInput = document.getElementById('inputAddShares');
  const code = input.value.trim();
  const entryPrice = parseFloat(priceInput.value) || 0;
  const shares = parseInt(sharesInput.value) || 0;

  if (!code) {
    alert('请输入主板股票代码，如 600519 或 002594');
    return;
  }

  try {
    const res = await fetch('/api/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: code, entry_price: entryPrice, shares: shares, t0_enabled: true })
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || '添加失败');
      return;
    }
    input.value = '';
    priceInput.value = '';
    sharesInput.value = '';
    fetchWatchlist();
  } catch (e) {
    alert('请求异常: ' + e);
  }
}

// 3.5 A股 T+1 日内做T雷达逻辑
async function fetchT0Monitor() {
  const container = document.getElementById('t0Container');
  if (!container) return;

  try {
    const res = await fetch('/api/t0/monitor');
    const list = await res.json();
    renderT0Cards(list);
  } catch (e) {
    console.error('获取做T监控失败:', e);
  }
}

function renderT0Cards(list) {
  const container = document.getElementById('t0Container');
  if (!list || list.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1/-1; text-align: center; padding: 60px 20px; color: var(--text-muted);">
        <p style="font-size: 16px; margin-bottom: 8px;">暂无持仓做T监控标的</p>
        <p style="font-size: 13px;">请在「盘中自选实时监控」中录入持有底仓股数（至少100股），系统将全自动分析日内分时VWAP均线并研判做T机会。</p>
      </div>`;
    return;
  }

  container.innerHTML = list.map(item => {
    const isBuyT = item.t_action === 'BUY_T';
    const isSellT = item.t_action === 'SELL_T';
    
    let cardClass = 'stock-card';
    let badgeClass = 'badge-tag badge-watch';
    let badgeText = '分时中性 (观望蓄势)';
    
    if (isBuyT) {
      cardClass = 'stock-card card-buy';
      badgeClass = 'badge-tag badge-buy';
      badgeText = '⚡ 正T低吸点 (建议买入)';
    } else if (isSellT) {
      cardClass = 'stock-card';
      badgeClass = 'badge-tag badge-watch';
      badgeText = '🎯 倒T高抛点 (冲高先卖)';
    }

    const biasColor = item.bias >= 0 ? '#ef4444' : '#10b981';
    const pivots = item.pivots || {};
    const reasonsHtml = (item.reasons || []).map(r => `<li>${r}</li>`).join('');

    return `
      <div class="${cardClass}">
        <div class="stock-card-header">
          <div class="stock-name-box">
            <h3>${item.name} <span class="stock-code">${item.symbol}</span></h3>
            <span class="${badgeClass}">${badgeText}</span>
          </div>
          <div class="stock-price-box">
            <div class="stock-price">${item.price.toFixed(2)}</div>
            <div style="font-size: 12px; color: ${biasColor}; font-weight:700;">
              偏离均线: ${item.bias >= 0 ? '+' : ''}${item.bias}%
            </div>
          </div>
        </div>

        <!-- 分时与VWAP均线对比 -->
        <div class="metrics-row">
          <div class="metric-item">
            <span>分时现价</span>
            <span style="font-weight:700;">${item.price.toFixed(2)}元</span>
          </div>
          <div class="metric-item">
            <span>分时均价(VWAP)</span>
            <span style="color:#38bdf8; font-weight:700;">${item.vwap.toFixed(2)}元</span>
          </div>
          <div class="metric-item">
            <span>持有底仓</span>
            <span>${item.holding_shares > 0 ? item.holding_shares + '股' : '未持仓'}</span>
          </div>
          <div class="metric-item">
            <span>建议做T股数</span>
            <span style="color:#f59e0b; font-weight:700;">${item.suggested_shares > 0 ? item.suggested_shares + '股' : '--'}</span>
          </div>
        </div>

        <!-- 枢轴阻力与支撑 -->
        <div class="trade-levels-box" style="display:flex; flex-direction:column; gap:6px;">
          <div style="display:flex; justify-content:space-between;">
            <span style="color:var(--text-dim);">日内压力 R1: <strong>${pivots.r1 || 0}元</strong></span>
            <span style="color:var(--text-dim);">日内支撑 S1: <strong>${pivots.s1 || 0}元</strong></span>
          </div>
          <div style="display:flex; justify-content:space-between; font-weight:700;">
            <span style="color:#10b981;">对冲目标价: ${item.target_price || 0}元</span>
            <span style="color:#f59e0b;">预期差价: +${item.expected_spread_pct || 0}%</span>
          </div>
        </div>

        <ul class="reasons-list">
          ${reasonsHtml}
        </ul>

        <div style="display: flex; gap: 8px; margin-top: auto; padding-top: 8px;">
          <button class="btn btn-outline" style="flex:1; padding: 6px;" onclick="quickDiagnose('${item.symbol}')">查看日线K线与RSRS</button>
        </div>
      </div>
    `;
  }).join('');
}

async function addStockToWatch(symbol, price) {
  try {
    const res = await fetch('/api/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: symbol, entry_price: price })
    });
    if (res.ok) {
      alert(`已将 ${symbol} 加入自选监控池！`);
      fetchWatchlist();
    }
  } catch (e) {
    console.error(e);
  }
}

async function deleteWatch(symbol) {
  if (!confirm(`确认将 ${symbol} 从自选池移除？`)) return;
  try {
    await fetch(`/api/watchlist/${symbol}`, { method: 'DELETE' });
    fetchWatchlist();
  } catch (e) {
    alert('移除失败: ' + e);
  }
}

// 4. 单股深度量化诊断与 Canvas K线/RSRS渲染
function quickDiagnose(symbol) {
  document.getElementById('inputDiagnoseCode').value = symbol;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.style.display = 'none');
  
  const targetBtn = document.querySelector('[data-tab="diagnose"]');
  if (targetBtn) targetBtn.classList.add('active');
  const targetPane = document.getElementById('pane-diagnose');
  if (targetPane) targetPane.style.display = 'block';
  activeTab = 'diagnose';

  runDiagnose();
}

async function runDiagnose() {
  const code = document.getElementById('inputDiagnoseCode').value.trim();
  if (!code) {
    alert('请输入要诊断的主板股票代码，如 600519');
    return;
  }

  const resultContainer = document.getElementById('diagnoseResultContainer');
  resultContainer.innerHTML = `<div style="text-align:center; padding: 40px; color:var(--text-muted);">正在计算 ${code} 的修正RSRS与多周期量价特征...</div>`;

  try {
    const res = await fetch(`/api/stock/diagnose?symbol=${code}`);
    const data = await res.json();
    if (!res.ok) {
      resultContainer.innerHTML = `<div style="color:#ef4444; padding:20px;">诊断失败: ${data.detail || '未知原因'}</div>`;
      return;
    }

    renderDiagnoseDetails(data);
    renderKlineChart(data.kline);
  } catch (e) {
    resultContainer.innerHTML = `<div style="color:#ef4444; padding:20px;">诊断异常: ${e}</div>`;
  }
}

function renderDiagnoseDetails(data) {
  const a = data.analysis;
  const q = data.quote;
  const isBuy = a.signal_type === 'BUY';
  const badgeClass = isBuy ? 'badge-tag badge-buy' : 'badge-tag badge-watch';
  const changeClass = a.change_pct >= 0 ? 'bull' : 'bear';
  const levels = a.trade_levels || {};

  const reasonsHtml = (a.reasons || []).map(r => `<li>${r}</li>`).join('');

  const chipInfo = a.chip_info || {};
  const mainCost = a.main_cost || chipInfo.main_cost || a.price;
  const biasToMain = a.bias_to_main !== undefined ? a.bias_to_main : (chipInfo.bias_to_main || 0);
  const controlStatus = a.control_status || chipInfo.control_status || '洗盘蓄势';
  const profitRatio = a.profit_chip_ratio !== undefined ? a.profit_chip_ratio : (chipInfo.profit_chip_ratio || 50);
  let statusBadgeClass = 'badge-neutral';
  if (controlStatus.includes('起爆')) statusBadgeClass = 'badge-bull';
  else if (controlStatus.includes('派发')) statusBadgeClass = 'badge-bear';
  else if (controlStatus.includes('主升')) statusBadgeClass = 'badge-gold';

  const html = `
    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-color); padding-bottom: 16px;">
      <div>
        <h2 style="font-size: 22px;">${a.name} <span style="font-size:14px; color:var(--text-muted);">${a.symbol}</span></h2>
        <div style="margin-top:6px; display:flex; align-items:center; gap:8px;">
          <span class="${badgeClass}" style="font-size: 13px;">${a.signal_desc} (量化评分: ${a.score}分)</span>
          <button class="btn btn-primary" style="padding: 3px 10px; font-size: 11px;" onclick="addStockToWatch('${a.symbol}', ${a.price})">+ 加自选</button>
        </div>
      </div>
      <div style="text-align:right;">
        <div style="font-size: 28px; font-weight:800; font-family:monospace;" class="${changeClass}">${a.price.toFixed(2)}</div>
        <div style="font-size: 14px;" class="${changeClass}">${a.change_pct >= 0 ? '+' : ''}${a.change_pct.toFixed(2)}%</div>
      </div>
    </div>

    <!-- 🏦 主力筹码成本与庄家控盘深度透视矩阵 -->
    <div class="card" style="margin-top:16px; background: rgba(14, 165, 233, 0.05); border: 1px solid rgba(14, 165, 233, 0.25); padding:16px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <h4 style="font-size:14px; color:var(--color-gold); display:flex; align-items:center; gap:8px;">
          <span>🏦 主力筹码与庄家控盘透视矩阵</span>
          <span class="badge ${statusBadgeClass}">${controlStatus}</span>
        </h4>
        <span style="font-size:12px; color:var(--text-muted);">安全边际评分: <strong style="color:var(--color-accent); font-size:14px;">${chipInfo.safety_score || 85}分</strong></span>
      </div>

      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap:12px; margin-bottom:12px;">
        <div>
          <span style="font-size:11px; color:var(--text-dim);">主力建仓加权成本</span>
          <div style="font-size:18px; font-weight:700; color:var(--color-gold); font-family:monospace;">${mainCost.toFixed(2)}元</div>
          <small style="color:${biasToMain >= 0 ? 'var(--color-bull)' : 'var(--color-bear)'};">${biasToMain >= 0 ? '+' : ''}${biasToMain}% 较主力溢价</small>
        </div>
        <div>
          <span style="font-size:11px; color:var(--text-dim);">筹码最高密集主峰</span>
          <div style="font-size:18px; font-weight:700; font-family:monospace;">${(chipInfo.chip_peak_price || mainCost).toFixed(2)}元</div>
          <small style="color:var(--text-dim);">底部密集成交价位</small>
        </div>
        <div>
          <span style="font-size:11px; color:var(--text-dim);">全盘获利比例</span>
          <div style="font-size:18px; font-weight:700; color:#10b981; font-family:monospace;">${profitRatio}%</div>
          <small style="color:var(--text-dim);">${profitRatio > 70 ? '🟢 抛压极轻 无深套盘' : '🟡 存在上方解套抛压'}</small>
        </div>
        <div>
          <span style="font-size:11px; color:var(--text-dim);">70% 筹码集中度</span>
          <div style="font-size:18px; font-weight:700; font-family:monospace;">${chipInfo.concentration_70 || 12}%</div>
          <small style="color:var(--text-dim);">${(chipInfo.concentration_70 || 12) < 12 ? '🔥 筹码高度单峰锁定' : '筹码相对分散'}</small>
        </div>
      </div>

      <div style="background:rgba(255,255,255,0.06); height:6px; border-radius:3px; overflow:hidden; margin-bottom:10px;">
        <div style="width:${Math.min(Math.max(profitRatio, 0), 100)}%; height:100%; background:linear-gradient(90deg, #10b981, #38bdf8);"></div>
      </div>

      <div style="font-size:12px; color:var(--text-muted); line-height:1.6; background:rgba(0,0,0,0.25); padding:8px 12px; border-radius:4px;">
        💡 <strong>主力操盘建议</strong>：${chipInfo.action_advice || '主力建仓成本提供坚实支撑，依托生命线顺势波段交易。'}
      </div>
    </div>

    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-top:16px;">
      <div class="card" style="padding:12px; background:rgba(0,0,0,0.3);">
        <span style="font-size:11px; color:var(--text-dim);">修正 RSRS 指标</span>
        <div style="font-size:18px; font-weight:700; color:#38bdf8; margin-top:4px;">${a.rsrs_norm}</div>
        <small style="color:var(--text-dim);">R²: ${a.rsrs_r2} | Beta: ${a.rsrs_beta}</small>
      </div>
      <div class="card" style="padding:12px; background:rgba(0,0,0,0.3);">
        <span style="font-size:11px; color:var(--text-dim);">MA20 生命线</span>
        <div style="font-size:18px; font-weight:700; margin-top:4px;">${a.ma20}</div>
        <small style="color:var(--text-dim);">${a.price > a.ma20 ? '✅ 站上MA20多头' : '⚠️ 位于MA20下方'}</small>
      </div>
      <div class="card" style="padding:12px; background:rgba(0,0,0,0.3);">
        <span style="font-size:11px; color:var(--text-dim);">ATR 波动止损建议</span>
        <div style="font-size:18px; font-weight:700; color:#ef4444; margin-top:4px;">${levels.initial_stop}元</div>
        <small style="color:var(--text-dim);">最大防守比例 -${levels.stop_pct}%</small>
      </div>
      <div class="card" style="padding:12px; background:rgba(0,0,0,0.3);">
        <span style="font-size:11px; color:var(--text-dim);">波段目标止盈</span>
        <div style="font-size:18px; font-weight:700; color:#10b981; margin-top:4px;">${levels.target_price}元</div>
        <small style="color:var(--text-dim);">预期收益空间 +${levels.reward_pct}%</small>
      </div>
    </div>

    <div style="margin-top:16px;">
      <h4 style="font-size:13px; color:var(--text-muted); margin-bottom:8px;">💡 核心研判逻辑剖析：</h4>
      <ul class="reasons-list">
        ${reasonsHtml}
      </ul>
    </div>
  `;
  document.getElementById('diagnoseResultContainer').innerHTML = html;
}

// Canvas 高精专业绘制 K线 与 RSRS 副图
function renderKlineChart(klineData) {
  if (!klineData || klineData.length === 0) return;

  const canvas = document.getElementById('klineCanvas');
  const rsrsCanvas = document.getElementById('rsrsCanvas');
  const ctx = canvas.getContext('2d');
  const rsrsCtx = rsrsCanvas.getContext('2d');

  // 处理高清 DPR 渲染
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.parentElement.clientWidth - 32;
  const height = 340;
  const rsrsHeight = 100;

  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  ctx.scale(dpr, dpr);

  rsrsCanvas.width = width * dpr;
  rsrsCanvas.height = rsrsHeight * dpr;
  rsrsCanvas.style.width = width + 'px';
  rsrsCanvas.style.height = rsrsHeight + 'px';
  rsrsCtx.scale(dpr, dpr);

  // 清空画布
  ctx.clearRect(0, 0, width, height);
  rsrsCtx.clearRect(0, 0, width, rsrsHeight);

  const len = klineData.length;
  const paddingLeft = 10;
  const paddingRight = 60;
  const chartWidth = width - paddingLeft - paddingRight;
  const candleStep = chartWidth / len;
  const candleWidth = Math.max(candleStep * 0.7, 3);

  // 计算价格最值
  let maxPrice = -Infinity;
  let minPrice = Infinity;
  let maxRSRS = -Infinity;
  let minRSRS = Infinity;

  klineData.forEach(d => {
    maxPrice = Math.max(maxPrice, d.high, d.ma5 || 0, d.ma20 || 0);
    minPrice = Math.min(minPrice, d.low);
    if (d.rsrs_norm !== null) {
      maxRSRS = Math.max(maxRSRS, d.rsrs_norm);
      minRSRS = Math.min(minRSRS, d.rsrs_norm);
    }
  });

  const pricePadding = (maxPrice - minPrice) * 0.08 || 1;
  maxPrice += pricePadding;
  minPrice = Math.max(0, minPrice - pricePadding);

  maxRSRS = Math.max(maxRSRS, 1.2);
  minRSRS = Math.min(minRSRS, -1.2);

  const getY = (p) => height - 30 - ((p - minPrice) / (maxPrice - minPrice)) * (height - 50);
  const getRsrsY = (r) => rsrsHeight - 20 - ((r - minRSRS) / (maxRSRS - minRSRS)) * (rsrsHeight - 35);

  // 绘制网格与刻度
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = 20 + i * ((height - 50) / 4);
    ctx.beginPath();
    ctx.moveTo(paddingLeft, y);
    ctx.lineTo(width - paddingRight, y);
    ctx.stroke();

    const priceVal = maxPrice - i * ((maxPrice - minPrice) / 4);
    ctx.fillStyle = '#64748b';
    ctx.font = '10px monospace';
    ctx.fillText(priceVal.toFixed(2), width - paddingRight + 8, y + 3);
  }

  // 绘制每根K线
  klineData.forEach((d, i) => {
    const x = paddingLeft + i * candleStep + candleStep / 2;
    const isBull = d.close >= d.open;
    const color = isBull ? '#ef4444' : '#10b981';

    // 影线
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(x, getY(d.high));
    ctx.lineTo(x, getY(d.low));
    ctx.stroke();

    // 烛体
    const topY = getY(Math.max(d.open, d.close));
    const bottomY = getY(Math.min(d.open, d.close));
    const bodyHeight = Math.max(bottomY - topY, 1.5);

    ctx.fillStyle = color;
    ctx.fillRect(x - candleWidth / 2, topY, candleWidth, bodyHeight);
  });

  // 绘制 X 轴日期刻度
  ctx.fillStyle = '#64748b';
  ctx.font = '10px monospace';
  const labelInterval = Math.max(Math.floor(len / 6), 1);
  klineData.forEach((d, i) => {
    if (i % labelInterval === 0 || i === len - 1) {
      const x = paddingLeft + i * candleStep;
      ctx.fillText((d.date || '').slice(5), x, height - 8);
    }
  });

  // 绘制均线 (MA5: 蓝色, MA20: 橙色)
  function drawLine(key, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let started = false;
    klineData.forEach((d, i) => {
      const val = d[key];
      if (val !== null && val !== undefined) {
        const x = paddingLeft + i * candleStep + candleStep / 2;
        const y = getY(val);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
    });
    ctx.stroke();
  }
  drawLine('ma5', '#38bdf8');
  drawLine('ma20', '#f59e0b');

  // 图例
  ctx.fillStyle = '#38bdf8';
  ctx.fillText('—— MA5', paddingLeft, 14);
  ctx.fillStyle = '#f59e0b';
  ctx.fillText('—— MA20', paddingLeft + 60, 14);

  // 绘制副图 RSRS 曲线与 0.7 阈值线
  const thresholdY = getRsrsY(0.7);
  rsrsCtx.strokeStyle = 'rgba(239, 68, 68, 0.4)';
  rsrsCtx.setLineDash([4, 4]);
  rsrsCtx.beginPath();
  rsrsCtx.moveTo(paddingLeft, thresholdY);
  rsrsCtx.lineTo(width - paddingRight, thresholdY);
  rsrsCtx.stroke();
  rsrsCtx.setLineDash([]);
  rsrsCtx.fillStyle = '#ef4444';
  rsrsCtx.fillText('买入临界: 0.7', width - paddingRight + 6, thresholdY + 3);

  // RSRS 折线
  rsrsCtx.strokeStyle = '#a855f7';
  rsrsCtx.lineWidth = 1.8;
  rsrsCtx.beginPath();
  let rsrsStarted = false;
  klineData.forEach((d, i) => {
    if (d.rsrs_norm !== null) {
      const x = paddingLeft + i * candleStep + candleStep / 2;
      const y = getRsrsY(d.rsrs_norm);
      if (!rsrsStarted) {
        rsrsCtx.moveTo(x, y);
        rsrsStarted = true;
      } else {
        rsrsCtx.lineTo(x, y);
      }
    }
  });
  rsrsCtx.stroke();

  rsrsCtx.fillStyle = '#a855f7';
  rsrsCtx.fillText('修正 RSRS 曲线', paddingLeft, 14);
}

// 5. 历史预警信号流
async function fetchSignalsHistory() {
  try {
    const res = await fetch('/api/signals/history');
    const list = await res.json();
    renderSignalsTimeline(list);
  } catch (e) {
    console.error('获取历史信号失败:', e);
  }
}

function renderSignalsTimeline(list) {
  const container = document.getElementById('signalsTimeline');
  if (!list || list.length === 0) {
    container.innerHTML = `<div style="text-align:center; padding: 40px; color:var(--text-dim);">暂无历史预警记录</div>`;
    return;
  }

  container.innerHTML = list.map(item => {
    const isBuy = item.signal_type === 'BUY';
    const badgeClass = isBuy ? 'badge-tag badge-buy' : 'badge-tag badge-watch';

    return `
      <div class="timeline-item ${isBuy ? 'buy' : ''}">
        <div>
          <span style="font-size:11px; color:var(--text-dim);">${item.timestamp || item.date}</span>
          <h4 style="margin-top:2px; font-size:15px;">${item.name} (${item.symbol}) - 现价 ${item.price}元</h4>
          <span style="font-size:12px; color:var(--text-muted);">${(item.reasons || [])[0] || item.signal_desc}</span>
        </div>
        <div>
          <span class="${badgeClass}">${item.signal_desc} (${item.score}分)</span>
        </div>
      </div>
    `;
  }).join('');
}

// 6. 系统配置与推送设置
async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    const cfg = await res.json();

    document.getElementById('cfgRsrsBuy').value = cfg.rsrs_buy_threshold || 0.7;
    document.getElementById('cfgTrailingStop').value = (cfg.trailing_stop_pct * 100) || 6;
    if (document.getElementById('cfgT0BiasBuy')) {
      document.getElementById('cfgT0BiasBuy').value = cfg.t0_bias_buy !== undefined ? cfg.t0_bias_buy : -1.5;
    }
    if (document.getElementById('cfgT0BiasSell')) {
      document.getElementById('cfgT0BiasSell').value = cfg.t0_bias_sell !== undefined ? cfg.t0_bias_sell : 2.0;
    }
    if (document.getElementById('cfgMinTurnover')) {
      document.getElementById('cfgMinTurnover').value = (cfg.min_turnover_amount / 100000000) || 1.0;
    }
    document.getElementById('cfgDingtalkEnabled').checked = cfg.dingtalk_enabled || false;
    document.getElementById('cfgDingtalkWebhook').value = cfg.dingtalk_webhook || '';
    document.getElementById('cfgDingtalkSecret').value = cfg.dingtalk_secret || '';

    document.getElementById('cfgWechatEnabled').checked = cfg.wechat_enabled || false;
    document.getElementById('cfgWechatProvider').value = cfg.wechat_provider || 'pushplus';
    document.getElementById('cfgWechatToken').value = cfg.wechat_token || '';
  } catch (e) {
    console.error('加载系统配置失败:', e);
  }
}

async function saveSettings() {
  const cfg = {
    rsrs_buy_threshold: parseFloat(document.getElementById('cfgRsrsBuy').value) || 0.7,
    trailing_stop_pct: (parseFloat(document.getElementById('cfgTrailingStop').value) || 6) / 100,
    t0_bias_buy: parseFloat(document.getElementById('cfgT0BiasBuy')?.value) || -1.5,
    t0_bias_sell: parseFloat(document.getElementById('cfgT0BiasSell')?.value) || 2.0,
    min_turnover_amount: (parseFloat(document.getElementById('cfgMinTurnover')?.value) || 1.0) * 100000000,
    dingtalk_enabled: document.getElementById('cfgDingtalkEnabled').checked,
    dingtalk_webhook: document.getElementById('cfgDingtalkWebhook').value.trim(),
    dingtalk_secret: document.getElementById('cfgDingtalkSecret').value.trim(),
    wechat_enabled: document.getElementById('cfgWechatEnabled').checked,
    wechat_provider: document.getElementById('cfgWechatProvider').value,
    wechat_token: document.getElementById('cfgWechatToken').value.trim()
  };

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg)
    });
    const data = await res.json();
    if (data.success) {
      alert('系统配置已成功保存！');
    } else {
      alert('保存失败');
    }
  } catch (e) {
    alert('保存异常: ' + e);
  }
}

async function sendTestNotification() {
  const btn = document.getElementById('btnTestNotify');
  btn.disabled = true;
  btn.textContent = '📨 正在发送测试...';
  try {
    const res = await fetch('/api/notify/test', { method: 'POST' });
    const data = await res.json();
    alert('测试消息发送完成！请检查您的钉钉群或微信消息。\n' + JSON.stringify(data.details, null, 2));
  } catch (e) {
    alert('测试发送失败: ' + e);
  } finally {
    btn.disabled = false;
    btn.textContent = '🔔 发送测试推送到微信/钉钉';
  }
}

// ==========================================
// 6. 收盘全景复盘与参数自迭代前端交互
// ==========================================

let latestReviewMarkdown = '';

async function fetchReviewData() {
  try {
    const [resRev, resOpt] = await Promise.all([
      fetch('/api/review/latest'),
      fetch('/api/optimization/log')
    ]);
    const reviewData = await resRev.json();
    const optLogs = await resOpt.json();

    if (!reviewData || !reviewData.market_analysis) {
      document.getElementById('reviewMarkdownView').textContent = '暂无收盘复盘数据，可点击右上角“立即执行收盘复盘 & 自迭代”开始生成。';
      return;
    }

    renderReviewOverview(reviewData, optLogs || []);
  } catch (e) {
    console.error('获取收盘复盘数据失败:', e);
  }
}

function renderReviewOverview(review, optLogs) {
  latestReviewMarkdown = review.report_markdown || '';

  // 1. 最近时间
  const timeEl = document.getElementById('reviewLastTime');
  if (timeEl) {
    timeEl.textContent = `最近复盘时间：${review.timestamp || review.date || '--'}`;
  }

  // 2. 指征卡片 1: 大盘定性
  const mkt = review.market_analysis || {};
  const regimeEl = document.getElementById('metricMarketRegime');
  const posEl = document.getElementById('metricMarketPos');
  if (regimeEl) {
    const regime = mkt.regime || '结构震荡';
    let badgeClass = 'badge-neutral';
    if (regime.includes('多头')) badgeClass = 'badge-bull';
    else if (regime.includes('空头')) badgeClass = 'badge-bear';
    regimeEl.innerHTML = `<span class="badge ${badgeClass}" style="font-size: 18px; padding: 4px 12px;">${regime}</span>`;
  }
  if (posEl) {
    posEl.textContent = `建议仓位: ${mkt.suggested_position || '5成左右'} (上限 ${mkt.max_position_pct || 60}%)`;
  }

  // 指征卡片 2: 自选持仓
  const wl = review.watchlist_review || {};
  const pnlEl = document.getElementById('metricHoldingPnL');
  const valEl = document.getElementById('metricHoldingValue');
  if (pnlEl) {
    const pnl = wl.total_floating_pnl || 0;
    const isUp = pnl >= 0;
    pnlEl.innerHTML = `<span style="color: ${isUp ? 'var(--color-bull)' : 'var(--color-bear)'};">${isUp ? '+' : ''}${pnl.toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})} 元</span>`;
  }
  if (valEl) {
    const totalMv = wl.total_market_value || 0;
    const mvWan = (totalMv / 10000).toFixed(2);
    valEl.textContent = `持仓市值: ${mvWan} 万元 (${wl.holding_count || 0} 只持仓)`;
  }

  // 指征卡片 3: 胜率追踪
  const sig = review.signal_tracking || {};
  const wrEl = document.getElementById('metricWinRate');
  const scEl = document.getElementById('metricSignalCount');
  if (wrEl) {
    const wr = sig.win_rate !== undefined ? sig.win_rate : 50;
    wrEl.textContent = `${wr.toFixed(1)}%`;
    wrEl.style.color = wr >= 60 ? 'var(--color-bull)' : (wr <= 40 ? 'var(--color-bear)' : 'var(--color-gold)');
  }
  if (scEl) {
    const avgProfit = sig.avg_profit_pct || 0;
    scEl.textContent = `核算 ${sig.total_audited || 0} 笔 | 均益: ${avgProfit >= 0 ? '+' : ''}${avgProfit.toFixed(2)}%`;
  }

  // 指征卡片 4: 策略自我迭代
  const opt = review.optimization || {};
  const rsrsEl = document.getElementById('metricRsrsThreshold');
  const optSubEl = document.getElementById('metricOptStatus');
  const curParams = opt.current_params || {};
  if (rsrsEl) {
    rsrsEl.textContent = `RSRS: ${curParams.rsrs_buy_threshold || 0.70}`;
  }
  if (optSubEl) {
    const trail = ((curParams.trailing_stop_pct || 0.06) * 100).toFixed(1);
    optSubEl.textContent = `移动止盈: ${trail}% | ${opt.action_taken || '参数稳定'}`;
  }

  // 3. 表格渲染：大盘指数诊断
  const mktTbody = document.getElementById('marketReviewTbody');
  if (mktTbody && mkt.indices) {
    let rows = '';
    for (const [code, idx] of Object.entries(mkt.indices)) {
      const isUp = (idx.change_pct || 0) >= 0;
      const color = isUp ? 'var(--color-bull)' : 'var(--color-bear)';
      const sign = isUp ? '+' : '';
      rows += `
        <tr>
          <td><strong>${idx.name}</strong> <span style="font-size:11px; color:var(--text-dim);">${idx.symbol}</span></td>
          <td style="font-weight:700; color:${color};">${(idx.close || 0).toFixed(2)}</td>
          <td style="font-weight:700; color:${color};">${sign}${(idx.change_pct || 0).toFixed(2)}%</td>
          <td><span class="badge ${idx.ma_status.includes('多头') ? 'badge-bull' : 'badge-bear'}">${idx.ma_status}</span></td>
          <td>${idx.vol_status} (量比 ${(idx.vol_ratio || 1).toFixed(2)})</td>
          <td><span class="badge ${idx.health.includes('强势') ? 'badge-bull' : 'badge-neutral'}">${idx.health}</span></td>
        </tr>
      `;
    }
    mktTbody.innerHTML = rows || '<tr><td colspan="6" style="text-align:center;">暂无大盘数据</td></tr>';
  }

  // 4. 表格渲染：持仓深度体检
  const wlTbody = document.getElementById('watchlistReviewTbody');
  if (wlTbody) {
    const holdings = wl.holdings || [];
    if (holdings.length === 0) {
      wlTbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--text-dim);">当前自选池中暂未录入持仓股数（可在“自选实时监控”中维护底仓）</td></tr>';
    } else {
      let rows = '';
      for (const h of holdings) {
        const isProfit = (h.profit_pct || 0) >= 0;
        const color = isProfit ? 'var(--color-bull)' : 'var(--color-bear)';
        const sign = isProfit ? '+' : '';
        let adviceBadge = 'badge-info';
        if (h.advice.includes('止损') || h.advice.includes('破位')) adviceBadge = 'badge-bear';
        else if (h.advice.includes('保利') || h.advice.includes('止盈')) adviceBadge = 'badge-gold';
        else if (h.advice.includes('安全')) adviceBadge = 'badge-bull';

        const mainCost = h.main_cost || h.close || 0;
        const controlStatus = h.control_status || '洗盘蓄势';
        let statusBadge = 'badge-neutral';
        if (controlStatus.includes('起爆')) statusBadge = 'badge-bull';
        else if (controlStatus.includes('派发')) statusBadge = 'badge-bear';
        else if (controlStatus.includes('主升')) statusBadge = 'badge-gold';

        rows += `
          <tr>
            <td><strong>${h.name}</strong> <span style="font-size:11px; color:var(--text-dim);">${h.symbol}</span></td>
            <td><strong>${(h.close || 0).toFixed(2)}</strong></td>
            <td>
              <strong style="color:var(--color-gold); font-family:monospace;">${mainCost.toFixed(2)}元</strong>
              <span style="font-size:11px; display:block; color:${(h.close || 0) >= mainCost ? 'var(--color-bull)' : 'var(--color-bear)'};">${h.cost_vs_main !== undefined ? (h.cost_vs_main >= 0 ? '+' : '') + h.cost_vs_main + '%' : '--'}</span>
            </td>
            <td><span class="badge ${statusBadge}">${controlStatus}</span></td>
            <td style="font-weight:700; color:${color};">${sign}${(h.profit_pct || 0).toFixed(2)}%</td>
            <td>${(h.stop_loss_price || 0).toFixed(2)} <span style="font-size:11px; color:var(--text-dim);">(距 ${h.stop_loss_margin_pct || 0}%)</span></td>
            <td>${(h.trailing_stop_price || 0).toFixed(2)} <span style="font-size:11px; color:var(--text-dim);">(距 ${h.trailing_stop_margin_pct || 0}%)</span></td>
            <td><span class="badge ${adviceBadge}">${h.advice}</span></td>
          </tr>
        `;
      }
      wlTbody.innerHTML = rows;
    }
  }

  // 5. 表格渲染：信号回访
  const sigTbody = document.getElementById('signalsTrackingTbody');
  if (sigTbody) {
    const list = sig.audited_signals || [];
    if (list.length === 0) {
      sigTbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-dim);">近10日内暂无策略触发信号记录</td></tr>';
    } else {
      let rows = '';
      for (const s of list) {
        const isUp = (s.profit_pct || 0) >= 0;
        const color = isUp ? 'var(--color-bull)' : 'var(--color-bear)';
        const sign = isUp ? '+' : '';
        let statusBadge = 'badge-neutral';
        let statusText = '持平';
        if (s.status === 'WIN') { statusBadge = 'badge-bull'; statusText = '盈利 (+%)'; }
        else if (s.status === 'LOSS') { statusBadge = 'badge-bear'; statusText = '回撤 (-%)'; }
        else if (s.status === 'OPEN') { statusBadge = 'badge-info'; statusText = '跟踪中'; }

        rows += `
          <tr>
            <td><strong>${s.name}</strong> <span style="font-size:11px; color:var(--text-dim);">${s.symbol}</span></td>
            <td>${s.date}</td>
            <td>${(s.benchmark_price || 0).toFixed(2)}</td>
            <td>${(s.current_price || 0).toFixed(2)}</td>
            <td style="font-weight:700; color:${color};">${sign}${(s.profit_pct || 0).toFixed(2)}%</td>
            <td><span class="badge ${statusBadge}">${statusText}</span></td>
          </tr>
        `;
      }
      sigTbody.innerHTML = rows;
    }
  }

  // 6. 表格渲染：参数自迭代调优记录
  const optTbody = document.getElementById('optimizationLogTbody');
  if (optTbody) {
    if (optLogs.length === 0) {
      optTbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-dim);">暂无参数调整记录，系统参数正处于稳态运行</td></tr>';
    } else {
      let rows = '';
      for (const item of optLogs.slice(0, 10)) {
        rows += `
          <tr>
            <td style="font-size:12px;">${item.time}</td>
            <td><span class="badge badge-neutral">${item.market_regime || '震荡'}</span></td>
            <td>${(item.recent_win_rate || 50).toFixed(1)}%</td>
            <td style="color:var(--color-accent); font-size:12px;">${item.action_taken || '维持当前参数'}</td>
            <td><span class="badge ${item.applied ? 'badge-bull' : 'badge-neutral'}">${item.applied ? '已自动生效' : '保持'}</span></td>
          </tr>
        `;
      }
      optTbody.innerHTML = rows;
    }
  }

  // 7. Markdown 视图渲染
  const mdView = document.getElementById('reviewMarkdownView');
  if (mdView) {
    mdView.textContent = latestReviewMarkdown || '暂无复盘文本报告';
  }
}

async function triggerDailyReview() {
  const btn = document.getElementById('btnTriggerReview');
  const chkNotify = document.getElementById('chkReviewNotify');
  const sendNotify = chkNotify ? chkNotify.checked : false;

  btn.disabled = true;
  btn.textContent = '⏳ 正在量化分析收盘大势与自我迭代中...';

  try {
    const res = await fetch('/api/review/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_optimize: true, send_notify: sendNotify })
    });
    const data = await res.json();
    if (data.success) {
      alert(`🎉 收盘复盘与系统自迭代已完成！\n• 大盘定性: ${data.regime || '结构震荡'}\n• 参数自迭代: ${data.optimization?.action_taken || '稳健保持'}\n• 推送状态: ${sendNotify ? '已发送至微信/钉钉' : '未开启推送'}`);
      await fetchReviewData();
      await loadConfig(); // 刷新配置中已调优的参数
    } else {
      alert('收盘复盘失败，请查看控制台日志');
    }
  } catch (e) {
    alert('触发收盘复盘异常: ' + e);
  } finally {
    btn.disabled = false;
    btn.textContent = '⚡ 立即执行收盘复盘 & 自迭代';
  }
}

function copyReviewMarkdown() {
  if (!latestReviewMarkdown) {
    alert('暂无复盘报告内容可复制');
    return;
  }
  navigator.clipboard.writeText(latestReviewMarkdown).then(() => {
    alert('✅ 收盘复盘 Markdown 报告长文已复制到剪贴板！');
  }).catch(e => {
    alert('复制失败: ' + e);
  });
}

