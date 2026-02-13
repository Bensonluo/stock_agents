# Stock Agent Frontend

Next.js frontend for the Stock Analysis Multi-Agent System.

## Features

- **Stock Analysis**: Submit analysis requests and view real-time workflow progress
- **Results Display**: Comprehensive results with technical, fundamental, sentiment, and risk analysis
- **Backtesting**: Run strategy backtests with historical data and visualize results
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
