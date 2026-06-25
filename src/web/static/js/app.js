// OpenClaw Monitor Web Application

// State
let ws = null;
let dashboardData = {};
let modelChart = null;
let tokenDailyChart = null;
let wsReconnectTimer = null;
let tpmTrendChart = null;

// Trace infinite scroll state
let traceState = {
    sessionKey: null,
    events: [],
    offset: 0,
    limit: 50,
    hasMore: true,
    isLoading: false
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    safeInitCharts();
    fetchData();
    connectWebSocket();
    setupEventListeners();
    // 加载 token daily 数据
    const tokenDaysFilter = document.getElementById('token-days-filter');
    const defaultDays = tokenDaysFilter ? parseInt(tokenDaysFilter.value) : 30;
    fetchTokenDailyData(defaultDays);
    
    // 设置默认筛选为"今天"
    setDefaultTimeFilters();
});

// 设置默认时间筛选为今天
function setDefaultTimeFilters() {
    const today = new Date().toISOString().split('T')[0];
    
    // 会话列表筛选 - 设置今天
    const sessionTimeFilter = document.getElementById('session-time-filter');
    if (sessionTimeFilter && sessionTimeFilter.value === 'today') {
        document.getElementById('session-date-start').value = today;
        document.getElementById('session-date-end').value = today;
    }
}

// Setup event listeners
function setupEventListeners() {
    document.getElementById('status-filter').addEventListener('change', fetchSessions);
    document.getElementById('search-input').addEventListener('input', debounce(fetchSessions, 300));
    document.getElementById('session-agent-filter').addEventListener('change', fetchSessions);
    document.getElementById('token-days-filter').addEventListener('change', (e) => {
        fetchTokenDailyData(parseInt(e.target.value));
    });

    // TPM 筛选器
    document.getElementById('tpm-hours-filter').addEventListener('change', fetchTPMData);
    document.getElementById('tpm-agent-filter').addEventListener('change', fetchTPMData);
    document.getElementById('tpm-metric-filter').addEventListener('change', () => {
        updateTPMMetricDesc();
        updateTPMDisplay();
    });

    // 会话列表时间筛选
    document.getElementById('session-time-filter').addEventListener('change', handleSessionTimeFilter);
    document.getElementById('session-date-start').addEventListener('change', fetchSessions);
    document.getElementById('session-date-end').addEventListener('change', fetchSessions);
}

// 设置今天的日期作为默认值
function setTodayDate(elementId) {
    const today = new Date().toISOString().split('T')[0];
    document.getElementById(elementId).value = today;
}

// 处理会话时间筛选快捷选项
function handleSessionTimeFilter() {
    const timeFilter = document.getElementById('session-time-filter').value;
    const dateStartInput = document.getElementById('session-date-start');
    const dateEndInput = document.getElementById('session-date-end');
    const today = new Date().toISOString().split('T')[0];

    if (timeFilter === '') {
        // 全部时间：清空日期并隐藏
        dateStartInput.value = '';
        dateEndInput.value = '';
        dateStartInput.style.display = 'none';
        dateEndInput.style.display = 'none';
    } else if (timeFilter === 'today') {
        // 今天：设置开始和结束为今天
        dateStartInput.value = today;
        dateEndInput.value = today;
        dateStartInput.style.display = 'none';
        dateEndInput.style.display = 'none';
    } else if (timeFilter === 'custom') {
        // 自定义范围：显示日期选择器
        dateStartInput.style.display = 'inline-block';
        dateEndInput.style.display = 'inline-block';
        return; // 不自动触发筛选，等用户选择日期
    } else {
        // 最近N天：计算日期范围
        const days = parseInt(timeFilter);
        const endDate = new Date();
        const startDate = new Date();
        startDate.setDate(startDate.getDate() - days + 1);
        
        dateStartInput.value = startDate.toISOString().split('T')[0];
        dateEndInput.value = endDate.toISOString().split('T')[0];
        dateStartInput.style.display = 'none';
        dateEndInput.style.display = 'none';
    }

    fetchSessions();
}



// Debounce helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Chart color palette - Modern design
const chartColors = {
    primary: '#6366f1',
    primaryLight: 'rgba(99, 102, 241, 0.15)',
    secondary: '#22d3ee',
    secondaryLight: 'rgba(34, 211, 238, 0.15)',
    success: '#34d399',
    successLight: 'rgba(52, 211, 153, 0.15)',
    warning: '#fbbf24',
    error: '#f87171',
    accent: '#f472b6',
    grid: 'rgba(255, 255, 255, 0.05)',
    text: '#94a3b8',
    textLight: '#f1f5f9',
    // Chart.js palette
    palette: [
        '#6366f1', '#22d3ee', '#f472b6', '#34d399', '#fbbf24',
        '#f87171', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16'
    ]
};

