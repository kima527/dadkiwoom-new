# Directive: Daily Financial YouTube Shorts Automated Production

## 1. Goal
Execute a 100% automated, repeatable, high-CPM YouTube Shorts video production pipeline that turns daily US market closing data and macro anomalies into high-engagement, compliant, 55-second vertical (9:16) financial intelligence videos.

---

## 2. Architecture & File Organization

### Layer 1: Directive
- `directives/financial_shorts_pipeline.md`: This SOP document.

### Layer 2: Orchestration (Agent)
- Orchestrates data anomaly detection, script generation, audio synthesis, and visual rendering.

### Layer 3: Execution Tools (`execution/`)
1. `execution/fetch_market_anomaly.py`: Fetches 17 global/US tickers, detects maximum % move anomaly, generates 3 killer hooks.
2. `execution/generate_financial_chart.py`: Generates 1080x1920 Full HD 9:16 dark-mode infographic with custom price curves and scoreboard.
3. `execution/generate_market_script.py`: Tightened 52~55s 4-stage script and Edge-TTS neural speech synthesis (+18% rate).
4. `execution/render_financial_shorts.py`: FFmpeg cinematic 60FPS zoompan video rendering.
5. `execution/build_daily_shorts.py`: Master one-click end-to-end runner.

### Storage & Outputs
- Deliverable Video: `D:\download\Daily_Quant_Shorts_Sample.mp4`
- Intermediate Cache: `.tmp/` (auto-regenerated on each run)
  - `.tmp/market_anomaly_today.json`
  - `.tmp/shorts_visual_today.png`
  - `.tmp/shorts_script.txt`
  - `.tmp/shorts_narration.mp3`

---

## 3. Execution Commands

```bash
# Run entire pipeline in one click:
.venv\Scripts\python.exe execution/build_daily_shorts.py

# Or step-by-step:
.venv\Scripts\python.exe execution/fetch_market_anomaly.py
.venv\Scripts\python.exe execution/generate_financial_chart.py
.venv\Scripts\python.exe execution/generate_market_script.py
.venv\Scripts\python.exe execution/render_financial_shorts.py
```

---

## 4. YouTube Compliance & Quality Controls
- **Duration**: Strictly 52~55 seconds ($\le 58$ seconds) to qualify 100% as a YouTube Short.
- **Resolution**: 1080x1920 (9:16 vertical), 60 FPS.
- **Copyright & YPP**: 100% original code-generated charts and neural voice, eliminating "Reused Content" rejection risk.
- **Legal Compliance**: Disclaimer auto-rendered at bottom of frame and footer.

