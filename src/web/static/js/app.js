// OpenClaw Monitor Web Application

// State
let ws = null;
let dashboardData = {};
let modelChart = null;
let tokenChart = null;
let tokenDailyChart = null;
let tpmChart = null;

// Trace infinite scroll state
let traceState = {
    sessionKey: null,
    events: [],
    offset: 0,
    limit: 20,
    hasMore: true,
    isLoading: false
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    // 设置默认日期为今天
    setTodayDate('session-date-start');
    setTodayDate('session-date-end');
    setTodayDate('error-date-start');
    setTodayDate('error-date-end');
    fetchData();
    connectWebSocket();
    setupEventListeners();
    // 加载 token daily 数据
    fetchTokenDailyData(30);
});

// Setup event listeners
function setupEventListeners() {
    document.getElementById('status-filter').addEventListener('change', fetchSessions);
    document.getElementById('search-input').addEventListener('input', debounce(fetchSessions, 300));
    document.getElementById('session-agent-filter').addEventListener('change', fetchSessions);
    document.getElementById('error-agent-filter').addEventListener('change', fetchErrors);
    document.getElementById('token-days-filter').addEventListener('change', (e) => {
        fetchTokenDailyData(parseInt(e.target.value));
    });

    // TPM 筛选器
    document.getElementById('tpm-hours-filter').addEventListener('change', fetchTPMData);
    document.getElementById('tpm-agent-filter').addEventListener('change', fetchTPMData);

    // 会话列表日期筛选
    document.getElementById('session-date-start').addEventListener('change', fetchSessions);
    document.getElementById('session-date-end').addEventListener('change', fetchSessions);

    // 模型错误日期筛选
    document.getElementById('error-date-start').addEventListener('change', fetchErrors);
    document.getElementById('error-date-end').addEventListener('change', fetchErrors);
}

// 设置今天的日期作为默认值
function setTodayDate(elementId) {
    const today = new Date().toISOString().split('T')[0];
    document.getElementById(elementId).value = today;
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
                backgroundColor: ['#334155'],
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        color: '#e2e8f0',
                        font: { size: 11 }
                    }
                }
            }
        }
    });

    // Token usage chart (Line)
    const tokenCtx = document.getElementById('token-chart').getContext('2d');
    tokenChart = new Chart(tokenCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: '输入 Tokens',
                    data: [],
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    tension: 0.4,
                },
                {
                    label: '输出 Tokens',
                    data: [],
                    borderColor: '#22c55e',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    fill: true,
                    tension: 0.4,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    ticks: { color: '#94a3b8' },
                    grid: { color: '#334155' }
                },
                y: {
                    ticks: { color: '#94a3b8' },
                    grid: { color: '#334155' }
                }
            },
            plugins: {
                legend: {
                    labels: { color: '#e2e8f0' }
                }
            }
        }
    });

    // Token daily chart (Bar)
    const tokenDailyCanvas = document.getElementById('token-daily-chart');
    if (tokenDailyCanvas) {
        const tokenDailyCtx = tokenDailyCanvas.getContext('2d');
        tokenDailyChart = new Chart(tokenDailyCtx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [
                    {
                        label: '输入 Tokens (M)',
                        data: [],
                        backgroundColor: 'rgba(59, 130, 246, 0.7)',
                        borderColor: '#3b82f6',
                        borderWidth: 1,
                    },
                    {
                        label: '输出 Tokens (M)',
                        data: [],
                        backgroundColor: 'rgba(34, 197, 94, 0.7)',
                        borderColor: '#22c55e',
                        borderWidth: 1,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        ticks: { color: '#94a3b8', maxRotation: 45 },
                        grid: { color: '#334155' }
                    },
                    y: {
                        ticks: { color: '#94a3b8' },
                        grid: { color: '#334155' },
                        beginAtZero: true
                    }
                },
                plugins: {
                    legend: {
                        labels: { color: '#e2e8f0' }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return context.dataset.label + ': ' + context.raw.toFixed(2) + 'M';
                            }
                        }
                    }
                }
            }
        });
    } else {
        console.error('token-daily-chart canvas not found');
    }

    // TPM chart (Line)
    const tpmCanvas = document.getElementById('tpm-chart');
    if (tpmCanvas) {
        const tpmCtx = tpmCanvas.getContext('2d');
        tpmChart = new Chart(tpmCtx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'TPM',
                    data: [],
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 3,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        ticks: { color: '#94a3b8', maxRotation: 45, autoSkip: true, maxTicksLimit: 20 },
                        grid: { color: '#334155' }
                    },
                    y: {
                        ticks: { color: '#94a3b8' },
                        grid: { color: '#334155' },
                        beginAtZero: true
                    }
                },
                plugins: {
                    legend: {
                        labels: { color: '#e2e8f0' }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return 'TPM: ' + formatNumber(context.raw);
                            }
                        }
                    }
                }
            }
        });
    }
}