// Initialize Chart.js charts
function initCharts() {
    // Model distribution chart (Doughnut)
    const modelCtx = document.getElementById('model-chart').getContext('2d');
    modelChart = new Chart(modelCtx, {
        type: 'doughnut',
        data: {
            labels: ['无数据'],
            datasets: [{
                data: [1],
                backgroundColor: ['rgba(100, 116, 139, 0.3)'],
                borderWidth: 0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        color: chartColors.text,
                        font: { size: 12, family: 'Inter' },
                        padding: 16,
                        usePointStyle: true,
                        pointStyle: 'circle'
                    }
                }
            }
        }
    });

    // Token daily chart (Bar) - supports both hourly and daily data
    const tokenDailyCanvas = document.getElementById('token-daily-chart');
    if (tokenDailyCanvas) {
        const tokenDailyCtx = tokenDailyCanvas.getContext('2d');
        tokenDailyChart = new Chart(tokenDailyCtx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [
                    {
                        label: '输入 Tokens',
                        data: [],
                        backgroundColor: 'rgba(99, 102, 241, 0.7)',
                        borderColor: chartColors.primary,
                        borderWidth: 1,
                        borderRadius: 4,
                    },
                    {
                        label: '输出 Tokens',
                        data: [],
                        backgroundColor: 'rgba(34, 211, 238, 0.7)',
                        borderColor: chartColors.secondary,
                        borderWidth: 1,
                        borderRadius: 4,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        ticks: { color: chartColors.text, maxRotation: 45, font: { size: 11 } },
                        grid: { color: chartColors.grid }
                    },
                    y: {
                        ticks: { 
                            color: chartColors.text, 
                            font: { size: 11 },
                            callback: function(value) {
                                return value + 'M';
                            }
                        },
                        grid: { color: chartColors.grid },
                        beginAtZero: true
                    }
                },
                plugins: {
                    legend: {
                        labels: { 
                            color: chartColors.textLight, 
                            font: { size: 12, family: 'Inter' },
                            usePointStyle: true,
                            pointStyle: 'rect'
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15, 15, 26, 0.9)',
                        titleColor: '#fff',
                        bodyColor: chartColors.text,
                        borderColor: 'rgba(255, 255, 255, 0.1)',
                        borderWidth: 1,
                        padding: 12,
                        cornerRadius: 8,
                        callbacks: {
                            label: function(context) {
                                const value = context.raw;
                                return context.dataset.label + ': ' + value.toFixed(2) + 'M tokens';
                            }
                        }
                    }
                }
            }
        });
    } else {
        console.error('token-daily-chart canvas not found');
    }

    // TPM chart - 使用 CSS 柱状图替代 Chart.js
    // 不需要初始化 Chart.js，改用 updateTPMChartBars 函数动态生成
}

// Guard: run initCharts only if Chart.js loaded and canvases exist
function safeInitCharts() {
    if (typeof Chart === 'undefined') {
        console.warn('Chart.js not loaded, skipping chart init');
        return;
    }
    const modelCanvas = document.getElementById('model-chart');
    if (!modelCanvas || !modelCanvas.getContext) {
        console.warn('model-chart canvas not found');
        return;
    }
    initCharts();
    initTPMTrendChart();
}

// Initialize TPM trend line chart
function initTPMTrendChart() {
    const canvas = document.getElementById('tpm-trend-chart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    tpmTrendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'TPM',
                data: [],
                borderColor: '#22d3ee',
                backgroundColor: 'rgba(34, 211, 238, 0.08)',
                fill: true,
                tension: 0.3,
                pointRadius: 2,
                pointHoverRadius: 4,
                borderWidth: 1.5,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(15, 15, 26, 0.9)',
                    titleColor: '#fff',
                    bodyColor: '#94a3b8',
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    borderWidth: 1,
                    padding: 10,
                    cornerRadius: 8,
                }
            },
            scales: {
                x: {
                    display: true,
                    ticks: {
                        color: '#64748b',
                        font: { size: 10, family: 'JetBrains Mono' },
                        maxTicksLimit: 8,
                    },
                    grid: { display: false }
                },
                y: {
                    display: true,
                    ticks: {
                        color: '#64748b',
                        font: { size: 10 },
                        maxTicksLimit: 4,
                    },
                    grid: {
                        color: 'rgba(255, 255, 255, 0.04)',
                    },
                    beginAtZero: true
                }
            },
            interaction: {
                intersect: false,
                mode: 'index',
            }
        }
    });
}

// Fetch all data
async function fetchData() {
    try {
        const tpmHours = document.getElementById('tpm-hours-filter')?.value || 24;
        
        const [dashboard, sessions, models, tpm] = await Promise.all([
            fetchAPI('/api/dashboard'),
            fetchAPI('/api/sessions?limit=50'),
            fetchAPI('/api/models/stats'),
            fetchAPI(`/api/tpm?hours=${tpmHours}`)
        ]);

        dashboardData = dashboard;
        updateDashboard(dashboard);
        updateSessionsTable(sessions);
        populateSessionFilters(sessions);
        updateModelsTable(models);
        window.tpmData = tpm;
        updateTPMDisplay();
        
        // 应用默认的"今天"筛选（仅设置日期，不触发二次 fetch）
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('session-date-start').value = today;
        document.getElementById('session-date-end').value = today;
    } catch (error) {
        console.error('Fetch error:', error);
    }
}

// Populate session filter dropdowns
function populateSessionFilters(sessions) {
    const agentFilter = document.getElementById('session-agent-filter');
    const tpmAgentFilter = document.getElementById('tpm-agent-filter');

    // Get unique agents
    const agents = new Set();

    sessions.forEach(s => {
        if (s.agent_id) {
            agents.add(s.agent_id);
        }
    });

    // Populate agent filter
    const sortedAgents = Array.from(agents).sort();
    const agentOptions = '<option value="">全部 Agent</option>' +
        sortedAgents.map(a => `<option value="${a}">${a}</option>`).join('');
    
    agentFilter.innerHTML = agentOptions;
    tpmAgentFilter.innerHTML = agentOptions;
}



// Fetch sessions with filters
async function fetchSessions() {
    const status = document.getElementById('status-filter').value;
    const search = document.getElementById('search-input').value;
    const dateStart = document.getElementById('session-date-start').value;
    const dateEnd = document.getElementById('session-date-end').value;
    const agentFilter = document.getElementById('session-agent-filter').value;

    let url = '/api/sessions?limit=200';
    if (status) url += `&status=${status}`;

    try {
        const sessions = await fetchAPI(url);

        // Filter by search, date range, and agent
        let filtered = sessions;
        if (search) {
            const searchLower = search.toLowerCase();
            filtered = filtered.filter(s =>
                (s.session_key || '').toLowerCase().includes(searchLower) ||
                (s.agent_id || '').toLowerCase().includes(searchLower) ||
                (s.last_user_message || '').toLowerCase().includes(searchLower)
            );
        }
        if (dateStart || dateEnd) {
            filtered = filtered.filter(s => {
                if (!s.date) return false;
                const sessionDate = s.date;
                if (dateStart && sessionDate < dateStart) return false;
                if (dateEnd && sessionDate > dateEnd) return false;
                return true;
            });
        }
        if (agentFilter) {
            filtered = filtered.filter(s => s.agent_id === agentFilter);
        }

        updateSessionsTable(filtered);
    } catch (error) {
        console.error('Fetch sessions error:', error);
    }
}

