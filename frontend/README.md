# Stock Agent Frontend

Next.js frontend for the Stock Analysis Multi-Agent System.

## Pages

| Route | Purpose |
|-------|---------|
| `/` (Home) | Submit analysis requests; history tab with per-run records and the signal-quality card (rank IC / ICIR, decay chips, confidence calibration) |
| `/result` | Full analysis report — decisions with portfolio overview, dimension-weights provenance strip, risk cards (β/α with confidence intervals, liquidity, sector-relative, market regime), technical card with price sparkline, research synthesis with the full bull/bear argument lists |
| `/monitor` | Real-time workflow monitoring — 8-agent grid (including research synthesis), parallel-superstep chip, live agent events; auto-routes to the result on completion |
| `/backtest` | Three tabs: single backtest, walk-forward parameter selection (with Deflated Sharpe Ratio verdict), and signal calibration (hit rates with Wilson lower bounds) |

## Features

- **Stock Analysis**: Submit analysis requests and view real-time workflow progress (WebSocket)
- **Results Display**: Technical / fundamental / sentiment / risk sections with evidence annotations; CN prices rendered in CNY, US in USD
- **Backtesting**: Costed strategies (SMA / RSI / MACD / `technical_score` / buy-and-hold), walk-forward grids, calibration panels, and a signal-vs-noise card (Monte Carlo random-entry null benchmark)
- **Signal Quality**: Historical recommendations scored against realized returns — IC mean, t-statistic, per-horizon decay, Brier-based confidence calibration
- **Monitoring Dashboard**: Real-time agent health, circuit breaker status, and system metrics

## Setup

1. Install dependencies:
```bash
cd frontend
npm install
```

2. Start the development server:
```bash
npm run dev
```

3. Open http://localhost:3000 in your browser

## Environment

Create a `.env.local` file:
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Build

```bash
npm run build
npm start
```

## Verification

```bash
npm run lint           # eslint, zero warnings allowed
npx tsc --noEmit       # type check
npm run build          # production build
```