// Fetch all data
async function fetchData() {
    try {
        const [dashboard, sessions, models, tokens, errors, tpm] = await Promise.all([
            fetchAPI('/api/dashboard'),
            fetchAPI('/api/sessions?limit=50'),
            fetchAPI('/api/models/stats'),
            fetchAPI('/api/tokens/histogram?hours=24'),
            fetchAPI('/api/errors?limit=50&group_by=agent'),
            fetchAPI('/api/tpm?hours=24')  // 获取 TPM 数据
        ]);

        dashboardData = dashboard;
        updateDashboard(dashboard);
        updateSessionsTable(sessions);
        populateSessionFilters(sessions);
        updateModelsTable(models);
        updateTokenChart(tokens);
        updateErrorsTable(errors);
        populateErrorFilters(errors);
        updateTPMStats(tpm);  // 更新 TPM 统计
    } catch (error) {
        console.error('Fetch error:', error);
    }
}

// Populate session filter dropdowns
function populateSessionFilters(sessions) {
    const agentFilter = document.getElementById('session-agent-filter');

    // Get unique agents
    const agents = new Set();

    sessions.forEach(s => {
        if (s.agent_id) {
            agents.add(s.agent_id);
        }
    });

    // Populate agent filter
    const sortedAgents = Array.from(agents).sort();
    agentFilter.innerHTML = '<option value="">全部 Agent</option>' +
        sortedAgents.map(a => `<option value="${a}">${a}</option>`).join('');

    // 日期筛选默认不设置，让用户手动选择
    // setTodayDate('session-date-start');
    // setTodayDate('session-date-end');
}

// Populate error filter dropdowns
function populateErrorFilters(errors) {
    const agentFilter = document.getElementById('error-agent-filter');

    // Get unique agents from flat errors
    const flatErrors = errors.flat || errors;
    const agents = new Set();

    flatErrors.forEach(e => {
        if (e.agent_id) agents.add(e.agent_id);
    });

    // Populate agent filter
    const sortedAgents = Array.from(agents).sort();
    agentFilter.innerHTML = '<option value="">全部 Agent</option>' +
        sortedAgents.map(a => `<option value="${a}">${a}</option>`).join('');

    // 日期筛选默认不设置，让用户手动选择
    // setTodayDate('error-date-start');
    // setTodayDate('error-date-end');
}