// API helper
async function fetchAPI(endpoint) {
    const response = await fetch(endpoint);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

// Update dashboard stats
function updateDashboard(data) {
    // Gateway status
    const gateway = data.gateway || {};
    const indicator = document.getElementById('gateway-indicator');
    const statusText = document.getElementById('gateway-status-text');
    const responseTime = document.getElementById('gateway-response-time');
    const gatewayContainer = indicator?.closest('.gateway-status');

    if (gateway.healthy) {
        indicator.className = 'status-dot';
        if (gatewayContainer) gatewayContainer.classList.remove('unhealthy');
        statusText.textContent = 'Gateway 正常';
    } else {
        indicator.className = 'status-dot unhealthy';
        if (gatewayContainer) gatewayContainer.classList.add('unhealthy');
        statusText.textContent = gateway.status || '离线';
    }

    responseTime.textContent = gateway.response_time_ms
        ? `${gateway.response_time_ms.toFixed(1)}ms`
        : '-';

    // Stats
    const sessions = data.sessions || {};
    const tokens = data.tokens || {};

    document.getElementById('total-sessions').textContent = sessions.total || 0;
    document.getElementById('active-sessions').textContent = sessions.active || 0;
    document.getElementById('total-tokens').textContent = formatNumber(tokens.total || 0);
    document.getElementById('model-count').textContent =
        Object.keys(data.models?.distribution || {}).length;

    // Update cost card
    const totalCost = data.cost?.total_cost || 0;
    const costCard = document.getElementById('total-cost');
    if (costCard) costCard.textContent = '$' + formatCost(totalCost);

    // Update model chart - 使用现代配色
    const modelDist = data.models?.distribution || {};
    modelChart.data.labels = Object.keys(modelDist);
    modelChart.data.datasets[0].data = Object.values(modelDist);
    modelChart.data.datasets[0].backgroundColor = chartColors.palette.slice(0, Object.keys(modelDist).length);
    modelChart.update();

    // Update last update time
    document.getElementById('last-update').textContent =
        new Date().toLocaleTimeString();
}

// Update sessions table
function updateSessionsTable(sessions) {
    const tbody = document.getElementById('sessions-tbody');

    if (!sessions || sessions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading">暂无会话数据</td></tr>';
        return;
    }

    tbody.innerHTML = sessions.map(s => `
        <tr class="clickable-row" onclick="showSessionDetail('${escapeHtml(s.session_key || '')}')">
            <td><span class="agent-name">${escapeHtml(s.agent_id || '-')}</span></td>
            <td><span class="status-badge ${getStatusClass(s.status)}">${getStatusText(s.status)}</span></td>
            <td>${escapeHtml(s.last_model || '-')}</td>
            <td class="mono">${s.message_count || 0}</td>
            <td class="mono">${formatNumber(s.total_tokens || 0)}</td>
            <td class="mono" style="color: var(--accent-orange)">$${formatCost(s.total_cost)}</td>
            <td>${formatTime(s.updated_at)}</td>
        </tr>
    `).join('');
}

// Format cost with appropriate precision
function formatCost(cost) {
    if (!cost || cost === 0) return '0';
    if (cost < 0.01) return cost.toFixed(4);
    if (cost < 1) return cost.toFixed(3);
    return cost.toFixed(2);
}

// Get status class for badge
function getStatusClass(status) {
    const classMap = {
        'WORKING': 'working',
        'FINISHED': 'finished',
        'INTERRUPTED': 'interrupted',
        'NO_MESSAGE': 'interrupted'
    };
    return classMap[status] || 'finished';
}

// Get status text for badge
function getStatusText(status) {
    const textMap = {
        'WORKING': '运行中',
        'FINISHED': '已完成',
        'INTERRUPTED': '中断',
        'NO_MESSAGE': '无消息'
    };
    return textMap[status] || status || '-';
}

// Update models table
function updateModelsTable(models) {
    const tbody = document.getElementById('models-tbody');

    if (!models || models.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="loading">暂无模型数据</td></tr>';
        return;
    }

    tbody.innerHTML = models.map(m => `
        <tr>
            <td><span class="model-name">${escapeHtml(m.model || '-')}</span></td>
            <td class="mono">${formatNumber(m.total_calls || 0)}</td>
            <td class="mono">${formatNumber(m.total_input_tokens || 0)}</td>
            <td class="mono">${formatNumber(m.total_output_tokens || 0)}</td>
            <td class="mono" style="color: var(--accent-orange)">$${formatCost(m.total_cost)}</td>
        </tr>
    `).join('');
}



// Show session detail modal
function showSessionDetail(sessionKey) {
    if (!sessionKey) return;

    // Reset trace state - 增加每次加载数量
    traceState = {
        sessionKey: sessionKey,
        events: [],
        offset: 0,
        limit: 50,
        totalEvents: 0,
        hasMore: true,
        isLoading: false
    };

    // Fetch session detail first, then load initial trace
    fetch(`/api/sessions/${encodeURIComponent(sessionKey)}`)
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                alert('会话不存在');
                return;
            }

            const modal = document.getElementById('session-modal');
            const modalContent = modal.querySelector('.modal-content');

            // 直接替换 modal-content 的内容
            modalContent.innerHTML = `
                <div class="modal-header-fixed">
                    <h3>📝 会话详情 - ${escapeHtml(data.agent_id || '-')}</h3>
                    <button class="close-btn" onclick="closeModal()">×</button>
                </div>

                <div class="session-tabs-fixed">
                    <button class="tab-btn active" onclick="switchTab('overview', this)">概览</button>
                    <button class="tab-btn" id="trace-tab-btn" onclick="switchTab('trace', this)">Trace (加载中...)</button>
                    <button class="tab-btn" onclick="switchTab('tokens', this)">Token</button>
                </div>

                <div class="modal-body" id="session-modal-body">
                    <div id="tab-overview" class="tab-content active">
                        ${renderOverviewTab(data)}
                    </div>

                    <div id="tab-trace" class="tab-content">
                        <div class="trace-info-bar" id="trace-info-bar">
                            <span class="trace-loaded-count">已加载: 0</span>
                            <span class="trace-total-count">总数: ?</span>
                            <span class="trace-scroll-hint">↓ 滚动加载更多</span>
                        </div>
                        <div class="trace-timeline" id="trace-timeline"></div>
                        <div id="trace-loading" class="trace-loading" style="display: none;">
                            <span class="loading-spinner"></span> 正在加载中...
                        </div>
                        <div id="trace-end" class="trace-end" style="display: none;">
                            已加载全部数据
                        </div>
                    </div>

                    <div id="tab-tokens" class="tab-content">
                        ${renderTokensTab(data)}
                    </div>
                </div>
            `;

            modal.style.display = 'flex';

            // Setup infinite scroll for trace tab
            setupTraceInfiniteScroll();

            // Load initial trace data
            loadMoreTraceData();
        })
        .catch(err => {
            console.error('Failed to fetch session:', err);
            alert('获取会话详情失败');
        });
}

