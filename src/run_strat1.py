import os
import time
from decimal import Decimal
import sys
import configparser
import threading
import ccxt
import pandas as pd
from dotenv import load_dotenv

# --- Config loading ---
load_dotenv()
config = configparser.ConfigParser()
conf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bot.conf')
if os.path.exists(conf_path):
    config.read(conf_path)
    conf = config['strategy'] if 'strategy' in config else {}
else:
    conf = {}

def get_conf(key, typ, env=None, default=None):
    if key in conf:
        return typ(conf[key])
    if env and os.getenv(env) is not None:
        return typ(os.getenv(env))
    return default

API_KEY = os.getenv('BITGET_API_KEY', '')
API_SECRET = os.getenv('BITGET_API_SECRET', '')
API_PASSWORD = os.getenv('BITGET_API_PASSWORD', '')


# Multi-symbol support
SYMBOLS_RAW = get_conf('SYMBOLS', str, 'SYMBOLS', 'SOL')
SYMBOLS = [s.strip().upper() for s in SYMBOLS_RAW.split(',') if s.strip()]
MARKET_TYPE = 'swap'
TIMEFRAME = get_conf('TIMEFRAME', str, 'TIMEFRAME', '5m')
FAST_EMA = get_conf('FAST_EMA', int, 'FAST_EMA', 21)
SLOW_EMA = get_conf('SLOW_EMA', int, 'SLOW_EMA', 55)
POSITION_SIZE_USDT = get_conf('POSITION_SIZE_USDT', float, 'POSITION_SIZE_USDT', 50)
TP_PCT = get_conf('TP_PCT', float, 'TP_PCT', 0.01)
SL_PCT = get_conf('SL_PCT', float, 'SL_PCT', 0.005)
POLL_SECONDS = get_conf('POLL_SECONDS', int, 'POLL_SECONDS', 10)
LEVERAGE = get_conf('LEVERAGE', int, 'LEVERAGE', 1)

DEBUG = os.getenv('DEBUG', 'false').lower() == 'true' or '--debug' in sys.argv or 'debug=true' in [a.lower() for a in sys.argv]
def dprint(*args, **kwargs):
    if DEBUG:
        print('[DEBUG]', *args, **kwargs)

def make_exchange():
    dprint('Creating Bitget exchange instance...')
    params = {
        'enableRateLimit': True,
        'options': {
            'defaultType': MARKET_TYPE,
        }
    }
    if API_KEY and API_SECRET and API_PASSWORD:
        params.update({'apiKey': API_KEY, 'secret': API_SECRET, 'password': API_PASSWORD})
    dprint('Exchange params:', params)
    return ccxt.bitget(params)

