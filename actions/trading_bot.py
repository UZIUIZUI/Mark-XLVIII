"""Trading bot for Jarvis (ccxt based).

Safe by default: runs in PAPER mode (simulated money, real market data).
Live trading needs config/trading.json with "mode": "live" plus exchange API keys
(trade-only permission, withdrawals DISABLED) and an explicit confirm.
Deposits/withdrawals happen at the exchange itself, not inside this code.
"""
import json
import threading
import time
from pathlib import Path

BASE_DIR    = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "trading.json"
STATE_PATH  = BASE_DIR / "memory" / "trading_state.json"

DEFAULTS = {
    "exchange": "kraken",        # any ccxt exchange id (kraken, bitvavo, coinbase, binance ...)
    "api_key": "",
    "api_secret": "",
    "mode": "paper",             # paper | live
    "symbol": "BTC/EUR",
    "timeframe": "15m",
    "interval_sec": 60,
    "trade_fraction": 0.10,      # max share of quote balance per buy
    "stop_loss_pct": 2.0,
    "take_profit_pct": 4.0,
    "max_daily_loss_pct": 5.0,   # bot halts for the day beyond this
    "paper_start_balance": 1000.0,
    "risk_per_trade_pct": 1.0,   # max loss per trade as % of equity (ATR-sized)
    "atr_stop_mult": 2.0,        # stop distance = 2 x ATR, trails upward
    "fee_pct": 0.26,             # taker fee per side, counted in paper mode too
}

_thread = None
_stop   = threading.Event()
_lock   = threading.Lock()


def _cfg() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return cfg


def _load_state(cfg) -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"cash": cfg["paper_start_balance"], "qty": 0.0, "entry": 0.0,
            "day": time.strftime("%Y-%m-%d"), "day_start_equity": cfg["paper_start_balance"],
            "log": [], "halted": False}


def _save_state(st):
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, indent=1), encoding="utf-8")


def _exchange(cfg):
    import ccxt
    ex = getattr(ccxt, cfg["exchange"])({
        "apiKey": cfg["api_key"], "secret": cfg["api_secret"], "enableRateLimit": True,
        "options": {"defaultType": "spot"}})  # spot only: no leverage/margin/futures, so no debt
    return ex


def _ema(vals, n):
    k, e = 2 / (n + 1), vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def _rsi(closes, n=14):
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)


def _atr(ohlcv, n=14):
    trs = [max(h - l, abs(h - pc), abs(l - pc))
           for (_, _, h, l, _, _), pc in zip(ohlcv[1:], [c[4] for c in ohlcv[:-1]])]
    return sum(trs[-n:]) / n


def analyze(ex, cfg) -> dict:
    ohlcv  = ex.fetch_ohlcv(cfg["symbol"], cfg["timeframe"], limit=120)
    closes = [c[4] for c in ohlcv]
    fast, slow, rsi = _ema(closes[-60:], 9), _ema(closes[-60:], 21), _rsi(closes)
    ema50, atr = _ema(closes[-100:], 50), _atr(ohlcv)
    signal = "hold"
    if fast > slow and rsi < 70 and closes[-1] > ema50:  # only buy in an uptrend
        signal = "buy"
    elif fast < slow or rsi > 75:
        signal = "sell"
    return {"price": closes[-1], "atr": atr, "ema9": fast, "ema21": slow, "rsi": rsi, "signal": signal}


def _equity(st, price):
    return st["cash"] + st["qty"] * price


def _log(st, msg):
    st["log"] = (st["log"] + [f"{time.strftime('%H:%M:%S')} {msg}"])[-50:]