// Setup infinite scroll for trace tab
function setupTraceInfiniteScroll() {
    const modalBody = document.getElementById('session-modal-body');
    if (!modalBody) return;

    // Remove previous scroll listener if exists
    modalBody.removeEventListener('scroll', handleTraceScroll);

    // Add scroll listener with throttle
    modalBody.addEventListener('scroll', throttle(handleTraceScroll, 200));
}

// Handle scroll event for trace infinite loading
function handleTraceScroll() {
    const modalBody = document.getElementById('session-modal-body');
    const traceTab = document.getElementById('tab-trace');

    // Only trigger when trace tab is active
    if (!traceTab || !traceTab.classList.contains('active')) return;

    // Check if near bottom (100px threshold)
    const scrollBottom = modalBody.scrollHeight - modalBody.scrollTop - modalBody.clientHeight;
    if (scrollBottom > 100) return;

    // Don't load if already loading or no more data
    if (traceState.isLoading || !traceState.hasMore) return;

    loadMoreTraceData();
}

// Load more trace data
function loadMoreTraceData() {
    if (traceState.isLoading || !traceState.hasMore) return;

    traceState.isLoading = true;
    showTraceLoading(true);

    const url = `/api/sessions/${encodeURIComponent(traceState.sessionKey)}/trace?offset=${traceState.offset}&limit=${traceState.limit}`;

    fetch(url)
        .then(r => r.json())
        .then(trace => {
            traceState.isLoading = false;
            showTraceLoading(false);

            // 更新总事件数
            if (trace.event_count !== undefined) {
                traceState.totalEvents = trace.event_count;
            }

            if (!trace.events || trace.events.length === 0) {
                traceState.hasMore = false;
                showTraceEnd(true);
                updateTraceInfo();
                return;
            }

            // Append new events and rebuild tree
            traceState.events = traceState.events.concat(trace.events);
            traceState.offset += trace.events.length;

            const timeline = document.getElementById('trace-timeline');
            if (timeline) {
                const tree = buildTraceTree(traceState.events);
                timeline.innerHTML = renderTraceTree(tree);
            }

            // Check if we've loaded all data
            if (trace.events.length < traceState.limit || traceState.offset >= traceState.totalEvents) {
                traceState.hasMore = false;
                showTraceEnd(true);
            }

            // Update trace info display
            updateTraceInfo();
        })
        .catch(err => {
            console.error('Failed to load trace:', err);
            traceState.isLoading = false;
            showTraceLoading(false);
        });
}

// Show/hide trace loading indicator
function showTraceLoading(show) {
    const loading = document.getElementById('trace-loading');
    if (loading) {
        loading.style.display = show ? 'block' : 'none';
    }
}

// Show/hide trace end indicator
function showTraceEnd(show) {
    const end = document.getElementById('trace-end');
    if (end) {
        end.style.display = show ? 'block' : 'none';
    }
}

// Update trace info display
function updateTraceInfo() {
    // 更新标签按钮
    const traceBtn = document.getElementById('trace-tab-btn');
    if (traceBtn) {
        const total = traceState.totalEvents || '?';
        traceBtn.textContent = `Trace (${traceState.offset}/${total})`;
    }

    // 更新信息栏
    const loadedSpan = document.querySelector('.trace-loaded-count');
    const totalSpan = document.querySelector('.trace-total-count');
    const hintSpan = document.querySelector('.trace-scroll-hint');

    if (loadedSpan) {
        loadedSpan.textContent = `已加载: ${traceState.offset}`;
    }
    if (totalSpan) {
        totalSpan.textContent = `总数: ${traceState.totalEvents || '?'}`;
    }
    if (hintSpan) {
        // 如果已加载全部，隐藏滚动提示
        hintSpan.style.display = traceState.hasMore ? 'inline' : 'none';
    }
}

// Throttle function for scroll optimization
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// Render expandable content with collapse/expand
function renderExpandableContent(content, className) {
    const maxLength = 500;
    const isLong = content.length > maxLength;
    const displayContent = isLong ? content.slice(0, maxLength) + '...' : content;

    // Store full content URI-encoded (safe for any special chars in HTML attr)
    const encoded = encodeURIComponent(content);

    return `
        <div class="${className} ${isLong ? 'collapsed' : ''}">
            ${escapeHtml(isLong ? displayContent : content)}
        </div>
        ${isLong ? `<button class="trace-expand-btn" data-full="${encoded}" onclick="toggleTraceContent(this)">展开全部</button>` : ''}
    `;
}

// Toggle trace content expand/collapse
function toggleTraceContent(btn) {
    const contentDiv = btn.previousElementSibling;
    const isCollapsed = contentDiv.classList.contains('collapsed');
    const fullText = decodeURIComponent(btn.dataset.full);

    if (isCollapsed) {
        contentDiv.classList.remove('collapsed');
        contentDiv.textContent = fullText;
        btn.textContent = '收起';
    } else {
        contentDiv.classList.add('collapsed');
        contentDiv.textContent = fullText.slice(0, 500) + '...';
        btn.textContent = '展开全部';
    }
}