def round_amount(exchange: ccxt.bitget, market, amount: float) -> float:
    precision = market.get('precision', {}).get('amount')
    min_lot = market.get('limits', {}).get('amount', {}).get('min')
    if precision is not None:
        precision = int(precision)
        q = Decimal(10) ** int(-precision)
        amount = float((Decimal(amount) // q) * q)
    if min_lot and amount < min_lot:
        amount = min_lot
    return max(0.0, amount)

def get_market(exchange: ccxt.bitget, symbol: str):
    dprint('Loading markets...')
    exchange.load_markets()
    market = exchange.market(symbol)
    dprint('Market info:', market)
    if not market.get('linear'):
        raise RuntimeError(f"Expected linear USDT perpetual for {symbol}")
    return market

def fetch_ohlcv_df(exchange: ccxt.Exchange, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    dprint(f'Fetching OHLCV for {symbol} {timeframe}...')
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    dprint('OHLCV head:', df.head())
    return df

def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()

def get_signal(df: pd.DataFrame) -> str:
    if len(df) < max(FAST_EMA, SLOW_EMA) + 2:
        dprint('Not enough data for signal')
        return 'none'
    df = df.copy()
    df['ema_fast'] = ema(df['close'], FAST_EMA)
    df['ema_slow'] = ema(df['close'], SLOW_EMA)
    f_prev, f_last = df['ema_fast'].iloc[-3], df['ema_fast'].iloc[-2]
    s_prev, s_last = df['ema_slow'].iloc[-3], df['ema_slow'].iloc[-2]
    dprint(f'EMAs: f_prev={f_prev}, f_last={f_last}, s_prev={s_prev}, s_last={s_last}')
    if f_prev <= s_prev and f_last > s_last:
        dprint('Signal: long')
        return 'long'
    if f_prev >= s_prev and f_last < s_last:
        dprint('Signal: short')
        return 'short'
    dprint('Signal: none')
    return 'none'

def get_position(exchange: ccxt.Exchange, symbol: str):
    try:
        dprint('Fetching positions...')
        exchange.load_markets()
        positions = exchange.fetch_positions([symbol])
        dprint('Positions:', positions)
        for p in positions:
            if p.get('symbol') == symbol and float(p.get('contracts', 0)) > 0:
                dprint('Active position:', p)
                return p
        dprint('No active position')
        return None
    except Exception as e:
        print(f"fetch_positions error: {e}")
        return None

def side_from_position(pos):
    if not pos:
        return 'flat'
    side = pos.get('side')
    if side:
        return side
    contracts = float(pos.get('contracts', 0) or 0)
    if contracts == 0:
        return 'flat'
    return 'long' if contracts > 0 else 'short'

def get_last_price(exchange: ccxt.Exchange, symbol: str) -> float:
    dprint('Fetching last price...')
    ticker = exchange.fetch_ticker(symbol)
    dprint('Ticker:', ticker)
    return float(ticker['last'])

def usd_to_contracts(exchange: ccxt.Exchange, market, quote_usdt: float, price: float) -> float:
    base_amount = quote_usdt / price
    return round_amount(exchange, market, base_amount)

def market_order(exchange: ccxt.Exchange, symbol: str, side: str, amount: float):
    print(f"[TRADE] Placing market {side.upper()} {amount} {symbol}")
    dprint('Order params:', {'symbol': symbol, 'side': side, 'amount': amount})
    try:
        order = exchange.create_order(symbol, 'market', side, amount)
        order_id = order.get('id', 'N/A')
        price = order.get('price', 'N/A')
        status = order.get('status', 'N/A')
        print(f"[TRADE] SUCCESS: {side.upper()} {amount} {symbol} | order_id: {order_id} | price: {price} | status: {status}")
        dprint('Order result:', order)
        return order
    except Exception as e:
        print(f"[TRADE] ERROR placing {side.upper()} {amount} {symbol}: {e}")
        raise

def close_position(exchange: ccxt.Exchange, market, symbol: str, pos, price_now: float, tp_pct: float, sl_pct: float):
    side = side_from_position(pos)
    if side == 'flat':
        return False
    entry = float(pos.get('entryPrice') or 0) or float(pos.get('info', {}).get('avgPrice', 0) or 0)
    contracts = float(pos.get('contracts') or 0)
    if contracts <= 0 or entry <= 0:
        return False
    pnl_pct = (price_now - entry) / entry if side == 'long' else (entry - price_now) / entry
    hit_tp = pnl_pct >= tp_pct
    hit_sl = pnl_pct <= -sl_pct
    if hit_tp or hit_sl:
        exit_side = 'sell' if side == 'long' else 'buy'
        amt = round_amount(exchange, market, contracts)
        try:
            order = market_order(exchange, symbol, exit_side, amt)
            print(f"[EXIT] {symbol} {side.upper()} position closed: TP={hit_tp} SL={hit_sl} pnl_pct={pnl_pct:.4f} | order_id: {order.get('id', 'N/A')}")
            return True
        except Exception as e:
            print(f"[EXIT] ERROR closing {symbol} {side.upper()} position: {e}")
    return False

def set_leverage(exchange, symbol, leverage):
    try:
        market = exchange.market(symbol)
        if hasattr(exchange, 'set_leverage'):
            dprint(f"Setting leverage {leverage}x for {symbol}")
            exchange.set_leverage(leverage, symbol)
            print(f"Leverage set to {leverage}x for {symbol}")
        else:
            print("Exchange does not support set_leverage method via ccxt.")
    except Exception as e:
        print(f"Failed to set leverage: {e}")


def symbol_to_ccxt(symbol):
    # Map e.g. SOL -> SOL/USDT:USDT
    return f"{symbol}/USDT:USDT"

def run_strategy_for_symbol(symbol):
    ccxt_symbol = symbol_to_ccxt(symbol)
    print(f"[Thread {symbol}] Starting bot with leverage control...")
    dprint(f'[Thread {symbol}] Debug mode enabled')
    exchange = make_exchange()
    dprint(f'[Thread {symbol}] Exchange created')
    exchange.set_sandbox_mode(False)
    dprint(f'[Thread {symbol}] Sandbox mode set to False')
    market = get_market(exchange, ccxt_symbol)
    dprint(f'[Thread {symbol}] Market loaded')
    set_leverage(exchange, ccxt_symbol, LEVERAGE)
    print(f"[Thread {symbol}] Running EMA cross bot on {ccxt_symbol} {TIMEFRAME} | fast={FAST_EMA} slow={SLOW_EMA} | leverage={LEVERAGE}x")
    last_signal_time = None
    last_signal_type = None
    while True:
        try:
            dprint(f'[Thread {symbol}] Top of main loop')
            df = fetch_ohlcv_df(exchange, ccxt_symbol, TIMEFRAME, limit=max(200, SLOW_EMA + 50))
            if len(df) >= max(FAST_EMA, SLOW_EMA) + 2:
                ema_fast = df['close'].ewm(span=FAST_EMA, adjust=False).mean().iloc[-2]
                ema_slow = df['close'].ewm(span=SLOW_EMA, adjust=False).mean().iloc[-2]
                ema_diff = ema_fast - ema_slow
                if last_signal_time is not None:
                    mins_ago = (time.time() - last_signal_time) / 60
                    print(f"[Thread {symbol}] data pooled | EMA diff = {ema_diff:.5f} | last signal: {last_signal_type} {mins_ago:.1f} min ago")
                else:
                    print(f"[Thread {symbol}] data pooled | EMA diff = {ema_diff:.5f} | last signal: NOTYET")
            else:
                print(f"[Thread {symbol}] data pooled | Not enough data for EMA diff yet | last signal: NOTYET")
            signal = get_signal(df)
            if signal in ("long", "short"):
                last_signal_time = time.time()
                last_signal_type = signal
            pos = get_position(exchange, ccxt_symbol)
            side = side_from_position(pos)
            price = get_last_price(exchange, ccxt_symbol)
            dprint(f'[Thread {symbol}] signal={signal}, side={side}, price={price}')
            closed = close_position(exchange, market, ccxt_symbol, pos, price, TP_PCT, SL_PCT)
            if closed:
                dprint(f'[Thread {symbol}] Position closed for TP/SL')
                time.sleep(POLL_SECONDS)
                continue
            if side == 'flat' and signal in ('long', 'short'):
                amount = usd_to_contracts(exchange, market, POSITION_SIZE_USDT, price)
                dprint(f'[Thread {symbol}] Calculated amount: {amount}')
                if amount <= 0:
                    print(f"[Thread {symbol}] Amount rounded to 0; increase POSITION_SIZE_USDT")
                else:
                    order_side = 'buy' if signal == 'long' else 'sell'
                    try:
                        order = market_order(exchange, ccxt_symbol, order_side, amount)
                        print(f"[ENTRY] {ccxt_symbol} {order_side.upper()} {amount} contracts at ~{price} | order_id: {order.get('id', 'N/A')}")
                    except Exception as e:
                        print(f"[ENTRY] ERROR placing entry order for {ccxt_symbol}: {e}")
        except ccxt.NetworkError as e:
            print(f"[Thread {symbol}] Network error: {e}")
        except ccxt.ExchangeError as e:
            print(f"[Thread {symbol}] Exchange error: {e}")
        except Exception as e:
            print(f"[Thread {symbol}] Unhandled error: {e}")
        time.sleep(POLL_SECONDS)

def main():
    print(f"Starting multi-symbol bot for: {', '.join(SYMBOLS)}")
    threads = []
    for symbol in SYMBOLS:
        t = threading.Thread(target=run_strategy_for_symbol, args=(symbol,), daemon=True)
        t.start()
        threads.append(t)
    # Keep main thread alive
    while True:
        time.sleep(60)

if __name__ == '__main__':
    main()
