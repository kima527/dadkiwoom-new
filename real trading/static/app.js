// Antigravity Premium Dashboard JS Controller

document.addEventListener("DOMContentLoaded", () => {
    // UI Elements
    const modeSelect = document.getElementById("mode-select");
    const daysSelect = document.getElementById("days-select");
    const btnRefresh = document.getElementById("btn-refresh");
    const refreshIcon = document.getElementById("refresh-icon");
    const btnText = document.getElementById("btn-text");
    const loadingOverlay = document.getElementById("loading-overlay");
    const tableSearch = document.getElementById("table-search");
    
    // Summary values
    const valTotalReturn = document.getElementById("val-total-return");
    const valWinRate = document.getElementById("val-win-rate");
    const valWinRatio = document.getElementById("val-win-ratio");
    const valTradeCount = document.getElementById("val-trade-count");
    const valCompletedCount = document.getElementById("val-completed-count");
    const valAvgReturn = document.getElementById("val-avg-return");
    
    // Tables & messaging
    const tradesTableBody = document.getElementById("trades-table-body");
    const noTradesMessage = document.getElementById("no-trades-message");
    
    // Global chart instances
    let cumulativeChart = null;
    let performanceChart = null;
    let globalTradesData = []; // Cache for local searching

    // Fetch and render data
    async function loadDashboardData() {
        // Show loading overlay
        loadingOverlay.classList.remove("hidden");
        refreshIcon.classList.add("fa-spin");
        btnRefresh.disabled = true;
        btnText.textContent = "로딩 중...";

        const mode = modeSelect.value;
        const days = daysSelect.value;

        try {
            const response = await fetch(`/api/backtest?mode=${mode}&days=${days}`);
            if (!response.ok) {
                throw new Error("서버에서 에러를 반환했습니다.");
            }
            const data = await response.json();
            
            if (data.success) {
                renderSummary(data.summary);
                renderCharts(data.daily_cumulative, data.stock_performance);
                renderTable(data.trades);
                globalTradesData = data.trades; // Cache for search
            } else {
                alert(`에러 발생: ${data.error}`);
            }
        } catch (error) {
            console.error("데이터 로딩 실패:", error);
            alert("백테스팅 서버 연결에 실패했습니다. 키움 로그인 상태를 점검해 주세요.");
        } finally {
            // Hide loading overlay
            loadingOverlay.classList.add("hidden");
            refreshIcon.classList.remove("fa-spin");
            btnRefresh.disabled = false;
            btnText.textContent = "데이터 동기화";
        }
    }

    // Render Stats Cards
    function renderSummary(summary) {
        // Total Return
        const totalRet = summary.total_return;
        valTotalReturn.textContent = `${totalRet >= 0 ? '+' : ''}${totalRet.toFixed(2)}%`;
        if (totalRet >= 0) {
            valTotalReturn.className = "stat-value neon-green-text";
        } else {
            valTotalReturn.className = "stat-value neon-red-text";
        }

        // Win Rate
        const winRate = summary.win_rate;
        valWinRate.textContent = `${winRate.toFixed(1)}%`;
        
        // Calculate Win/Loss numbers
        const totalTrades = summary.trades_count;
        const wins = Math.round((winRate / 100) * totalTrades);
        const losses = totalTrades - wins;
        valWinRatio.textContent = `${wins}승 / ${losses}패`;

        // Total Trades Count
        valTradeCount.textContent = `${totalTrades}회`;
        
        // Average Return
        const avgRet = summary.avg_return;
        valAvgReturn.textContent = `${avgRet >= 0 ? '+' : ''}${avgRet.toFixed(2)}%`;
        if (avgRet >= 0) {
            valAvgReturn.style.color = "var(--neon-green)";
        } else {
            valAvgReturn.style.color = "var(--neon-red)";
        }
    }

    // Render Chart.js Visualizations
    function renderCharts(dailyCumulative, stockPerformance) {
        // ────────────────────────────────────────────────────────────
        // Chart 1: Cumulative Return Line Chart
        // ────────────────────────────────────────────────────────────
        if (cumulativeChart) {
            cumulativeChart.destroy();
        }

        const labels = dailyCumulative.map(item => item.date);
        const returnData = dailyCumulative.map(item => item.cumulative_return);

        const ctx1 = document.getElementById("cumulativeReturnChart").getContext("2d");
        
        // Create premium gradient fill
        const gradient = ctx1.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, 'rgba(0, 176, 255, 0.25)');
        gradient.addColorStop(1, 'rgba(0, 176, 255, 0.0)');

        cumulativeChart = new Chart(ctx1, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: '누적 수익률 (%)',
                    data: returnData,
                    borderColor: '#00b0ff',
                    borderWidth: 3,
                    backgroundColor: gradient,
                    fill: true,
                    tension: 0.35,
                    pointBackgroundColor: '#00b0ff',
                    pointBorderColor: '#fff',
                    pointHoverRadius: 6,
                    pointHoverBackgroundColor: '#00e676',
                    pointHoverBorderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: '#12131a',
                        titleColor: '#fff',
                        bodyColor: '#8e94a5',
                        borderColor: 'rgba(255, 255, 255, 0.08)',
                        borderWidth: 1,
                        callbacks: {
                            label: function(context) {
                                return ` 누적 수익률: ${context.parsed.y.toFixed(2)}%`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.02)' },
                        ticks: { color: '#8e94a5', font: { family: 'Outfit' } }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.04)' },
                        ticks: { 
                            color: '#8e94a5',
                            font: { family: 'Outfit' },
                            callback: function(value) {
                                return value.toFixed(1) + '%';
                            }
                        }
                    }
                }
            }
        });

        // ────────────────────────────────────────────────────────────
        // Chart 2: Stock Performance Bar Chart
        // ────────────────────────────────────────────────────────────
        if (performanceChart) {
            performanceChart.destroy();
        }

        const stockLabels = stockPerformance.map(item => `${item.name}`);
        const stockData = stockPerformance.map(item => item.total_return);
        
        // Dynamically color positive returns green and negative returns red
        const barColors = stockData.map(val => val >= 0 ? 'rgba(0, 230, 118, 0.85)' : 'rgba(255, 23, 68, 0.85)');
        const borderColors = stockData.map(val => val >= 0 ? '#00e676' : '#ff1744');

        const ctx2 = document.getElementById("stockPerformanceChart").getContext("2d");
        performanceChart = new Chart(ctx2, {
            type: 'bar',
            data: {
                labels: stockLabels,
                datasets: [{
                    label: '수익률 (%)',
                    data: stockData,
                    backgroundColor: barColors,
                    borderColor: borderColors,
                    borderWidth: 1.5,
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: '#12131a',
                        borderColor: 'rgba(255, 255, 255, 0.08)',
                        borderWidth: 1,
                        callbacks: {
                            label: function(context) {
                                return ` 누적 손익: ${context.parsed.y.toFixed(2)}%`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#8e94a5', font: { family: 'Outfit' } }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.04)' },
                        ticks: { 
                            color: '#8e94a5',
                            font: { family: 'Outfit' },
                            callback: function(value) {
                                return value.toFixed(1) + '%';
                            }
                        }
                    }
                }
            }
        });
    }

    // Render detailed trade logs to the table
    function renderTable(trades) {
        tradesTableBody.innerHTML = "";
        
        if (trades.length === 0) {
            noTradesMessage.classList.remove("hidden");
            return;
        }
        noTradesMessage.classList.add("hidden");

        trades.forEach(t => {
            const tr = document.createElement("tr");
            
            // Format cells
            const codeName = `<div class="trade-stock-name">${t.name}</div><div class="trade-stock-code">${t.code}</div>`;
            const retClass = t.return_pct >= 0 ? "profit-text" : "loss-text";
            const retSign = t.return_pct >= 0 ? "+" : "";
            const retText = `<span class="${retClass}">${retSign}${t.return_pct.toFixed(2)}%</span>`;
            
            // Status Pill
            let statusBadge = "";
            if (!t.is_completed) {
                statusBadge = '<span class="pill-badge pill-warning">보유중(평가)</span>';
            } else if (t.return_pct >= 0) {
                statusBadge = '<span class="pill-badge pill-success">익절완료</span>';
            } else {
                statusBadge = '<span class="pill-badge pill-danger">손절완료</span>';
            }

            tr.innerHTML = `
                <td>${codeName}</td>
                <td>${t.buy_time}</td>
                <td>${t.buy_price.toLocaleString()}원</td>
                <td>${t.sell_time}</td>
                <td>${t.sell_price.toLocaleString()}원</td>
                <td>${retText}</td>
                <td>${t.holding_bars}개 (약 ${(t.holding_bars * 15).toLocaleString()}분)</td>
                <td>${statusBadge}</td>
            `;
            
            tradesTableBody.appendChild(tr);
        });
    }

    // Local Search Filter in the Trades Table
    tableSearch.addEventListener("input", (e) => {
        const query = e.target.value.toLowerCase().strip();
        if (!query) {
            renderTable(globalTradesData);
            return;
        }

        const filtered = globalTradesData.filter(t => 
            t.name.toLowerCase().includes(query) || 
            t.code.includes(query) ||
            t.buy_time.includes(query)
        );
        renderTable(filtered);
    });

    // Strip helper
    String.prototype.strip = function() {
        return this.replace(/^\s+|\s+$/g, "");
    };

    // Filter Trigger Change Events
    modeSelect.addEventListener("change", loadDashboardData);
    daysSelect.addEventListener("change", loadDashboardData);
    btnRefresh.addEventListener("click", loadDashboardData);

    // Initial Load
    loadDashboardData();
});