// Switch tab
function switchTab(tabName, btn) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(`tab-${tabName}`).classList.add('active');
    btn.classList.add('active');
}

// Render overview tab
function renderOverviewTab(data) {
    return `
        <div class="detail-section">
            <h4>📋 基本信息</h4>
            <div class="detail-grid">
                <div class="detail-row"><span class="detail-label">Session Key:</span> <span class="detail-value text-ellipsis">${escapeHtml(data.session_key || '-')}</span></div>
                <div class="detail-row"><span class="detail-label">Agent:</span> <span class="detail-value">${escapeHtml(data.agent_id || '-')}</span></div>
                <div class="detail-row"><span class="detail-label">状态:</span> <span class="status-badge ${getStatusClass(data.status)}">${getStatusText(data.status)}</span></div>
                <div class="detail-row"><span class="detail-label">通道:</span> <span class="detail-value">${escapeHtml(data.channel || '-')}</span></div>
                <div class="detail-row"><span class="detail-label">消息数:</span> <span class="detail-value">${data.message_count || 0}</span></div>
                <div class="detail-row"><span class="detail-label">Token:</span> <span class="detail-value">${formatNumber((data.total_input_tokens||0) + (data.total_output_tokens||0))}</span></div>
                <div class="detail-row"><span class="detail-label">费用:</span> <span class="detail-value" style="color:var(--accent-orange)">$${formatCost(data.total_cost)}</span></div>
                <div class="detail-row"><span class="detail-label">更新时间:</span> <span class="detail-value">${formatTime(data.updated_at)}</span></div>
            </div>
        </div>

        <div class="detail-section">
            <h4>🤖 模型信息</h4>
            <div class="detail-grid">
                <div class="detail-row"><span class="detail-label">当前模型:</span> <span class="detail-value">${escapeHtml(data.last_model || '-')}</span></div>
                <div class="detail-row"><span class="detail-label">Provider:</span> <span class="detail-value">${escapeHtml(data.last_provider || '-')}</span></div>
            </div>
        </div>

        ${data.model_errors && data.model_errors.length > 0 ? `
        <div class="detail-section error-section">
            <h4>❌ 模型错误 (${data.model_errors.length})</h4>
            <div class="error-list-container">
                ${data.model_errors.slice(0, 10).map((e, i) => `
                <div class="error-item">
                    <div class="error-header">
                        <span class="error-model">${escapeHtml(e.model || 'unknown')}</span>
                        <span class="error-provider">${escapeHtml(e.provider || 'unknown')}</span>
                    </div>
                    <div class="error-text">${escapeHtml(e.error || 'Unknown error')}</div>
                </div>
                `).join('')}
            </div>
        </div>
        ` : ''}
    `;
}

// Render trace tab
function renderTraceTab(trace) {
    if (!trace.events || trace.events.length === 0) {
        return '<div class="no-data">暂无 Trace 数据</div>';
    }

    return `
        <div class="trace-timeline">
            ${trace.events.map((event, index) => renderTraceEvent(event, index)).join('')}
        </div>
    `;
}

// Render single trace event
function renderTraceEvent(event, index) {
    const type = event.type || 'unknown';
    let icon, color, content;

    switch (type) {
        case 'message':
            const role = event.role || 'unknown';
            icon = role === 'user' ? '👤' : role === 'assistant' ? '🤖' : '🔧';
            color = role === 'user' ? 'user-msg' : role === 'assistant' ? 'assistant-msg' : 'tool-msg';

            // Build tool calls HTML
            let toolCallsHtml = '';
            if (event.tool_calls && event.tool_calls.length > 0) {
                toolCallsHtml = event.tool_calls.map(tc => `
                    <div class="trace-tool-call">
                        <span class="tool-call-name">🔧 ${escapeHtml(tc.name)}</span>
                        ${tc.input ? `<div class="tool-call-input">${escapeHtml(JSON.stringify(tc.input, null, 2).slice(0, 300))}</div>` : ''}
                    </div>
                `).join('');
            }

            // Build tool results HTML (for role=toolResult messages)
            let toolResultsHtml = '';
            if (event.tool_results && event.tool_results.length > 0) {
                toolResultsHtml = event.tool_results.map(tr => `
                    <div class="trace-tool-result">
                        <span class="tool-result-status">${tr.status === 'error' ? '❌' : '✅'}</span>
                        <div class="tool-result-content">${renderExpandableContent(tr.content || '', 'trace-result-content')}</div>
                    </div>
                `).join('');
            }

            content = `
                <div class="trace-event-header">
                    <span class="trace-role">${role === 'user' ? '用户' : role === 'assistant' ? '助手' : '工具结果'}</span>
                    ${event.model ? `<span class="trace-model">${escapeHtml(event.model)}</span>` : ''}
                    ${event.input_tokens ? `<span class="trace-tokens">输入: ${formatNumber(event.input_tokens)}</span>` : ''}
                    ${event.output_tokens ? `<span class="trace-tokens">输出: ${formatNumber(event.output_tokens)}</span>` : ''}
                </div>
                ${event.content ? renderExpandableContent(event.content, 'trace-content') : ''}
                ${toolCallsHtml}
                ${toolResultsHtml}
                ${event.error ? `<div class="trace-error">❌ ${escapeHtml(event.error)}</div>` : ''}
            `;
            break;

        case 'tool':
            icon = '🔧';
            color = 'tool-msg';
            content = `
                <div class="trace-event-header">
                    <span class="trace-tool-name">${escapeHtml(event.tool_name || 'unknown')}</span>
                    <span class="trace-status">${event.status || ''}</span>
                </div>
                ${event.tool_input ? `<div class="trace-tool-input"><strong>输入:</strong> ${escapeHtml(event.tool_input)}</div>` : ''}
                ${event.tool_result ? `<div class="trace-tool-result"><strong>结果:</strong> ${escapeHtml(event.tool_result)}</div>` : ''}
            `;
            break;

        case 'model_change':
            icon = '🔄';
            color = 'system-msg';
            content = `
                <div class="trace-event-header">
                    <span class="trace-model">${escapeHtml(event.model || '-')}</span>
                    <span class="trace-provider">${escapeHtml(event.provider || '-')}</span>
                </div>
            `;
            break;

        case 'lifecycle':
            icon = event.phase === 'start' ? '▶️' : event.phase === 'end' ? '⏹️' : '⚠️';
            color = 'system-msg';
            content = `
                <div class="trace-event-header">
                    <span class="trace-phase">${escapeHtml(event.phase || '-')}</span>
                    ${event.reason ? `<span class="trace-reason">${escapeHtml(event.reason)}</span>` : ''}
                </div>
            `;
            break;

        case 'session':
            icon = '📋';
            color = 'system-msg';
            content = `<div class="trace-event-header">Session v${event.version || '?'}</div>`;
            break;

        case 'custom':
            icon = '📌';
            color = 'system-msg';
            content = `
                <div class="trace-event-header">
                    <span class="trace-custom-type">${escapeHtml(event.custom_type || '-')}</span>
                </div>
                ${event.data ? `<div class="trace-data">${escapeHtml(JSON.stringify(event.data, null, 2).slice(0, 300))}</div>` : ''}
            `;
            break;

        default:
            icon = '❓';
            color = 'system-msg';
            content = `<div class="trace-event-header">${escapeHtml(type)}</div>`;
    }

    return `
        <div class="trace-event ${color}" data-index="${index}">
            <div class="trace-icon">${icon}</div>
            <div class="trace-body">
                <div class="trace-meta">
                    <span class="trace-index">#${index + 1}</span>
                    <span class="trace-type">${type}</span>
                    ${event.timestamp ? `<span class="trace-time">${event.timestamp}</span>` : ''}
                </div>
                ${content}
            </div>
        </div>
    `;
}

