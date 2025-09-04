# Bitget EMA Cross Strategy (SOLUSDT Perps)

This is a minimal EMA crossover strategy for Bitget USDT-margined perpetual futures on SOLUSDT, using ccxt. It opens a position when a fast EMA crosses a slow EMA and manages take-profit and stop-loss via market exits managed by the bot.

Important: Use at your own risk. Test on paper or with very small size first.

## Features
- Exchange access via `ccxt` (Bitget)
- Uses symbol: `SOLUSDT` (USDT-M perpetual) with linear contracts
- Fast/slow EMA crossover on close prices
- Single position mode: one open position at a time
- Risk params: position size in USDT, take-profit %, stop-loss %
- Polling loop with rate limiting and basic error handling

## Setup
1. Create a `.env` file from the example and fill your API credentials:
```
BITGET_API_KEY=...
BITGET_API_SECRET=...
BITGET_API_PASSWORD=...
```

2. Install packages
```
pip install -r requirements.txt
```

## Run
```
python src/main.py
```

### Optional args (env or edit code)
- FAST_EMA=21
- SLOW_EMA=55
- TIMEFRAME=5m
- POSITION_SIZE_USDT=50
- TP_PCT=0.01   # 1%
- SL_PCT=0.005  # 0.5%
- POLL_SECONDS=10

## Notes
- The bot uses market orders and does not place resting TP/SL orders; it monitors price and exits when TP or SL hit.
- Ensure your Bitget account is in USDT-M linear contracts and has one-way mode.
- Mind ccxt/Bitget min trade size and lot step. The bot rounds to the symbol's amount precision.
- This code is educational; extend with logging, persistence, and better state handling for production use.
