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
        showLoading("키움증권 REST API 동기화 및 백테스팅 분석 중...");
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
            hideLoading();
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

    // ────────────────────────────────────────────────────────────
    // Tab Navigation Logic
    // ────────────────────────────────────────────────────────────
    const navItems = document.querySelectorAll(".sidebar-nav .nav-item");
    const tabContents = document.querySelectorAll(".tab-content");

    navItems.forEach(item => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const targetTabId = item.getAttribute("data-tab");
            if (!targetTabId) return;

            // Update active menu class
            navItems.forEach(nav => nav.classList.remove("active"));
            item.classList.add("active");

            // Show target tab content, hide others
            tabContents.forEach(tab => {
                if (tab.id === targetTabId) {
                    tab.classList.remove("hidden");
                } else {
                    tab.classList.add("hidden");
                }
            });

            // Trigger tab specific loads
            if (targetTabId === "watchlist-tab") {
                loadWatchlist();
            } else if (targetTabId === "holdings-tab") {
                loadHoldings();
            } else if (targetTabId === "dashboard-tab") {
                loadDashboardData();
            }
        });
    });

    // ────────────────────────────────────────────────────────────
    // Watchlist Management Logic
    // ────────────────────────────────────────────────────────────
    const watchlistTableBody = document.getElementById("watchlist-table-body");
    const watchlistEmptyMessage = document.getElementById("watchlist-empty-message");
    const newStockCodeInput = document.getElementById("new-stock-code");
    const btnAddWatchlist = document.getElementById("btn-add-watchlist");
    const btnImportHts = document.getElementById("btn-import-hts");
    const loadingMessageText = document.getElementById("loading-message");

    async function loadWatchlist() {
        showLoading("관심종목 목록 불러오는 중...");
        try {
            const response = await fetch("/api/watchlist");
            const data = await response.json();
            if (data.success) {
                renderWatchlistTable(data.watchlist);
            } else {
                alert(`오류: ${data.error}`);
            }
        } catch (error) {
            console.error("관심종목 로드 에러:", error);
            alert("관심종목 목록을 불러오지 못했습니다.");
        } finally {
            hideLoading();
        }
    }

    function renderWatchlistTable(watchlist) {
        watchlistTableBody.innerHTML = "";
        if (!watchlist || watchlist.length === 0) {
            watchlistEmptyMessage.classList.remove("hidden");
            return;
        }
        watchlistEmptyMessage.classList.add("hidden");

        watchlist.forEach(stock => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><code>${stock.code}</code></td>
                <td><strong>${stock.name}</strong></td>
                <td style="text-align: right;">
                    <button class="btn-delete" data-code="${stock.code}" title="관심종목에서 삭제">
                        <i class="fa-solid fa-trash-can"></i>
                    </button>
                </td>
            `;
            // Bind delete event
            tr.querySelector(".btn-delete").addEventListener("click", () => {
                if (confirm(`'${stock.name}(${stock.code})' 종목을 관심종목에서 삭제하시겠습니까?`)) {
                    deleteWatchlist(stock.code);
                }
            });
            watchlistTableBody.appendChild(tr);
        });
    }

    async function addWatchlist(code) {
        if (!code || code.length !== 6 || isNaN(code)) {
            alert("유효한 6자리 숫자 종목코드를 입력해주세요.");
            return;
        }
        showLoading(`종목코드 ${code} 검증 및 추가 중...`);
        try {
            const response = await fetch("/api/watchlist/add", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ code: code })
            });
            const data = await response.json();
            if (data.success) {
                newStockCodeInput.value = ""; // Clear input if form
                renderWatchlistTable(data.watchlist);
                alert(data.message);
            } else {
                alert(`추가 실패: ${data.error}`);
            }
        } catch (error) {
            console.error("종목 추가 실패:", error);
            alert("종목을 추가하는 데 실패했습니다.");
        } finally {
            hideLoading();
        }
    }

    async function deleteWatchlist(code) {
        showLoading("관심종목 삭제 중...");
        try {
            const response = await fetch("/api/watchlist/delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ code: code })
            });
            const data = await response.json();
            if (data.success) {
                renderWatchlistTable(data.watchlist);
            } else {
                alert(`삭제 실패: ${data.error}`);
            }
        } catch (error) {
            console.error("종목 삭제 실패:", error);
            alert("종목을 삭제하는 데 실패했습니다.");
        } finally {
            hideLoading();
        }
    }

    // Bind Add button
    btnAddWatchlist.addEventListener("click", () => {
        const code = newStockCodeInput.value.trim();
        addWatchlist(code);
    });

    // Enter key support for input
    newStockCodeInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            const code = newStockCodeInput.value.trim();
            addWatchlist(code);
        }
    });

    async function importHtsMypick() {
        if (!confirm("영웅문 HTS 관심그룹 '나의픽'의 종목들을 대시보드 관심종목으로 불러오시겠습니까?")) {
            return;
        }
        showLoading("영웅문 관심그룹 '나의픽'에서 종목 리스트 가져오는 중...");
        try {
            const response = await fetch("/api/watchlist/import_hts", {
                method: "POST"
            });
            const data = await response.json();
            if (data.success) {
                renderWatchlistTable(data.watchlist);
                alert(data.message);
            } else {
                alert(`가져오기 실패: ${data.error}`);
            }
        } catch (error) {
            console.error("영웅문 관심종목 가져오기 에러:", error);
            alert("영웅문 관심종목을 불러오는 중 에러가 발생했습니다.");
        } finally {
            hideLoading();
        }
    }

    if (btnImportHts) {
        btnImportHts.addEventListener("click", importHtsMypick);
    }

    // ────────────────────────────────────────────────────────────
    // Holdings Management Logic
    // ────────────────────────────────────────────────────────────
    const holdingsTableBody = document.getElementById("holdings-table-body");
    const holdingsEmptyMessage = document.getElementById("holdings-empty-message");
    const btnImportAll = document.getElementById("btn-import-all");
    const btnRefreshHoldings = document.getElementById("btn-refresh-holdings");

    async function loadHoldings() {
        showLoading("실시간 계좌 보유 종목 조회 중...");
        try {
            const response = await fetch("/api/holdings");
            const data = await response.json();
            if (data.success) {
                renderHoldingsTable(data.holdings);
            } else {
                alert(`오류: ${data.error}`);
            }
        } catch (error) {
            console.error("보유종목 로드 에러:", error);
            alert("보유종목 정보를 불러오지 못했습니다.");
        } finally {
            hideLoading();
        }
    }

    function renderHoldingsTable(holdings) {
        holdingsTableBody.innerHTML = "";
        if (!holdings || holdings.length === 0) {
            holdingsEmptyMessage.classList.remove("hidden");
            return;
        }
        holdingsEmptyMessage.classList.add("hidden");

        holdings.forEach(h => {
            const evalAmount = h.quantity * h.current_price;
            const profitLossPct = h.buy_price > 0 ? ((h.current_price - h.buy_price) / h.buy_price) * 100 : 0;
            const profitClass = profitLossPct >= 0 ? "profit-text" : "loss-text";
            const profitSign = profitLossPct >= 0 ? "+" : "";

            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>
                    <div class="trade-stock-name">${h.name}</div>
                    <div class="trade-stock-code">${h.code}</div>
                </td>
                <td>${h.quantity.toLocaleString()}주</td>
                <td>${Math.round(h.buy_price).toLocaleString()}원</td>
                <td>${Math.round(h.current_price).toLocaleString()}원</td>
                <td>${Math.round(evalAmount).toLocaleString()}원</td>
                <td><span class="${profitClass}">${profitSign}${profitLossPct.toFixed(2)}%</span></td>
                <td style="text-align: right;">
                    <button class="btn-add-action" data-code="${h.code}">
                        <i class="fa-solid fa-plus"></i> 관심종목 추가
                    </button>
                </td>
            `;

            // Bind individual import
            tr.querySelector(".btn-add-action").addEventListener("click", () => {
                addWatchlist(h.code);
            });

            holdingsTableBody.appendChild(tr);
        });
    }

    async function importAllHoldings() {
        if (!confirm("현재 계좌에 보유 중인 모든 종목을 관심종목 목록에 추가하시겠습니까?")) {
            return;
        }
        showLoading("계좌 보유 종목을 관심종목 엑셀에 일괄 동기화 중...");
        try {
            const response = await fetch("/api/watchlist/import_holdings", {
                method: "POST"
            });
            const data = await response.json();
            if (data.success) {
                alert(data.message);
            } else {
                alert(`연동 실패: ${data.error}`);
            }
        } catch (error) {
            console.error("일괄 연동 에러:", error);
            alert("일괄 연동에 실패했습니다.");
        } finally {
            hideLoading();
        }
    }

    btnImportAll.addEventListener("click", importAllHoldings);
    btnRefreshHoldings.addEventListener("click", loadHoldings);

    // ────────────────────────────────────────────────────────────
    // Loading overlay helpers
    // ────────────────────────────────────────────────────────────
    function showLoading(message) {
        if (loadingMessageText) {
            loadingMessageText.textContent = message;
        }
        loadingOverlay.classList.remove("hidden");
    }

    function hideLoading() {
        loadingOverlay.classList.add("hidden");
        // Reset message to default
        if (loadingMessageText) {
            loadingMessageText.textContent = "키움증권 REST API 동기화 및 백테스팅 분석 중...";
        }
    }

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