// ── Tree view helpers ─────────────────────────────────────────

// Build a tree from flat events using parent_id
function buildTraceTree(events) {
    const nodeMap = {};
    const roots = [];

    // Create node objects
    events.forEach((e, i) => {
        const nodeId = e.id || `_evt_${i}`;
        nodeMap[nodeId] = { ...e, children: [], _nodeId: nodeId, _idx: i };
    });

    // Link children to parents
    events.forEach((e, i) => {
        const nodeId = e.id || `_evt_${i}`;
        const node = nodeMap[nodeId];
        const parentId = e.parent_id;
        if (parentId && nodeMap[parentId]) {
            nodeMap[parentId].children.push(node);
        } else {
            roots.push(node);
        }
    });

    return roots;
}

// Recursively render a trace tree
function renderTraceTree(nodes, depth = 0) {
    if (!nodes || nodes.length === 0) return '';
    return nodes.map(node => {
        const hasChildren = node.children && node.children.length > 0;
        const toggleIcon = hasChildren ? '▾' : '';
        const collapsibleClass = hasChildren ? ' collapsible' : '';
        const eventHtml = renderTraceEvent(node, node._idx);

        // If node has children, wrap them in a toggleable container
        const childrenHtml = hasChildren
            ? `<div class="trace-children" style="--depth: ${depth + 1}">${renderTraceTree(node.children, depth + 1)}</div>`
            : '';

        return `
            <div class="trace-node${collapsibleClass}" data-depth="${depth}">
                <div class="trace-toggle-bar">
                    ${hasChildren ? `<span class="trace-toggle-btn" onclick="toggleTraceNode(this)">${toggleIcon}</span>` : '<span class="trace-toggle-spacer"></span>'}
                </div>
                <div class="trace-node-body">
                    ${eventHtml}
                    ${childrenHtml}
                </div>
            </div>
        `;
    }).join('');
}

// Toggle a tree node's children visibility
function toggleTraceNode(btn) {
    const node = btn.closest('.trace-node');
    if (!node) return;
    node.classList.toggle('collapsed');
    btn.textContent = node.classList.contains('collapsed') ? '▸' : '▾';
}

// Render tokens tab
function renderTokensTab(data) {
    return `
        <div class="token-stats">
            <div class="token-stat">
                <div class="token-label">输入 Tokens</div>
                <div class="token-value">${formatNumber(data.total_input_tokens || 0)}</div>
            </div>
            <div class="token-stat">
                <div class="token-label">输出 Tokens</div>
                <div class="token-value">${formatNumber(data.total_output_tokens || 0)}</div>
            </div>
            <div class="token-stat">
                <div class="token-label">总计</div>
                <div class="token-value">${formatNumber((data.total_input_tokens || 0) + (data.total_output_tokens || 0))}</div>
            </div>
        </div>
        ${data.token_summary && Object.keys(data.token_summary.by_model || {}).length > 0 ? `
        <table class="token-table">
            <thead>
                <tr>
                    <th>模型</th>
                    <th>输入</th>
                    <th>输出</th>
                    <th>总计</th>
                </tr>
            </thead>
            <tbody>
                ${Object.entries(data.token_summary.by_model).map(([model, tokens]) => `
                <tr>
                    <td>${escapeHtml(model)}</td>
                    <td>${formatNumber(tokens.input)}</td>
                    <td>${formatNumber(tokens.output)}</td>
                    <td>${formatNumber(tokens.input + tokens.output)}</td>
                </tr>
                `).join('')}
            </tbody>
        </table>
        ` : '<div class="no-data">暂无 token 使用数据</div>'}

        ${data.token_usage && data.token_usage.length > 0 ? `
        <div class="detail-section" style="margin-top: 20px;">
            <h4>Token 使用记录 (${data.token_usage.length})</h4>
            <div class="token-usage-list">
                ${data.token_usage.slice(0, 20).map((u, i) => `
                <div class="token-usage-item">
                    <span class="usage-model">${escapeHtml(u.model || '-')}</span>
                    <span class="usage-tokens">输入: ${formatNumber(u.input_tokens || 0)} / 输出: ${formatNumber(u.output_tokens || 0)}</span>
                </div>
                `).join('')}
            </div>
        </div>
        ` : ''}
    `;
}

// Close modal
function closeModal() {
    document.getElementById('session-modal').style.display = 'none';
}

