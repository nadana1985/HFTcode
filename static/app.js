// Quant Multi-Timeframe Dashboard JS Engine
let chart;
let candleSeries;
let volumeSeries;
let rawKlines = [];
let rawEvents = [];

const symbolSelect = document.getElementById("symbol-select");
const timeframeSelect = document.getElementById("timeframe-select");
const datePicker = document.getElementById("date-picker");
const prevDayBtn = document.getElementById("prev-day-btn");
const nextDayBtn = document.getElementById("next-day-btn");
const markerToggle = document.getElementById("marker-toggle");
const confluenceSlider = document.getElementById("confluence-slider");
const confluenceVal = document.getElementById("confluence-val");
const chartStatus = document.getElementById("chart-status");

// Stats selectors
const chartTitle = document.getElementById("chart-title");
const statsTitle = document.getElementById("stats-title");
const selectedTime = document.getElementById("selected-time");
const statOpen = document.getElementById("stat-open");
const statHigh = document.getElementById("stat-high");
const statLow = document.getElementById("stat-low");
const statClose = document.getElementById("stat-close");
const statVol = document.getElementById("stat-vol");
const statIndex = document.getElementById("stat-index");
const htfHeatmapGrid = document.getElementById("htf-heatmap-grid");
const heatmapDetail = document.getElementById("heatmap-detail");
const heatmapTimeSubtitle = document.getElementById("heatmap-time-subtitle");