// Fetch errors with filters
async function fetchErrors() {
    const dateStart = document.getElementById('error-date-start').value;
    const dateEnd = document.getElementById('error-date-end').value;
    const agentFilter = document.getElementById('error-agent-filter').value;

    console.log('fetchErrors called - dateStart:', dateStart, 'dateEnd:', dateEnd, 'agentFilter:', agentFilter);

    let url = '/api/errors?limit=50&group_by=agent';

    try {
        let errors = await fetchAPI(url);
        console.log('Fetched errors:', errors.total, 'total');

        // Apply filters
        if (dateStart || dateEnd || agentFilter) {
            const filtered = [];
            errors.grouped.forEach(group => {
                const filteredErrors = group.errors.filter(e => {
                    const errorDate = e.date;
                    if (dateStart && errorDate < dateStart) return false;
                    if (dateEnd && errorDate > dateEnd) return false;
                    if (agentFilter && group.agent_id !== agentFilter) return false;
                    return true;
                });
                if (filteredErrors.length > 0) {
                    filtered.push({
                        ...group,
                        errors: filteredErrors,
                        error_count: filteredErrors.length
                    });
                }
            });
            errors.grouped = filtered;
            errors.total = filtered.reduce((sum, g) => sum + g.error_count, 0);
            console.log('After filter:', errors.total, 'total');
        }

        updateErrorsTable(errors);
    } catch (error) {
        console.error('Fetch errors error:', error);
    }
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

    if (gateway.healthy) {
        indicator.className = 'status-indicator healthy';
        statusText.textContent = '运行正常';
    } else {
        indicator.className = 'status-indicator unhealthy';
        statusText.textContent = gateway.status || '离线';
    }

    responseTime.textContent = gateway.response_time_ms
        ? `${gateway.response_time_ms.toFixed(1)} ms`
        : '-';

    // Stats
    const sessions = data.sessions || {};
    const tokens = data.tokens || {};

    document.getElementById('total-sessions').textContent = sessions.total || 0;
    document.getElementById('active-sessions').textContent = sessions.active || 0;
    document.getElementById('total-tokens').textContent = formatNumber(tokens.total || 0);
    document.getElementById('model-count').textContent =
        Object.keys(data.models?.distribution || {}).length;

    // Update model chart - 带颜色
    const modelDist = data.models?.distribution || {};
    const colors = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6',
                    '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#6366f1'];
    modelChart.data.labels = Object.keys(modelDist);
    modelChart.data.datasets[0].data = Object.values(modelDist);
    modelChart.data.datasets[0].backgroundColor = colors.slice(0, Object.keys(modelDist).length);
    modelChart.update();

    // Update last update time
    document.getElementById('last-update').textContent =
        `更新于 ${new Date().toLocaleTimeString()}`;
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
            <td>${escapeHtml(s.agent_id || '-')}</td>
            <td><span class="status-cell ${s.status}">${s.status || '-'}</span></td>
            <td>${escapeHtml(s.channel || '-')}</td>
            <td>${escapeHtml(s.last_model || '-')}</td>
            <td>${s.message_count || 0}</td>
            <td>${formatTime(s.updated_at)}</td>
        </tr>
    `).join('');
}

// Update models table
function updateModelsTable(models) {
    const tbody = document.getElementById('models-tbody');

    if (!models || models.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading">暂无模型数据</td></tr>';
        return;
    }

    tbody.innerHTML = models.map(m => `
        <tr>
            <td>${escapeHtml(m.model || '-')}</td>
            <td>${escapeHtml(m.provider || '-')}</td>
            <td>${formatNumber(m.total_calls || 0)}</td>
            <td>${formatNumber(m.total_input_tokens || 0)}</td>
            <td>${formatNumber(m.total_output_tokens || 0)}</td>
            <td>${m.total_errors || 0}</td>
        </tr>
    `).join('');
}

// Update token chart
function updateTokenChart(data) {
    if (!data || data.length === 0) return;

    const labels = data.map(d => d.hour?.split(' ')[1] || d.hour);
    const inputData = data.map(d => d.input_tokens || 0);
    const outputData = data.map(d => d.output_tokens || 0);

    tokenChart.data.labels = labels;
    tokenChart.data.datasets[0].data = inputData;
    tokenChart.data.datasets[1].data = outputData;
    tokenChart.update();
}

// Update errors table with grouping
function updateErrorsTable(errors) {
    const section = document.getElementById('errors-section');
    const container = document.getElementById('errors-container');
    const countBadge = document.getElementById('error-count');

    // 始终显示错误模块
    section.style.display = 'block';

    if (!errors || (errors.grouped && errors.grouped.length === 0) || (!errors.grouped && errors.length === 0)) {
        countBadge.textContent = '0';
        container.innerHTML = '<div class="no-data">暂无模型错误记录</div>';
        return;
    }

    // Handle grouped format
    if (errors.grouped) {
        countBadge.textContent = errors.total || 0;

        container.innerHTML = errors.grouped.map(group => `
            <div class="error-group">
                <div class="error-group-header">
                    <span class="agent-name">🤖 ${escapeHtml(group.agent_id)}</span>
                    <span class="error-count-badge">${group.error_count} 个错误</span>
                </div>
                <table class="errors-table">
                    <thead>
                        <tr>
                            <th>日期</th>
                            <th>时间</th>
                            <th>模型</th>
                            <th>Provider</th>
                            <th>错误信息</th>
                            <th>会话</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${group.errors.slice(0, 5).map(e => `
                            <tr>
                                <td>${escapeHtml(e.date || '-')}</td>
                                <td>${escapeHtml(e.time || '-')}</td>
                                <td>${escapeHtml(e.model || '-')}</td>
                                <td>${escapeHtml(e.provider || '-')}</td>
                                <td class="error-message" title="${escapeHtml(e.error || '')}">${escapeHtml(e.error || '-')}</td>
                                <td><a href="#" class="session-link" onclick="showSessionDetail('${escapeHtml(e.session_key || '')}'); return false;">查看详情</a></td>
                            </tr>
                        `).join('')}
                        ${group.error_count > 5 ? `
                            <tr class="more-errors">
                                <td colspan="6" style="text-align: center; color: var(--text-muted);">
                                    还有 ${group.error_count - 5} 个错误...
                                    <a href="#" class="session-link" onclick="showAgentErrors('${escapeHtml(group.agent_id)}'); return false;">查看全部</a>
                                </td>
                            </tr>
                        ` : ''}
                    </tbody>
                </table>
            </div>
        `).join('');
    } else {
        // Fallback to flat format (old API)
        countBadge.textContent = errors.length;

        container.innerHTML = `
            <table class="errors-table">
                <thead>
                    <tr>
                        <th>日期</th>
                        <th>时间</th>
                        <th>模型</th>
                        <th>Provider</th>
                        <th>错误信息</th>
                        <th>会话</th>
                    </tr>
                </thead>
                <tbody>
                    ${errors.map(e => `
                        <tr>
                            <td>${escapeHtml(e.date || '-')}</td>
                            <td>${escapeHtml(e.time || '-')}</td>
                            <td>${escapeHtml(e.model || '-')}</td>
                            <td>${escapeHtml(e.provider || '-')}</td>
                            <td class="error-message" title="${escapeHtml(e.error || '')}">${escapeHtml(e.error || '-')}</td>
                            <td><a href="#" class="session-link" onclick="showSessionDetail('${escapeHtml(e.session_key || '')}'); return false;">查看详情</a></td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    }
}

// Show agent errors modal
function showAgentErrors(agentId) {
    fetch(`/api/errors?limit=50&group_by=flat`)
        .then(resp => resp.json())
        .then(data => {
            const errors = (data.flat || data).filter(e => e.agent_id === agentId);

            const modal = document.getElementById('session-modal');
            const content = document.getElementById('session-detail-content');

            content.innerHTML = `
                <div class="modal-header" style="margin-bottom: 15px;">
                    <h3>🤖 ${escapeHtml(agentId)} 的所有错误</h3>
                </div>
                <div style="margin-bottom: 15px;">
                    共 <strong>${errors.length}</strong> 个错误
                </div>
                <table class="errors-table">
                    <thead>
                        <tr>
                            <th>日期</th>
                            <th>时间</th>
                            <th>模型</th>
                            <th>Provider</th>
                            <th>错误信息</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${errors.map(e => `
                            <tr>
                                <td>${escapeHtml(e.date || '-')}</td>
                                <td>${escapeHtml(e.time || '-')}</td>
                                <td>${escapeHtml(e.model || '-')}</td>
                                <td>${escapeHtml(e.provider || '-')}</td>
                                <td class="error-message" title="${escapeHtml(e.error || '')}">${escapeHtml(e.error || '-')}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;

            modal.style.display = 'flex';
        });
}

// Show session detail modal
function showSessionDetail(sessionKey) {
    if (!sessionKey) return;

    // Reset trace state
    traceState = {
        sessionKey: sessionKey,
        events: [],
        offset: 0,
        limit: 20,
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
                    <button class="tab-btn" onclick="switchTab('trace', this)">Trace</button>
                    <button class="tab-btn" onclick="switchTab('tokens', this)">Token</button>
                </div>

                <div class="modal-body" id="session-modal-body">
                    <div id="tab-overview" class="tab-content active">
                        ${renderOverviewTab(data)}
                    </div>

                    <div id="tab-trace" class="tab-content">
                        <div class="trace-timeline" id="trace-timeline"></div>
                        <div id="trace-loading" class="trace-loading" style="display: none;">
                            <span class="loading-spinner"></span> 正在加载中...
                        </div>
                        <div id="trace-end" class="trace-end" style="display: none;">
                            没有更多数据了
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

            if (!trace.events || trace.events.length === 0) {
                traceState.hasMore = false;
                showTraceEnd(true);
                return;
            }

            // Append new events
            const timeline = document.getElementById('trace-timeline');
            if (timeline) {
                const newEventsHtml = trace.events.map((event, index) =>
                    renderTraceEvent(event, traceState.offset + index)
                ).join('');
                timeline.insertAdjacentHTML('beforeend', newEventsHtml);
            }

            // Update state
            traceState.events = traceState.events.concat(trace.events);
            traceState.offset += trace.events.length;

            // Check if we've loaded all data
            if (trace.events.length < traceState.limit) {
                traceState.hasMore = false;
                showTraceEnd(true);
            }

            // Update trace tab button count
            updateTraceTabCount();
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

// Update trace tab button count
function updateTraceTabCount() {
    const traceBtn = document.querySelector('.session-tabs-fixed .tab-btn:nth-child(2)');
    if (traceBtn) {
        traceBtn.textContent = `Trace (${traceState.offset})`;
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

    // Store full content in a data attribute (escaped for HTML attribute)
    const escapedFull = escapeHtml(content).replace(/"/g, '&quot;').replace(/'/g, '&#39;');

    return `
        <div class="${className} ${isLong ? 'collapsed' : ''}" data-full="${escapedFull}">
            ${escapeHtml(isLong ? displayContent : content)}
        </div>
        ${isLong ? `<button class="trace-expand-btn" onclick="toggleTraceContent(this)">展开全部</button>` : ''}
    `;
}

// Toggle trace content expand/collapse
function toggleTraceContent(btn) {
    const contentDiv = btn.previousElementSibling;
    const isCollapsed = contentDiv.classList.contains('collapsed');

    if (isCollapsed) {
        contentDiv.classList.remove('collapsed');
        // Decode from HTML entities back to text
        const textarea = document.createElement('textarea');
        textarea.innerHTML = contentDiv.dataset.full;
        contentDiv.textContent = textarea.value;
        btn.textContent = '收起';
    } else {
        contentDiv.classList.add('collapsed');
        const textarea = document.createElement('textarea');
        textarea.innerHTML = contentDiv.dataset.full;
        const fullText = textarea.value;
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
                <div class="detail-row"><span class="detail-label">状态:</span> <span class="status-cell ${data.status}">${data.status || '-'}</span></div>
                <div class="detail-row"><span class="detail-label">通道:</span> <span class="detail-value">${escapeHtml(data.channel || '-')}</span></div>
                <div class="detail-row"><span class="detail-label">消息数:</span> <span class="detail-value">${data.message_count || 0}</span></div>
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
    const wsUrl = `ws://${location.host}/api/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        document.getElementById('connection-status').textContent = '已连接';
        document.getElementById('connection-status').className = 'status-badge connected';

        // Subscribe to updates
        ws.send(JSON.stringify({
            type: 'subscribe',
            channels: ['sessions', 'metrics', 'alerts']
        }));
    };

    ws.onclose = () => {
        document.getElementById('connection-status').textContent = '已断开';
        document.getElementById('connection-status').className = 'status-badge error';

        // Reconnect after 5 seconds
        setTimeout(connectWebSocket, 5000);
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

    if (data.healthy) {
        indicator.className = 'status-indicator healthy';
        statusText.textContent = '运行正常';
    } else {
        indicator.className = 'status-indicator unhealthy';
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

    // Aggregate by date
    const dateMap = new Map();
    let totalInput = 0;
    let totalOutput = 0;
    let totalCalls = 0;

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

    // 生成连续日期范围
    const sortedDates = Array.from(dateMap.keys()).sort();
    const startDate = new Date(sortedDates[0]);
    const endDate = new Date(sortedDates[sortedDates.length - 1]);

    // 创建连续日期数组
    const continuousDates = [];
    const currentDate = new Date(startDate);
    while (currentDate <= endDate) {
        continuousDates.push(currentDate.toISOString().split('T')[0]);
        currentDate.setDate(currentDate.getDate() + 1);
    }

    // 为每个日期填充数据
    const inputData = [];
    const outputData = [];
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

    // Update chart
    tokenDailyChart.data.labels = continuousDates;
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

// Update TPM statistics
function updateTPMStats(tpm) {
    if (!tpm) return;

    document.getElementById('peak-tpm').textContent = formatNumber(tpm.peak_tpm || 0);
    document.getElementById('avg-tpm').textContent = formatNumber(tpm.avg_tpm || 0);
    document.getElementById('current-tpm').textContent = formatNumber(tpm.current_tpm || 0);
    document.getElementById('active-minutes').textContent = formatNumber(tpm.active_minutes || 0);

    // 更新峰值时间显示
    const peakTimeEl = document.getElementById('peak-tpm-time');
    if (tpm.peak_time) {
        peakTimeEl.textContent = tpm.peak_time;
    } else {
        peakTimeEl.textContent = '-';
    }

    // 更新 TPM 图表
    if (tpmChart && tpm.tpm_timeseries && tpm.tpm_timeseries.length > 0) {
        const labels = tpm.tpm_timeseries.map(d => d.minute);
        const data = tpm.tpm_timeseries.map(d => d.tpm);

        tpmChart.data.labels = labels;
        tpmChart.data.datasets[0].data = data;
        tpmChart.update();
    }
}

// Fetch TPM data with filters
async function fetchTPMData() {
    const hours = document.getElementById('tpm-hours-filter').value;
    const agentFilter = document.getElementById('tpm-agent-filter').value;

    try {
        let url = `/api/tpm?hours=${hours}`;
        if (agentFilter) {
            url += `&agent_id=${encodeURIComponent(agentFilter)}`;
        }

        const tpm = await fetchAPI(url);
        updateTPMStats(tpm);
    } catch (error) {
        console.error('Fetch TPM error:', error);
    }
}