// WebSocket connection
let lastSessionUpdate = 0;  // 用于节流

function connectWebSocket() {
    // 清理旧连接
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
    }
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }

    const wsUrl = `ws://${location.host}/api/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        const statusEl = document.getElementById('connection-status');
        if (statusEl) {
            statusEl.textContent = '已连接';
            statusEl.className = 'connection-status connected';
        }

        // Subscribe to updates
        ws.send(JSON.stringify({
            type: 'subscribe',
            channels: ['sessions', 'metrics', 'alerts']
        }));
    };

    ws.onclose = () => {
        const statusEl = document.getElementById('connection-status');
        if (statusEl) {
            statusEl.textContent = '已断开';
            statusEl.className = 'connection-status error';
        }

        // Reconnect after 5 seconds
        wsReconnectTimer = setTimeout(connectWebSocket, 5000);
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);

        switch (message.type) {
            case 'initial':
                updateDashboard(message.data);
                break;
            case 'session_update':
                // Throttle session refresh to at most once per 10 seconds
                const now = Date.now();
                if (now - lastSessionUpdate > 10000) {
                    lastSessionUpdate = now;
                    fetchSessions();
                }
                break;
            case 'gateway_status':
                updateGatewayStatus(message.data);
                break;
            case 'heartbeat':
                // Just ignore
                break;
            default:
                console.log('Unknown message type:', message.type);
        }
    };
}

// Update gateway status in real-time
function updateGatewayStatus(data) {
    const indicator = document.getElementById('gateway-indicator');
    const statusText = document.getElementById('gateway-status-text');
    const gatewayContainer = indicator?.closest('.gateway-status');

    if (data.healthy) {
        indicator.className = 'status-dot';
        if (gatewayContainer) gatewayContainer.classList.remove('unhealthy');
        statusText.textContent = 'Gateway 正常';
    } else {
        indicator.className = 'status-dot unhealthy';
        if (gatewayContainer) gatewayContainer.classList.add('unhealthy');
        statusText.textContent = data.status || '离线';
    }
}

// Helpers
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

function formatTime(isoString) {
    if (!isoString) return '-';
    try {
        const date = new Date(isoString);
        const now = new Date();
        const diff = (now - date) / 1000;

        if (diff < 60) return '刚刚';
        if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
        if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
        return date.toLocaleDateString();
    } catch {
        return isoString;
    }
}

// Fetch token daily data
async function fetchTokenDailyData(days) {
    try {
        const data = await fetchAPI(`/api/tokens/daily?days=${days}`);
        updateTokenDailyChart(data);
    } catch (error) {
        console.error('Failed to fetch token daily data:', error);
    }
}

// Update token daily chart
function updateTokenDailyChart(data) {
    if (!tokenDailyChart) return;

    if (!data || data.length === 0) {
        tokenDailyChart.data.labels = ['无数据'];
        tokenDailyChart.data.datasets[0].data = [0];
        tokenDailyChart.data.datasets[1].data = [0];
        tokenDailyChart.update();
        return;
    }

    // Check if this is hourly data (has 'hour' field) or daily data (has 'date' field)
    const isHourly = data[0] && data[0].hour !== undefined;
    
    let labels = [];
    let inputData = [];
    let outputData = [];
    let totalInput = 0;
    let totalOutput = 0;
    let totalCalls = 0;

    if (isHourly) {
        // Hourly data for 24h view
        const hourMap = new Map();
        
        data.forEach(item => {
            const hour = item.hour;
            if (!hourMap.has(hour)) {
                hourMap.set(hour, { input: 0, output: 0, calls: 0 });
            }
            const agg = hourMap.get(hour);
            agg.input += item.input_tokens || 0;
            agg.output += item.output_tokens || 0;
            agg.calls += item.calls || 0;
            totalInput += item.input_tokens || 0;
            totalOutput += item.output_tokens || 0;
            totalCalls += item.calls || 0;
        });

        // Generate continuous 24-hour range
        const now = new Date();
        for (let i = 23; i >= 0; i--) {
            const hourDate = new Date(now.getTime() - i * 60 * 60 * 1000);
            const hourKey = hourDate.toISOString().slice(0, 13) + ':00';
            const label = hourDate.getHours().toString().padStart(2, '0') + ':00';
            labels.push(label);
            
            const agg = hourMap.get(hourKey);
            if (agg) {
                inputData.push(agg.input / 1000);
                outputData.push(agg.output / 1000);
            } else {
                inputData.push(0);
                outputData.push(0);
            }
        }
    } else {
        // Daily data
        const dateMap = new Map();
        
        data.forEach(item => {
            const date = item.date;
            if (!dateMap.has(date)) {
                dateMap.set(date, { input: 0, output: 0, calls: 0 });
            }
            const agg = dateMap.get(date);
            agg.input += item.input_tokens || 0;
            agg.output += item.output_tokens || 0;
            agg.calls += item.calls || 0;
            totalInput += item.input_tokens || 0;
            totalOutput += item.output_tokens || 0;
            totalCalls += item.calls || 0;
        });

        // Generate continuous date range
        const sortedDates = Array.from(dateMap.keys()).sort();
        const startDate = new Date(sortedDates[0]);
        const endDate = new Date(sortedDates[sortedDates.length - 1]);

        const continuousDates = [];
        const currentDate = new Date(startDate);
        while (currentDate <= endDate) {
            continuousDates.push(currentDate.toISOString().split('T')[0]);
            currentDate.setDate(currentDate.getDate() + 1);
        }

        labels = continuousDates;
        continuousDates.forEach(date => {
            const agg = dateMap.get(date);
            if (agg) {
                inputData.push(agg.input / 1000000);
                outputData.push(agg.output / 1000000);
            } else {
                inputData.push(0);
                outputData.push(0);
            }
        });
    }

    // Update chart
    tokenDailyChart.data.labels = labels;
    tokenDailyChart.data.datasets[0].data = inputData;
    tokenDailyChart.data.datasets[1].data = outputData;
    tokenDailyChart.update();

    // Update summary
    const summaryDiv = document.getElementById('token-summary');
    if (summaryDiv) {
        summaryDiv.style.display = 'flex';
        document.getElementById('total-input').textContent = formatNumber(totalInput);
        document.getElementById('total-output').textContent = formatNumber(totalOutput);
        document.getElementById('total-calls').textContent = formatNumber(totalCalls);
    }
}

// TPM data version guard against stale async responses
let tpmDataVersion = 0;

// Fetch TPM data with filters
async function fetchTPMData() {
    const hours = document.getElementById('tpm-hours-filter').value;
    const agentId = document.getElementById('tpm-agent-filter').value;

    try {
        let url = `/api/tpm?hours=${hours}`;
        if (agentId) {
            url += `&agent_id=${encodeURIComponent(agentId)}`;
        }
        const tpm = await fetchAPI(url);
        // Stale response guard
        const thisVersion = ++tpmDataVersion;
        if (thisVersion !== tpmDataVersion) return;
        window.tpmData = tpm;
        updateTPMMetricDesc();
        updateTPMDisplay();
    } catch (error) {
        console.error('Fetch TPM error:', error);
    }
}

// Update TPM metric description
function updateTPMMetricDesc() {
    // 不再需要显示描述
}

// Update TPM display based on selected metric
function updateTPMDisplay() {
    const tpm = window.tpmData;
    if (!tpm) return;
    
    const metric = document.getElementById('tpm-metric-filter').value;
    const stats = tpm[metric] || {};
    
    document.getElementById('peak-tpm').textContent = formatNumber(stats.peak_tpm || 0);
    document.getElementById('avg-tpm').textContent = formatNumber(stats.avg_tpm || 0);
    document.getElementById('current-tpm').textContent = formatNumber(stats.current_tpm || 0);
    document.getElementById('active-minutes').textContent = formatNumber(tpm.active_minutes || 0);

    // 更新峰值时间显示
    const peakTimeEl = document.getElementById('peak-tpm-time');
    if (stats.peak_time) {
        peakTimeEl.textContent = stats.peak_time;
    } else {
        peakTimeEl.textContent = '-';
    }

    // 更新 Input/Output TPM 独立统计
    const inputStats = tpm.input || {};
    const outputStats = tpm.output || {};
    document.getElementById('peak-input-tpm').textContent = formatNumber(inputStats.peak_tpm || 0);
    document.getElementById('peak-output-tpm').textContent = formatNumber(outputStats.peak_tpm || 0);

    // 更新 TPM 柱状图（CSS bars）
    const chartContainer = document.getElementById('tpm-chart-bars');
    const xAxisContainer = document.getElementById('tpm-chart-xaxis');
    
    if (chartContainer) {
        if (tpm.tpm_timeseries && tpm.tpm_timeseries.length > 0) {
            // 根据筛选选择数据源
            let dataKey;
            if (metric === 'rate_limit') {
                dataKey = 'rate_limit_tpm';
            } else if (metric === 'actual') {
                dataKey = 'actual_tpm';
            } else if (metric === 'input') {
                dataKey = 'input_tpm';
            } else if (metric === 'output') {
                dataKey = 'output_tpm';
            } else {
                dataKey = 'rate_limit_tpm';
            }
            
            const data = tpm.tpm_timeseries.map(d => d[dataKey]);
            const times = tpm.tpm_timeseries.map(d => d.minute);
            const maxTpm = Math.max(...data, 1);
            
            // 生成柱状图 bars - 有值的才渲染
            chartContainer.innerHTML = data.map((value, i) => {
                if (value === 0) return '<div class="chart-bar chart-bar-zero"></div>';
                const heightPercent = (value / maxTpm) * 100;
                return `<div class="chart-bar" style="height: ${heightPercent}%;" title="${times[i]}\n${formatNumber(value)} TPM"></div>`;
            }).join('');
            
            // 生成 X 轴标签（只显示部分，避免太密集）
            if (xAxisContainer) {
                const totalPoints = times.length;
                const labelInterval = Math.max(1, Math.floor(totalPoints / 6)); // 最多显示6个标签
                xAxisContainer.innerHTML = times.map((time, i) => {
                    if (i % labelInterval === 0 || i === totalPoints - 1) {
                        // 提取时间部分 (HH:MM)
                        const timePart = time.split(' ')[1] || time;
                        return `<div class="xaxis-label">${timePart}</div>`;
                    }
                    return '<div class="xaxis-label"></div>';
                }).join('');
            }
        } else {
            // 无数据时显示提示
            chartContainer.innerHTML = '<div class="no-data-hint">选定时间范围内无 TPM 数据</div>';
            if (xAxisContainer) xAxisContainer.innerHTML = '';
        }
    }

    // Update TPM trend line chart (single line matching current metric filter)
    if (tpmTrendChart && tpm.tpm_timeseries && tpm.tpm_timeseries.length > 0) {
        const times = tpm.tpm_timeseries.map(d => {
            const t = d.minute || '';
            return t.split(' ')[1] || t;
        });
        let trendKey;
        const metricVal = document.getElementById('tpm-metric-filter')?.value || 'rate_limit';
        if (metricVal === 'rate_limit') trendKey = 'rate_limit_tpm';
        else if (metricVal === 'actual') trendKey = 'actual_tpm';
        else if (metricVal === 'input') trendKey = 'input_tpm';
        else if (metricVal === 'output') trendKey = 'output_tpm';
        else trendKey = 'rate_limit_tpm';

        const lineData = tpm.tpm_timeseries.map(d => d[trendKey] || 0);

        tpmTrendChart.data.labels = times;
        tpmTrendChart.data.datasets[0].data = lineData;
        const metricText = document.getElementById('tpm-metric-filter')?.selectedOptions?.[0]?.text || 'TPM';
        tpmTrendChart.data.datasets[0].label = metricText;
        const legendLabel = document.getElementById('trend-metric-label');
        if (legendLabel) legendLabel.textContent = metricText;
        tpmTrendChart.update('none');
    } else if (tpmTrendChart) {
        tpmTrendChart.data.labels = [];
        tpmTrendChart.data.datasets[0].data = [];
        tpmTrendChart.update('none');
    }
}