def _step(ex, cfg, st):
    a, price, live = analyze(ex, cfg), None, cfg["mode"] == "live"
    price = a["price"]
    today = time.strftime("%Y-%m-%d")
    if st["day"] != today:
        st.update(day=today, day_start_equity=_equity(st, price), halted=False)
    if _equity(st, price) < st["day_start_equity"] * (1 - cfg["max_daily_loss_pct"] / 100):
        if st["qty"] > 0:
            _sell(ex, cfg, st, price, "daily loss limit")
        st["halted"] = True
        return
    if st["halted"]:
        return
    if st["qty"] > 0:
        chg = (price / st["entry"] - 1) * 100
        st["stop"] = max(st.get("stop", 0), price - cfg["atr_stop_mult"] * a["atr"])  # trailing
        if price <= st["stop"]:
            _sell(ex, cfg, st, price, f"ATR stop {chg:.1f}%")
        elif chg >= cfg["take_profit_pct"]:
            _sell(ex, cfg, st, price, f"take-profit {chg:.1f}%")
        elif a["signal"] == "sell":
            _sell(ex, cfg, st, price, "sell signal")
    elif a["signal"] == "buy":
        dist  = cfg["atr_stop_mult"] * a["atr"]
        risk  = _equity(st, price) * cfg["risk_per_trade_pct"] / 100
        spend = min(risk / dist * price, st["cash"] * cfg["trade_fraction"], st["cash"] / (1 + cfg["fee_pct"] / 100))
        if spend > 5:
            qty = spend / price
            if live:
                ex.create_market_buy_order(cfg["symbol"], qty)
            st["cash"] -= spend * (1 + cfg["fee_pct"] / 100)
            st["qty"], st["entry"], st["stop"] = qty, price, price - dist
            _log(st, f"BUY {qty:.6f} @ {price:.2f}")


def _sell(ex, cfg, st, price, why):
    if cfg["mode"] == "live":
        ex.create_market_sell_order(cfg["symbol"], st["qty"])
    st["cash"] += st["qty"] * price * (1 - cfg["fee_pct"] / 100)
    _log(st, f"SELL {st['qty']:.6f} @ {price:.2f} ({why})")
    st["qty"], st["entry"] = 0.0, 0.0


def _loop():
    cfg = _cfg()
    ex  = _exchange(cfg)
    while not _stop.is_set():
        try:
            with _lock:
                st = _load_state(cfg)
                _step(ex, cfg, st)
                _save_state(st)
        except Exception as e:
            with _lock:
                st = _load_state(cfg)
                _log(st, f"error: {e}")
                _save_state(st)
        _stop.wait(cfg["interval_sec"])


def trading_bot(parameters: dict, player=None, session_memory=None) -> str:
    global _thread
    action = (parameters.get("action") or "status").lower()
    try:
        cfg = _cfg()
    except Exception as e:
        return f"Sir, config/trading.json is invalid: {e}"

    if action == "start":
        if _thread and _thread.is_alive():
            return "The trading bot is already running, sir."
        if cfg["mode"] == "live":
            if not (cfg["api_key"] and cfg["api_secret"]):
                return "Live mode needs api_key and api_secret in config/trading.json, sir."
            if not parameters.get("confirm_live"):
                return ("Live mode uses REAL money. Please confirm explicitly "
                        "(confirm_live=true) and make sure the API key has withdrawals disabled.")
        _stop.clear()
        _thread = threading.Thread(target=_loop, daemon=True)
        _thread.start()
        return f"Trading bot started in {cfg['mode'].upper()} mode on {cfg['symbol']}, sir."

    if action == "stop":
        _stop.set()
        return "Trading bot stopped, sir."

    if action == "analyze":
        a = analyze(_exchange(cfg), cfg)
        return (f"{cfg['symbol']}: {a['price']:.2f} | EMA9 {a['ema9']:.2f} / EMA21 {a['ema21']:.2f} "
                f"| RSI {a['rsi']:.0f} -> signal: {a['signal'].upper()} (not financial advice)")

    if action == "balance" and cfg["mode"] == "live":
        return "Live balance: " + str(_exchange(cfg).fetch_balance().get("total", {}))

    if action == "deposit_info":
        return ("Deposits and withdrawals (bank transfer, card, PayPal where offered) are done in your "
                "exchange/broker account, not through Jarvis. Fund the account there; the bot then trades "
                "with that balance. Paysafecard is not accepted by regulated exchanges for withdrawals-capable accounts.")

    st = _load_state(cfg)
    running = bool(_thread and _thread.is_alive())
    try:
        price = analyze(_exchange(cfg), cfg)["price"]
    except Exception:
        price = st["entry"] or 0
    return (f"Bot {'running' if running else 'stopped'} ({cfg['mode']}). Equity {_equity(st, price):.2f}, "
            f"cash {st['cash']:.2f}, position {st['qty']:.6f}{' - HALTED today' if st['halted'] else ''}. "
            f"Last: {'; '.join(st['log'][-3:]) or 'no trades yet'}")