function initChart() {
    const container = document.getElementById("chart-container");
    
    // Create the chart instance
    chart = LightweightCharts.createChart(container, {
        layout: {
            background: { type: 'solid', color: '#131722' },
            textColor: '#d1d4dc',
        },
        grid: {
            vertLines: { color: 'rgba(42, 46, 57, 0.5)' },
            horzLines: { color: 'rgba(42, 46, 57, 0.5)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: 'rgba(197, 203, 206, 0.8)',
        },
        timeScale: {
            borderColor: 'rgba(197, 203, 206, 0.8)',
            timeVisible: true,
            secondsVisible: false,
        },
    });

    // Add candlestick series
    candleSeries = chart.addCandlestickSeries({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
    });

    // Add volume series overlay on a separate pane
    volumeSeries = chart.addHistogramSeries({
        color: '#26a69a',
        priceFormat: {
            type: 'volume',
        },
        priceScaleId: '', // overlay
    });

    volumeSeries.priceScale().applyOptions({
        scaleMargins: {
            top: 0.8,
            bottom: 0,
        },
    });

    // Handle crosshair hover tracking
    chart.subscribeCrosshairMove((param) => {
        if (!param || !param.time || param.point === undefined) {
            clearStats();
            return;
        }

        // Get the hovered candle data
        const data = param.seriesData.get(candleSeries);
        const volData = param.seriesData.get(volumeSeries);
        if (data) {
            updateStats(param.time, data, volData);
        }
    });

    // Resize listener
    window.addEventListener('resize', () => {
        chart.resize(container.clientWidth, container.clientHeight);
    });
}

function getDivisors(elapsedMinutes, R) {
    let divisors = [];
    for (let i = R; i <= elapsedMinutes; i += R) {
        if (elapsedMinutes % i === 0) {
            divisors.push(i);
        }
    }
    return divisors.sort((a, b) => a - b);
}

function getCandleNumber(timestampSec, R) {
    const date = new Date(timestampSec * 1000);
    const hour = date.getUTCHours();
    const min = date.getUTCMinutes();
    const elapsedMinutes = (hour * 60 + min) + R;
    return Math.floor(elapsedMinutes / R);
}

function updateStats(timeSec, candle, vol) {
    const date = new Date(timeSec * 1000);
    const dateStr = date.toISOString().replace('T', ' ').substring(0, 16) + " UTC";
    
    const tf = timeframeSelect.value;
    const R = tf === "15m" ? 15 : (tf === "30m" ? 30 : 1);
    
    chartTitle.innerText = `${tf.toUpperCase()} Candlestick Chart (TradingView)`;
    statsTitle.innerText = `${tf.toUpperCase()} Candle Stats`;
    
    selectedTime.innerText = dateStr;
    heatmapTimeSubtitle.innerText = `at ${dateStr}`;
    statOpen.innerText = `$${candle.open.toLocaleString()}`;
    statHigh.innerText = `$${candle.high.toLocaleString()}`;
    statLow.innerText = `$${candle.low.toLocaleString()}`;
    statClose.innerText = `$${candle.close.toLocaleString()}`;
    statVol.innerText = vol ? vol.value.toLocaleString() : "-";
    
    const hour = date.getUTCHours();
    const min = date.getUTCMinutes();
    const elapsedMinutes = (hour * 60 + min) + R;
    
    const candleNum = Math.floor(elapsedMinutes / R);
    const maxIndex = 1440 / R;
    statIndex.innerText = `#${candleNum} / ${maxIndex}`;

    // Get divisors for the candle number (multiples of R)
    const divisors = getDivisors(elapsedMinutes, R);
    
    // Find events matching the close time of this resampled bar
    const closeTimeSec = timeSec + (R - 1) * 60;
    const matchingEvents = rawEvents.filter(e => e.time === closeTimeSec);

    // Build the Heatmap Grid
    htfHeatmapGrid.innerHTML = "";
    
    divisors.forEach(tf => {
        const cell = document.createElement("div");
        cell.innerText = `${tf}m`;
        cell.style.padding = "6px 10px";
        cell.style.borderRadius = "4px";
        cell.style.fontSize = "12px";
        cell.style.fontWeight = "bold";
        cell.style.fontFamily = "monospace";
        cell.style.cursor = "pointer";
        cell.style.transition = "transform 0.1s";
        
        // Find if this timeframe triggered an event
        const event = matchingEvents.find(e => e.timeframe === tf);
        
        let detailHtml = `${tf}m: Inside prior range (Neutral)`;
        
        if (event) {
            if (event.event_type === "Bullish_Expansion") {
                cell.style.background = "var(--accent-green)";
                cell.style.color = "#000";
                detailHtml = `${tf}m: 🟢 Bullish Expansion (Closed above previous High at $${event.price_at_close.toLocaleString()})`;
            } else if (event.event_type === "Bearish_Expansion") {
                cell.style.background = "var(--accent-red)";
                cell.style.color = "#fff";
                detailHtml = `${tf}m: 🔴 Bearish Breakdown (Closed below previous Low at $${event.price_at_close.toLocaleString()})`;
            }
        } else {
            cell.style.background = "var(--neutral-gray)";
            cell.style.color = "var(--text-secondary)";
        }
        
        // Hover interactions for the heatmap block
        cell.addEventListener("mouseover", () => {
            cell.style.transform = "scale(1.1)";
            heatmapDetail.innerHTML = detailHtml;
            heatmapDetail.style.color = event ? (event.event_type === "Bullish_Expansion" ? "var(--accent-green)" : "var(--accent-red)") : "var(--accent-blue)";
        });
        
        cell.addEventListener("mouseout", () => {
            cell.style.transform = "scale(1)";
        });

        htfHeatmapGrid.appendChild(cell);
    });
}

function clearStats() {
    selectedTime.innerText = "Hover or click a candle on the chart";
    heatmapTimeSubtitle.innerText = "";
    statOpen.innerText = "-";
    statHigh.innerText = "-";
    statLow.innerText = "-";
    statClose.innerText = "-";
    statVol.innerText = "-";
    statIndex.innerText = "-";
    htfHeatmapGrid.innerHTML = `
        <span class="placeholder-text" style="width: 100%; text-align: center; color: var(--text-secondary); margin-top: 15px;">Hover over the chart to inspect timeframes.</span>
    `;
    heatmapDetail.innerText = "Hover over blocks for details";
    heatmapDetail.style.color = "var(--text-secondary)";
}

async function loadData() {
    const symbol = symbolSelect.value;
    const date = datePicker.value;
    const tf = timeframeSelect.value;
    
    chartStatus.innerText = "Fetching data...";
    
    try {
        // Fetch raw klines
        const klineRes = await fetch(`/api/klines?symbol=${symbol}&date=${date}&resolution=${tf}`);
        const klines = await klineRes.json();
        
        if (klines.error) {
            chartStatus.innerText = `Error: ${klines.error}`;
            return;
        }
        
        // Fetch events
        const eventRes = await fetch(`/api/events?symbol=${symbol}&date=${date}`);
        const events = await eventRes.json();
        
        rawKlines = klines;
        rawEvents = events;
        
        // Populate chart
        candleSeries.setData(klines);
        
        // Populate volume
        const volData = klines.map(k => ({
            time: k.time,
            value: k.volume,
            color: k.close >= k.open ? 'rgba(38, 166, 154, 0.5)' : 'rgba(239, 83, 80, 0.5)'
        }));
        volumeSeries.setData(volData);
        
        // Render markers
        updateChartMarkers();
        
        chartStatus.innerText = `Loaded ${klines.length} candles, ${events.length} total timeframe events.`;
        chart.timeScale().fitContent();
    } catch (e) {
        chartStatus.innerText = `Fetch Error: ${e.message}`;
    }
}

function updateChartMarkers() {
    if (!markerToggle.checked) {
        candleSeries.setMarkers([]);
        return;
    }
    
    const tf = timeframeSelect.value;
    const targetTf = tf === "15m" ? 15 : (tf === "30m" ? 30 : 1);
    
    const markers = [];
    rawEvents.forEach(e => {
        if (e.timeframe === targetTf) {
            const R = targetTf;
            const markerTime = e.time - (R - 1) * 60;
            if (e.event_type === "Bullish_Expansion") {
                markers.push({
                    time: markerTime,
                    position: 'belowBar',
                    color: '#00e676',
                    shape: 'arrowUp',
                });
            } else if (e.event_type === "Bearish_Expansion") {
                markers.push({
                    time: markerTime,
                    position: 'aboveBar',
                    color: '#ff3d00',
                    shape: 'arrowDown',
                });
            }
        }
    });
    
    candleSeries.setMarkers(markers);
}

// Date helper buttons
function offsetDay(days) {
    const currentDate = new Date(datePicker.value);
    currentDate.setDate(currentDate.getDate() + days);
    
    // Format YYYY-MM-DD
    const yyyy = currentDate.getFullYear();
    const mm = String(currentDate.getMonth() + 1).padStart(2, '0');
    const dd = String(currentDate.getDate()).padStart(2, '0');
    const dateStr = `${yyyy}-${mm}-${dd}`;
    
    // Keep inside boundaries
    if (dateStr >= datePicker.min && dateStr <= datePicker.max) {
        datePicker.value = dateStr;
        loadData();
    }
}

// Event Listeners
symbolSelect.addEventListener("change", loadData);
timeframeSelect.addEventListener("change", loadData);
datePicker.addEventListener("change", loadData);
prevDayBtn.addEventListener("click", () => offsetDay(-1));
nextDayBtn.addEventListener("click", () => offsetDay(1));
markerToggle.addEventListener("change", updateChartMarkers);

confluenceSlider.addEventListener("input", (e) => {
    confluenceVal.innerText = e.target.value;
    updateChartMarkers();
});

// Run
initChart();
loadData();
