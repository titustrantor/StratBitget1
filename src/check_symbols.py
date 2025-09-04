import os
import configparser
import ccxt
from dotenv import load_dotenv

def get_symbols_from_conf():
    load_dotenv()
    config = configparser.ConfigParser()
    conf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bot.conf')
    if os.path.exists(conf_path):
        config.read(conf_path)
        conf = config['strategy'] if 'strategy' in config else {}
    else:
        conf = {}
    symbols_raw = conf.get('SYMBOLS', 'SOL')
    return [s.strip().upper() for s in symbols_raw.split(',') if s.strip()]

def symbol_to_ccxt(symbol):
    return f"{symbol}/USDT:USDT"

def check_symbols_exist():
    exchange = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    exchange.load_markets()
    all_markets = exchange.markets
    symbols = get_symbols_from_conf()
    print("Checking symbols on Bitget (USDT-margined perps):")
    for symbol in symbols:
        ccxt_symbol = symbol_to_ccxt(symbol)
        if ccxt_symbol in all_markets and all_markets[ccxt_symbol].get('linear'):
            # Try to fetch ticker for more market data
            try:
                ticker = exchange.fetch_ticker(ccxt_symbol)
                last = ticker.get('last', 'N/A')
                bid = ticker.get('bid', 'N/A')
                ask = ticker.get('ask', 'N/A')
                high = ticker.get('high', 'N/A')
                low = ticker.get('low', 'N/A')
                base_vol = ticker.get('baseVolume', 'N/A')
                quote_vol = ticker.get('quoteVolume', 'N/A')
                funding = ticker.get('info', {}).get('fundingRate', 'N/A')
                mark = ticker.get('info', {}).get('markPrice', 'N/A')
                print(f"  [OK] {ccxt_symbol} exists and is linear | last: {last} | bid: {bid} | ask: {ask} | high24h: {high} | low24h: {low} | baseVol24h: {base_vol} | quoteVol24h: {quote_vol} | funding: {funding} | mark: {mark}")
            except Exception as e:
                print(f"  [OK] {ccxt_symbol} exists and is linear | [ticker error: {e}]")
        else:
            print(f"  [MISSING] {ccxt_symbol} does NOT exist as a linear USDT perp")

if __name__ == '__main__':
    check_symbols_exist()
