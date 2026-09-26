# ======================================================
# PART 1 - CORE IMPORTS + GLOBAL CONFIG + HOLIDAY ENGINE
# ======================================================

import os
import json
import asyncio
import threading
import time
from datetime import datetime, timedelta, date
import requests

try:
    from flask import Flask, jsonify, request, render_template_string
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Telegram imports are defined again in the compatibility section below.
# The bot is written in a synchronous style but runs on modern
# python-telegram-bot (v20+) through a small compatibility adapter.
CallbackContext = object

# ================== TELEGRAM CONFIG ==================
TOKEN = "8635470675:AAE-uJTyYwhXf5z5BguS7uH72mbfu4hRbl0"
OWNER_ID = int(os.getenv("OWNER_ID", "8210011971"))

AUTO_DELETE_SECONDS = 21000

# ================== DHAN CONFIG ==================
CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "1109097878").strip()

# 🔥 IMPORTANT CHANGE
# ❌ hard-coded token hata diya
# ✅ token Telegram se dynamically set hoga
ACCESS_TOKEN = ""

# 🔥 OWNER TOKEN UPLOAD STATE
waiting_for_token = set()

# ================== UNDERLYING IDS ==================
UNDERLYING_IDS = {
    "NIFTY": 13,
    "BANKNIFTY": 25,
    "SENSEX": 1,
}

# ================== APPROVED USERS ==================
approved_users = set()
approved_users.add(OWNER_ID)

# ======================================================
# 🗓️ NSE HOLIDAY CALENDAR (STATIC – VERIFIED)
# ======================================================
NSE_HOLIDAYS = {
    date(2024, 1, 26): "Republic Day",
    # 2025
    date(2025, 1, 26): "Republic Day",
    date(2025, 2, 26): "Mahashivratri",
    date(2025, 3, 14): "Holi",
    date(2025, 3, 31): "Id-Ul-Fitr",
    date(2025, 4, 10): "Ram Navami",
    date(2025, 4, 14): "Ambedkar Jayanti",
    date(2025, 4, 18): "Good Friday",
    date(2025, 5, 1):  "Maharashtra Day",
    date(2025, 8, 15): "Independence Day",
    date(2025, 8, 27): "Ganesh Chaturthi",
    date(2025, 10, 2): "Gandhi Jayanti",
    date(2025, 10, 2): "Dussehra",
    date(2025, 10, 21):"Diwali Laxmi Pujan",
    date(2025, 10, 22):"Diwali Balipratipada",
    date(2025, 11, 5): "Guru Nanak Jayanti",
    date(2025, 12, 25):"Christmas",
    # 2026
    date(2026, 1, 26): "Republic Day",
    date(2026, 3, 20): "Holi",
    date(2026, 4, 3):  "Good Friday",
    date(2026, 4, 14): "Ambedkar Jayanti",
    date(2026, 4, 15): "Ram Navami",
    date(2026, 5, 1):  "Maharashtra Day",
    date(2026, 8, 15): "Independence Day",
    date(2026, 10, 2): "Gandhi Jayanti",
    date(2026, 11, 13):"Diwali",
    date(2026, 12, 25):"Christmas",
    date(2024, 3, 8):  "Mahashivratri",
    date(2024, 3, 25): "Holi",
    date(2024, 3, 29): "Good Friday",
    date(2024, 4, 11): "Id-Ul-Fitr",
    date(2024, 4, 17): "Ram Navami",
    date(2024, 5, 1):  "Maharashtra Day",
    date(2024, 6, 17): "Bakri Id",
    date(2024, 7, 17): "Moharram",
    date(2024, 8, 15): "Independence Day",
    date(2024, 10, 2): "Gandhi Jayanti",
    date(2024, 11, 1): "Diwali Laxmi Pujan",
    date(2024, 11, 15):"Gurunanak Jayanti",
    date(2024, 12, 25):"Christmas Day",
}

# ======================================================
# 🧠 MARKET DAY HELPERS
# ======================================================
def is_weekend(today: date):
    return today.weekday() >= 5  # Sat/Sun


def is_market_holiday(today: date):
    return today in NSE_HOLIDAYS


def get_holiday_info(today: date):
    if is_market_holiday(today):
        return {
            "date": today.strftime("%d %B %Y"),
            "name": NSE_HOLIDAYS[today],
            "reason": "NSE & BSE officially closed",
        }
    return None


def get_next_trading_day(today: date):
    next_day = today + timedelta(days=1)
    while is_weekend(next_day) or is_market_holiday(next_day):
        next_day += timedelta(days=1)
    return next_day


# ======================================================
# 🔐 AUTH / TOKEN ERROR DETECTOR
# ======================================================
def is_auth_error(response: requests.Response):
    if response is None:
        return False
    if response.status_code in (401, 403):
        return True
    txt = (response.text or "").lower()
    if "unauthorized" in txt or "invalid token" in txt or "authentication" in txt:
        return True
    return False


# ======================================================
# 🧹 AUTO DELETE HELPER
# ======================================================
def schedule_auto_delete(context: CallbackContext, chat_id: int, message_id: int):
    def delete_message():
        try:
            context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass

    t = threading.Timer(AUTO_DELETE_SECONDS, delete_message)
    t.daemon = True
    t.start()

# ======================================================
# PART 2 - DHAN OPTION CHAIN (SAFE FETCH WITH REAL CACHE)
# ======================================================

from datetime import date
import requests
import math

# 🔒 LAST REAL OPTION CHAIN CACHE (NO DUMMY)
_LAST_OC_CACHE = {}

def fetch_option_chain_extended(symbol: str):
    """
    REAL Dhan Option Chain:
    - Market open → live data
    - Market closed / weekend → LAST REAL cached data
    - NO dummy / NO fake calculation
    """

    if symbol not in UNDERLYING_IDS:
        raise ValueError(f"Unsupported symbol for Dhan: {symbol}")

    underlying_id = UNDERLYING_IDS[symbol]
    underlying_seg = "IDX_B" if symbol == "SENSEX" else "IDX_I"

    base_url = "https://api.dhan.co/v2"
    headers = {
        "Content-Type": "application/json",
        "access-token": ACCESS_TOKEN,
        "client-id": CLIENT_ID,
    }

    try:
        # ===================== EXPIRY LIST =====================
        r_exp = requests.post(
            f"{base_url}/optionchain/expirylist",
            headers=headers,
            json={
                "UnderlyingScrip": underlying_id,
                "UnderlyingSeg": underlying_seg,
            },
            timeout=10
        )

        if is_auth_error(r_exp):
            raise Exception("AUTH ERROR")

        expiries = r_exp.json().get("data", [])
        if not expiries:
            raise Exception("No expiries")

        expiry = expiries[0]   # 🔥 NEAREST EXPIRY

        # ===================== OPTION CHAIN =====================
        r_oc = requests.post(
            f"{base_url}/optionchain",
            headers=headers,
            json={
                "UnderlyingScrip": underlying_id,
                "UnderlyingSeg": underlying_seg,
                "Expiry": expiry,
            },
            timeout=10
        )

        if is_auth_error(r_oc):
            raise Exception("AUTH ERROR")

        root = r_oc.json().get("data", {})
        spot = float(root.get("last_price", 0))
        oc = root.get("oc", {})

        if not oc:
            raise Exception("Empty option chain")

        ce_oi = pe_oi = ce_vol = pe_vol = 0

        for _, legs in oc.items():
            if legs.get("ce"):
                ce_oi += int(legs["ce"].get("oi", 0))
                ce_vol += int(legs["ce"].get("volume", 0))
            if legs.get("pe"):
                pe_oi += int(legs["pe"].get("oi", 0))
                pe_vol += int(legs["pe"].get("volume", 0))

        pcr = pe_oi / ce_oi if ce_oi else 0

        # ======================================================
        # 🔥 ATM STRIKE + REAL PREMIUM CACHE
        # ======================================================
        step = 100 if symbol in ("BANKNIFTY", "SENSEX") else 50
        atm_strike = int(round(spot / step) * step)
        strike_leg = oc.get(str(atm_strike))

        last_premium = None
        if strike_leg:
            pe = strike_leg.get("pe")
            ce = strike_leg.get("ce")
            if pe and pe.get("last_price", 0) > 0:
                last_premium = float(pe["last_price"])
            elif ce and ce.get("last_price", 0) > 0:
                last_premium = float(ce["last_price"])

        # ===================== SAVE REAL DATA =====================
        _LAST_OC_CACHE[symbol] = {
            "spot": spot,
            "pcr": pcr,
            "ce_oi": ce_oi,
            "pe_oi": pe_oi,
            "ce_vol": ce_vol,
            "pe_vol": pe_vol,
            "oc_map": oc,
            "expiry": expiry,
            "last_premium": last_premium,
        }

        return _LAST_OC_CACHE[symbol]

    except Exception:
        # ===== Market closed → last REAL cached data =====
        if symbol in _LAST_OC_CACHE:
            return _LAST_OC_CACHE[symbol]
        raise Exception("Market closed & no previous live data available")


def fetch_option_chain_basic(symbol: str):
    """
    OLD wrapper (unchanged)
    """
    data = fetch_option_chain_extended(symbol)
    return (
        data["spot"],
        data["pcr"],
        data["ce_oi"],
        data["pe_oi"],
    )

# ======================================================
# PART 3 - INDIA VIX FETCH (SAFE MODE)
# ======================================================

def fetch_india_vix():
    """
    India VIX approx fetch (NSE public API).
    - Holiday / weekend me None return karega
    - JSON na mile to bhi crash nahi karega
    """

    today = date.today()

    # ---------- MARKET CLOSED CHECK ----------
    if is_weekend(today) or is_market_holiday(today):
        return None

    url = "https://www.nseindia.com/api/allIndices?index=INDIA%20VIX"
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    }

    try:
        r = session.get(url, headers=headers, timeout=10)

        # ---------- RESPONSE VALIDATION ----------
        if r.status_code != 200:
            return None

        if not r.text or not r.text.strip().startswith("{"):
            return None

        data = r.json()
        indices = data.get("data") or data.get("indices") or []

        if not indices:
            return None

        for item in indices:
            name = item.get("index") or item.get("indexName") or ""
            if "VIX" in name.upper():
                try:
                    return float(item.get("last", 0.0))
                except Exception:
                    return None

        return None

    except Exception:
        return None

# ======================================================
# PART 4 - SINGLE SWING SETUP + REAL PREMIUM CONFIRMATION
# ======================================================

def get_atm_premium_from_oc(symbol: str, spot: float, option_side: str, oc_map: dict):
    """
    ATM strike + REAL premium from PART 2 oc_map
    """
    if symbol in ("BANKNIFTY", "SENSEX"):
        step = 100
    else:
        step = 50  # NIFTY

    atm_strike = round(spot / step) * step
    leg = oc_map.get(str(atm_strike))

    if not leg:
        return atm_strike, None

    opt = leg.get("pe" if option_side == "PE" else "ce")
    if not opt:
        return atm_strike, None

    premium = opt.get("last_price")
    if premium is None:
        return atm_strike, None

    return atm_strike, float(premium)


def generate_single_swing_setup(symbol: str, spot, pcr, ce_oi, pe_oi, oc_map, user_id=0):
    setup = ""

    # ----- Support / Resistance -----
    s1 = round(spot - 100)
    s2 = round(spot - 150)
    r1 = round(spot + 100)
    r2 = round(spot + 150)

    setup += "🔥 Big Support / Resistance (Simple)\n"
    setup += f"• S1: {s1}\n• S2: {s2}\n• R1: {r1}\n• R2: {r2}\n"
    setup += "──────────────────────────\n\n"

    # ----- BUYER SIDE LOGIC -----
    if pcr < 1 and ce_oi > pe_oi:
        sentiment = "Downside bias - PUT BUY"
        trade_type = "PE BUY"
        option_side = "PE"
    else:
        sentiment = "Upside bias - CALL BUY"
        trade_type = "CE BUY"
        option_side = "CE"

    # ----- Spot Levels -----
    entry_low = round(spot - 40)
    entry_high = round(spot - 10)
    sl = round(spot + 30)
    t1 = round(spot - 30)
    t2 = round(spot - 70)
    t3 = round(spot - 120)

    setup += f"🔴 Single Swing Setup - {trade_type}\n\n"
    setup += f"Spot Entry: {entry_low} – {entry_high}\n"
    setup += f"Spot SL: {sl}\n"
    setup += f"Spot Targets: {t1} | {t2} | {t3}\n"
    setup += "──────────────────────────\n\n"

    # ==================================================
    # 💰 REAL OPTION PREMIUM (FROM PART 2 DATA)
    # ==================================================

    atm_strike, premium = get_atm_premium_from_oc(
        symbol, spot, option_side, oc_map
    )

    setup += "💰 Premium Confirmation (REAL OPTION DATA)\n"

    if premium is None:
        setup += "• Premium data abhi available nahi\n"
        setup += "• Market open hone par auto update hoga\n"
    else:
        buy_low = round(premium * 0.90)
        buy_high = round(premium * 1.05)
        premium_sl = round(premium * 0.75)
        tp1 = round(premium * 1.25)
        tp2 = round(premium * 1.6)
        tp3 = round(premium * 2.0)

        setup += f"• Option: {atm_strike} {option_side} BUY\n"
        setup += f"• Current Premium: ₹{premium}\n"
        setup += f"• BUY Zone: ₹{buy_low} – ₹{buy_high}\n"
        setup += f"• Premium SL: ₹{premium_sl}\n"
        setup += "• Premium Targets:\n"
        setup += f"  - TP1: ₹{tp1}\n"
        setup += f"  - TP2: ₹{tp2}\n"
        setup += f"  - TP3: ₹{tp3}\n"

    setup += "──────────────────────────\n\n"
    setup += "🧠 Execution Logic:\n"
    setup += f"• {sentiment}\n"
    setup += "• Spot level hit → premium BUY\n"
    setup += "• No fake price | No fixed premium\n"
    setup += "• Pure option BUYER logic (₹10k–₹20k capital)\n"
    setup += "──────────────────────────\n"
    setup += "👑 Owner: 😈 #KETAN 😈"

    return setup

# ======================================================
# PART 5 - PRO LOGIC + REAL OPTION PREMIUM (BUYER ONLY)
# ======================================================

# 🔥 OI SNAPSHOT MEMORY
_LAST_OI_SNAPSHOT = {}

# ------------------------------------------------------
def format_lakh_crore(value: int) -> str:
    try:
        value = float(value)
    except:
        return str(value)

    if abs(value) >= 1_00_00_000:
        return f"{value / 1_00_00_000:.2f} Cr"
    elif abs(value) >= 1_00_000:
        return f"{value / 1_00_000:.2f} L"
    else:
        return str(int(value))


def get_atm_strike(symbol: str, spot: float) -> int:
    step = 100 if symbol in ("BANKNIFTY", "SENSEX") else 50
    return int(round(spot / step) * step)


# ------------------------------------------------------
# 🔥 LIVE OPTION LTP (DHAN)
def fetch_option_ltp(trading_symbol: str):

    token = globals().get("ACCESS_TOKEN")
    if not token:
        return None

    url = "https://api.dhan.co/v2/market/quote"
    headers = {
        "access-token": token,
        "client-id": CLIENT_ID,
        "Content-Type": "application/json"
    }

    try:
        r = requests.post(
            url,
            headers=headers,
            json={"symbols": [trading_symbol]},
            timeout=5
        )
        data = r.json().get("data", {})
        info = next(iter(data.values()), {})
        return info.get("ltp")
    except:
        return None


# ------------------------------------------------------
def get_atm_premium(symbol, spot, option_side, oc_map, expiry):

    step = 100 if symbol in ("BANKNIFTY", "SENSEX") else 50
    atm = get_atm_strike(symbol, spot)

    strikes = [atm]
    strikes += [atm + step, atm + step * 2] if option_side == "PE" else [atm - step, atm - step * 2]

    for strike in strikes:
        leg = oc_map.get(str(strike))
        if not leg:
            continue

        opt = leg.get("pe" if option_side == "PE" else "ce")
        if not opt:
            continue

        premium = opt.get("last_price") or opt.get("ltp") or opt.get("best_bid_price")

        if not premium:
            ts = f"NIFTY{expiry}{strike}{option_side}"
            premium = fetch_option_ltp(ts)

        if premium:
            return strike, float(premium)

    return atm, None


# ======================================================
# 🔥 PRO SETUP
# ======================================================
def generate_pro_setup(symbol: str, oc_data: dict, user_id=0):

    spot    = oc_data["spot"]
    pcr     = oc_data["pcr"]
    ce_oi   = oc_data["ce_oi"]
    pe_oi   = oc_data["pe_oi"]
    ce_vol  = oc_data["ce_vol"]
    pe_vol  = oc_data["pe_vol"]
    oc_map  = oc_data.get("oc_map", {})
    expiry  = oc_data.get("expiry")

    # ---------- INDIA VIX ----------
    vix = fetch_india_vix() if symbol in ("NIFTY", "BANKNIFTY") else None
    vix_bias = "BULLISH" if vix and vix < 13 else "BEARISH" if vix and vix > 18 else "NEUTRAL" if vix else "N/A"

    # ---------- OI CHANGE ----------
    prev = _LAST_OI_SNAPSHOT.get(symbol)
    ce_change = pe_change = None

    if prev:
        ce_change = ce_oi - prev["ce"]
        pe_change = pe_oi - prev["pe"]

    _LAST_OI_SNAPSHOT[symbol] = {"ce": ce_oi, "pe": pe_oi}

    # ---------- DIRECTION ----------
    bull = bear = 0
    bull += 2 if pcr > 1.1 else 0
    bear += 2 if pcr < 0.9 else 0
    bull += 2 if pe_oi > ce_oi else 0
    bear += 2 if ce_oi > pe_oi else 0
    bull += 1 if pe_vol > ce_vol else 0
    bear += 1 if ce_vol > pe_vol else 0

    if bull > bear:
        direction, option_side, emoji = "BULLISH", "CE", "🟢"
    elif bear > bull:
        direction, option_side, emoji = "BEARISH", "PE", "🔴"
    else:
        return "NO TRADE - Data mixed, direction unclear"

    # ---------- LEVELS ----------
    base = 80 if symbol == "BANKNIFTY" else 40

    if direction == "BULLISH":
        entry_low, entry_high = round(spot - base), round(spot - base / 2)
        sl = round(spot - base * 1.5)
        t1, t2, t3 = round(spot + base), round(spot + base * 2), round(spot + base * 3)
    else:
        entry_low, entry_high = round(spot + base / 2), round(spot + base)
        sl = round(spot + base * 1.5)
        t1, t2, t3 = round(spot - base), round(spot - base * 2), round(spot - base * 3)

    strike, premium = get_atm_premium(symbol, spot, option_side, oc_map, expiry)

    # ---------- TEXT ----------
    text = f"""
💎 KETAN PRO - Institutional Smart Entry
{symbol} PRO SETUP

══════ MARKET DATA ══════
Spot: {spot:.2f}
PCR: {pcr:.2f}
CE OI: {format_lakh_crore(ce_oi)} | PE OI: {format_lakh_crore(pe_oi)}
Vol CE: {format_lakh_crore(ce_vol)} | Vol PE: {format_lakh_crore(pe_vol)}
India VIX: {vix if vix else 'N/A'} ({vix_bias})

══════ DIRECTION ══════
{emoji} {direction} ({option_side} BUY)

══════ ENTRY ZONE ══════
Entry: {entry_low} – {entry_high}
SL: {sl}

══════ TARGETS ══════
T1: {t1}
T2: {t2}
T3: {t3}

══════ OPTION EXECUTION ══════
Option: {strike} {option_side} BUY
"""

    if premium:
        text += f"""Buy Price: ₹{round(premium*0.9)} – ₹{round(premium*1.05)}
Stop Loss: ₹{round(premium*0.75)}
Targets: ₹{round(premium*1.25)} | ₹{round(premium*1.6)} | ₹{round(premium*2)}
"""
    else:
        text += "Live premium abhi available nahi\n"

    # ---------- OI CHANGE ----------
    text += "\n══════ OI CHANGE (Since Last Check) ══════\n"

    if ce_change is None:
        text += "No previous data\nWaiting for next snapshot...\n"
        text += "\n══════ BUILD-UP STATUS ══════\nStatus: Waiting for comparison\n"
    else:
        text += (
            f"CALL OI Change : {format_lakh_crore(ce_change)}\n"
            f"PUT  OI Change : {format_lakh_crore(pe_change)}\n\n"
        )

        if ce_change > pe_change:
            text += (
                "Dominant Change : CALL SIDE\n\n"
                "══════ BUILD-UP STATUS ══════\n"
                "Selling Side Build-up : STRONG 🔥\n"
                "Buying  Side Build-up : MODERATE\n"
            )
        else:
            text += (
                "Dominant Change : PUT SIDE\n\n"
                "══════ BUILD-UP STATUS ══════\n"
                "Buying  Side Build-up : STRONG 🔥\n"
                "Selling Side Build-up : WEAK\n"
            )

    text += "\n👑 Owner: 😈 #KETAN 😈"
    return text

# ======================================================
# PART 7 - SMART ENTRY LOGIC
# ======================================================

def generate_smart_entry(symbol: str, user_id=0):
    """
    Smart Entry Logic:
    - Direction via PCR + OI
    - Liquidity grab + pullback
    - Auto Trade Type: SCALP / SWING-INTRADAY
    """

    # ---------- DATA FETCH ----------
    oc_data = fetch_option_chain_extended(symbol)

    spot   = oc_data["spot"]
    pcr    = oc_data["pcr"]
    ce_oi  = oc_data["ce_oi"]
    pe_oi  = oc_data["pe_oi"]

    vix = fetch_india_vix()

    # ---------- DIRECTION FILTER ----------
    if pcr > 1 and pe_oi > ce_oi:
        bias = "BULLISH"
        side_emoji = "🟢"
    elif pcr < 1 and ce_oi > pe_oi:
        bias = "BEARISH"
        side_emoji = "🔴"
    else:
        return (
            f"🧠 SMART ENTRY - {symbol}\n"
            "──────────────────────────\n"
            f"Spot: {round(spot,2)}\n"
            f"PCR: {round(pcr,2)}\n"
            "──────────────────────────\n"
            "⚠️ NO TRADE\n\n"
            "Reason:\n"
            "• PCR & OI se clear direction nahi\n"
            "• Liquidity structure unclear\n"
            "⛔ Entry avoid karo"
        )

    # ---------- SYMBOL BASED PARAMS ----------
    if symbol == "BANKNIFTY":
        pullback = 80
        sl_gap = 120
        t1_gap = 60
        t2_gap = 120
    elif symbol == "SENSEX":
        pullback = 100
        sl_gap = 150
        t1_gap = 80
        t2_gap = 160
    else:  # NIFTY
        pullback = 40
        sl_gap = 60
        t1_gap = 30
        t2_gap = 70

    # ---------- TRADE TYPE DETECTION ----------
    if pullback <= 40 and sl_gap <= 60:
        trade_type = "⚡ SCALP"
    else:
        trade_type = "📈 SWING / INTRADAY"

    # ---------- ENTRY / SL / TARGET ----------
    if bias == "BULLISH":
        entry_low = round(spot - pullback)
        entry_high = round(spot - pullback / 2)
        sl = round(spot - sl_gap)
        t1 = round(spot + t1_gap)
        t2 = round(spot + t2_gap)
        invalidation = "Recent swing low break"
    else:
        entry_low = round(spot + pullback / 2)
        entry_high = round(spot + pullback)
        sl = round(spot + sl_gap)
        t1 = round(spot - t1_gap)
        t2 = round(spot - t2_gap)
        invalidation = "Recent swing high break"

    # ---------- MESSAGE BUILD ----------
    text = (
        f"🧠 SMART ENTRY - {symbol}\n"
        "──────────────────────────\n"
        f"Spot: {round(spot,2)}\n"
        f"PCR: {round(pcr,2)}\n"
        f"CE OI: {int(ce_oi)} | PE OI: {int(pe_oi)}\n"
    )

    if vix is not None:
        text += f"India VIX: {round(vix,2)}\n"

    text += (
        "──────────────────────────\n"
        f"{side_emoji} Bias: {bias}\n"
        f"🕒 Trade Type: {trade_type}\n\n"
        "ENTRY ZONE:\n"
        f"Entry: {entry_low} – {entry_high}\n"
        f"SL: {sl}\n"
        f"T1: {t1}\n"
        f"T2: {t2}\n\n"
        "🧠 Entry Logic:\n"
        "• OI + PCR se higher timeframe bias\n"
        "• Liquidity grab ke baad pullback entry\n"
        "• Weak retracement = continuation\n\n"
        f"❌ Invalidation: {invalidation}"
    )

    return text


# ======================================================
# ======================================================
# PART 6 - ACCESS CHECK + HANDLERS + UI (UPDATED)
# ======================================================

import requests
from datetime import date
import time
import random
import string

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ======================================================
# TERMUX / MODERN TELEGRAM COMPATIBILITY LAYER
# ======================================================
class SyncBotAdapter:
    """
    Keeps the existing 5k+ line synchronous bot code working with
    modern python-telegram-bot (v20+ / Python 3.13).
    """
    def __init__(self, bot, loop):
        self._bot = bot
        self._loop = loop

    def _run(self, coro):
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        # Handler is already running on Telegram's event loop.
        # Schedule the coroutine and return immediately.
        if running is self._loop:
            return asyncio.create_task(coro)

        # Flask/OI-monitor/background threads.
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    def send_message(self, *args, **kwargs):
        return self._run(self._bot.send_message(*args, **kwargs))

    def delete_message(self, *args, **kwargs):
        return self._run(self._bot.delete_message(*args, **kwargs))


class SyncCallbackQueryAdapter:
    def __init__(self, query, bot_adapter):
        self._query = query
        self._bot_adapter = bot_adapter

    def answer(self, *args, **kwargs):
        return self._bot_adapter._run(self._query.answer(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._query, name)


class SyncUpdateAdapter:
    def __init__(self, update, bot_adapter):
        self._update = update
        self._bot_adapter = bot_adapter

    @property
    def callback_query(self):
        q = self._update.callback_query
        return SyncCallbackQueryAdapter(q, self._bot_adapter) if q else None

    def __getattr__(self, name):
        return getattr(self._update, name)


class SyncContextAdapter:
    def __init__(self, context, bot_adapter):
        self._context = context
        self.bot = bot_adapter

    def __getattr__(self, name):
        return getattr(self._context, name)


def make_sync_callback(handler, bot_adapter):
    async def wrapper(update, context):
        sync_update = SyncUpdateAdapter(update, bot_adapter)
        sync_context = SyncContextAdapter(context, bot_adapter)
        return handler(sync_update, sync_context)
    return wrapper

# ======================================================
# BOARD / JIMMY API CONFIG
# ======================================================
JIMMY_API_KEY = os.getenv("JIMMY_API_KEY", "").strip()

# ======================================================
# TEMP ACCESS STORAGE
# ======================================================
access_keys    = {}          # key_string -> seconds
temporary_users = {}         # user_id -> expiry_timestamp
waiting_for_key = set()
waiting_for_token = set()

# ✅ NEW: Blocked users storage
blocked_users = set()        # user_id set - permanently blocked

# 🔥 PER MESSAGE SIGNAL STORAGE
owner_signals = {}           # signal_id -> text

# ======================================================
# ✅ WELCOME MESSAGE (Owner change kar sakta hai)
# ======================================================
welcome_message = "Namaste! Yeh Ketan AI Bot hai.\nAccess ke liye ek plan choose karo."

# Owner ka Telegram username (contact button mein dikhega)
OWNER_USERNAME = "https://t.me/KETAN_AI"   # apna username yahan daalo

# ✅ Waiting state for welcome message update
waiting_for_welcome = set()

# ✅ Waiting state: owner kisko key bhejne wala hai
# { owner_user_id -> target_user_id }
pending_key_send = {}

# ======================================================
# ✅ PLANS LIST (price + days)
# ======================================================
PLANS = [
    {"label": "1 Day",   "days": 1,  "price": 99},
    {"label": "7 Days",  "days": 7,  "price": 499},
    {"label": "15 Days", "days": 15, "price": 799},
    {"label": "30 Days", "days": 30, "price": 1499},
]

# ======================================================
# ✅ KEY GENERATION HELPER
# Ek function jo kisi bhi din ka key banata hai
# ======================================================
def generate_key_for_days(days: int) -> str:
    """
    Given days (1-30), ek random key banao aur
    access_keys dict mein store karo (seconds mein).
    """
    key = "".join(random.choices(string.ascii_letters + string.digits, k=120))
    access_keys[key] = days * 86400   # days → seconds
    return key


# ======================================================
# ACCESS CHECK
# ======================================================
def is_allowed(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    # ✅ blocked user ko access nahi milega
    if user_id in blocked_users:
        return False
    expiry = temporary_users.get(user_id)
    if expiry and time.time() < expiry:
        return True
    return False


# ======================================================
# ======================================================
# ✅ OWNER PANEL - Sab kuch ek hi message mein
# Trading buttons + Key generation + User management
# ======================================================
def send_owner_panel(chat_id, context):
    """
    Owner ka ALL-IN-ONE panel:
    - Stats (active/blocked)
    - Trading buttons (BASIC / PRO / SMART)
    - Key generation (1-30 days)
    - User management (list, token)
    """
    now = time.time()

    active_count  = sum(1 for uid, exp in temporary_users.items()
                        if exp > now and uid not in blocked_users)
    blocked_count = len(blocked_users)

    header = (
        f"*TRADER KETAN AI x INSTITUTIONAL EXECUTION MODEL*\n"
        f"*Owner: 😈 #KETAN 😈*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Active Users  : *{active_count}*\n"
        f"🚫 Blocked Users : *{blocked_count}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *BASIC MODE*  |  ⚡ *PRO MODE*  |  🧠 *SMART MODE*\n\n"
        f"🔑 *Key Generate:*"
    )

    # ---- TRADING ROWS ----
    trade_row1 = [
        InlineKeyboardButton("📊 NIFTY",     callback_data="old:NIFTY"),
        InlineKeyboardButton("📊 BANKNIFTY", callback_data="old:BANKNIFTY"),
        InlineKeyboardButton("📊 SENSEX",    callback_data="old:SENSEX"),
    ]
    trade_row2 = [
        InlineKeyboardButton("⚡ NIFTY PRO",     callback_data="pro:NIFTY"),
        InlineKeyboardButton("⚡ BANKNIFTY PRO", callback_data="pro:BANKNIFTY"),
        InlineKeyboardButton("⚡ SENSEX PRO",    callback_data="pro:SENSEX"),
    ]
    trade_row3 = [
        InlineKeyboardButton("🧠 Smart NIFTY", callback_data="inst:NIFTY"),
        InlineKeyboardButton("🧠 Smart BN",    callback_data="inst:BANKNIFTY"),
        InlineKeyboardButton("🧠 Smart SX",    callback_data="inst:SENSEX"),
    ]

    # ---- DIVIDER (dummy button as label) ----
    divider = [InlineKeyboardButton("━━━ 🔑 KEY GENERATE ━━━", callback_data="noop")]

    # ---- KEY GENERATION ROWS ----
    key_row1 = [
        InlineKeyboardButton("1d",  callback_data="gen_days:1"),
        InlineKeyboardButton("2d",  callback_data="gen_days:2"),
        InlineKeyboardButton("3d",  callback_data="gen_days:3"),
        InlineKeyboardButton("5d",  callback_data="gen_days:5"),
        InlineKeyboardButton("7d",  callback_data="gen_days:7"),
    ]
    key_row2 = [
        InlineKeyboardButton("10d", callback_data="gen_days:10"),
        InlineKeyboardButton("15d", callback_data="gen_days:15"),
        InlineKeyboardButton("20d", callback_data="gen_days:20"),
        InlineKeyboardButton("25d", callback_data="gen_days:25"),
        InlineKeyboardButton("30d", callback_data="gen_days:30"),
    ]

    # ---- DIVIDER 2 ----
    divider2 = [InlineKeyboardButton("━━━ ⚙️ MANAGEMENT ━━━", callback_data="noop")]

    # ---- MANAGEMENT ROW ----
    mgmt_row = [
        InlineKeyboardButton("🔐 Upload Token", callback_data="upload_token"),
        InlineKeyboardButton("👥 User List",    callback_data="user_list:0"),
    ]
    mgmt_row2 = [
        InlineKeyboardButton("✏️ Welcome Msg",  callback_data="edit_welcome"),
    ]

    # ---- MY EXPIRY ----
    expiry_row = [
        InlineKeyboardButton("⏳ My Expiry", callback_data="my_expiry"),
    ]

    keyboard = [
        trade_row1,
        trade_row2,
        trade_row3,
        divider,
        key_row1,
        key_row2,
        divider2,
        mgmt_row,
        mgmt_row2,
        expiry_row,
    ]

    context.bot.send_message(
        chat_id,
        header,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ======================================================
# /start
# ======================================================
def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # ✅ Owner ko sirf owner panel - ek hi message
    if user_id == OWNER_ID:
        send_owner_panel(chat_id, context)
        return

    # Normal user - access check
    if is_allowed(user_id):
        send_main_menu(chat_id, context)
        return

    # Blocked user
    if user_id in blocked_users:
        context.bot.send_message(
            chat_id,
            "🚫 Aapka access block kar diya gaya hai.\nOwner se contact karo."
        )
        return

    # No access - New user ko plan menu dikhao
    send_plan_menu(chat_id, context)


# ======================================================
# PLAN MENU - New user ko dikhta hai
# ======================================================
def send_plan_menu(chat_id, context):
    text = (
        f"{welcome_message}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💎 KETAN AI - PLANS\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🥉 1 Day    -  Rs.99\n"
        "🥈 7 Days   -  Rs.499\n"
        "🥈 15 Days  -  Rs.799\n"
        "🥇 30 Days  -  Rs.1499\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Plan lene ke liye niche button dabao 👇"
    )

    keyboard = []
    emojis = ["🥉", "🥈", "🥈", "🥇"]
    for i, plan in enumerate(PLANS):
        keyboard.append([
            InlineKeyboardButton(
                f"{emojis[i]} {plan['label']} - Rs.{plan['price']}",
                callback_data=f"buy_plan:{plan['days']}:{plan['price']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton("📞 Owner se Contact karo", url=OWNER_USERNAME)
    ])
    keyboard.append([
        InlineKeyboardButton("🔑 Mere paas Key hai", callback_data="enter_key")
    ])

    context.bot.send_message(
        chat_id,
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ======================================================
# MAIN MENU
# ======================================================
def send_main_menu(chat_id, context):

    text = (
        "TRADER KETAN AI × INSTITUTIONAL EXECUTION MODEL\n\n"
        "📊 BASIC MODE\n"
        "⚡ PRO MODE\n"
        "🧠 SMART MODE\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("📊 NIFTY",       callback_data="old:NIFTY"),
            InlineKeyboardButton("📊 BANKNIFTY",   callback_data="old:BANKNIFTY"),
            InlineKeyboardButton("📊 SENSEX",      callback_data="old:SENSEX"),
        ],
        [
            InlineKeyboardButton("⚡ NIFTY PRO",   callback_data="pro:NIFTY"),
            InlineKeyboardButton("⚡ BANKNIFTY PRO", callback_data="pro:BANKNIFTY"),
            InlineKeyboardButton("⚡ SENSEX PRO",  callback_data="pro:SENSEX"),
        ],
        [
            InlineKeyboardButton("🧠 Smart NIFTY", callback_data="inst:NIFTY"),
            InlineKeyboardButton("🧠 Smart BN",    callback_data="inst:BANKNIFTY"),
            InlineKeyboardButton("🧠 Smart SX",    callback_data="inst:SENSEX"),
        ],
        [
            InlineKeyboardButton("⏳ My Expiry",   callback_data="my_expiry")
        ]
    ]

    context.bot.send_message(
        chat_id,
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ======================================================
# ✅ USER LIST BUILDER (with block/unblock buttons)
# PAGE_SIZE = 5 users per page
# ======================================================
PAGE_SIZE = 5

def send_user_list(chat_id, context, page: int = 0):
    """
    Owner ke liye paginated user list:
    - Active users + blocked users dono dikhata hai
    - Har user ke saath Block/Unblock button
    """
    now = time.time()

    # Saare known users = temporary_users + blocked_users
    all_user_ids = list(set(list(temporary_users.keys()) + list(blocked_users)))

    if not all_user_ids:
        context.bot.send_message(chat_id, "📭 Koi user abhi tak nahi hai.")
        return

    total = len(all_user_ids)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))

    start_i = page * PAGE_SIZE
    page_users = all_user_ids[start_i: start_i + PAGE_SIZE]

    # ---- Header ----
    active_count  = sum(1 for uid in all_user_ids
                        if uid not in blocked_users
                        and temporary_users.get(uid, 0) > now)
    blocked_count = len(blocked_users)

    msg = (
        f"👥 *User List* (Page {page+1}/{total_pages})\n"
        f"✅ Active: {active_count}  🚫 Blocked: {blocked_count}\n"
        "──────────────────────\n"
    )

    keyboard = []

    for uid in page_users:
        exp = temporary_users.get(uid, 0)
        is_blocked = uid in blocked_users

        if is_blocked:
            status = "🚫 BLOCKED"
            time_str = ""
        elif exp > now:
            rem = int(exp - now)
            h, m = rem // 3600, (rem % 3600) // 60
            status = "✅ ACTIVE"
            time_str = f" ({h}h {m}m left)"
        else:
            status = "⏰ EXPIRED"
            time_str = ""

        msg += f"\n👤 `{uid}`\n{status}{time_str}\n"

        # Block / Unblock button
        if is_blocked:
            btn = InlineKeyboardButton(
                f"🔓 Unblock {uid}",
                callback_data=f"unblock_user:{uid}"
            )
        else:
            btn = InlineKeyboardButton(
                f"🔴 Block {uid}",
                callback_data=f"block_user:{uid}"
            )
        keyboard.append([btn])

    # ---- Pagination ----
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"user_list:{page-1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"user_list:{page+1}"))
    if nav_row:
        keyboard.append(nav_row)

    # Refresh + Back
    keyboard.append([
        InlineKeyboardButton("🔄 Refresh", callback_data=f"user_list:{page}"),
    ])

    context.bot.send_message(
        chat_id,
        msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ======================================================
# BUTTON CALLBACK
# ======================================================
def handle_button_callback(update: Update, context: CallbackContext):
    if not update or not update.callback_query:
        return


    global ACCESS_TOKEN

    query = update.callback_query
    data  = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    query.answer()

    # ---------- NOOP (divider buttons) ----------
    if data == "noop":
        return

    # ✅ USER PLAN PURCHASE REQUEST
    # callback: buy_plan:<days>:<price>
    if data.startswith("buy_plan:"):
        parts = data.split(":")
        days  = int(parts[1])
        price = int(parts[2])

        user = query.from_user
        uname = f"@{user.username}" if user.username else "No username"
        name  = user.full_name or "No name"

        # User ko confirmation
        context.bot.send_message(
            chat_id,
            f"✅ Aapne plan choose kiya:\n\n"
            f"📦 Plan  : {days} Day(s)\n"
            f"💰 Price : Rs.{price}\n\n"
            f"⏳ Owner ko notify kar diya gaya hai.\n"
            f"Woh jald aapse contact karenge!\n\n"
            f"Ya seedha contact karo 👇",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📞 Owner se Contact karo", url=OWNER_USERNAME)],
                [InlineKeyboardButton("🔑 Mere paas Key hai", callback_data="enter_key")]
            ])
        )

        # Owner ko TURANT notification
        context.bot.send_message(
            OWNER_ID,
            f"🔔 *NEW PLAN REQUEST!*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👤 User ID  : `{user.id}`\n"
            f"👤 Username : {uname}\n"
            f"📱 Name     : {name}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Plan     : {days} Day(s)\n"
            f"💰 Price    : Rs.{price}\n"
            f"━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"✅ {days} Din Ki Key Bhejo Is User Ko",
                    callback_data=f"sendkey:{user.id}:{days}"
                )],
                [InlineKeyboardButton("❌ Ignore", callback_data="noop")]
            ])
        )
        return

    # ✅ OWNER: Specific user ko key bhejo
    # callback: sendkey:<target_uid>:<days>
    if data.startswith("sendkey:") and user_id == OWNER_ID:
        parts      = data.split(":")
        target_uid = int(parts[1])
        days       = int(parts[2])

        key = generate_key_for_days(days)

        # User ko key bhejo
        try:
            context.bot.send_message(
                target_uid,
                f"🎉 *Aapka plan activate ho gaya!*\n\n"
                f"📦 Plan   : {days} Day(s)\n"
                f"💰 Price  : ---\n\n"
                f"🔑 Aapki Key:\n`{key}`\n\n"
                f"👉 /start karo aur key enter karo!",
                parse_mode="Markdown"
            )
            context.bot.send_message(
                chat_id,
                f"✅ Key successfully bhej di!\n"
                f"👤 User: `{target_uid}`\n"
                f"📦 Plan: {days} Day(s)\n"
                f"🔑 Key: `{key}`",
                parse_mode="Markdown"
            )
        except Exception as e:
            context.bot.send_message(
                chat_id,
                f"❌ Key nahi bheji ja ski.\nError: {e}"
            )
        return

    # ✅ OWNER: Welcome message change button
    if data == "edit_welcome" and user_id == OWNER_ID:
        waiting_for_welcome.add(user_id)
        context.bot.send_message(
            chat_id,
            f"✏️ *Current Welcome Message:*\n\n"
            f"{welcome_message}\n\n"
            f"Nayi welcome message type karke bhejo:",
            parse_mode="Markdown"
        )
        return

    # ---------- USER ENTER KEY ----------
    if data == "enter_key":
        waiting_for_key.add(user_id)
        context.bot.send_message(chat_id, "🔐 Access key paste karo:")
        return

    # ---------- OWNER - UPLOAD TOKEN ----------
    if data == "upload_token" and user_id == OWNER_ID:
        waiting_for_token.add(user_id)
        context.bot.send_message(chat_id, "🔑 Dhan Access Token paste karo")
        return

    # ✅ OWNER - MULTI-DAY KEY GENERATION
    # callback: gen_days:<days>
    if data.startswith("gen_days:") and user_id == OWNER_ID:
        days = int(data.split(":")[1])
        key  = generate_key_for_days(days)
        context.bot.send_message(
            chat_id,
            f"🔑 *{days}-Day Access Key*\n\n`{key}`\n\n"
            f"⏳ Valid for: *{days} day(s)*",
            parse_mode="Markdown"
        )
        return

    # ✅ OWNER - USER LIST (paginated)
    # callback: user_list:<page>
    if data.startswith("user_list:") and user_id == OWNER_ID:
        page = int(data.split(":")[1])
        send_user_list(chat_id, context, page)
        return

    # ✅ OWNER - BLOCK USER
    # callback: block_user:<uid>
    if data.startswith("block_user:") and user_id == OWNER_ID:
        target_uid = int(data.split(":")[1])
        blocked_users.add(target_uid)
        # Uska active session bhi remove karo
        temporary_users.pop(target_uid, None)
        save_data()
        context.bot.send_message(
            chat_id,
            f"🚫 User `{target_uid}` ko block kar diya gaya.\n"
            f"Ab woh bot use nahi kar sakta.",
            parse_mode="Markdown"
        )
        # ✅ Blocked user ko bhi notify karo
        try:
            context.bot.send_message(
                target_uid,
                "🚫 Aapka access block kar diya gaya hai.\nOwner se contact karo."
            )
        except Exception:
            pass
        return

    # ✅ OWNER - UNBLOCK USER
    # callback: unblock_user:<uid>
    if data.startswith("unblock_user:") and user_id == OWNER_ID:
        target_uid = int(data.split(":")[1])
        blocked_users.discard(target_uid)
        save_data()
        context.bot.send_message(
            chat_id,
            f"✅ User `{target_uid}` ko unblock kar diya gaya.\n"
            f"Ab woh nayi key se access le sakta hai.",
            parse_mode="Markdown"
        )
        # ✅ Unblocked user ko bhi notify karo
        try:
            context.bot.send_message(
                target_uid,
                "✅ Aapka block hat gaya hai!\n"
                "Nayi access key lekar /start karo."
            )
        except Exception:
            pass
        return

    # ---------- ACTIVE USERS (legacy - ab user_list use karo) ----------
    if data == "active_users" and user_id == OWNER_ID:
        send_user_list(chat_id, context, 0)
        return

    # ---------- MY EXPIRY ----------
    if data == "my_expiry":
        exp = temporary_users.get(user_id)
        if not exp:
            context.bot.send_message(chat_id, "❌ No active access")
            return
        rem = int(exp - time.time())
        if rem <= 0:
            context.bot.send_message(chat_id, "⏰ Aapka access expire ho gaya hai.")
            return
        days_rem  = rem // 86400
        hours_rem = (rem % 86400) // 3600
        mins_rem  = (rem % 3600)  // 60
        secs_rem  = rem % 60
        context.bot.send_message(
            chat_id,
            f"⏳ *Remaining Time:*\n"
            f"{days_rem}d {hours_rem}h {mins_rem}m {secs_rem}s",
            parse_mode="Markdown"
        )
        return

    # ---------- BROADCAST ----------
    if data.startswith("broadcast:") and user_id == OWNER_ID:
        signal_id   = data.split(":", 1)[1]
        signal_text = owner_signals.get(signal_id)

        if not signal_text:
            context.bot.send_message(chat_id, "❌ Signal expired")
            return

        sent = 0
        for uid, exp in temporary_users.items():
            if time.time() < exp and uid not in blocked_users:
                try:
                    context.bot.send_message(
                        uid,
                        f"🔥 OWNER SHARED TRADE\n\n{signal_text}"
                    )
                    sent += 1
                except:
                    pass

        context.bot.send_message(chat_id, f"✅ Sent to {sent} users")
        return

    # ---------- ACCESS CHECK ----------
    if not is_allowed(user_id):
        if user_id in blocked_users:
            context.bot.send_message(chat_id, "🚫 Aapka access block hai.")
        else:
            context.bot.send_message(chat_id, "❌ Access nahi mila hai.")
        return

    # ================= BASIC =================
    if data.startswith("old:"):
        symbol = data.split(":", 1)[1]

        try:
            oc_data = fetch_option_chain_extended(symbol)
            text = generate_single_swing_setup(
                symbol,
                oc_data["spot"],
                oc_data["pcr"],
                oc_data["ce_oi"],
                oc_data["pe_oi"],
                oc_data["oc_map"]
            )
        except Exception:
            if symbol == "SENSEX":
                context.bot.send_message(
                    chat_id,
                    "⚠️ SENSEX option data abhi Dhan API se stable nahi aa raha.\n\n"
                    "✔ NIFTY / BANKNIFTY fully live hai\n"
                    "⏳ Sensex ke liye smart / spot-based mode use karo"
                )
                return
            else:
                raise

        refresh_btn = InlineKeyboardButton(
            f"🔁 Refresh {symbol}", callback_data=f"old:{symbol}"
        )

        if user_id == OWNER_ID:
            signal_id = str(time.time())
            owner_signals[signal_id] = text
            kb = [
                [InlineKeyboardButton("📤 Send To All Users",
                    callback_data=f"broadcast:{signal_id}")],
                [refresh_btn]
            ]
        else:
            kb = [[refresh_btn]]

        context.bot.send_message(
            chat_id,
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    # ================= PRO =================
    if data.startswith("pro:"):
        symbol = data.split(":", 1)[1]

        try:
            oc_data = fetch_option_chain_extended(symbol)
            text    = generate_pro_setup(symbol, oc_data)
        except Exception:
            if symbol == "SENSEX":
                context.bot.send_message(
                    chat_id,
                    "⚠️ SENSEX PRO mode temporarily unavailable.\n\n"
                    "Reason: Dhan option chain instability\n"
                    "✔ Use NIFTY / BANKNIFTY PRO"
                )
                return
            else:
                raise

        refresh_btn = InlineKeyboardButton(
            f"🔁 Refresh {symbol} PRO", callback_data=f"pro:{symbol}"
        )

        if user_id == OWNER_ID:
            signal_id = str(time.time())
            owner_signals[signal_id] = text
            kb = [
                [InlineKeyboardButton("📤 Send To All Users",
                    callback_data=f"broadcast:{signal_id}")],
                [refresh_btn]
            ]
        else:
            kb = [[refresh_btn]]

        context.bot.send_message(
            chat_id,
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    # ================= SMART =================
    if data.startswith("inst:"):
        symbol = data.split(":", 1)[1]

        try:
            text = generate_smart_entry(symbol)
        except Exception:
            context.bot.send_message(
                chat_id,
                "⚠️ Smart engine temporary issue. Try again."
            )
            return

        refresh_btn = InlineKeyboardButton(
            f"🔁 Refresh Smart {symbol}",
            callback_data=f"inst:{symbol}"
        )

        if user_id == OWNER_ID:
            signal_id = str(time.time())
            owner_signals[signal_id] = text
            kb = [
                [InlineKeyboardButton("📤 Send To All Users",
                    callback_data=f"broadcast:{signal_id}")],
                [refresh_btn]
            ]
        else:
            kb = [[refresh_btn]]

        context.bot.send_message(
            chat_id,
            text,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return


# ======================================================
# TEXT HANDLER
# ======================================================
def handle_text_message(update: Update, context: CallbackContext):
    if not update or not update.message or not update.message.text:
        return

    global ACCESS_TOKEN

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text    = update.message.text.strip()

    # ---------- OWNER: Token upload ----------
    if user_id in waiting_for_token and user_id == OWNER_ID:
        waiting_for_token.discard(user_id)
        ACCESS_TOKEN = text
        context.bot.send_message(chat_id, "✅ Access Token updated")
        return

    # ---------- OWNER: Welcome message update ----------
    if user_id in waiting_for_welcome and user_id == OWNER_ID:
        global welcome_message
        waiting_for_welcome.discard(user_id)
        welcome_message = text
        context.bot.send_message(
            chat_id,
            f"✅ *Welcome message update ho gaya!*\n\n"
            f"New message:\n{welcome_message}",
            parse_mode="Markdown"
        )
        return

    # ---------- USER: Key entry ----------
    if user_id in waiting_for_key:
        waiting_for_key.discard(user_id)

        # ✅ Blocked user key daalega toh bhi access nahi milega
        if user_id in blocked_users:
            context.bot.send_message(
                chat_id,
                "🚫 Aapka account block hai. Key accept nahi hogi."
            )
            return

        if text not in access_keys:
            context.bot.send_message(chat_id, "❌ Invalid key")
            return

        # Key valid hai - access do
        temporary_users[user_id] = time.time() + access_keys[text]
        seconds = access_keys[text]
        days    = seconds // 86400
        del access_keys[text]
        save_data()

        context.bot.send_message(
            chat_id,
            f"✅ *Access activated!*\n"
            f"⏳ Duration: *{days} day(s)*\n\n"
            f"👉 /start karo",
            parse_mode="Markdown"
        )
        return



DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_data.json")
web_sessions = {}

def save_data():
    try:
        data = {
            "temporary_users": {str(uid): exp for uid, exp in temporary_users.items() if exp > time.time()},
            "blocked_users": list(blocked_users),
        }
        with open(DATA_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"⚠️ Data save error: {e}")

def load_data():
    global temporary_users, blocked_users
    try:
        if not os.path.exists(DATA_FILE):
            pass
        else:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            now = time.time()
            for uid_str, exp in data.get("temporary_users", {}).items():
                if exp > now:
                    temporary_users[int(uid_str)] = exp
            for uid in data.get("blocked_users", []):
                blocked_users.add(int(uid))
    except Exception as e:
        print(f"⚠️ Data load error: {e}")
    # Always ensure owner has access
    temporary_users[OWNER_ID] = time.time() + (365 * 86400)
    print(f"✅ Data loaded: {len(temporary_users)} users, {len(blocked_users)} blocked")



# ======================================================
# OWNER DASHBOARD HTML (Separate page)
# ======================================================
_ticker_prev = {}
oi_push_alerts = []

OWNER_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>KETAN AI &#8212; Owner Panel</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;}
:root{--bg:#03050a;--orange:#ff6b00;--red:#ff2d55;--green:#00ff88;--blue:#00d4ff;--text:#e8f4ff;--muted:rgba(255,255,255,0.3);--border:rgba(255,255,255,0.07);}
body{background:var(--bg);color:var(--text);font-family:'Rajdhani',sans-serif;min-height:100vh;}
.bg-grid{position:fixed;inset:0;z-index:0;pointer-events:none;background-image:linear-gradient(rgba(255,107,0,0.03) 1px,transparent 1px),linear-gradient(90deg,rgba(255,107,0,0.03) 1px,transparent 1px);background-size:40px 40px;}

/* LOGIN */
.login-wrap{display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px;position:relative;z-index:1;}
.login-card{background:rgba(255,255,255,0.02);border:1px solid rgba(255,107,0,0.2);border-radius:20px;padding:36px 26px;width:100%;max-width:360px;text-align:center;position:relative;}
.login-card::before{content:'';position:absolute;top:0;left:20%;right:20%;height:1px;background:linear-gradient(90deg,transparent,var(--orange),transparent);box-shadow:0 0 8px var(--orange);}
.login-icon{font-size:3rem;margin-bottom:8px;}
.login-title{font-family:'Orbitron',monospace;font-size:1rem;font-weight:700;color:var(--orange);margin-bottom:4px;letter-spacing:2px;}
.login-sub{font-size:0.72rem;color:var(--muted);margin-bottom:22px;}
.login-inp{width:100%;background:rgba(0,0,0,0.3);border:1px solid rgba(255,107,0,0.2);border-radius:12px;padding:14px;color:var(--text);font-size:1rem;outline:none;text-align:center;letter-spacing:2px;margin-bottom:12px;font-family:'Rajdhani',sans-serif;}
.login-inp:focus{border-color:rgba(255,107,0,0.5);}
.login-btn{width:100%;background:linear-gradient(135deg,var(--orange),#cc5500);color:#000;border:none;border-radius:12px;padding:14px;font-size:0.95rem;font-weight:700;cursor:pointer;font-family:'Rajdhani',sans-serif;letter-spacing:1px;margin-bottom:10px;}
.login-btn:disabled{opacity:0.6;cursor:not-allowed;}
.login-err{display:none;background:rgba(255,45,85,0.1);border:1px solid rgba(255,45,85,0.3);border-radius:10px;padding:10px;color:var(--red);font-size:0.78rem;margin-top:8px;}
.user-link{margin-top:14px;font-size:0.7rem;color:var(--muted);}
.user-link a{color:var(--blue);text-decoration:none;}

/* PANEL */
.panel{display:none;position:relative;z-index:1;padding:12px;max-width:480px;margin:0 auto;}

/* Topbar */
.op-topbar{position:sticky;top:0;z-index:100;background:rgba(3,5,10,0.97);backdrop-filter:blur(20px);border-bottom:1px solid rgba(255,107,0,0.1);padding:42px 14px 10px;display:flex;justify-content:space-between;align-items:center;margin:-12px -12px 12px;}
.op-logo{font-family:'Orbitron',monospace;font-size:0.85rem;font-weight:700;color:var(--orange);letter-spacing:1px;}
.op-logout{background:transparent;border:1px solid rgba(255,45,85,0.25);border-radius:8px;color:var(--red);padding:4px 12px;font-size:0.68rem;cursor:pointer;font-family:'Rajdhani',sans-serif;}

/* Sections */
.sec{background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:14px;padding:14px;margin-bottom:10px;}
.sec-title{font-size:0.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:2px;margin-bottom:10px;font-weight:700;display:flex;justify-content:space-between;align-items:center;}

/* Stats */
.stats-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;}
.stat-box{background:rgba(0,0,0,0.2);border-radius:10px;padding:10px 6px;text-align:center;}
.stat-num{font-family:'Orbitron',monospace;font-size:1.4rem;font-weight:700;color:var(--orange);}
.stat-lbl{font-size:0.52rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-top:2px;}

/* Keys */
.key-btns{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;}
.kbtn{padding:6px 12px;border:1px solid rgba(255,107,0,0.3);border-radius:20px;background:rgba(255,107,0,0.07);color:var(--orange);font-size:0.7rem;font-weight:700;cursor:pointer;font-family:'Rajdhani',sans-serif;}
.key-out{background:rgba(0,0,0,0.3);border:1px solid rgba(255,107,0,0.3);border-radius:10px;padding:11px;font-family:'Courier New',monospace;font-size:0.72rem;color:var(--orange);word-break:break-all;cursor:pointer;min-height:42px;margin-bottom:8px;}
.inp-row{display:flex;gap:7px;}
.inp{flex:1;background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:8px;padding:8px 10px;color:var(--text);font-size:0.8rem;outline:none;font-family:'Rajdhani',sans-serif;}
.inp:focus{border-color:rgba(255,107,0,0.4);}
.sel{background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:8px;padding:8px;color:var(--text);font-size:0.75rem;outline:none;}
.btn-g{padding:8px 14px;border:none;border-radius:8px;cursor:pointer;font-size:0.75rem;font-weight:700;font-family:'Rajdhani',sans-serif;letter-spacing:1px;}
.btn-green{background:#00c853;color:#000;}
.btn-orange{background:var(--orange);color:#000;}
.btn-red{background:var(--red);color:#fff;}
.btn-blue{background:#1565c0;color:#fff;}
.btn-grey{background:#37474f;color:#fff;}

/* Signal */
.sig-sel{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:8px;}
.sig-out{background:rgba(0,0,0,0.3);border:1px solid rgba(0,212,255,0.2);border-radius:10px;padding:11px;font-family:'Courier New',monospace;font-size:0.72rem;color:#cbd5e1;white-space:pre-wrap;min-height:60px;cursor:pointer;}

/* Users table */
.tbl{width:100%;border-collapse:collapse;font-size:0.75rem;}
.tbl th{text-align:left;padding:7px 5px;color:var(--muted);border-bottom:1px solid var(--border);font-size:0.56rem;text-transform:uppercase;letter-spacing:1px;}
.tbl td{padding:7px 5px;border-bottom:1px solid rgba(255,255,255,0.03);}
.badge-g{background:rgba(0,255,136,0.1);color:var(--green);padding:2px 8px;border-radius:20px;font-size:0.62rem;font-weight:700;}
.badge-r{background:rgba(255,45,85,0.1);color:var(--red);padding:2px 8px;border-radius:20px;font-size:0.62rem;font-weight:700;}

/* Broadcast / Token */
.textarea{width:100%;background:rgba(0,0,0,0.3);border:1px solid var(--border);border-radius:10px;padding:10px;color:var(--text);font-size:0.8rem;min-height:65px;resize:vertical;outline:none;font-family:'Rajdhani',sans-serif;margin-bottom:8px;}

.mkt-status{background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:10px;padding:8px 12px;display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;}
.mkt-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px;animation:blink 1s infinite;}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.2}}

.toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:rgba(255,107,0,0.9);color:#000;padding:9px 18px;border-radius:10px;font-size:0.8rem;font-weight:700;opacity:0;pointer-events:none;transition:opacity 0.3s;z-index:999;white-space:nowrap;}
.toast.show{opacity:1;}
</style>
</head>
<body>
<div class="bg-grid"></div>

<!-- LOGIN -->
<div class="login-wrap" id="login-wrap">
  <div class="login-card">
    <div class="login-icon">&#128081;</div>
    <div class="login-title">OWNER PANEL</div>
    <div class="login-sub">KETAN AI &#8212; Secure Access</div>
    <input class="login-inp" type="number" id="oid-inp" placeholder="Owner Telegram ID">
    <button class="login-btn" id="login-btn" onclick="doLogin()">&#128272; Enter Panel</button>
    <div class="login-err" id="login-err">&#10060; Owner ID galat hai</div>
    <div class="user-link">User panel: <a href="/user">Click here &#8594;</a></div>
  </div>
</div>

<!-- PANEL -->
<div class="panel" id="panel">
  <div class="op-topbar">
    <span class="op-logo">&#128081; OWNER PANEL</span>
    <button class="op-logout" onclick="doLogout()">&#128682; Logout</button>
  </div>

  <!-- Market Status -->
  <div class="mkt-status" id="mkt-status">
    <span><span class="mkt-dot" style="background:#ff2d55"></span>Market Closed</span>
    <span style="font-size:0.65rem;color:var(--muted)" id="mkt-time">--</span>
  </div>

  <!-- Stats -->
  <div class="sec">
    <div class="sec-title">&#128202; Dashboard Stats</div>
    <div class="stats-grid">
      <div class="stat-box"><div class="stat-num" id="st-active">--</div><div class="stat-lbl">Active Users</div></div>
      <div class="stat-box"><div class="stat-num" id="st-blocked">--</div><div class="stat-lbl">Blocked</div></div>
      <div class="stat-box"><div class="stat-num" id="st-keys">--</div><div class="stat-lbl">Keys</div></div>
    </div>
  </div>

  <!-- Signal Generator -->
  <div class="sec">
    <div class="sec-title">&#128225; Signal Generator</div>
    <div class="sig-sel">
      <select class="sel" id="sig-sym"><option value="NIFTY">NIFTY</option><option value="BANKNIFTY">BANKNIFTY</option></select>
      <button class="btn-g btn-blue" onclick="getSig('basic')">&#128202; Basic</button>
      <button class="btn-g btn-orange" onclick="getSig('pro')">&#9889; PRO</button>
      <button class="btn-g btn-green" onclick="getSig('smart')">&#129504; Smart</button>
      <button class="btn-g btn-grey" onclick="getSig('sr')">&#127919; S&R</button>
    </div>
    <div class="sig-out" id="sig-out" onclick="copySig()">Signal yahan aayega... (tap to copy)</div>
  </div>

  <!-- Key Generation -->
  <div class="sec">
    <div class="sec-title">&#128273; Key Generation</div>
    <div class="key-btns">
      <button class="kbtn" onclick="genKey(1)">1d</button>
      <button class="kbtn" onclick="genKey(2)">2d</button>
      <button class="kbtn" onclick="genKey(3)">3d</button>
      <button class="kbtn" onclick="genKey(5)">5d</button>
      <button class="kbtn" onclick="genKey(7)">7d</button>
      <button class="kbtn" onclick="genKey(10)">10d</button>
      <button class="kbtn" onclick="genKey(15)">15d</button>
      <button class="kbtn" onclick="genKey(30)">30d</button>
    </div>
    <div class="key-out" id="key-out" onclick="copyKey()">Key yahan aayegi... (tap to copy)</div>
    <div class="inp-row">
      <input class="inp" type="number" id="send-uid" placeholder="User Telegram ID">
      <select class="sel" id="send-days"><option value="1">1d</option><option value="7">7d</option><option value="15">15d</option><option value="30">30d</option></select>
      <button class="btn-g btn-green" onclick="sendKey()">Send</button>
    </div>
  </div>

  <!-- Users -->
  <div class="sec">
    <div class="sec-title">
      <span>&#128101; Users</span>
      <button class="btn-g btn-blue" style="font-size:0.6rem;padding:3px 8px" onclick="loadUsers()">&#128260; Refresh</button>
    </div>
    <div style="overflow-x:auto">
      <table class="tbl">
        <thead><tr><th>User ID</th><th>Expiry</th><th>Status</th><th>Action</th></tr></thead>
        <tbody id="users-tbody"><tr><td colspan="4" style="text-align:center;color:var(--muted);padding:14px">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- Broadcast -->
  <div class="sec">
    <div class="sec-title">&#128228; Broadcast Message</div>
    <textarea class="textarea" id="bcast-msg" placeholder="Saare users ko message..."></textarea>
    <button class="btn-g btn-orange" style="width:100%" onclick="doBroadcast()">&#128228; Send to All</button>
  </div>

  <!-- Dhan Token -->
  <div class="sec">
    <div class="sec-title">&#128272; Dhan Token Update</div>
    <div class="inp-row">
      <input class="inp" type="text" id="dhan-tok" placeholder="Naya Dhan Access Token">
      <button class="btn-g btn-grey" onclick="updateToken()">Update</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>
<script>
var OWNER_ID = 8210011971;
var isLoggedIn = false;

function toast(m){var t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(function(){t.classList.remove('show');},2200);}

function doLogin(){
  var v=parseInt(document.getElementById('oid-inp').value.trim());
  if(v!==OWNER_ID){document.getElementById('login-err').style.display='block';return;}
  document.getElementById('login-err').style.display='none';
  isLoggedIn=true;
  document.getElementById('login-wrap').style.display='none';
  document.getElementById('panel').style.display='block';
  loadStats();loadUsers();checkMkt();
}

function doLogout(){
  isLoggedIn=false;
  document.getElementById('panel').style.display='none';
  document.getElementById('login-wrap').style.display='flex';
  document.getElementById('oid-inp').value='';
}

function checkMkt(){
  var n=new Date(),h=n.getHours(),m=n.getMinutes(),d=n.getDay();
  var open=(d>=1&&d<=5&&(h>9||(h===9&&m>=15))&&(h<15||(h===15&&m<=25)));
  var el=document.getElementById('mkt-status');
  var time_str=n.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  document.getElementById('mkt-time').textContent=time_str;
  el.innerHTML='<span><span class="mkt-dot" style="background:'+(open?'#00ff88':'#ff2d55')+'"></span>'+(open?'Market Open':'Market Closed')+'</span><span style="font-size:0.65rem;color:var(--muted)" id="mkt-time">'+time_str+'</span>';
  setInterval(function(){
    var n2=new Date();document.getElementById('mkt-time')&&(document.getElementById('mkt-time').textContent=n2.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',second:'2-digit'}));
  },1000);
}

function xhr2(url,cb){var x=new XMLHttpRequest();x.open('GET',url,true);x.onreadystatechange=function(){if(x.readyState===4){try{cb(JSON.parse(x.responseText));}catch(e){cb(null);}}};x.send();}
function post2(url,data,cb){var x=new XMLHttpRequest();x.open('POST',url,true);x.setRequestHeader('Content-Type','application/json');x.onreadystatechange=function(){if(x.readyState===4){try{cb(JSON.parse(x.responseText));}catch(e){cb(null);}}};x.send(JSON.stringify(data));}

function loadStats(){
  xhr2('/api/stats',function(d){
    if(!d)return;
    document.getElementById('st-active').textContent=d.active_users;
    document.getElementById('st-blocked').textContent=d.blocked_users;
    document.getElementById('st-keys').textContent=d.unused_keys;
  });
}

function getSig(type){
  var sym=document.getElementById('sig-sym').value;
  document.getElementById('sig-out').textContent='&#9203; Loading...';
  xhr2('/api/signal?type='+type+'&symbol='+sym,function(d){
    document.getElementById('sig-out').textContent=d&&d.text?d.text:'Error';
  });
}
function copySig(){
  var t=document.getElementById('sig-out').textContent;
  navigator.clipboard.writeText(t).then(function(){toast('&#128203; Copied!');});
}

function genKey(days){
  post2('/api/genkey',{days:days},function(d){
    if(d&&d.key){document.getElementById('key-out').textContent=d.key;toast('&#9989; Key generated!');}
  });
}
function copyKey(){
  var k=document.getElementById('key-out').textContent;
  if(k&&k!=='Key yahan aayegi... (tap to copy)'){
    navigator.clipboard.writeText(k).then(function(){toast('&#128203; Copied!');});
  }
}
function sendKey(){
  var uid=parseInt(document.getElementById('send-uid').value);
  var days=parseInt(document.getElementById('send-days').value);
  if(!uid){toast('User ID daalo');return;}
  post2('/api/sendkey',{uid:uid,days:days},function(d){toast(d&&d.ok?'&#9989; Key sent!':'&#10060; Failed');});
}

function loadUsers(){
  xhr2('/api/users',function(d){
    if(!d)return;
    var tb=document.getElementById('users-tbody');
    if(!d.users||!d.users.length){tb.innerHTML='<tr><td colspan="4" style="text-align:center;color:var(--muted);padding:14px">Koi user nahi</td></tr>';return;}
    tb.innerHTML=d.users.map(function(u){
      return '<tr><td style="font-family:monospace;font-size:0.7rem">'+u.uid+'</td>'
        +'<td style="color:'+(u.blocked?'var(--red)':'var(--green)')+'">'+u.expiry+'</td>'
        +'<td><span class="'+(u.blocked?'badge-r':'badge-g')+'">'+(u.blocked?'Blocked':'Active')+'</span></td>'
        +'<td>'+(u.blocked
          ?'<button class="btn-g btn-green" style="font-size:0.6rem;padding:3px 7px" onclick="blockUser('+u.uid+',false)">Unblock</button>'
          :'<button class="btn-g btn-red" style="font-size:0.6rem;padding:3px 7px" onclick="blockUser('+u.uid+',true)">Block</button>')
        +'</td></tr>';
    }).join('');
  });
}
function blockUser(uid,blk){
  post2('/api/block',{uid:uid,block:blk},function(d){
    if(d&&d.ok){toast(blk?'&#128683; Blocked':'&#9989; Unblocked');loadUsers();loadStats();}
  });
}
function doBroadcast(){
  var msg=document.getElementById('bcast-msg').value.trim();
  if(!msg){toast('Message daalo');return;}
  post2('/api/broadcast',{message:msg},function(d){
    if(d&&d.ok){toast('&#9989; Sent to '+d.count+' users!');document.getElementById('bcast-msg').value='';}
  });
}
function updateToken(){
  var t=document.getElementById('dhan-tok').value.trim();
  if(!t){toast('Token daalo');return;}
  post2('/api/token',{token:t},function(d){
    if(d&&d.ok){toast('&#9989; Token updated!');document.getElementById('dhan-tok').value='';}
  });
}
</script>
</body>
</html>"""

# ======================================================
# USER DASHBOARD HTML
# ======================================================
USER_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>KETAN AI</title>
<style>
[data-theme="dark"]{--bg:#04060d;--surf:#080c18;--card:#0c1220;--bdr:rgba(255,255,255,.07);--bdr2:rgba(255,255,255,.12);--txt:#f1f5f9;--txt2:#94a3b8;--muted:#64748b;--hbg:rgba(4,6,13,.96);--inp:rgba(255,255,255,.05);--sh:rgba(0,0,0,.5);--nav:#080c18;}
[data-theme="light"]{--bg:#eef2f7;--surf:#e2e8f0;--card:#f8fafc;--bdr:rgba(15,23,42,.08);--bdr2:rgba(15,23,42,.14);--txt:#1e293b;--txt2:#475569;--muted:#94a3b8;--hbg:rgba(238,242,247,.97);--inp:rgba(15,23,42,.05);--sh:rgba(15,23,42,.12);--nav:#f1f5f9;}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);color:var(--txt);font-family:Arial,sans-serif;min-height:100vh;overflow-x:hidden;}
/* SPLASH */
#splash{position:fixed;inset:0;z-index:9000;background:#04060d;display:flex;flex-direction:column;align-items:center;justify-content:center;animation:splashOut 0.5s ease 3s forwards;}
@keyframes splashOut{to{opacity:0;visibility:hidden;pointer-events:none;}}
.sp-bg{position:absolute;inset:0;background-image:linear-gradient(rgba(59,130,246,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(59,130,246,.04) 1px,transparent 1px);background-size:44px 44px;}
.sp-inner{position:relative;z-index:1;text-align:center;}
.sp-ring{width:110px;height:110px;border-radius:50%;position:relative;display:flex;align-items:center;justify-content:center;margin:0 auto 20px;}
.sp-ring-o{position:absolute;inset:-3px;border-radius:50%;background:conic-gradient(#3b82f6,#8b5cf6,#ef4444,#10b981,#3b82f6);animation:ringR 2.5s linear infinite;}
@keyframes ringR{to{transform:rotate(360deg)}}
.sp-ring-i{position:absolute;inset:3px;border-radius:50%;background:#04060d;}
.sp-face{position:relative;z-index:1;font-size:3rem;}
.sp-t1{font-size:2.2rem;font-weight:900;background:linear-gradient(135deg,#60a5fa,#34d399);-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-.02em;}
.sp-t2{font-size:.75rem;color:rgba(255,255,255,.3);letter-spacing:.2em;text-transform:uppercase;margin-top:6px;}
.sp-t3{font-size:.72rem;color:#f59e0b;letter-spacing:.18em;text-transform:uppercase;margin-top:5px;}
.sp-dots{display:flex;gap:8px;justify-content:center;margin-top:26px;}
.sp-dot{width:8px;height:8px;border-radius:50%;background:#3b82f6;}
.sp-dot:nth-child(1){animation:db 1s 0s infinite;}
.sp-dot:nth-child(2){animation:db 1s .25s infinite;}
.sp-dot:nth-child(3){animation:db 1s .5s infinite;}
@keyframes db{0%,100%{opacity:.2;transform:scale(.8)}50%{opacity:1;transform:scale(1.2)}}
.sp-bar{position:absolute;bottom:0;left:0;right:0;height:3px;background:rgba(255,255,255,.05);}
.sp-prog{height:100%;background:linear-gradient(90deg,#3b82f6,#10b981);animation:prog 2.8s linear forwards;}
@keyframes prog{from{width:0}to{width:100%}}
/* LOGIN SCREEN */
#login-screen{position:fixed;inset:0;z-index:8500;background:var(--bg);display:none;align-items:center;justify-content:center;padding:20px;}
#login-screen.show{display:flex;}
.login-box{background:var(--card);border:1px solid var(--bdr2);border-radius:20px;padding:28px 24px;width:100%;max-width:360px;text-align:center;}
.login-logo{font-size:2.5rem;margin-bottom:12px;}
.login-title{font-size:1.3rem;font-weight:900;background:linear-gradient(135deg,#60a5fa,#34d399);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:6px;}
.login-sub{font-size:.75rem;color:var(--muted);margin-bottom:24px;line-height:1.6;}
.login-label{font-size:.65rem;color:var(--txt2);text-align:left;display:block;margin-bottom:6px;text-transform:uppercase;letter-spacing:.08em;}
.login-input{width:100%;background:var(--inp);border:1px solid var(--bdr2);border-radius:12px;padding:13px 16px;color:var(--txt);font-size:1rem;font-weight:700;outline:none;text-align:center;letter-spacing:.1em;margin-bottom:16px;}
.login-input:focus{border-color:rgba(59,130,246,.5);}
.login-btn{width:100%;background:linear-gradient(135deg,#3b82f6,#06b6d4);color:#fff;border:none;border-radius:12px;padding:14px;font-size:.9rem;font-weight:700;cursor:pointer;margin-bottom:10px;}
.login-btn:active{transform:scale(.97);}
.login-err{font-size:.72rem;color:#f87171;min-height:20px;margin-top:4px;}
.login-help{font-size:.62rem;color:var(--muted);margin-top:12px;line-height:1.7;}
/* TERMS */
#tc-overlay{position:fixed;inset:0;z-index:8000;background:rgba(0,0,0,.85);backdrop-filter:blur(16px);display:none;align-items:flex-end;justify-content:center;}
#tc-overlay.show{display:flex;}
.tc-box{background:var(--card);border:1px solid var(--bdr2);border-radius:24px 24px 0 0;width:100%;max-width:480px;max-height:85vh;display:flex;flex-direction:column;animation:tcUp .35s ease;}
@keyframes tcUp{from{transform:translateY(100%)}to{transform:translateY(0)}}
.tc-head{padding:18px 20px 12px;text-align:center;border-bottom:1px solid var(--bdr);}
.tc-drag{width:40px;height:4px;background:var(--bdr2);border-radius:4px;margin:0 auto 14px;}
.tc-title{font-size:1rem;font-weight:800;background:linear-gradient(135deg,#60a5fa,#34d399);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.tc-scroll{flex:1;overflow-y:auto;padding:16px 20px;font-size:.72rem;color:var(--txt2);line-height:1.8;}
.tc-scroll h4{color:#60a5fa;margin:12px 0 6px;font-size:.78rem;}
.tc-warn{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2);border-radius:10px;padding:10px;color:#f59e0b;}
.tc-ul{list-style:none;margin:4px 0;}
.tc-ul li{padding:2px 0 2px 14px;position:relative;}
.tc-ul li::before{content:'•';position:absolute;left:0;color:#3b82f6;}
.tc-foot{padding:14px 20px;border-top:1px solid var(--bdr);}
.tc-btn{width:100%;background:linear-gradient(135deg,#3b82f6,#06b6d4);color:#fff;border:none;border-radius:12px;padding:14px;font-size:.88rem;font-weight:700;cursor:pointer;}
.tc-note{text-align:center;font-size:.58rem;color:var(--muted);margin-top:8px;}
/* APP */
#app{display:block;position:relative;z-index:1;padding-bottom:72px;}
.page{display:none;}
.page.active{display:block;}
/* HEADER */
.hdr{position:sticky;top:0;z-index:100;background:var(--hbg);backdrop-filter:blur(24px);border-bottom:1px solid var(--bdr);}
.hdr-top{display:flex;align-items:center;justify-content:space-between;padding:44px 14px 9px;}
.logo{display:flex;align-items:center;gap:8px;}
.logo-face{font-size:1.2rem;}
.logo-text{font-weight:900;font-size:1rem;background:linear-gradient(135deg,#60a5fa,#34d399);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.hdr-right{display:flex;align-items:center;gap:6px;}
.pill{display:flex;align-items:center;gap:4px;padding:4px 10px;border-radius:20px;font-size:.58rem;font-weight:600;border:1px solid;}
.pill-g{background:rgba(16,185,129,.1);border-color:rgba(16,185,129,.2);color:#10b981;}
.pill-b{background:rgba(59,130,246,.1);border-color:rgba(59,130,246,.2);color:#60a5fa;font-family:monospace;}
.ldot{width:5px;height:5px;border-radius:50%;background:#10b981;animation:ldotPulse 1.5s infinite;}
@keyframes ldotPulse{0%,100%{box-shadow:0 0 0 0 rgba(16,185,129,.4)}50%{box-shadow:0 0 0 4px rgba(16,185,129,0)}}
.ibtn{width:32px;height:32px;border-radius:9px;border:1px solid var(--bdr2);background:var(--card);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:.82rem;position:relative;}
.ibtn:active{transform:scale(.9);}
/* TICKER */
.ticker-wrap{overflow:hidden;border-bottom:1px solid var(--bdr);background:var(--surf);position:relative;}
.ticker-wrap::before,.ticker-wrap::after{content:'';position:absolute;top:0;bottom:0;width:36px;z-index:2;pointer-events:none;}
.ticker-wrap::before{left:0;background:linear-gradient(90deg,var(--surf),transparent);}
.ticker-wrap::after{right:0;background:linear-gradient(-90deg,var(--surf),transparent);}
.ticker-inner{display:flex;animation:tickerMove 30s linear infinite;width:max-content;}
@keyframes tickerMove{from{transform:translateX(0)}to{transform:translateX(-50%)}}
.tick{display:flex;align-items:center;gap:6px;padding:7px 16px;border-right:1px solid var(--bdr);white-space:nowrap;flex-shrink:0;}
.tlbl{font-size:.5rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;}
.tval{font-family:monospace;font-size:.7rem;font-weight:700;}
.tchg{font-size:.48rem;padding:1px 5px;border-radius:4px;}
.up{color:#10b981;} .dn{color:#ef4444;} .am{color:#f59e0b;}
.up-bg{background:rgba(16,185,129,.12);color:#10b981;} .dn-bg{background:rgba(239,68,68,.12);color:#ef4444;}
/* STATUS */
.status-bar{display:flex;justify-content:space-between;align-items:center;padding:6px 14px;border-bottom:1px solid var(--bdr);}
.mkt{display:flex;align-items:center;gap:5px;padding:3px 10px;border-radius:20px;font-size:.6rem;font-weight:600;}
.mkt-o{background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.2);color:#10b981;}
.mkt-c{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.2);color:#ef4444;}
.mkt-dot{width:6px;height:6px;border-radius:50%;background:currentColor;animation:ldotPulse 1s infinite;}
.clk{font-family:monospace;font-size:.6rem;color:var(--txt2);}
/* MAIN */
.main{padding:12px 14px;max-width:480px;margin:0 auto;}
/* PRICE CARD */
.price-card{background:var(--card);border:1px solid var(--bdr2);border-radius:20px;overflow:hidden;margin-bottom:12px;box-shadow:0 4px 24px var(--sh);}
.price-tabs{display:grid;grid-template-columns:1fr 1fr;gap:7px;padding:14px 14px 0;}
.ptab{padding:11px 10px;border-radius:12px;cursor:pointer;border:1px solid var(--bdr);background:var(--inp);}
.ptab.active{background:rgba(59,130,246,.1);border-color:rgba(59,130,246,.35);}
.ptab-lbl{font-size:.5rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px;}
.ptab-val{font-family:monospace;font-size:.88rem;font-weight:700;}
.ptab-chg{font-size:.5rem;margin-top:2px;}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;padding:10px 14px 14px;}
.metric{background:var(--inp);border:1px solid var(--bdr);border-radius:10px;padding:7px 8px;text-align:center;}
.mlbl{font-size:.44rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px;}
.mval{font-family:monospace;font-size:.68rem;font-weight:700;}
/* TABS */
.sym-row{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:9px;}
.sym-btn{padding:10px;border-radius:12px;text-align:center;font-size:.72rem;font-weight:700;cursor:pointer;border:1px solid var(--bdr);background:var(--inp);color:var(--muted);}
.sym-btn.active{border-color:rgba(59,130,246,.4);color:#60a5fa;background:rgba(59,130,246,.08);}
.type-row{display:flex;gap:6px;margin-bottom:10px;overflow-x:auto;padding-bottom:2px;}
.type-row::-webkit-scrollbar{display:none;}
.tbtn{display:flex;align-items:center;gap:4px;padding:7px 13px;border-radius:20px;font-size:.63rem;font-weight:600;cursor:pointer;white-space:nowrap;flex-shrink:0;border:1px solid var(--bdr);background:var(--inp);color:var(--muted);}
.tbtn.active{border-color:rgba(59,130,246,.4);color:#60a5fa;background:rgba(59,130,246,.1);}
/* SIGNAL CARD */
.sig-card{background:var(--card);border:1px solid var(--bdr2);border-radius:20px;overflow:hidden;margin-bottom:12px;box-shadow:0 4px 24px var(--sh);}
.sig-head{padding:14px 16px 12px;border-bottom:1px solid var(--bdr);display:flex;justify-content:space-between;align-items:flex-start;}
.sig-title{font-size:.8rem;font-weight:700;color:#60a5fa;}
.sig-sub{font-size:.54rem;color:var(--muted);margin-top:2px;}
.sig-time{font-family:monospace;font-size:.52rem;color:var(--muted);}
.sig-body{min-height:100px;}
.load-box{display:flex;flex-direction:column;align-items:center;padding:32px;gap:10px;}
.spinner{width:26px;height:26px;border:2.5px solid var(--bdr);border-top-color:#3b82f6;border-radius:50%;animation:spin .7s linear infinite;}
@keyframes spin{to{transform:rotate(360deg)}}
.load-msg{font-size:.68rem;color:var(--muted);}
.sig-out{padding:12px 16px;font-size:.78rem;line-height:1.9;color:var(--txt);white-space:pre-wrap;font-family:monospace;}
.sig-err{padding:20px 16px;font-size:.74rem;color:#f87171;text-align:center;}
.sig-foot{padding:10px 14px;border-top:1px solid var(--bdr);display:flex;gap:8px;}
.btn-main{flex:1;background:linear-gradient(135deg,#3b82f6,#06b6d4);color:#fff;border:none;border-radius:12px;padding:11px;font-size:.76rem;font-weight:700;cursor:pointer;}
.btn-main:active{transform:scale(.97);}
.btn-sec{background:var(--inp);border:1px solid var(--bdr2);border-radius:12px;padding:11px 14px;font-size:.76rem;color:var(--txt2);cursor:pointer;}
.watermark{text-align:center;padding:7px;font-size:.5rem;color:var(--muted);border-top:1px solid var(--bdr);}
/* P&L */
.pnl-card{background:var(--card);border:1px solid var(--bdr2);border-radius:20px;overflow:hidden;margin-bottom:12px;box-shadow:0 4px 24px var(--sh);}
.pnl-head{padding:14px 16px;border-bottom:1px solid var(--bdr);display:flex;justify-content:space-between;align-items:center;}
.pnl-title{font-size:.8rem;font-weight:700;color:#34d399;}
.pnl-sub{font-size:.54rem;color:var(--muted);margin-top:2px;}
.tog{font-size:.58rem;font-weight:600;padding:4px 10px;border-radius:20px;cursor:pointer;border:1px solid var(--bdr2);background:var(--inp);color:var(--txt2);}
.pnl-inner{padding:14px 16px;}
.fgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;}
.flabel{font-size:.48rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;display:block;margin-bottom:5px;}
.finput{width:100%;background:var(--inp);border:1px solid var(--bdr2);border-radius:10px;padding:9px 12px;color:var(--txt);font-size:.84rem;font-family:monospace;font-weight:700;outline:none;}
.finput:focus{border-color:rgba(16,185,129,.4);}
.fsel{width:100%;background:var(--inp);border:1px solid var(--bdr2);border-radius:10px;padding:9px 12px;color:var(--txt);font-size:.78rem;outline:none;cursor:pointer;}
.calc-btn{width:100%;background:linear-gradient(135deg,#10b981,#06b6d4);color:#fff;border:none;border-radius:12px;padding:12px;font-size:.82rem;font-weight:700;cursor:pointer;margin-bottom:12px;}
.calc-btn:active{transform:scale(.97);}
.res-box{display:none;background:var(--inp);border:1px solid var(--bdr);border-radius:14px;padding:14px;}
.res-box.show{display:block;}
.rgrid{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:10px;}
.ritem{background:var(--card);border:1px solid var(--bdr);border-radius:10px;padding:8px 10px;text-align:center;}
.rlbl{font-size:.44rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px;}
.rval{font-family:monospace;font-size:.78rem;font-weight:700;}
.rsum{margin-top:10px;padding:12px;border-radius:10px;border:1px solid;text-align:center;}
.rsump{background:rgba(16,185,129,.08);border-color:rgba(16,185,129,.2);}
.rsuml{background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.2);}
.rnet{font-family:monospace;font-size:1.1rem;font-weight:700;}
.scrow{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--bdr);}
.scrow:last-child{border:none;}
/* PAGES */
.ptitle{font-size:1.1rem;font-weight:800;margin-bottom:4px;}
.psub{font-size:.72rem;color:var(--muted);margin-bottom:16px;}
.clist{background:var(--card);border:1px solid var(--bdr2);border-radius:18px;overflow:hidden;margin-bottom:10px;}
.citem{display:flex;align-items:center;gap:14px;padding:15px 16px;border-bottom:1px solid var(--bdr);text-decoration:none;color:var(--txt);}
.citem:last-child{border:none;}
.citem:active{background:var(--inp);}
.cic{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:1.3rem;flex-shrink:0;}
.cwa{background:rgba(37,211,102,.12);border:1px solid rgba(37,211,102,.2);}
.ctg{background:rgba(0,136,204,.12);border:1px solid rgba(0,136,204,.2);}
.cig{background:rgba(225,48,108,.12);border:1px solid rgba(225,48,108,.2);}
.cnm{font-weight:700;font-size:.82rem;}
.chd{font-size:.62rem;color:var(--muted);margin-top:2px;}
.icard{background:var(--card);border:1px solid var(--bdr2);border-radius:18px;padding:18px;margin-bottom:10px;}
.irow{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--bdr);}
.irow:last-child{border:none;}
.il{font-size:.7rem;color:var(--muted);}
.iv{font-family:monospace;font-size:.7rem;font-weight:700;}
.sset{background:var(--card);border:1px solid var(--bdr2);border-radius:18px;overflow:hidden;margin-bottom:12px;}
.shed{padding:12px 16px;border-bottom:1px solid var(--bdr);font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-weight:600;}
.srow{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--bdr);}
.srow:last-child{border:none;}
.sleft{display:flex;align-items:center;gap:10px;}
.sicon{font-size:1.1rem;width:28px;text-align:center;}
.stxt{font-size:.8rem;font-weight:600;}
.shint{font-size:.6rem;color:var(--muted);margin-top:2px;}
.sw{position:relative;width:46px;height:26px;flex-shrink:0;}
.sw input{opacity:0;width:0;height:0;}
.sw-s{position:absolute;cursor:pointer;inset:0;background:rgba(255,255,255,.1);border-radius:26px;transition:.3s;border:1px solid var(--bdr2);}
.sw-s::before{content:'';position:absolute;height:18px;width:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s;}
input:checked+.sw-s{background:linear-gradient(135deg,#3b82f6,#06b6d4);}
input:checked+.sw-s::before{transform:translateX(20px);}
.ssel{background:var(--inp);border:1px solid var(--bdr2);border-radius:8px;padding:5px 10px;color:var(--txt);font-size:.74rem;outline:none;cursor:pointer;}
.sbadge{font-family:monospace;font-size:.64rem;font-weight:700;padding:3px 10px;border-radius:20px;background:rgba(59,130,246,.1);color:#60a5fa;border:1px solid rgba(59,130,246,.2);}
/* VIDEO */
.vc-hero{background:linear-gradient(135deg,rgba(16,185,129,.08),rgba(59,130,246,.06));border:1px solid rgba(16,185,129,.15);border-radius:20px;padding:24px 20px;text-align:center;margin-bottom:14px;}
.vc-ic{font-size:2.8rem;margin-bottom:12px;}
.vc-t{font-size:1.1rem;font-weight:800;margin-bottom:6px;background:linear-gradient(135deg,#34d399,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.vc-s{font-size:.72rem;color:var(--muted);line-height:1.7;}
.vc-sb{width:100%;background:linear-gradient(135deg,#10b981,#06b6d4);color:#fff;border:none;border-radius:16px;padding:15px;font-size:.9rem;font-weight:700;cursor:pointer;margin-top:14px;}
.vcgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px;}
.vcslot{border-radius:16px;aspect-ratio:1;position:relative;overflow:hidden;border:1px solid var(--bdr2);}
.vcslot.on{border-color:rgba(16,185,129,.4);}
.vcslot.off{background:var(--inp);border-style:dashed;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:6px;}
.vcav{width:100%;height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:6px;}
.vcav-c{width:52px;height:52px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:1.5rem;font-weight:700;}
.vcav-n{font-size:.62rem;font-weight:700;color:rgba(255,255,255,.9);}
.vcav-t{font-size:.5rem;color:rgba(255,255,255,.5);}
.vcwave{position:absolute;inset:0;border-radius:16px;border:2px solid #10b981;animation:wv .5s ease infinite alternate;}
@keyframes wv{from{opacity:.3}to{opacity:1}}
.vcibox{background:var(--card);border:1px solid var(--bdr2);border-radius:14px;padding:14px 16px;margin-bottom:10px;}
.vcirow{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--bdr);}
.vcirow:last-child{border:none;}
.vcctrl{display:flex;gap:8px;margin-top:10px;}
.vcbtn{flex:1;background:var(--inp);border:1px solid var(--bdr2);border-radius:14px;padding:12px;text-align:center;cursor:pointer;}
.vcend{background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.2);}
/* NAV */
.bnav{position:fixed;bottom:0;left:0;right:0;z-index:200;background:var(--nav);border-top:1px solid var(--bdr2);backdrop-filter:blur(20px);display:flex;padding:8px 0 calc(8px + env(safe-area-inset-bottom));}
.nitem{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;padding:6px 4px;}
.nic{font-size:1.25rem;line-height:1;}
.nlb{font-size:.5rem;font-weight:600;color:var(--muted);}
.nitem.active .nlb{color:#3b82f6;}
.nitem.active .nic{filter:drop-shadow(0 0 6px rgba(59,130,246,.5));}
/* TOAST */
@keyframes vcPulse{0%,100%{opacity:1}50%{opacity:.4}}
.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:var(--card);border:1px solid var(--bdr2);border-radius:12px;padding:10px 20px;font-size:.76rem;color:var(--txt);opacity:0;pointer-events:none;transition:opacity .3s;z-index:9999;white-space:nowrap;box-shadow:0 8px 32px var(--sh);}
.toast.show{opacity:1;}
@keyframes vcPulse{0%,100%{opacity:1}50%{opacity:.3}}
.vc-notif{position:fixed;top:60px;left:50%;transform:translateX(-50%);background:linear-gradient(135deg,#10b981,#06b6d4);color:#fff;padding:12px 20px;border-radius:14px;font-size:.76rem;font-weight:700;z-index:9998;white-space:nowrap;box-shadow:0 8px 32px rgba(0,0,0,.4);display:none;text-align:center;}
</style>
</head>
<body>

<!-- SPLASH -->
<div id="splash">
  <div class="sp-bg"></div>
  <div class="sp-inner">
    <div class="sp-ring"><div class="sp-ring-o"></div><div class="sp-ring-i"></div><span class="sp-face">&#128520;</span></div>
    <div class="sp-t1">KETAN AI</div>
    <div class="sp-t2">Institutional Trading Terminal</div>
    <div class="sp-t3">&#10022; By Ketan Kondekar &#10022;</div>
    <div class="sp-dots"><div class="sp-dot"></div><div class="sp-dot"></div><div class="sp-dot"></div></div>
  </div>
  <div class="sp-bar"><div class="sp-prog"></div></div>
</div>

<!-- LOGIN SCREEN -->
<div id="login-screen">
  <div class="login-box">
    <div class="login-logo">&#128520;</div>
    <div class="login-title">KETAN AI</div>
    <div class="login-sub">Apna Telegram User ID enter karo<br>access activate karne ke liye</div>
    <label class="login-label">Telegram User ID</label>
    <input class="login-input" type="number" id="uid-input" placeholder="8210011971">
    <div class="login-err" id="login-err"></div>
    <button class="login-btn" onclick="doLogin()">Login &rarr;</button>
    <div class="login-help">Telegram mein @userinfobot ko message karo<br>apna User ID pata karne ke liye</div>
  </div>
</div>

<!-- TERMS -->
<div id="tc-overlay">
  <div class="tc-box">
    <div class="tc-head"><div class="tc-drag"></div><div class="tc-title">Terms and Conditions</div></div>
    <div class="tc-scroll">
      <h4>Risk Disclaimer</h4>
      <div class="tc-warn">Stock market trading mein significant financial risk hota hai. Sirf woh paisa invest karo jo aap khone ke liye afford kar sako.</div>
      <h4>Service Terms</h4>
      <ul class="tc-ul">
        <li>Ketan AI ek educational platform hai</li>
        <li>Signals guaranteed returns nahi deti</li>
        <li>Final decision aapka apna hona chahiye</li>
      </ul>
      <h4>Privacy</h4>
      <ul class="tc-ul">
        <li>Aapka UID securely store hoga</li>
        <li>Data third parties ke saath share nahi hoga</li>
      </ul>
    </div>
    <div class="tc-foot">
      <button class="tc-btn" onclick="agreeTC()">I Agree - Continue to App</button>
      <div class="tc-note">Yeh sirf pehli baar dikhega.</div>
    </div>
  </div>
</div>

<!-- APP -->
<div id="app">
  <!-- HEADER -->
  <div class="hdr">
    <div class="hdr-top">
      <div class="logo">
        <span class="logo-face">&#128202;</span>
        <span class="logo-text">KETAN AI</span>
      </div>
      <div class="hdr-right">
        <div class="pill pill-g"><div class="ldot"></div><span id="hdr-time">--:--</span></div>
        <div class="pill pill-b" id="exp-pill">--</div>
        <div class="ibtn" id="theme-btn" onclick="toggleTheme()">&#9728;&#65039;</div>
        <div class="ibtn" onclick="toast('OI Alert active!')">&#128276;</div>
        <div class="ibtn" onclick="toast('Owner: /owner URL')">&#128081;</div>
      </div>
    </div>
    <div class="ticker-wrap">
      <div class="ticker-inner" id="ticker-inner">
        <div class="tick"><span class="tlbl">NIFTY</span><span class="tval dn" id="tick-n">--</span><span class="tchg dn-bg" id="tchg-n">--</span></div>
        <div class="tick"><span class="tlbl">BANKNIFTY</span><span class="tval up" id="tick-b">--</span><span class="tchg up-bg" id="tchg-b">--</span></div>
        <div class="tick"><span class="tlbl">PCR</span><span class="tval am" id="tick-pcr">--</span><span class="tchg dn-bg" id="tick-pcr-bias">--</span></div>
        <div class="tick"><span class="tlbl">VIX</span><span class="tval dn" id="tick-vix">--</span><span class="tchg dn-bg">--</span></div>
        <div class="tick"><span class="tlbl">NIFTY</span><span class="tval dn" id="tick-n2">--</span><span class="tchg dn-bg">--</span></div>
        <div class="tick"><span class="tlbl">BANKNIFTY</span><span class="tval up" id="tick-b2">--</span><span class="tchg up-bg">--</span></div>
        <div class="tick"><span class="tlbl">PCR</span><span class="tval am" id="tick-pcr2">--</span><span class="tchg dn-bg">--</span></div>
        <div class="tick"><span class="tlbl">VIX</span><span class="tval dn">--</span><span class="tchg dn-bg">--</span></div>
      </div>
    </div>
    <div class="status-bar">
      <div class="mkt mkt-c" id="mkt-pill"><div class="mkt-dot"></div><span id="mkt-text">Market Closed</span></div>
      <span class="clk" id="clock">--:--:--</span>
    </div>
  </div>

  <!-- HOME PAGE -->
  <div class="page active" id="pg-home">
    <div class="main">
      <!-- PRICE WIDGET -->
      <div class="price-card">
        <div class="price-tabs">
          <div class="ptab active" id="tab-N" onclick="switchSym('NIFTY')">
            <div class="ptab-lbl">NIFTY 50</div>
            <div class="ptab-val dn" id="pv-N">--</div>
            <div class="ptab-chg dn" id="pc-N">--</div>
          </div>
          <div class="ptab" id="tab-B" onclick="switchSym('BANKNIFTY')">
            <div class="ptab-lbl">BANKNIFTY</div>
            <div class="ptab-val up" id="pv-B">--</div>
            <div class="ptab-chg up" id="pc-B">--</div>
          </div>
        </div>
        <div class="metrics">
          <div class="metric"><div class="mlbl">PCR</div><div class="mval am" id="m-pcr">--</div></div>
          <div class="metric"><div class="mlbl">VIX</div><div class="mval dn" id="m-vix">--</div></div>
          <div class="metric"><div class="mlbl">CE OI</div><div class="mval dn" id="m-ceoi">--</div></div>
          <div class="metric"><div class="mlbl">PE OI</div><div class="mval up" id="m-peoi">--</div></div>
        </div>
      </div>
      <!-- SYM TABS -->
      <div class="sym-row">
        <div class="sym-btn active" id="sym-N" onclick="setSym('NIFTY',this)">&#128202; NIFTY</div>
        <div class="sym-btn" id="sym-B" onclick="setSym('BANKNIFTY',this)">&#127981; BANKNIFTY</div>
      </div>
      <!-- TYPE TABS -->
      <div class="type-row">
        <div class="tbtn active" onclick="setType('basic',this)">&#128202; Basic</div>
        <div class="tbtn" onclick="setType('pro',this)">&#9889; PRO</div>
        <div class="tbtn" onclick="setType('smart',this)">&#129504; Smart MTF</div>
        <div class="tbtn" onclick="setType('sr',this)">&#127919; S and R</div>
      </div>
      <!-- SIGNAL CARD -->
      <div class="sig-card">
        <div class="sig-head">
          <div><div class="sig-title" id="sig-title">BASIC - NIFTY</div><div class="sig-sub">Institutional Smart Entry</div></div>
          <div class="sig-time" id="sig-time">--</div>
        </div>
        <div class="sig-body" id="sig-body">
          <div class="load-box"><div class="spinner"></div><div class="load-msg">Loading...</div></div>
        </div>
        <div class="sig-foot">
          <button class="btn-main" onclick="fetchSignal()">&#128260; Refresh Signal</button>
          <button class="btn-sec" onclick="copySignal()">&#128203; Copy</button>
        </div>
        <div class="watermark">POWERED BY KETAN AI</div>
      </div>
      <!-- P&L CARD -->
      <div class="pnl-card">
        <div class="pnl-head">
          <div><div class="pnl-title">&#128176; P and L Calculator</div><div class="pnl-sub">NIFTY=65, BANKNIFTY=35</div></div>
          <button class="tog" id="pnl-tog" onclick="togPnL()">Show</button>
        </div>
        <div id="pnl-body" style="display:none">
          <div class="pnl-inner">
            <div class="fgrid">
              <div><label class="flabel">Buy Price</label><input class="finput" type="number" id="p-buy" placeholder="185"></div>
              <div><label class="flabel">Sell Price</label><input class="finput" type="number" id="p-sell" placeholder="250"></div>
              <div><label class="flabel">Lots</label><input class="finput" type="number" id="p-lots" value="1"></div>
              <div><label class="flabel">Index</label>
                <select class="fsel" id="p-idx" onchange="syncLotSize()">
                  <option value="65">NIFTY (65)</option>
                  <option value="35">BANKNIFTY (35)</option>
                </select>
              </div>
              <div><label class="flabel">SL Price</label><input class="finput" type="number" id="p-sl" placeholder="139"></div>
              <div><label class="flabel">Lot Size</label><input class="finput" type="number" id="p-ls" value="65" readonly style="opacity:.6;cursor:not-allowed"></div>
            </div>
            <button class="calc-btn" onclick="calcPnL()">&#128202; Calculate P and L</button>
            <div class="res-box" id="pnl-res">
              <div style="font-size:.5rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;">Result</div>
              <div class="rgrid" id="pnl-rgrid"></div>
              <div class="rsum" id="pnl-rsum"><div style="font-size:.54rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px;">Net P and L</div><div class="rnet" id="pnl-net">--</div></div>
              <div style="margin-top:10px;background:var(--inp);border:1px solid var(--bdr);border-radius:10px;padding:10px 12px;">
                <div style="font-size:.46rem;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;margin-bottom:7px;">Target Scenarios</div>
                <div id="pnl-scen"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- VIDEO PAGE -->
  <div class="page" id="pg-video">
    <div class="main">
      <div class="ptitle">Video Session</div>
      <div class="psub">Real WebRTC - max 4 users</div>

      <!-- WAITING STATE -->
      <div id="vc-wait">
        <div class="vc-hero">
          <div class="vc-ic">&#128222;</div>
          <div class="vc-t">Start Live Session</div>
          <div class="vc-s">Real video call. Sab active users ko Telegram notification jayegi. Max 4 log join kar sakte hain.</div>
          <button class="vc-sb" onclick="vcStart()">Start Live Session</button>
        </div>
        <div id="vc-join-box" style="display:none">
          <div class="vcibox" style="margin-bottom:10px">
            <div style="font-size:.56rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;">Active Session</div>
            <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Participants</span><span style="font-family:monospace;font-size:.68rem;font-weight:700;color:#10b981" id="vc-join-cnt">--</span></div>
          </div>
          <button class="vc-sb" onclick="vcJoin()" style="background:linear-gradient(135deg,#10b981,#06b6d4)">Join Active Session</button>
        </div>
        <div class="vcibox" style="margin-top:10px">
          <div style="font-size:.56rem;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;">Info</div>
          <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Max Users</span><span style="font-family:monospace;font-size:.68rem;font-weight:700;color:#10b981">4</span></div>
          <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Notification</span><span style="font-family:monospace;font-size:.68rem;font-weight:700;color:#60a5fa">Telegram</span></div>
          <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Technology</span><span style="font-family:monospace;font-size:.68rem;font-weight:700;color:#a78bfa">WebRTC</span></div>
        </div>
      </div>

      <!-- ACTIVE CALL STATE -->
      <div id="vc-active" style="display:none">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <div style="font-size:.82rem;font-weight:700;display:flex;align-items:center;gap:8px;">
            Live
            <span id="vc-cnt" style="background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.3);color:#f87171;font-size:.58rem;padding:2px 9px;border-radius:20px;animation:vcPulse 1s infinite">LIVE</span>
            <span id="vc-pcnt" style="background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.2);color:#10b981;font-size:.58rem;padding:2px 9px;border-radius:20px;">1/4</span>
          </div>
          <div style="display:flex;gap:6px;">
            <div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.25);border-radius:8px;padding:4px 12px;font-size:.6rem;color:#f87171;cursor:pointer;" onclick="vcLeave()">Leave</div>
          </div>
        </div>

        <!-- VIDEO GRID - 2x2 -->
        <div id="vc-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
          <!-- Slot 0: Local (self) -->
          <div id="vc-slot-0" style="border-radius:16px;aspect-ratio:1;position:relative;overflow:hidden;background:#0a0f1a;border:2px solid rgba(59,130,246,.4);">
            <video id="vc-local-video" autoplay muted playsinline style="width:100%;height:100%;object-fit:cover;border-radius:14px;"></video>
            <div id="vc-local-off" style="display:none;width:100%;height:100%;position:absolute;top:0;left:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;background:linear-gradient(135deg,#1a3a5c,#0d2040);">
              <div style="width:52px;height:52px;border-radius:50%;background:rgba(59,130,246,.2);color:#60a5fa;display:flex;align-items:center;justify-content:center;font-size:1.4rem;font-weight:700;" id="vc-local-init">K</div>
              <div style="font-size:.62rem;font-weight:700;color:rgba(255,255,255,.9)" id="vc-local-name">You</div>
              <div style="font-size:.5rem;color:rgba(255,255,255,.5)">No Camera</div>
            </div>
            <div style="position:absolute;bottom:6px;left:6px;background:rgba(0,0,0,.6);border-radius:6px;padding:2px 7px;font-size:.5rem;color:#fff" id="vc-local-label">You (Host)</div>
            <div id="vc-mic-indicator" style="position:absolute;top:6px;right:6px;width:20px;height:20px;border-radius:50%;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;font-size:.65rem;">&#127908;</div>
          </div>
          <!-- Slots 1-3: Remote peers -->
          <div id="vc-slot-1" style="border-radius:16px;aspect-ratio:1;position:relative;overflow:hidden;background:#0a0f1a;border:1px dashed rgba(255,255,255,.15);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;">
            <video id="vc-remote-video-1" autoplay playsinline style="width:100%;height:100%;object-fit:cover;border-radius:14px;display:none;"></video>
            <div id="vc-remote-av-1" style="display:flex;flex-direction:column;align-items:center;gap:5px;"><div style="font-size:1.4rem;opacity:.25">&#128100;</div><div style="font-size:.58rem;color:var(--muted)" id="vc-remote-name-1">Waiting...</div></div>
          </div>
          <div id="vc-slot-2" style="border-radius:16px;aspect-ratio:1;position:relative;overflow:hidden;background:#0a0f1a;border:1px dashed rgba(255,255,255,.15);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;">
            <video id="vc-remote-video-2" autoplay playsinline style="width:100%;height:100%;object-fit:cover;border-radius:14px;display:none;"></video>
            <div id="vc-remote-av-2" style="display:flex;flex-direction:column;align-items:center;gap:5px;"><div style="font-size:1.4rem;opacity:.25">&#128100;</div><div style="font-size:.58rem;color:var(--muted)" id="vc-remote-name-2">Waiting...</div></div>
          </div>
          <div id="vc-slot-3" style="border-radius:16px;aspect-ratio:1;position:relative;overflow:hidden;background:#0a0f1a;border:1px dashed rgba(255,255,255,.15);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;">
            <video id="vc-remote-video-3" autoplay playsinline style="width:100%;height:100%;object-fit:cover;border-radius:14px;display:none;"></video>
            <div id="vc-remote-av-3" style="display:flex;flex-direction:column;align-items:center;gap:5px;"><div style="font-size:1.4rem;opacity:.25">&#128100;</div><div style="font-size:.58rem;color:var(--muted)" id="vc-remote-name-3">Waiting...</div></div>
          </div>
        </div>

        <!-- CONTROLS -->
        <div style="display:flex;gap:8px;margin-bottom:10px;">
          <div id="btn-mic" onclick="vcToggleMic()" style="flex:1;background:var(--inp);border:1px solid var(--bdr2);border-radius:14px;padding:12px;text-align:center;cursor:pointer;">
            <div id="mic-ic" style="font-size:1.3rem;margin-bottom:3px;">&#127908;</div>
            <div id="mic-txt" style="font-size:.56rem;color:var(--txt2);">Mic On</div>
          </div>
          <div id="btn-cam" onclick="vcToggleCam()" style="flex:1;background:var(--inp);border:1px solid var(--bdr2);border-radius:14px;padding:12px;text-align:center;cursor:pointer;">
            <div id="cam-ic" style="font-size:1.3rem;margin-bottom:3px;">&#128249;</div>
            <div id="cam-txt" style="font-size:.56rem;color:var(--txt2);">Cam On</div>
          </div>
          <div onclick="vcLeave()" style="flex:1;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.2);border-radius:14px;padding:12px;text-align:center;cursor:pointer;">
            <div style="font-size:1.3rem;margin-bottom:3px;">&#9940;&#65039;</div>
            <div style="font-size:.56rem;color:#f87171;">End</div>
          </div>
        </div>

        <!-- INFO -->
        <div class="vcibox">
          <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Duration</span><span style="font-family:monospace;font-size:.68rem;font-weight:700;color:#10b981" id="vc-dur">00:00</span></div>
          <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Participants</span><span style="font-family:monospace;font-size:.68rem;font-weight:700;color:#60a5fa" id="vc-parts-txt">1/4</span></div>
          <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Status</span><span style="font-family:monospace;font-size:.68rem;font-weight:700;color:#ef4444">LIVE</span></div>
        </div>
      </div>
    </div>
  </div>

  <!-- CONTACT PAGE -->
  <div class="page" id="pg-contact">
    <div class="main">
      <div class="ptitle">Contact</div>
      <div class="psub">Owner se directly contact karo</div>
      <div class="clist">
        <a class="citem" href="https://wa.me/qr/PQ5JLDLPQCBVI1" target="_blank"><div class="cic cwa">&#128241;</div><div><div class="cnm" style="color:#25D366">WhatsApp</div><div class="chd">Owner se baat karo</div></div></a>
        <a class="citem" href="https://t.me/KETAN_AI" target="_blank"><div class="cic ctg">&#9992;&#65039;</div><div><div class="cnm" style="color:#0088cc">Telegram</div><div class="chd">@KETAN_AI</div></div></a>
        <a class="citem" href="https://www.instagram.com/ketankondekar" target="_blank"><div class="cic cig">&#128247;</div><div><div class="cnm" style="color:#e1306c">Instagram</div><div class="chd">@ketankondekar</div></div></a>
      </div>
      <div class="icard">
        <div style="font-size:.8rem;font-weight:700;margin-bottom:12px;color:#60a5fa">App Info</div>
        <div class="irow"><span class="il">App</span><span class="iv" style="color:#34d399">KETAN AI</span></div>
        <div class="irow"><span class="il">UID</span><span class="iv" id="info-uid" style="color:#f59e0b">--</span></div>
        <div class="irow"><span class="il">Access</span><span class="iv" id="info-exp">--</span></div>
        <div class="irow"><span class="il">Lot Sizes</span><span class="iv">NIFTY:65 BN:35</span></div>
      </div>
    </div>
  </div>

  <!-- SETTINGS PAGE -->
  <div class="page" id="pg-settings">
    <div class="main">
      <div class="ptitle">Settings</div>
      <div class="psub">Apni preferences customize karo</div>
      <div class="sset">
        <div class="shed">Appearance</div>
        <div class="srow"><div class="sleft"><span class="sicon">&#127769;</span><div><div class="stxt">Dark Mode</div><div class="shint">Dark / Light theme</div></div></div><label class="sw"><input type="checkbox" id="sw-dark" checked onchange="onThemeSw(this)"><span class="sw-s"></span></label></div>
      </div>
      <div class="sset">
        <div class="shed">Trading</div>
        <div class="srow"><div class="sleft"><span class="sicon">&#128200;</span><div><div class="stxt">Default Index</div></div></div><select class="ssel" id="set-sym" onchange="saveSetting('def_sym',this.value)"><option value="NIFTY">NIFTY</option><option value="BANKNIFTY">BANKNIFTY</option></select></div>
        <div class="srow"><div class="sleft"><span class="sicon">&#9889;</span><div><div class="stxt">Default Signal</div></div></div><select class="ssel" id="set-type" onchange="saveSetting('def_type',this.value)"><option value="basic">Basic</option><option value="pro">PRO</option><option value="smart">Smart MTF</option><option value="sr">S and R</option></select></div>
      </div>
      <div class="sset">
        <div class="shed">Lot Sizes</div>
        <div class="srow"><div class="sleft"><span class="sicon">&#128202;</span><div><div class="stxt">NIFTY</div></div></div><span class="sbadge">65</span></div>
        <div class="srow"><div class="sleft"><span class="sicon">&#127981;</span><div><div class="stxt">BANKNIFTY</div></div></div><span class="sbadge">35</span></div>
      </div>
      <div class="sset">
        <div class="shed">Account</div>
        <div class="srow" onclick="logout()" style="cursor:pointer"><div class="sleft"><span class="sicon">&#128464;</span><div><div class="stxt" style="color:#ef4444">Logout</div><div class="shint">UID remove karke login page pe jao</div></div></div><span style="font-size:.7rem;color:var(--muted)">></span></div>
        <div class="srow" onclick="resetAll()" style="cursor:pointer"><div class="sleft"><span class="sicon">&#128465;&#65039;</span><div><div class="stxt" style="color:#f97316">Reset Settings</div></div></div><span style="font-size:.7rem;color:var(--muted)">></span></div>
      </div>
    </div>
  </div>

  <!-- BOTTOM NAV -->
  <div class="bnav">
    <div class="nitem active" id="nav-home" onclick="goPage('home')"><span class="nic">&#127968;</span><span class="nlb">Home</span></div>
    <div class="nitem" id="nav-video" onclick="goPage('video')"><span class="nic">&#127897;&#65039;</span><span class="nlb">Video</span></div>
    <div class="nitem" id="nav-contact" onclick="goPage('contact')"><span class="nic">&#128222;</span><span class="nlb">Contact</span></div>
    <div class="nitem" id="nav-settings" onclick="goPage('settings')"><span class="nic">&#9881;&#65039;</span><span class="nlb">Settings</span></div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// =============================================
// STATE
// =============================================
var UID = 0;
var CUR_SYM = 'NIFTY';
var CUR_TYPE = 'basic';
var SIG_TEXT = '';
var SIG_PT1 = 0, SIG_PT2 = 0, SIG_PT3 = 0;
var LOT = {NIFTY:65, BANKNIFTY:35};
var vcSec=0, vcCnt=1, vcTimer=null, micOn=true, camOn=true;
var VC_USERS = [
  {n:'You',  bg:'linear-gradient(135deg,#1a3a5c,#0d2040)', i:'K', t:'Host'},
  {n:'Ravi', bg:'linear-gradient(135deg,#1a3a1a,#0d2010)', i:'R', t:'Trader'},
  {n:'Priya',bg:'linear-gradient(135deg,#3a1a1a,#200d0d)', i:'P', t:'Analyst'},
  {n:'Amit', bg:'linear-gradient(135deg,#2a1a3a,#180d27)', i:'A', t:'Member'}
];

// =============================================
// STARTUP - After splash (3.5s)
// =============================================
setTimeout(function() {
  document.getElementById('splash').style.display = 'none';

  // Apply saved theme
  var th = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', th);
  document.getElementById('sw-dark').checked = (th === 'dark');
  document.getElementById('theme-btn').textContent = th === 'dark' ? '\u2600\ufe0f' : '&#127769;';

  var savedUID = localStorage.getItem('uid');
  if (savedUID) {
    UID = parseInt(savedUID);
    if (!localStorage.getItem('agreed')) {
      document.getElementById('tc-overlay').classList.add('show');
    } else {
      startApp();
    }
  } else {
    // Show login
    document.getElementById('login-screen').classList.add('show');
  }
}, 3500);

// =============================================
// LOGIN
// =============================================
function doLogin() {
  var val = document.getElementById('uid-input').value.trim();
  var errEl = document.getElementById('login-err');
  if (!val || isNaN(val) || parseInt(val) <= 0) {
    errEl.textContent = 'Valid Telegram UID daalo!';
    return;
  }
  errEl.textContent = 'Checking...';
  var uid = parseInt(val);
  fetch('/api/user/check?uid=' + uid)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.blocked) {
        errEl.textContent = 'Aapka account blocked hai. Owner se contact karo.';
        return;
      }
      if (!data.valid) {
        errEl.textContent = data.msg || 'Invalid UID ya access expired. Bot mein key activate karo.';
        return;
      }
      // Valid!
      UID = uid;
      localStorage.setItem('uid', uid);
      document.getElementById('login-screen').classList.remove('show');
      if (!localStorage.getItem('agreed')) {
        document.getElementById('tc-overlay').classList.add('show');
      } else {
        startApp();
      }
    })
    .catch(function() {
      errEl.textContent = 'Server se connect nahi ho pa raha. Bot chal raha hai?';
    });
}

// Enter key for login
document.getElementById('uid-input').addEventListener('keyup', function(e) {
  if (e.key === 'Enter') doLogin();
});

// =============================================
// TERMS
// =============================================
function agreeTC() {
  localStorage.setItem('agreed', '1');
  document.getElementById('tc-overlay').classList.remove('show');
  startApp();
  toast('Welcome to KETAN AI!');
}

// =============================================
// START APP
// =============================================
function startApp() {
  // Apply settings
  var ds = localStorage.getItem('def_sym') || 'NIFTY';
  var dt = localStorage.getItem('def_type') || 'basic';
  CUR_SYM = ds;
  CUR_TYPE = dt;
  var ss = document.getElementById('set-sym');
  if (ss) for (var i=0;i<ss.options.length;i++) if(ss.options[i].value===ds) ss.selectedIndex=i;
  var st = document.getElementById('set-type');
  if (st) for (var i=0;i<st.options.length;i++) if(st.options[i].value===dt) st.selectedIndex=i;

  // Update sym/type tab UI
  document.querySelectorAll('.sym-btn').forEach(function(b) {
    b.classList.toggle('active', b.id === 'sym-' + ds[0]);
  });

  // Update info
  var uEl = document.getElementById('info-uid');
  if (uEl) uEl.textContent = UID;

  // Start clock
  updateClock();
  setInterval(updateClock, 1000);

  // Fetch ticker + signal
  fetchTicker();
  setInterval(fetchTicker, 10000);

  updateSigTitle();
  fetchSignal();
  vcCheckStatus();
}

// =============================================
// CLOCK
// =============================================
function getIST() {
  // Always use IST (UTC+5:30) regardless of device timezone
  var now = new Date();
  var utc = now.getTime() + (now.getTimezoneOffset() * 60000);
  return new Date(utc + (5.5 * 3600000));
}

function updateClock() {
  var ist = getIST();
  var ck = document.getElementById('clock');
  var ht = document.getElementById('hdr-time');
  var timeStr = ist.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:true});
  var timeShort = ist.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:true});
  if (ck) ck.textContent = timeStr;
  if (ht) ht.textContent = timeShort;
  var h=ist.getHours(), m=ist.getMinutes(), d=ist.getDay();
  // Market: Mon-Fri, 9:15 AM to 3:30 PM IST
  var open = d>=1 && d<=5 && (h>9||(h===9&&m>=15)) && (h<15||(h===15&&m<=30));
  var pill = document.getElementById('mkt-pill');
  var txt  = document.getElementById('mkt-text');
  if (pill) pill.className = 'mkt ' + (open ? 'mkt-o' : 'mkt-c');
  if (txt)  txt.textContent = open ? 'Market Open' : 'Market Closed';
}

// =============================================
// FETCH TICKER - REAL API CALL
// =============================================
function fetchTicker() {
  if (!UID) return;
  fetch('/api/user/ticker?uid=' + UID)
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d || !d.nifty) return;
      // --- NIFTY ---
      var ns = d.nifty;
      var nc = parseFloat(d.nifty_chg) || 0;
      var ncp = parseFloat(d.nifty_chg_pct) || 0;
      setText('tick-n',  ns);
      setText('tick-n2', ns);
      setText('pv-N', ns);
      setText('pc-N', (nc >= 0 ? '+' : '') + ncp.toFixed(2) + '%');
      setClass('tick-n', 'tval ' + (nc >= 0 ? 'up' : 'dn'));
      setClass('pv-N',   'ptab-val ' + (nc >= 0 ? 'up' : 'dn'));
      // --- BANKNIFTY ---
      var bs = d.banknifty;
      var bc = parseFloat(d.bn_chg) || 0;
      var bcp = parseFloat(d.bn_chg_pct) || 0;
      setText('tick-b',  bs);
      setText('tick-b2', bs);
      setText('pv-B', bs);
      setText('pc-B', (bc >= 0 ? '+' : '') + bcp.toFixed(2) + '%');
      setClass('tick-b', 'tval ' + (bc >= 0 ? 'up' : 'dn'));
      setClass('pv-B',   'ptab-val ' + (bc >= 0 ? 'up' : 'dn'));
      // --- PCR ---
      if (d.pcr_n) {
        var pcr = parseFloat(d.pcr_n);
        var bias = pcr >= 1.0 ? 'Bullish' : (pcr >= 0.8 ? 'Neutral' : 'Bearish');
        setText('tick-pcr',      d.pcr_n);
        setText('tick-pcr2',     d.pcr_n);
        setText('tick-pcr-bias', bias);
        setText('m-pcr',         d.pcr_n);
      }
      // --- VIX ---
      if (d.vix && d.vix !== 'N/A') {
        setText('tick-vix', d.vix);
        setText('m-vix',    d.vix);
      }
      // --- CE/PE OI ---
      if (d.ce_oi) {
        var ceoi = (parseFloat(d.ce_oi)/1e7).toFixed(1) + 'Cr';
        var peoi = (parseFloat(d.pe_oi)/1e7).toFixed(1) + 'Cr';
        setText('m-ceoi', ceoi);
        setText('m-peoi', peoi);
      }
    })
    .catch(function(e) { console.log('Ticker error:', e); });
}

function fmtCr(n) {
  return (n / 1e7).toFixed(2);
}

// =============================================
// FETCH SIGNAL - REAL API CALL
// =============================================
function fetchSignal() {
  if (!UID) return;
  var body = document.getElementById('sig-body');
  var tm   = document.getElementById('sig-time');
  if (!body) return;
  body.innerHTML = '<div class="load-box"><div class="spinner"></div><div class="load-msg">Fetching ' + CUR_TYPE + ' signal for ' + CUR_SYM + '...</div></div>';
  if (tm) tm.textContent = '--';

  var url = '/api/user/signal?uid=' + UID + '&type=' + CUR_TYPE + '&symbol=' + CUR_SYM;
  fetch(url)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data || !data.text) {
        body.innerHTML = '<div class="sig-err">Signal data nahi mila. Dobara try karo.</div>';
        return;
      }
      SIG_TEXT = data.text;
      if (tm) tm.textContent = new Date().toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit'});

      // Display the signal text
      body.innerHTML = '<div class="sig-out">' + escapeHTML(data.text) + '</div>';

      // Try to parse numeric values for P&L auto-fill
      tryParsePremium(data.text);
    })
    .catch(function(e) {
      body.innerHTML = '<div class="sig-err">Error: ' + escapeHTML(e.message || 'Server se connect nahi hua') + '</div>';
    });
}

function tryParsePremium(text) {
  // Match exact pattern from bot: "Current Premium: Rs{number}" or "Current Premium: ₹{number}"
  var m = text.match(/Current Premium[^0-9]*([0-9]+)/);
  if (m) {
    var pb = document.getElementById('p-buy');
    if (pb) pb.value = m[1];
  }
  // Match premium SL: "Premium SL: Rs{number}"
  var msl = text.match(/Premium SL[^0-9]*([0-9]+)/);
  if (msl) {
    var ps = document.getElementById('p-sl');
    if (ps) ps.value = msl[1];
  }
  // Match TP1, TP2, TP3 for scenarios
  var tp1 = text.match(/TP1[^0-9]*([0-9]+)/);
  var tp2 = text.match(/TP2[^0-9]*([0-9]+)/);
  var tp3 = text.match(/TP3[^0-9]*([0-9]+)/);
  if (tp1) SIG_PT1 = parseInt(tp1[1]);
  if (tp2) SIG_PT2 = parseInt(tp2[1]);
  if (tp3) SIG_PT3 = parseInt(tp3[1]);
  // Sync lot size with current symbol
  syncLotSize();
}

function escapeHTML(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// =============================================
// NAVIGATION
// =============================================
function goPage(name) {
  // Hide all pages, show only target
  var pages = document.querySelectorAll('.page');
  pages.forEach(function(p) { p.style.display = 'none'; p.classList.remove('active'); });
  document.querySelectorAll('.nitem').forEach(function(n) { n.classList.remove('active'); });
  var p = document.getElementById('pg-' + name);
  var n = document.getElementById('nav-' + name);
  if (p) { p.style.display = 'block'; p.classList.add('active'); }
  if (n) n.classList.add('active');
  window.scrollTo(0, 0);
}

// =============================================
// SYMBOL + TYPE
// =============================================
function setSym(sym, el) {
  CUR_SYM = sym;
  document.querySelectorAll('.sym-btn').forEach(function(b) { b.classList.remove('active'); });
  if (el) el.classList.add('active');
  switchSym(sym);
  syncLotSize();
  updateSigTitle();
  fetchSignal();
  vcCheckStatus();
}

function switchSym(sym) {
  document.getElementById('tab-N').classList.toggle('active', sym==='NIFTY');
  document.getElementById('tab-B').classList.toggle('active', sym==='BANKNIFTY');
}

function setType(typ, el) {
  CUR_TYPE = typ;
  document.querySelectorAll('.tbtn').forEach(function(b) { b.classList.remove('active'); });
  if (el) el.classList.add('active');
  updateSigTitle();
  fetchSignal();
  vcCheckStatus();
}

function updateSigTitle() {
  var names = {basic:'BASIC', pro:'PRO', smart:'SMART MTF', sr:'S and R'};
  var el = document.getElementById('sig-title');
  if (el) el.textContent = (names[CUR_TYPE]||'BASIC') + ' - ' + CUR_SYM;
}

// =============================================
// COPY SIGNAL
// =============================================
function copySignal() {
  if (!SIG_TEXT) { toast('Pehle signal load karo!'); return; }
  if (navigator.clipboard) {
    navigator.clipboard.writeText(SIG_TEXT).then(function() { toast('Signal Copied!'); });
  } else {
    toast('Copy: signal text');
  }
}

// =============================================
// P&L CALCULATOR
// =============================================
function togPnL() {
  var b = document.getElementById('pnl-body');
  var t = document.getElementById('pnl-tog');
  if (!b) return;
  var open = b.style.display !== 'none';
  b.style.display = open ? 'none' : 'block';
  if (t) t.textContent = open ? 'Show' : 'Hide';
}

function syncLotSize() {
  var sel = document.getElementById('p-idx');
  var ls  = document.getElementById('p-ls');
  if (sel && ls) ls.value = sel.value;
  // Also sync with current symbol
  var symLS = LOT[CUR_SYM] || 65;
  if (ls) ls.value = symLS;
  if (sel) {
    for (var i=0; i<sel.options.length; i++) {
      if (parseInt(sel.options[i].value) === symLS) { sel.selectedIndex = i; break; }
    }
  }
}

function calcPnL() {
  var buy  = parseFloat(document.getElementById('p-buy').value) || 0;
  var sell = parseFloat(document.getElementById('p-sell').value) || 0;
  var lots = parseInt(document.getElementById('p-lots').value) || 1;
  var sl   = parseFloat(document.getElementById('p-sl').value) || 0;
  var ls   = parseInt(document.getElementById('p-ls').value) || 65;
  if (!buy) { toast('Buy price daalo!'); return; }
  var qty = lots * ls;
  var invest = buy * qty;
  var slLoss = sl > 0 ? Math.abs(buy - sl) * qty : 0;
  var net  = sell > 0 ? (sell - buy) * qty : null;
  var nPct = sell > 0 ? ((sell - buy) / buy * 100).toFixed(2) : null;
  var rr   = (sell > 0 && sl > 0) ? Math.abs((sell-buy)/(buy-sl)).toFixed(2) : '--';

  var rows = [
    ['Investment', 'Rs ' + Math.round(invest).toLocaleString(), '#60a5fa'],
    ['Total Qty',  qty,   '#94a3b8'],
    ['Lot Size',   ls,    '#94a3b8'],
    ['Lots',       lots,  '#94a3b8'],
    ['SL Loss',    'Rs ' + Math.round(slLoss).toLocaleString(), '#f87171'],
    ['R:R',        rr,    '#a78bfa']
  ];
  var gh = '';
  rows.forEach(function(r) {
    gh += '<div class="ritem"><div class="rlbl">' + r[0] + '</div><div class="rval" style="color:' + r[2] + '">' + r[1] + '</div></div>';
  });
  document.getElementById('pnl-rgrid').innerHTML = gh;

  // Scenarios from real parsed signal data
  var scHTML = '';
  if (SIG_PT1 > 0 && buy > 0) {
    var scenarios = [
      ['T1 (Rs' + SIG_PT1 + ')', SIG_PT1],
      ['T2 (Rs' + SIG_PT2 + ')', SIG_PT2],
      ['T3 (Rs' + SIG_PT3 + ')', SIG_PT3],
      ['SL  (Rs' + (parseFloat(document.getElementById('p-sl').value)||0) + ')', parseFloat(document.getElementById('p-sl').value)||0]
    ];
    scenarios.forEach(function(sc) {
      if (sc[1] <= 0) return;
      var p = (sc[1] - buy) * qty;
      var pct = ((sc[1] - buy) / buy * 100).toFixed(1);
      var col = p >= 0 ? '#34d399' : '#f87171';
      scHTML += '<div class="scrow"><span style="font-size:.62rem;color:var(--txt2)">' + sc[0] + '</span>';
      scHTML += '<span class="scenario-val" style="color:' + col + '">' + (p>=0?'+':'') + 'Rs ' + Math.round(Math.abs(p)).toLocaleString() + ' (' + pct + '%)</span></div>';
    });
    if (!scHTML) scHTML = '<div style="font-size:.62rem;color:var(--muted);text-align:center;padding:8px">Signal refresh karo aur phir calculate karo</div>';
  } else {
    scHTML = '<div style="font-size:.62rem;color:var(--muted);text-align:center;padding:8px">Signal refresh karo phir calculate karo (market hours mein)</div>';
  }
  document.getElementById('pnl-scen').innerHTML = scHTML;

  // Net
  var ne = document.getElementById('pnl-net');
  var su = document.getElementById('pnl-rsum');
  if (net !== null) {
    var isP = net >= 0;
    ne.textContent = (isP?'+':'') + 'Rs ' + Math.round(Math.abs(net)).toLocaleString() + ' (' + (isP?'+':'') + nPct + '%)';
    ne.style.color = isP ? '#34d399' : '#ef4444';
    su.className = 'rsum ' + (isP ? 'rsump' : 'rsuml');
  } else {
    ne.textContent = 'Sell price daalo';
    ne.style.color = 'var(--muted)';
    su.className = 'rsum';
  }
  document.getElementById('pnl-res').classList.add('show');
  toast('Calculated!');
}

// =============================================
// THEME
// =============================================
function toggleTheme() {
  var cur = document.documentElement.getAttribute('data-theme') || 'dark';
  var next = cur === 'dark' ? 'light' : 'dark';
  applyTheme(next);
}
function onThemeSw(el) { applyTheme(el.checked ? 'dark' : 'light'); }
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('theme', t);
  var tbtn = document.getElementById('theme-btn');
  if (tbtn) tbtn.textContent = t === 'dark' ? '\u2600\ufe0f' : '&#127769;';
  var sw = document.getElementById('sw-dark');
  if (sw) sw.checked = (t === 'dark');
  toast(t === 'dark' ? 'Dark Mode' : 'Light Mode');
}

// =============================================
// SETTINGS
// =============================================
function saveSetting(k, v) { localStorage.setItem(k, v); toast('Saved!'); }
function logout() {
  if (confirm('Logout karoge?')) { localStorage.removeItem('uid'); localStorage.removeItem('agreed'); location.reload(); }
}
function resetAll() {
  if (confirm('Sab settings reset?')) { localStorage.clear(); location.reload(); }
}

// =============================================
// VIDEO CALL - Real WebRTC
// =============================================
var VC = {
  stream: null,
  peers: {},       // uid -> RTCPeerConnection
  micOn: true,
  camOn: true,
  isHost: false,
  polling: null,
  durTimer: null,
  durSec: 0,
  pollIdx: {offers:0, answers:0, ice:0},
  myName: 'User'
};

var STUN = { iceServers: [
  {urls: 'stun:stun.l.google.com:19302'},
  {urls: 'stun:stun1.l.google.com:19302'},
  {urls: 'stun:stun2.l.google.com:19302'}
]};

// Check if session is active on page load
function vcCheckStatus() {
  fetch('/api/vc/status')
    .then(function(r){return r.json();})
    .then(function(d){
      if (d.active && d.count > 0 && d.host_uid != UID) {
        // Show join option
        var jb = document.getElementById('vc-join-box');
        if (jb) {
          jb.style.display = 'block';
          setText('vc-join-cnt', d.count + '/4');
        }
      }
    }).catch(function(){});
}

function vcGetMedia(callback) {
  // Step 1: Try video+audio together
  navigator.mediaDevices.getUserMedia({video:true, audio:true})
    .then(function(stream) { callback(stream, true, true); })
    .catch(function(e1) {
      // Step 2: Maybe mic not available - try video only
      if (e1.name === 'NotFoundError' || e1.name === 'OverconstrainedError') {
        navigator.mediaDevices.getUserMedia({video:true, audio:false})
          .then(function(stream) {
            toast('Mic nahi mila - sirf camera chal raha hai');
            callback(stream, true, false);
          })
          .catch(function(e2) {
            // Step 3: Maybe camera not available - try audio only
            navigator.mediaDevices.getUserMedia({video:false, audio:true})
              .then(function(stream) {
                toast('Camera nahi mila - sirf audio chal raha hai');
                callback(stream, false, true);
              })
              .catch(function(e3) {
                vcPermissionError(e3);
              });
          });
      } else if (e1.name === 'NotAllowedError' || e1.name === 'PermissionDeniedError') {
        // Permission denied - try video only (mic might be denied separately)
        navigator.mediaDevices.getUserMedia({video:true, audio:false})
          .then(function(stream) {
            toast('Mic permission nahi mili - sirf camera chal raha hai');
            callback(stream, true, false);
          })
          .catch(function() {
            vcPermissionError(e1);
          });
      } else {
        vcPermissionError(e1);
      }
    });
}

function vcPermissionError(e) {
  var msg = '';
  if (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError') {
    msg = 'Permission deny! Chrome settings mein:\nSettings > Site Settings > Camera/Microphone > Allow karo';
  } else if (e.name === 'NotFoundError') {
    msg = 'Camera ya Mic nahi mila. Device check karo.';
  } else if (e.name === 'NotReadableError') {
    msg = 'Camera already use ho raha hai. Doosra app band karo.';
  } else if (e.name === 'SecurityError') {
    msg = 'HTTPS chahiye video call ke liye. Cloudflare URL use karo.';
  } else {
    msg = 'Media error: ' + (e.message || e.name || 'unknown');
  }
  alert(msg);
  toast('Permission error - details dekho');
}

function vcStart() {
  toast('Camera/mic permission maang raha hoon...');
  vcGetMedia(function(stream, hasVideo, hasAudio) {
    VC.stream = stream;
    VC.isHost = true;
    VC.myName = 'User ' + UID;
    VC.micOn = hasAudio;
    VC.camOn = hasVideo;
    showVCActive();
    // Show local video
    var lv = document.getElementById('vc-local-video');
    if (lv && hasVideo) { lv.srcObject = stream; lv.style.display='block'; }
    var lo = document.getElementById('vc-local-off');
    if (lo) lo.style.display = hasVideo ? 'none' : 'flex';
    // Update mic/cam button states
    updateMicUI();
    updateCamUI();
    // Start room on server
    fetch('/api/vc/start', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({uid: UID, name: VC.myName})
    })
    .then(function(r){return r.json();})
    .then(function(d){
      if (d.ok) {
        toast('Session started! Sabko Telegram notification gayi');
        startVCPoll();
        startVCTimer();
      } else {
        toast('Error: ' + (d.msg||'server error'));
        vcCleanup();
      }
    })
    .catch(function(e) {
      toast('Server error: ' + e.message);
      vcCleanup();
    });
  });
}

function vcJoin() {
  toast('Camera/mic permission maang raha hoon...');
  vcGetMedia(function(stream, hasVideo, hasAudio) {
    VC.stream = stream;
    VC.isHost = false;
    VC.myName = 'User ' + UID;
    VC.micOn = hasAudio;
    VC.camOn = hasVideo;
    showVCActive();
    var lv = document.getElementById('vc-local-video');
    if (lv && hasVideo) { lv.srcObject = stream; lv.style.display='block'; }
    var lo = document.getElementById('vc-local-off');
    if (lo) lo.style.display = hasVideo ? 'none' : 'flex';
    updateMicUI();
    updateCamUI();
    fetch('/api/vc/join', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({uid: UID, name: VC.myName})
    })
    .then(function(r){return r.json();})
    .then(function(d){
      if (!d.ok) { toast(d.msg || 'Join failed'); vcCleanup(); return; }
      toast('Joined! ' + d.count + '/4 participants');
      startVCPoll();
      startVCTimer();
      var parts = d.participants || [];
      parts.forEach(function(p) {
        if (p.uid != UID) vcCreateOffer(p.uid, p.name);
      });
    })
    .catch(function(e){
      toast('Server error: ' + e.message);
      vcCleanup();
    });
  });
}

function vcCreateOffer(toUid, toName) {
  var pc = new RTCPeerConnection(STUN);
  VC.peers[toUid] = pc;
  // Add local tracks
  if (VC.stream) {
    VC.stream.getTracks().forEach(function(track) {
      pc.addTrack(track, VC.stream);
    });
  }
  // Handle remote stream
  pc.ontrack = function(e) { vcShowRemoteStream(e.streams[0], toUid, toName); };
  // ICE candidates
  pc.onicecandidate = function(e) {
    if (e.candidate) {
      fetch('/api/vc/ice', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({from_uid:UID, to_uid:toUid, candidate:e.candidate})
      });
    }
  };
  // Create offer
  pc.createOffer()
    .then(function(offer) { return pc.setLocalDescription(offer).then(function(){return offer;}); })
    .then(function(offer) {
      fetch('/api/vc/offer', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({from_uid:UID, to_uid:toUid, sdp:offer, name:VC.myName})
      });
    })
    .catch(function(e){ console.log('offer error', e); });
}

function vcHandleOffer(data) {
  var fromUid = data.from_uid;
  var name = data.name || 'User';
  var pc = new RTCPeerConnection(STUN);
  VC.peers[fromUid] = pc;
  if (VC.stream) {
    VC.stream.getTracks().forEach(function(track) {
      pc.addTrack(track, VC.stream);
    });
  }
  pc.ontrack = function(e) { vcShowRemoteStream(e.streams[0], fromUid, name); };
  pc.onicecandidate = function(e) {
    if (e.candidate) {
      fetch('/api/vc/ice', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({from_uid:UID, to_uid:fromUid, candidate:e.candidate})
      });
    }
  };
  pc.setRemoteDescription(new RTCSessionDescription(data.sdp))
    .then(function(){ return pc.createAnswer(); })
    .then(function(ans){ return pc.setLocalDescription(ans).then(function(){return ans;}); })
    .then(function(ans){
      fetch('/api/vc/answer', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({from_uid:UID, to_uid:fromUid, sdp:ans})
      });
    })
    .catch(function(e){ console.log('answer error', e); });
}

function vcHandleAnswer(data) {
  var pc = VC.peers[data.from_uid];
  if (!pc) return;
  pc.setRemoteDescription(new RTCSessionDescription(data.sdp))
    .catch(function(e){ console.log('set answer error', e); });
}

function vcHandleICE(data) {
  var pc = VC.peers[data.from_uid];
  if (!pc) return;
  pc.addIceCandidate(new RTCIceCandidate(data.candidate))
    .catch(function(e){ console.log('ice error', e); });
}

function vcShowRemoteStream(stream, uid, name) {
  // Find empty slot
  for (var i=1; i<=3; i++) {
    var vid = document.getElementById('vc-remote-video-' + i);
    var av  = document.getElementById('vc-remote-av-' + i);
    var nm  = document.getElementById('vc-remote-name-' + i);
    if (vid && vid.style.display === 'none') {
      vid.srcObject = stream;
      vid.style.display = 'block';
      if (av) av.style.display = 'none';
      if (nm) nm.textContent = name;
      var slot = document.getElementById('vc-slot-' + i);
      if (slot) slot.style.borderColor = 'rgba(16,185,129,.4)';
      toast(name + ' joined!');
      break;
    }
  }
}

// Polling for new signals
function startVCPoll() {
  VC.polling = setInterval(function() {
    var url = '/api/vc/poll?uid=' + UID + '&lo=' + VC.pollIdx.offers + '&la=' + VC.pollIdx.answers + '&li=' + VC.pollIdx.ice;
    fetch(url)
      .then(function(r){return r.json();})
      .then(function(d){
        if (!d.ok) return;
        // Update counts
        if (d.offer_idx  !== undefined) VC.pollIdx.offers  = d.offer_idx;
        if (d.answer_idx !== undefined) VC.pollIdx.answers = d.answer_idx;
        if (d.ice_idx    !== undefined) VC.pollIdx.ice     = d.ice_idx;
        // Handle signals
        (d.offers  || []).forEach(function(o){ vcHandleOffer(o); });
        (d.answers || []).forEach(function(a){ vcHandleAnswer(a); });
        (d.ice     || []).forEach(function(i){ vcHandleICE(i); });
        // Update participant count
        var cnt = d.count || 1;
        setText('vc-pcnt', cnt + '/4');
        setText('vc-parts-txt', cnt + '/4');
        // If host left
        if (!d.active && !VC.isHost) {
          toast('Host ne session end kiya');
          vcLeave();
        }
      })
      .catch(function(){});
  }, 1500);
}

function startVCTimer() {
  VC.durSec = 0;
  VC.durTimer = setInterval(function() {
    VC.durSec++;
    var m=Math.floor(VC.durSec/60), s=VC.durSec%60;
    setText('vc-dur', (m<10?'0':'')+m+':'+(s<10?'0':'')+s);
  }, 1000);
}

function updateMicUI() {
  var ic = document.getElementById('mic-ic');
  var tx = document.getElementById('mic-txt');
  var ind = document.getElementById('vc-mic-indicator');
  var hasMic = VC.stream && VC.stream.getAudioTracks().length > 0;
  if (ic) ic.innerHTML = (!hasMic) ? '&#128263;' : (VC.micOn ? '&#127908;' : '&#128263;');
  if (tx) tx.textContent = (!hasMic) ? 'No Mic' : (VC.micOn ? 'Mic On' : 'Mic Off');
  if (ind) ind.innerHTML = (!hasMic) ? '&#128263;' : (VC.micOn ? '&#127908;' : '&#128263;');
}

function updateCamUI() {
  var ic = document.getElementById('cam-ic');
  var tx = document.getElementById('cam-txt');
  var hasCam = VC.stream && VC.stream.getVideoTracks().length > 0;
  if (ic) ic.innerHTML = (!hasCam) ? '&#128680;' : (VC.camOn ? '&#128249;' : '&#128680;');
  if (tx) tx.textContent = (!hasCam) ? 'No Cam' : (VC.camOn ? 'Cam On' : 'Cam Off');
}

function vcToggleMic() {
  if (!VC.stream || VC.stream.getAudioTracks().length === 0) {
    toast('Mic nahi hai. Permission check karo.');
    return;
  }
  VC.micOn = !VC.micOn;
  VC.stream.getAudioTracks().forEach(function(t){ t.enabled = VC.micOn; });
  updateMicUI();
  toast('Mic ' + (VC.micOn?'ON':'OFF'));
}

function vcToggleCam() {
  if (!VC.stream || VC.stream.getVideoTracks().length === 0) {
    toast('Camera nahi hai. Permission check karo.');
    return;
  }
  VC.camOn = !VC.camOn;
  VC.stream.getVideoTracks().forEach(function(t){ t.enabled = VC.camOn; });
  var lv = document.getElementById('vc-local-video');
  var lo = document.getElementById('vc-local-off');
  if (lv) lv.style.display = VC.camOn ? 'block' : 'none';
  if (lo) lo.style.display = VC.camOn ? 'none' : 'flex';
  updateCamUI();
  toast('Camera ' + (VC.camOn?'ON':'OFF'));
}

function vcLeave() {
  fetch('/api/vc/leave', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({uid: UID})
  }).catch(function(){});
  vcCleanup();
  toast('Session se leave kar diya');
}

function vcCleanup() {
  // Stop polling
  if (VC.polling)  { clearInterval(VC.polling);  VC.polling=null;  }
  if (VC.durTimer) { clearInterval(VC.durTimer); VC.durTimer=null; }
  // Close all peer connections
  Object.keys(VC.peers).forEach(function(uid) {
    try { VC.peers[uid].close(); } catch(e){}
  });
  VC.peers = {};
  // Stop media stream
  if (VC.stream) {
    VC.stream.getTracks().forEach(function(t){ t.stop(); });
    VC.stream = null;
  }
  // Reset UI
  for (var i=1; i<=3; i++) {
    var vid = document.getElementById('vc-remote-video-' + i);
    var av  = document.getElementById('vc-remote-av-' + i);
    if (vid) { vid.srcObject=null; vid.style.display='none'; }
    if (av)  { av.style.display='flex'; }
    var slot = document.getElementById('vc-slot-' + i);
    if (slot) slot.style.borderColor = 'rgba(255,255,255,.15)';
  }
  var lv = document.getElementById('vc-local-video');
  if (lv) lv.srcObject = null;
  VC.pollIdx = {offers:0, answers:0, ice:0};
  VC.durSec = 0;
  // Show waiting screen
  document.getElementById('vc-wait').style.display = 'block';
  document.getElementById('vc-active').style.display = 'none';
  vcCheckStatus();
}

function showVCActive() {
  document.getElementById('vc-wait').style.display = 'none';
  document.getElementById('vc-active').style.display = 'block';
  var nameEl = document.getElementById('vc-local-label');
  if (nameEl) nameEl.textContent = 'You' + (VC.isHost ? ' (Host)' : '');
}

// =============================================
// HELPERS
// =============================================
function setText(id, val) { var e=document.getElementById(id); if(e) e.textContent=val; }
function setHTML(id, val) { var e=document.getElementById(id); if(e) e.innerHTML=val; }
function setClass(id, cls) { var e=document.getElementById(id); if(e) e.className=cls; }
function toast(msg) {
  var t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(function() { t.classList.remove('show'); }, 2200);
}
</script>
</body>
</html>
"""

USER_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>KETAN AI</title>
<style>
:root{--bg:#04060d;--surf:#080c18;--card:#0c1220;--bdr:rgba(255,255,255,.07);--bdr2:rgba(255,255,255,.12);--txt:#f1f5f9;--txt2:#94a3b8;--muted:#64748b;--hbg:rgba(4,6,13,.97);--inp:rgba(255,255,255,.05);--sh:rgba(0,0,0,.5);--nav:#080c18;}
[data-theme="light"]{--bg:#eef2f7;--surf:#e2e8f0;--card:#f8fafc;--bdr:rgba(15,23,42,.08);--bdr2:rgba(15,23,42,.14);--txt:#1e293b;--txt2:#475569;--muted:#94a3b8;--hbg:rgba(238,242,247,.97);--inp:rgba(15,23,42,.05);--sh:rgba(15,23,42,.12);--nav:#f1f5f9;}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);color:var(--txt);font-family:Arial,sans-serif;min-height:100vh;overflow-x:hidden;}

/* SPLASH */
#splash{position:fixed;inset:0;z-index:9000;background:#04060d;display:flex;flex-direction:column;align-items:center;justify-content:center;}
.sp-ring{width:100px;height:100px;border-radius:50%;position:relative;display:flex;align-items:center;justify-content:center;margin:0 auto 20px;}
.sp-ring-o{position:absolute;inset:-3px;border-radius:50%;background:conic-gradient(#3b82f6,#8b5cf6,#ef4444,#10b981,#3b82f6);animation:ringR 2s linear infinite;}
@keyframes ringR{to{transform:rotate(360deg)}}
.sp-ring-i{position:absolute;inset:3px;border-radius:50%;background:#04060d;}
.sp-face{position:relative;z-index:1;font-size:2.8rem;}
.sp-t1{font-size:2rem;font-weight:900;background:linear-gradient(135deg,#60a5fa,#34d399);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.sp-t2{font-size:.7rem;color:rgba(255,255,255,.3);letter-spacing:.15em;text-transform:uppercase;margin-top:6px;}
.sp-dots{display:flex;gap:8px;justify-content:center;margin-top:20px;}
.sp-dot{width:8px;height:8px;border-radius:50%;background:#3b82f6;}
.sp-dot:nth-child(1){animation:db 1s 0s infinite;}
.sp-dot:nth-child(2){animation:db 1s .25s infinite;}
.sp-dot:nth-child(3){animation:db 1s .5s infinite;}
@keyframes db{0%,100%{opacity:.2;transform:scale(.8)}50%{opacity:1;transform:scale(1.2)}}
.sp-bar{position:absolute;bottom:0;left:0;right:0;height:3px;}
.sp-prog{height:100%;background:linear-gradient(90deg,#3b82f6,#10b981);animation:prog 2.8s linear forwards;}
@keyframes prog{from{width:0}to{width:100%}}

/* LOGIN */
#login-screen{position:fixed;inset:0;z-index:8500;background:var(--bg);display:none;align-items:center;justify-content:center;padding:20px;}
.login-box{background:var(--card);border:1px solid var(--bdr2);border-radius:20px;padding:28px 24px;width:100%;max-width:360px;text-align:center;}
.login-logo{font-size:2.5rem;margin-bottom:12px;}
.login-title{font-size:1.3rem;font-weight:900;background:linear-gradient(135deg,#60a5fa,#34d399);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:6px;}
.login-sub{font-size:.75rem;color:var(--muted);margin-bottom:20px;line-height:1.6;}
.login-label{font-size:.65rem;color:var(--txt2);text-align:left;display:block;margin-bottom:6px;text-transform:uppercase;}
.login-input{width:100%;background:var(--inp);border:1px solid var(--bdr2);border-radius:12px;padding:13px 16px;color:var(--txt);font-size:1rem;font-weight:700;outline:none;text-align:center;letter-spacing:.1em;margin-bottom:16px;}
.login-btn{width:100%;background:linear-gradient(135deg,#3b82f6,#06b6d4);color:#fff;border:none;border-radius:12px;padding:14px;font-size:.9rem;font-weight:700;cursor:pointer;margin-bottom:10px;}
.login-err{font-size:.72rem;color:#f87171;min-height:20px;margin-top:4px;}
.login-help{font-size:.62rem;color:var(--muted);margin-top:12px;line-height:1.7;}

/* TERMS */
#tc-overlay{position:fixed;inset:0;z-index:8000;background:rgba(0,0,0,.85);backdrop-filter:blur(16px);display:none;align-items:flex-end;justify-content:center;}
.tc-box{background:var(--card);border:1px solid var(--bdr2);border-radius:24px 24px 0 0;width:100%;max-width:480px;max-height:85vh;display:flex;flex-direction:column;}
.tc-head{padding:18px 20px 12px;text-align:center;border-bottom:1px solid var(--bdr);}
.tc-drag{width:40px;height:4px;background:var(--bdr2);border-radius:4px;margin:0 auto 14px;}
.tc-title{font-size:1rem;font-weight:800;color:#60a5fa;}
.tc-scroll{flex:1;overflow-y:auto;padding:16px 20px;font-size:.72rem;color:var(--txt2);line-height:1.8;}
.tc-scroll h4{color:#60a5fa;margin:12px 0 6px;}
.tc-warn{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2);border-radius:10px;padding:10px;color:#f59e0b;}
.tc-foot{padding:14px 20px;border-top:1px solid var(--bdr);}
.tc-btn{width:100%;background:linear-gradient(135deg,#3b82f6,#06b6d4);color:#fff;border:none;border-radius:12px;padding:14px;font-size:.88rem;font-weight:700;cursor:pointer;}
.tc-note{text-align:center;font-size:.58rem;color:var(--muted);margin-top:8px;}

/* APP */
#app{display:none;padding-bottom:72px;}
.page{display:none;}

/* HEADER */
.hdr{position:sticky;top:0;z-index:100;background:var(--hbg);backdrop-filter:blur(24px);border-bottom:1px solid var(--bdr);}
.hdr-top{display:flex;align-items:center;justify-content:space-between;padding:44px 14px 9px;}
.logo{display:flex;align-items:center;gap:8px;}
.logo-text{font-weight:900;font-size:1rem;background:linear-gradient(135deg,#60a5fa,#34d399);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.hdr-right{display:flex;align-items:center;gap:6px;}
.pill{display:flex;align-items:center;gap:4px;padding:4px 10px;border-radius:20px;font-size:.58rem;font-weight:600;border:1px solid;}
.pill-g{background:rgba(16,185,129,.1);border-color:rgba(16,185,129,.2);color:#10b981;}
.pill-b{background:rgba(59,130,246,.1);border-color:rgba(59,130,246,.2);color:#60a5fa;font-family:monospace;}
.ldot{width:5px;height:5px;border-radius:50%;background:#10b981;animation:pulse 1.5s infinite;}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(16,185,129,.4)}50%{box-shadow:0 0 0 4px rgba(16,185,129,0)}}
.ibtn{width:32px;height:32px;border-radius:9px;border:1px solid var(--bdr2);background:var(--card);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:.82rem;}
.ibtn:active{transform:scale(.9);}

/* TICKER */
.ticker-wrap{overflow:hidden;border-bottom:1px solid var(--bdr);background:var(--surf);}
.ticker-inner{display:flex;animation:tickerMove 30s linear infinite;width:max-content;}
@keyframes tickerMove{from{transform:translateX(0)}to{transform:translateX(-50%)}}
.tick{display:flex;align-items:center;gap:6px;padding:7px 16px;border-right:1px solid var(--bdr);white-space:nowrap;}
.tlbl{font-size:.5rem;color:var(--muted);text-transform:uppercase;}
.tval{font-family:monospace;font-size:.7rem;font-weight:700;}
.tchg{font-size:.48rem;padding:1px 5px;border-radius:4px;}
.up{color:#10b981;}.dn{color:#ef4444;}.am{color:#f59e0b;}
.up-bg{background:rgba(16,185,129,.12);color:#10b981;}.dn-bg{background:rgba(239,68,68,.12);color:#ef4444;}

/* STATUS BAR */
.status-bar{display:flex;justify-content:space-between;align-items:center;padding:6px 14px;border-bottom:1px solid var(--bdr);}
.mkt{display:flex;align-items:center;gap:5px;padding:3px 10px;border-radius:20px;font-size:.6rem;font-weight:600;}
.mkt-o{background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.2);color:#10b981;}
.mkt-c{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.2);color:#ef4444;}
.mkt-dot{width:6px;height:6px;border-radius:50%;background:currentColor;animation:pulse 1s infinite;}
.clk{font-family:monospace;font-size:.6rem;color:var(--txt2);}

/* MAIN */
.main{padding:12px 14px;max-width:480px;margin:0 auto;}

/* PRICE CARD */
.price-card{background:var(--card);border:1px solid var(--bdr2);border-radius:20px;overflow:hidden;margin-bottom:12px;box-shadow:0 4px 24px var(--sh);}
.price-tabs{display:grid;grid-template-columns:1fr 1fr;gap:7px;padding:14px 14px 0;}
.ptab{padding:11px 10px;border-radius:12px;cursor:pointer;border:1px solid var(--bdr);background:var(--inp);}
.ptab.active{background:rgba(59,130,246,.1);border-color:rgba(59,130,246,.35);}
.ptab-lbl{font-size:.5rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px;}
.ptab-val{font-family:monospace;font-size:.88rem;font-weight:700;}
.ptab-chg{font-size:.5rem;margin-top:2px;}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;padding:10px 14px 14px;}
.metric{background:var(--inp);border:1px solid var(--bdr);border-radius:10px;padding:7px 8px;text-align:center;}
.mlbl{font-size:.44rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px;}
.mval{font-family:monospace;font-size:.68rem;font-weight:700;}

/* TABS */
.sym-row{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:9px;}
.sym-btn{padding:10px;border-radius:12px;text-align:center;font-size:.72rem;font-weight:700;cursor:pointer;border:1px solid var(--bdr);background:var(--inp);color:var(--muted);}
.sym-btn.active{border-color:rgba(59,130,246,.4);color:#60a5fa;background:rgba(59,130,246,.08);}
.type-row{display:flex;gap:6px;margin-bottom:10px;overflow-x:auto;padding-bottom:2px;}
.type-row::-webkit-scrollbar{display:none;}
.tbtn{display:flex;align-items:center;gap:4px;padding:7px 13px;border-radius:20px;font-size:.63rem;font-weight:600;cursor:pointer;white-space:nowrap;flex-shrink:0;border:1px solid var(--bdr);background:var(--inp);color:var(--muted);}
.tbtn.active{border-color:rgba(59,130,246,.4);color:#60a5fa;background:rgba(59,130,246,.1);}

/* SIGNAL CARD */
.sig-card{background:var(--card);border:1px solid var(--bdr2);border-radius:20px;overflow:hidden;margin-bottom:12px;box-shadow:0 4px 24px var(--sh);}
.sig-head{padding:14px 16px 12px;border-bottom:1px solid var(--bdr);display:flex;justify-content:space-between;align-items:flex-start;}
.sig-title{font-size:.8rem;font-weight:700;color:#60a5fa;}
.sig-sub{font-size:.54rem;color:var(--muted);margin-top:2px;}
.sig-time{font-family:monospace;font-size:.52rem;color:var(--muted);}
.sig-body{min-height:80px;}
.load-box{display:flex;flex-direction:column;align-items:center;padding:32px;gap:10px;}
.spinner{width:26px;height:26px;border:2.5px solid var(--bdr);border-top-color:#3b82f6;border-radius:50%;animation:spin .7s linear infinite;}
@keyframes spin{to{transform:rotate(360deg)}}
.load-msg{font-size:.68rem;color:var(--muted);}
.sig-out{padding:12px 16px;font-size:.76rem;line-height:1.9;color:var(--txt);white-space:pre-wrap;font-family:monospace;}
.sig-err{padding:20px 16px;font-size:.74rem;color:#f87171;text-align:center;}
.sig-foot{padding:10px 14px;border-top:1px solid var(--bdr);display:flex;gap:8px;}
.btn-main{flex:1;background:linear-gradient(135deg,#3b82f6,#06b6d4);color:#fff;border:none;border-radius:12px;padding:11px;font-size:.76rem;font-weight:700;cursor:pointer;}
.btn-main:active{transform:scale(.97);}
.btn-sec{background:var(--inp);border:1px solid var(--bdr2);border-radius:12px;padding:11px 14px;font-size:.76rem;color:var(--txt2);cursor:pointer;}
.watermark{text-align:center;padding:7px;font-size:.5rem;color:var(--muted);border-top:1px solid var(--bdr);}

/* P&L */
.pnl-card{background:var(--card);border:1px solid var(--bdr2);border-radius:20px;overflow:hidden;margin-bottom:12px;}
.pnl-head{padding:14px 16px;border-bottom:1px solid var(--bdr);display:flex;justify-content:space-between;align-items:center;}
.pnl-title{font-size:.8rem;font-weight:700;color:#34d399;}
.pnl-sub{font-size:.54rem;color:var(--muted);margin-top:2px;}
.tog{font-size:.58rem;font-weight:600;padding:4px 10px;border-radius:20px;cursor:pointer;border:1px solid var(--bdr2);background:var(--inp);color:var(--txt2);}
.pnl-inner{padding:14px 16px;}
.fgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;}
.flabel{font-size:.48rem;color:var(--muted);text-transform:uppercase;display:block;margin-bottom:5px;}
.finput{width:100%;background:var(--inp);border:1px solid var(--bdr2);border-radius:10px;padding:9px 12px;color:var(--txt);font-size:.84rem;font-family:monospace;font-weight:700;outline:none;}
.fsel{width:100%;background:var(--inp);border:1px solid var(--bdr2);border-radius:10px;padding:9px 12px;color:var(--txt);font-size:.78rem;outline:none;cursor:pointer;}
.calc-btn{width:100%;background:linear-gradient(135deg,#10b981,#06b6d4);color:#fff;border:none;border-radius:12px;padding:12px;font-size:.82rem;font-weight:700;cursor:pointer;margin-bottom:12px;}
.res-box{display:none;background:var(--inp);border:1px solid var(--bdr);border-radius:14px;padding:14px;}
.res-box.show{display:block;}
.rgrid{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:10px;}
.ritem{background:var(--card);border:1px solid var(--bdr);border-radius:10px;padding:8px 10px;text-align:center;}
.rlbl{font-size:.44rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px;}
.rval{font-family:monospace;font-size:.78rem;font-weight:700;}
.rsum{margin-top:10px;padding:12px;border-radius:10px;border:1px solid;text-align:center;}
.rsump{background:rgba(16,185,129,.08);border-color:rgba(16,185,129,.2);}
.rsuml{background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.2);}
.rnet{font-family:monospace;font-size:1.1rem;font-weight:700;}
.scrow{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--bdr);}
.scrow:last-child{border:none;}

/* CONTACT PAGE */
.ptitle{font-size:1.1rem;font-weight:800;margin-bottom:4px;}
.psub{font-size:.72rem;color:var(--muted);margin-bottom:16px;}
.clist{background:var(--card);border:1px solid var(--bdr2);border-radius:18px;overflow:hidden;margin-bottom:10px;}
.citem{display:flex;align-items:center;gap:14px;padding:15px 16px;border-bottom:1px solid var(--bdr);text-decoration:none;color:var(--txt);}
.citem:last-child{border:none;}
.citem:active{background:var(--inp);}
.cic{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:1.3rem;flex-shrink:0;}
.cwa{background:rgba(37,211,102,.12);border:1px solid rgba(37,211,102,.2);}
.ctg{background:rgba(0,136,204,.12);border:1px solid rgba(0,136,204,.2);}
.cig{background:rgba(225,48,108,.12);border:1px solid rgba(225,48,108,.2);}
.cnm{font-weight:700;font-size:.82rem;}
.chd{font-size:.62rem;color:var(--muted);margin-top:2px;}
.icard{background:var(--card);border:1px solid var(--bdr2);border-radius:18px;padding:18px;margin-bottom:10px;}
.irow{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--bdr);}
.irow:last-child{border:none;}
.il{font-size:.7rem;color:var(--muted);}
.iv{font-family:monospace;font-size:.7rem;font-weight:700;}

/* SETTINGS PAGE */
.sset{background:var(--card);border:1px solid var(--bdr2);border-radius:18px;overflow:hidden;margin-bottom:12px;}
.shed{padding:12px 16px;border-bottom:1px solid var(--bdr);font-size:.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-weight:600;}
.srow{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--bdr);}
.srow:last-child{border:none;}
.sleft{display:flex;align-items:center;gap:10px;}
.sicon{font-size:1.1rem;width:28px;text-align:center;}
.stxt{font-size:.8rem;font-weight:600;}
.shint{font-size:.6rem;color:var(--muted);margin-top:2px;}
.sw{position:relative;width:46px;height:26px;flex-shrink:0;}
.sw input{opacity:0;width:0;height:0;}
.sw-s{position:absolute;cursor:pointer;inset:0;background:rgba(255,255,255,.1);border-radius:26px;transition:.3s;border:1px solid var(--bdr2);}
.sw-s::before{content:'';position:absolute;height:18px;width:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s;}
input:checked+.sw-s{background:linear-gradient(135deg,#3b82f6,#06b6d4);}
input:checked+.sw-s::before{transform:translateX(20px);}
.ssel{background:var(--inp);border:1px solid var(--bdr2);border-radius:8px;padding:5px 10px;color:var(--txt);font-size:.74rem;outline:none;cursor:pointer;}
.sbadge{font-family:monospace;font-size:.64rem;font-weight:700;padding:3px 10px;border-radius:20px;background:rgba(59,130,246,.1);color:#60a5fa;border:1px solid rgba(59,130,246,.2);}
.danger-btn{width:100%;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.2);border-radius:12px;padding:12px;color:#ef4444;font-size:.82rem;font-weight:700;cursor:pointer;margin-top:8px;}

/* VIDEO PAGE */
.vc-hero{background:linear-gradient(135deg,rgba(16,185,129,.08),rgba(59,130,246,.06));border:1px solid rgba(16,185,129,.15);border-radius:20px;padding:24px 20px;text-align:center;margin-bottom:14px;}
.vc-t{font-size:1.1rem;font-weight:800;margin-bottom:6px;background:linear-gradient(135deg,#34d399,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.vc-s{font-size:.72rem;color:var(--muted);line-height:1.7;}
.vc-sb{width:100%;background:linear-gradient(135deg,#10b981,#06b6d4);color:#fff;border:none;border-radius:16px;padding:15px;font-size:.9rem;font-weight:700;cursor:pointer;margin-top:14px;}
.vcibox{background:var(--card);border:1px solid var(--bdr2);border-radius:14px;padding:14px 16px;margin-bottom:10px;}
.vcirow{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--bdr);}
.vcirow:last-child{border:none;}

/* BOTTOM NAV */
.bnav{position:fixed;bottom:0;left:0;right:0;z-index:200;background:var(--nav);border-top:1px solid var(--bdr2);backdrop-filter:blur(20px);display:flex;padding:8px 0 calc(8px + env(safe-area-inset-bottom));}
.nitem{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;padding:6px 4px;}
.nic{font-size:1.25rem;line-height:1;}
.nlb{font-size:.5rem;font-weight:600;color:var(--muted);}
.nitem.active .nlb{color:#3b82f6;}
.nitem.active .nic{filter:drop-shadow(0 0 6px rgba(59,130,246,.5));}

/* TOAST */
.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:var(--card);border:1px solid var(--bdr2);border-radius:12px;padding:10px 20px;font-size:.76rem;color:var(--txt);opacity:0;pointer-events:none;transition:opacity .3s;z-index:9999;white-space:nowrap;box-shadow:0 8px 32px var(--sh);}
.toast.show{opacity:1;}
@keyframes vcPulse{0%,100%{opacity:1}50%{opacity:.3}}
.vc-notif{position:fixed;top:60px;left:50%;transform:translateX(-50%);background:linear-gradient(135deg,#10b981,#06b6d4);color:#fff;padding:12px 20px;border-radius:14px;font-size:.76rem;font-weight:700;z-index:9998;white-space:nowrap;box-shadow:0 8px 32px rgba(0,0,0,.4);display:none;text-align:center;}
</style>
</head>
<body>

<!-- SPLASH -->
<div id="splash">
  <div class="sp-ring"><div class="sp-ring-o"></div><div class="sp-ring-i"></div><span class="sp-face">&#128202;</span></div>
  <div class="sp-t1">KETAN AI</div>
  <div class="sp-t2">Institutional Trading Terminal</div>
  <div class="sp-dots"><div class="sp-dot"></div><div class="sp-dot"></div><div class="sp-dot"></div></div>
  <div class="sp-bar"><div class="sp-prog"></div></div>
</div>

<!-- LOGIN SCREEN -->
<div id="login-screen">
  <div class="login-box">
    <div class="login-logo">&#128202;</div>
    <div class="login-title">KETAN AI</div>
    <div class="login-sub">Apna Telegram User ID enter karo<br>access activate karne ke liye</div>
    <label class="login-label">Telegram User ID</label>
    <input class="login-input" type="number" id="uid-input" placeholder="Enter your Telegram ID">
    <div class="login-err" id="login-err"></div>
    <button class="login-btn" id="login-btn" onclick="doLogin()">Login &#8594;</button>
    <div class="login-help">Telegram mein @userinfobot ko message karo apna ID pata karne ke liye</div>
  </div>
</div>

<!-- TERMS OVERLAY -->
<div id="tc-overlay">
  <div class="tc-box">
    <div class="tc-head"><div class="tc-drag"></div><div class="tc-title">Terms and Conditions</div></div>
    <div class="tc-scroll">
      <h4>Risk Disclaimer</h4>
      <div class="tc-warn">Trading mein significant financial risk hota hai. Sirf woh paisa invest karo jo aap khone ke liye afford kar sako.</div>
      <h4>Service Terms</h4>
      <ul style="list-style:none;margin:4px 0;">
        <li style="padding:2px 0 2px 14px;position:relative;">&#8226; Ketan AI ek educational platform hai</li>
        <li style="padding:2px 0 2px 14px;position:relative;">&#8226; Signals guaranteed returns nahi deti</li>
        <li style="padding:2px 0 2px 14px;position:relative;">&#8226; Final decision aapka apna hona chahiye</li>
      </ul>
      <h4>Privacy</h4>
      <ul style="list-style:none;margin:4px 0;">
        <li style="padding:2px 0 2px 14px;">&#8226; Aapka UID securely store hoga</li>
        <li style="padding:2px 0 2px 14px;">&#8226; Data third parties ke saath share nahi hoga</li>
      </ul>
    </div>
    <div class="tc-foot">
      <button class="tc-btn" onclick="agreeTC()">I Agree &mdash; Continue to App</button>
      <div class="tc-note">Yeh sirf pehli baar dikhega.</div>
    </div>
  </div>
</div>

<!-- MAIN APP -->
<div id="app">
  <!-- HEADER (always visible) -->
  <div class="hdr">
    <div class="hdr-top">
      <div class="logo">
        <span style="font-size:1.2rem;">&#128202;</span>
        <span class="logo-text">KETAN AI</span>
      </div>
      <div class="hdr-right">
        <div class="pill pill-g"><div class="ldot"></div><span id="hdr-time">--:--</span></div>
        <div class="pill pill-b" id="exp-pill">--</div>
        <div class="ibtn" id="theme-btn" onclick="toggleTheme()">&#9728;&#65039;</div>
        <div class="ibtn" onclick="toast('OI Alert monitoring active!')">&#128276;</div>
        <div class="ibtn" onclick="toast('Owner panel: /owner URL se access karo')">&#128081;</div>
      </div>
    </div>
    <div class="ticker-wrap">
      <div class="ticker-inner" id="ticker-inner">
        <div class="tick"><span class="tlbl">NIFTY</span><span class="tval dn" id="tick-n">--</span><span class="tchg dn-bg" id="tchg-n">--</span></div>
        <div class="tick"><span class="tlbl">BANKNIFTY</span><span class="tval up" id="tick-b">--</span><span class="tchg up-bg" id="tchg-b">--</span></div>
        <div class="tick"><span class="tlbl">PCR</span><span class="tval am" id="tick-pcr">--</span><span class="tchg dn-bg" id="tick-pcr-bias">--</span></div>
        <div class="tick"><span class="tlbl">VIX</span><span class="tval dn" id="tick-vix">--</span><span class="tchg dn-bg">--</span></div>
        <div class="tick"><span class="tlbl">NIFTY</span><span class="tval dn" id="tick-n2">--</span><span class="tchg dn-bg">--</span></div>
        <div class="tick"><span class="tlbl">BANKNIFTY</span><span class="tval up" id="tick-b2">--</span><span class="tchg up-bg">--</span></div>
        <div class="tick"><span class="tlbl">PCR</span><span class="tval am" id="tick-pcr2">--</span><span class="tchg dn-bg">--</span></div>
        <div class="tick"><span class="tlbl">VIX</span><span class="tval dn">--</span><span class="tchg dn-bg">--</span></div>
      </div>
    </div>
    <div class="status-bar">
      <div class="mkt mkt-c" id="mkt-pill"><div class="mkt-dot"></div><span id="mkt-text">Market Closed</span></div>
      <span class="clk" id="clock">--:--:--</span>
    </div>
  </div>

  <!-- ===== HOME PAGE ===== -->
  <div class="page" id="pg-home">
    <div class="main">
      <div class="price-card">
        <div class="price-tabs">
          <div class="ptab active" id="tab-N" onclick="switchSym('NIFTY')">
            <div class="ptab-lbl">NIFTY 50</div>
            <div class="ptab-val dn" id="pv-N">--</div>
            <div class="ptab-chg dn" id="pc-N">--</div>
          </div>
          <div class="ptab" id="tab-B" onclick="switchSym('BANKNIFTY')">
            <div class="ptab-lbl">BANKNIFTY</div>
            <div class="ptab-val up" id="pv-B">--</div>
            <div class="ptab-chg up" id="pc-B">--</div>
          </div>
        </div>
        <div class="metrics">
          <div class="metric"><div class="mlbl">PCR</div><div class="mval am" id="m-pcr">--</div></div>
          <div class="metric"><div class="mlbl">VIX</div><div class="mval dn" id="m-vix">--</div></div>
          <div class="metric"><div class="mlbl">CE OI</div><div class="mval dn" id="m-ceoi">--</div></div>
          <div class="metric"><div class="mlbl">PE OI</div><div class="mval up" id="m-peoi">--</div></div>
        </div>
      </div>

      <div class="sym-row">
        <div class="sym-btn active" id="sym-N" onclick="setSym('NIFTY',this)">&#128202; NIFTY</div>
        <div class="sym-btn" id="sym-B" onclick="setSym('BANKNIFTY',this)">&#127981; BANKNIFTY</div>
      </div>

      <div class="type-row">
        <div class="tbtn active" id="tb-basic" onclick="setType('basic',this)">&#128202; Basic</div>
        <div class="tbtn" id="tb-pro" onclick="setType('pro',this)">&#9889; PRO</div>
        <div class="tbtn" id="tb-smart" onclick="setType('smart',this)">&#129504; Smart MTF</div>
        <div class="tbtn" id="tb-sr" onclick="setType('sr',this)">&#127919; S and R</div>
      </div>

      <div class="sig-card">
        <div class="sig-head">
          <div><div class="sig-title" id="sig-title">BASIC - NIFTY</div><div class="sig-sub">Institutional Smart Entry</div></div>
          <div class="sig-time" id="sig-time">--</div>
        </div>
        <div class="sig-body" id="sig-body">
          <div class="load-box"><div class="spinner"></div><div class="load-msg">Loading...</div></div>
        </div>
        <div class="sig-foot">
          <button class="btn-main" onclick="fetchSignal()">&#128260; Refresh Signal</button>
          <button class="btn-sec" onclick="copySignal()">&#128203; Copy</button>
        </div>
        <div class="watermark">POWERED BY KETAN AI</div>
      </div>

      <div class="pnl-card">
        <div class="pnl-head">
          <div><div class="pnl-title">&#128176; P&amp;L Calculator</div><div class="pnl-sub">NIFTY=65, BANKNIFTY=35</div></div>
          <button class="tog" id="pnl-tog" onclick="togPnL()">Show</button>
        </div>
        <div id="pnl-body" style="display:none;">
          <div class="pnl-inner">
            <div class="fgrid">
              <div><label class="flabel">Buy Price</label><input class="finput" type="number" id="p-buy" placeholder="185"></div>
              <div><label class="flabel">Sell Price</label><input class="finput" type="number" id="p-sell" placeholder="250"></div>
              <div><label class="flabel">Lots</label><input class="finput" type="number" id="p-lots" value="1"></div>
              <div><label class="flabel">Index</label>
                <select class="fsel" id="p-idx" onchange="syncLotSize()">
                  <option value="65">NIFTY (65)</option>
                  <option value="35">BANKNIFTY (35)</option>
                </select>
              </div>
              <div><label class="flabel">SL Price</label><input class="finput" type="number" id="p-sl" placeholder="139"></div>
              <div><label class="flabel">Lot Size</label><input class="finput" type="number" id="p-ls" value="65" readonly style="opacity:.6"></div>
            </div>
            <button class="calc-btn" onclick="calcPnL()">&#128202; Calculate P&amp;L</button>
            <div class="res-box" id="pnl-res">
              <div style="font-size:.5rem;color:var(--muted);text-transform:uppercase;margin-bottom:10px;">Result</div>
              <div class="rgrid" id="pnl-rgrid"></div>
              <div class="rsum" id="pnl-rsum">
                <div style="font-size:.54rem;color:var(--muted);text-transform:uppercase;margin-bottom:3px;">Net P&amp;L</div>
                <div class="rnet" id="pnl-net">--</div>
              </div>
              <div style="margin-top:10px;background:var(--inp);border:1px solid var(--bdr);border-radius:10px;padding:10px 12px;">
                <div style="font-size:.46rem;color:var(--muted);text-transform:uppercase;margin-bottom:7px;">Target Scenarios</div>
                <div id="pnl-scen"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ===== VIDEO PAGE ===== -->
  <div class="page" id="pg-video">
    <div class="main">
      <div class="ptitle">&#128222; Video Session</div>
      <div class="psub">Live WebRTC &mdash; max 4 users</div>

      <!-- WAITING STATE -->
      <div id="vc-wait">
        <div class="vc-hero">
          <div style="font-size:2.8rem;margin-bottom:10px;">&#128222;</div>
          <div class="vc-t">Start Live Session</div>
          <div class="vc-s">Real video call with camera &amp; mic. Sab active users ko app mein join button milega aur Telegram notification bhi jayegi.</div>
          <button class="vc-sb" onclick="vcStart()">&#9654; Start Live Session</button>
        </div>
        <!-- JOIN BOX - shown when session is active -->
        <div id="vc-join-box" style="display:none;margin-top:10px;">
          <div class="vcibox" style="border:1px solid rgba(16,185,129,.3);">
            <div style="font-size:.7rem;font-weight:700;color:#10b981;margin-bottom:10px;">&#128994; Live Session Active!</div>
            <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Participants</span><span id="vc-join-cnt" style="font-family:monospace;font-size:.68rem;font-weight:700;color:#10b981">--/4</span></div>
            <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Host</span><span id="vc-join-host" style="font-family:monospace;font-size:.68rem;font-weight:700;color:#f59e0b">--</span></div>
          </div>
          <button class="vc-sb" onclick="vcJoin()" style="background:linear-gradient(135deg,#10b981,#06b6d4);margin-top:0;">&#128279; Join Session</button>
        </div>
        <div class="vcibox" style="margin-top:10px;">
          <div style="font-size:.56rem;color:var(--muted);text-transform:uppercase;margin-bottom:8px;">Info</div>
          <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Max Users</span><span style="font-family:monospace;font-size:.68rem;font-weight:700;color:#10b981">4</span></div>
          <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Notification</span><span style="font-family:monospace;font-size:.68rem;font-weight:700;color:#60a5fa">App + Telegram</span></div>
          <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Technology</span><span style="font-family:monospace;font-size:.68rem;font-weight:700;color:#a78bfa">WebRTC P2P</span></div>
        </div>
      </div>

      <!-- ACTIVE CALL STATE -->
      <div id="vc-active" style="display:none;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <div style="font-size:.82rem;font-weight:700;display:flex;align-items:center;gap:8px;">
            Live
            <span style="background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.3);color:#f87171;font-size:.58rem;padding:2px 9px;border-radius:20px;animation:vcPulse 1s infinite">LIVE</span>
            <span id="vc-pcnt" style="background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.2);color:#10b981;font-size:.58rem;padding:2px 9px;border-radius:20px;">1/4</span>
          </div>
          <div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.25);border-radius:8px;padding:4px 12px;font-size:.6rem;color:#f87171;cursor:pointer;" onclick="vcLeave()">Leave</div>
        </div>

        <!-- VIDEO GRID 2x2 -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
          <!-- Local video -->
          <div style="border-radius:16px;aspect-ratio:1;position:relative;overflow:hidden;background:#0a0f1a;border:2px solid rgba(59,130,246,.4);">
            <video id="vc-local-video" autoplay muted playsinline style="width:100%;height:100%;object-fit:cover;border-radius:14px;"></video>
            <div id="vc-local-avatar" style="display:none;width:100%;height:100%;position:absolute;top:0;left:0;background:linear-gradient(135deg,#1a3a5c,#0d2040);flex-direction:column;align-items:center;justify-content:center;gap:6px;">
              <div style="width:52px;height:52px;border-radius:50%;background:rgba(59,130,246,.2);color:#60a5fa;display:flex;align-items:center;justify-content:center;font-size:1.4rem;font-weight:700;" id="vc-local-init">Y</div>
              <div style="font-size:.62rem;font-weight:700;color:rgba(255,255,255,.9)">You</div>
            </div>
            <div style="position:absolute;bottom:6px;left:6px;background:rgba(0,0,0,.6);border-radius:6px;padding:2px 7px;font-size:.5rem;color:#fff" id="vc-local-label">You</div>
            <div id="vc-mic-ind" style="position:absolute;top:6px;right:6px;width:20px;height:20px;border-radius:50%;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;font-size:.65rem;">&#127908;</div>
          </div>
          <!-- Remote slots -->
          <div id="vc-slot-1" style="border-radius:16px;aspect-ratio:1;position:relative;overflow:hidden;background:#0a0f1a;border:1px dashed rgba(255,255,255,.15);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;">
            <video id="vc-rv-1" autoplay playsinline style="width:100%;height:100%;object-fit:cover;border-radius:14px;display:none;"></video>
            <div id="vc-ra-1" style="display:flex;flex-direction:column;align-items:center;gap:5px;"><div style="font-size:1.4rem;opacity:.25;">&#128100;</div><div style="font-size:.58rem;color:var(--muted)" id="vc-rn-1">Waiting...</div></div>
          </div>
          <div id="vc-slot-2" style="border-radius:16px;aspect-ratio:1;position:relative;overflow:hidden;background:#0a0f1a;border:1px dashed rgba(255,255,255,.15);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;">
            <video id="vc-rv-2" autoplay playsinline style="width:100%;height:100%;object-fit:cover;border-radius:14px;display:none;"></video>
            <div id="vc-ra-2" style="display:flex;flex-direction:column;align-items:center;gap:5px;"><div style="font-size:1.4rem;opacity:.25;">&#128100;</div><div style="font-size:.58rem;color:var(--muted)" id="vc-rn-2">Waiting...</div></div>
          </div>
          <div id="vc-slot-3" style="border-radius:16px;aspect-ratio:1;position:relative;overflow:hidden;background:#0a0f1a;border:1px dashed rgba(255,255,255,.15);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;">
            <video id="vc-rv-3" autoplay playsinline style="width:100%;height:100%;object-fit:cover;border-radius:14px;display:none;"></video>
            <div id="vc-ra-3" style="display:flex;flex-direction:column;align-items:center;gap:5px;"><div style="font-size:1.4rem;opacity:.25;">&#128100;</div><div style="font-size:.58rem;color:var(--muted)" id="vc-rn-3">Waiting...</div></div>
          </div>
        </div>

        <!-- Controls -->
        <div style="display:flex;gap:8px;margin-bottom:10px;">
          <div id="btn-mic" onclick="vcToggleMic()" style="flex:1;background:var(--inp);border:1px solid var(--bdr2);border-radius:14px;padding:12px;text-align:center;cursor:pointer;">
            <div id="mic-ic" style="font-size:1.3rem;margin-bottom:3px;">&#127908;</div>
            <div id="mic-txt" style="font-size:.56rem;color:var(--txt2);">Mic On</div>
          </div>
          <div id="btn-cam" onclick="vcToggleCam()" style="flex:1;background:var(--inp);border:1px solid var(--bdr2);border-radius:14px;padding:12px;text-align:center;cursor:pointer;">
            <div id="cam-ic" style="font-size:1.3rem;margin-bottom:3px;">&#128249;</div>
            <div id="cam-txt" style="font-size:.56rem;color:var(--txt2);">Cam On</div>
          </div>
          <div onclick="vcLeave()" style="flex:1;background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.2);border-radius:14px;padding:12px;text-align:center;cursor:pointer;">
            <div style="font-size:1.3rem;margin-bottom:3px;">&#9940;</div>
            <div style="font-size:.56rem;color:#f87171;">End</div>
          </div>
        </div>

        <div class="vcibox">
          <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Duration</span><span id="vc-dur" style="font-family:monospace;font-size:.68rem;font-weight:700;color:#10b981">00:00</span></div>
          <div class="vcirow"><span style="font-size:.68rem;color:var(--txt2)">Participants</span><span id="vc-parts-txt" style="font-family:monospace;font-size:.68rem;font-weight:700;color:#60a5fa">1/4</span></div>
        </div>
      </div>
    </div>
  </div>

  <!-- ===== CONTACT PAGE ===== -->
  <div class="page" id="pg-contact">
    <div class="main">
      <div class="ptitle">Contact</div>
      <div class="psub">Owner se directly contact karo</div>
      <div class="clist">
        <a class="citem" href="https://wa.me/qr/PQ5JLDLPQCBVI1" target="_blank">
          <div class="cic cwa">&#128241;</div>
          <div><div class="cnm" style="color:#25D366">WhatsApp</div><div class="chd">Owner se baat karo</div></div>
        </a>
        <a class="citem" href="https://t.me/KETAN_AI" target="_blank">
          <div class="cic ctg">&#9992;&#65039;</div>
          <div><div class="cnm" style="color:#0088cc">Telegram</div><div class="chd">@KETAN_AI</div></div>
        </a>
        <a class="citem" href="https://www.instagram.com/ketankondekar" target="_blank">
          <div class="cic cig">&#128247;</div>
          <div><div class="cnm" style="color:#e1306c">Instagram</div><div class="chd">@ketankondekar</div></div>
        </a>
      </div>
      <div class="icard">
        <div style="font-size:.8rem;font-weight:700;margin-bottom:12px;color:#60a5fa">App Info</div>
        <div class="irow"><span class="il">App</span><span class="iv" style="color:#34d399">KETAN AI v2</span></div>
        <div class="irow"><span class="il">Your UID</span><span class="iv" id="info-uid" style="color:#f59e0b">--</span></div>
        <div class="irow"><span class="il">Access Expiry</span><span class="iv" id="info-exp">--</span></div>
        <div class="irow"><span class="il">NIFTY Lot</span><span class="iv">65</span></div>
        <div class="irow"><span class="il">BANKNIFTY Lot</span><span class="iv">35</span></div>
      </div>
    </div>
  </div>

  <!-- ===== SETTINGS PAGE ===== -->
  <div class="page" id="pg-settings">
    <div class="main">
      <div class="ptitle">&#9881;&#65039; Settings</div>
      <div class="psub">Apni preferences customize karo</div>

      <div class="sset">
        <div class="shed">Appearance</div>
        <div class="srow">
          <div class="sleft"><span class="sicon">&#127769;</span><div><div class="stxt">Dark Mode</div><div class="shint">Dark / Light theme toggle</div></div></div>
          <label class="sw"><input type="checkbox" id="sw-dark" checked onchange="onThemeSw(this)"><span class="sw-s"></span></label>
        </div>
      </div>

      <div class="sset">
        <div class="shed">Trading Preferences</div>
        <div class="srow">
          <div class="sleft"><span class="sicon">&#128200;</span><div><div class="stxt">Default Index</div><div class="shint">Signal ke liye default symbol</div></div></div>
          <select class="ssel" id="set-sym" onchange="saveSetting('def_sym',this.value)">
            <option value="NIFTY">NIFTY</option>
            <option value="BANKNIFTY">BANKNIFTY</option>
          </select>
        </div>
        <div class="srow">
          <div class="sleft"><span class="sicon">&#9889;</span><div><div class="stxt">Default Signal Type</div><div class="shint">App open hone pe yeh type select hoga</div></div></div>
          <select class="ssel" id="set-type" onchange="saveSetting('def_type',this.value)">
            <option value="basic">Basic</option>
            <option value="pro">PRO</option>
            <option value="smart">Smart MTF</option>
            <option value="sr">S and R</option>
          </select>
        </div>
      </div>

      <div class="sset">
        <div class="shed">Lot Sizes</div>
        <div class="srow">
          <div class="sleft"><span class="sicon">&#128202;</span><div><div class="stxt">NIFTY</div><div class="shint">Per lot quantity</div></div></div>
          <span class="sbadge">65</span>
        </div>
        <div class="srow">
          <div class="sleft"><span class="sicon">&#127981;</span><div><div class="stxt">BANKNIFTY</div><div class="shint">Per lot quantity</div></div></div>
          <span class="sbadge">35</span>
        </div>
      </div>

      <div class="sset">
        <div class="shed">Account</div>
        <div class="srow" onclick="doLogout()" style="cursor:pointer;">
          <div class="sleft"><span class="sicon">&#128464;</span><div><div class="stxt" style="color:#ef4444">Logout</div><div class="shint">UID remove karke login page pe jao</div></div></div>
          <span style="font-size:.8rem;color:var(--muted);">&#8250;</span>
        </div>
        <div class="srow" onclick="resetAll()" style="cursor:pointer;">
          <div class="sleft"><span class="sicon">&#128465;&#65039;</span><div><div class="stxt" style="color:#f97316">Reset All Settings</div><div class="shint">Sab data clear ho jayega</div></div></div>
          <span style="font-size:.8rem;color:var(--muted);">&#8250;</span>
        </div>
      </div>

      <div style="text-align:center;padding:20px 0;font-size:.58rem;color:var(--muted);">
        KETAN AI &mdash; Institutional Trading Terminal<br>
        UID: <span id="settings-uid" style="color:#60a5fa;font-family:monospace;">--</span>
      </div>
    </div>
  </div>

  <!-- BOTTOM NAV -->
  <div class="bnav">
    <div class="nitem" id="nav-home" onclick="goPage('home')"><span class="nic">&#127968;</span><span class="nlb">Home</span></div>
    <div class="nitem" id="nav-video" onclick="goPage('video')"><span class="nic">&#127897;&#65039;</span><span class="nlb">Video</span></div>
    <div class="nitem" id="nav-contact" onclick="goPage('contact')"><span class="nic">&#128222;</span><span class="nlb">Contact</span></div>
    <div class="nitem" id="nav-settings" onclick="goPage('settings')"><span class="nic">&#9881;&#65039;</span><span class="nlb">Settings</span></div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// ============================================
// GLOBALS
// ============================================
var UID = 0;
var CUR_SYM = 'NIFTY';
var CUR_TYPE = 'basic';
var SIG_TEXT = '';
var SIG_PT1 = 0, SIG_PT2 = 0, SIG_PT3 = 0;
var LOT = {NIFTY:65, BANKNIFTY:35};

// ============================================
// HELPERS
// ============================================
function $(id){ return document.getElementById(id); }
function setText(id,v){ var e=$(id); if(e) e.textContent=v; }
function setHTML(id,v){ var e=$(id); if(e) e.innerHTML=v; }
function setClass(id,c){ var e=$(id); if(e) e.className=c; }
function show(id){ var e=$(id); if(e) e.style.display='block'; }
function hide(id){ var e=$(id); if(e) e.style.display='none'; }
function flex(id){ var e=$(id); if(e) e.style.display='flex'; }

function toast(msg) {
  var t=$('toast');
  if(!t) return;
  t.textContent=msg;
  t.classList.add('show');
  setTimeout(function(){ t.classList.remove('show'); }, 2200);
}

function xhr(url, cb) {
  var x = new XMLHttpRequest();
  x.open('GET', url, true);
  x.onreadystatechange = function(){
    if(x.readyState===4){
      try{ cb(JSON.parse(x.responseText)); }
      catch(e){ cb(null); }
    }
  };
  x.send();
}

function post(url, data, cb) {
  var x = new XMLHttpRequest();
  x.open('POST', url, true);
  x.setRequestHeader('Content-Type','application/json');
  x.onreadystatechange = function(){
    if(x.readyState===4){
      try{ cb(JSON.parse(x.responseText)); }
      catch(e){ cb(null); }
    }
  };
  x.send(JSON.stringify(data));
}

// ============================================
// IST TIME (UTC+5:30)
// ============================================
function getIST() {
  var now = new Date();
  var utc = now.getTime() + (now.getTimezoneOffset() * 60000);
  return new Date(utc + (5.5 * 3600000));
}

// ============================================
// STARTUP &#8212; splash 3s
// ============================================
setTimeout(function() {
  hide('splash');

  // Theme
  var th = localStorage.getItem('theme') || 'dark';
  applyTheme(th, true);

  var savedUID = localStorage.getItem('uid');
  if (savedUID && parseInt(savedUID) > 0) {
    UID = parseInt(savedUID);
    if (!localStorage.getItem('agreed')) {
      flex('tc-overlay');
    } else {
      startApp();
    }
  } else {
    flex('login-screen');
  }
}, 3000);

// ============================================
// LOGIN
// ============================================
function doLogin() {
  var val = $('uid-input').value.trim();
  var errEl = $('login-err');
  if (!val || isNaN(val) || parseInt(val) <= 0) {
    errEl.textContent = 'Valid Telegram UID daalo!';
    return;
  }
  errEl.textContent = 'Checking...';
  var btn = $('login-btn');
  if(btn) btn.disabled = true;
  var uid = parseInt(val);

  xhr('/api/user/check?uid=' + uid, function(data) {
    if(btn) btn.disabled = false;
    if (!data) {
      errEl.textContent = 'Server se connect nahi hua. Bot chal raha hai?';
      return;
    }
    if (data.blocked) {
      errEl.textContent = 'Account blocked hai. Owner se contact karo.';
      return;
    }
    if (!data.valid) {
      errEl.textContent = data.msg || 'Access nahi hai. Bot mein key activate karo.';
      return;
    }
    // Success
    UID = uid;
    localStorage.setItem('uid', uid);
    hide('login-screen');
    if (!localStorage.getItem('agreed')) {
      flex('tc-overlay');
    } else {
      startApp();
    }
  });
}

$('uid-input').addEventListener('keyup', function(e){ if(e.key==='Enter') doLogin(); });

// ============================================
// TERMS
// ============================================
function agreeTC() {
  localStorage.setItem('agreed', '1');
  hide('tc-overlay');
  startApp();
  toast('Welcome to KETAN AI!');
}

// ============================================
// MAIN APP START
// ============================================
function startApp() {
  // Show app
  show('app');

  // Apply saved settings
  var ds = localStorage.getItem('def_sym') || 'NIFTY';
  var dt = localStorage.getItem('def_type') || 'basic';
  CUR_SYM = ds;
  CUR_TYPE = dt;

  // Sync settings dropdowns
  var ss = $('set-sym');
  if(ss){ for(var i=0;i<ss.options.length;i++) if(ss.options[i].value===ds) ss.selectedIndex=i; }
  var st = $('set-type');
  if(st){ for(var i=0;i<st.options.length;i++) if(st.options[i].value===dt) st.selectedIndex=i; }

  // Update UID displays
  setText('info-uid', UID);
  setText('settings-uid', UID);

  // Fetch expiry
  xhr('/api/user/check?uid=' + UID, function(d){
    if(d && d.valid){
      var exp = d.is_owner ? '&#9825; Owner' : (d.expiry || '--');
      setHTML('exp-pill', exp);
      setText('info-exp', d.is_owner ? 'Owner (Lifetime)' : (d.expiry || '--'));
    }
  });

  // Start clock
  updateClock();
  setInterval(updateClock, 1000);

  // Go to home page
  goPage('home');

  // Active correct sym/type buttons
  activateSym(ds);
  activateType(dt);

  // Fetch data
  updateSigTitle();
  fetchSignal();
  fetchTicker();
  setInterval(fetchTicker, 15000);
  // Start video session check
  vcCheckStatus();
  startVcCheck();
}

// ============================================
// NAVIGATION
// ============================================
function goPage(name) {
  // Hide all pages
  var pages = document.querySelectorAll('.page');
  pages.forEach(function(p){ p.style.display='none'; p.classList.remove('active'); });
  // Deactivate all nav items
  document.querySelectorAll('.nitem').forEach(function(n){ n.classList.remove('active'); });
  // Show target page
  var pg = $('pg-' + name);
  var nv = $('nav-' + name);
  if(pg){ pg.style.display='block'; pg.classList.add('active'); }
  if(nv){ nv.classList.add('active'); }
  window.scrollTo(0,0);
}

// ============================================
// CLOCK + MARKET STATUS (IST)
// ============================================
function updateClock() {
  var ist = getIST();
  var h=ist.getHours(), m=ist.getMinutes(), d=ist.getDay();
  var timeStr = ist.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:true});
  setText('clock', timeStr);
  setText('hdr-time', ist.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:true}));
  // Market open: Mon-Fri, 9:15 AM - 3:30 PM IST
  var open = d>=1 && d<=5 && (h>9||(h===9&&m>=15)) && (h<15||(h===15&&m<=30));
  var pill = $('mkt-pill');
  var txt  = $('mkt-text');
  if(pill) pill.className = 'mkt ' + (open ? 'mkt-o' : 'mkt-c');
  if(txt)  txt.textContent = open ? 'Market Open' : 'Market Closed';
}

// ============================================
// TICKER
// ============================================
function fetchTicker() {
  if(!UID) return;
  xhr('/api/user/ticker?uid=' + UID, function(d){
    if(!d || !d.nifty) return;
    var nc = parseFloat(d.nifty_chg)||0;
    var bc = parseFloat(d.bn_chg)||0;
    var ncp = parseFloat(d.nifty_chg_pct)||0;
    var bcp = parseFloat(d.bn_chg_pct)||0;

    setText('tick-n', d.nifty); setText('tick-n2', d.nifty);
    setText('tick-b', d.banknifty); setText('tick-b2', d.banknifty);
    setText('pv-N', d.nifty);
    setText('pv-B', d.banknifty);
    setText('pc-N', (nc>=0?'+':'')+ncp.toFixed(2)+'%');
    setText('pc-B', (bc>=0?'+':'')+bcp.toFixed(2)+'%');
    setClass('pv-N','ptab-val '+(nc>=0?'up':'dn'));
    setClass('pv-B','ptab-val '+(bc>=0?'up':'dn'));
    setClass('tick-n','tval '+(nc>=0?'up':'dn'));
    setClass('tick-b','tval '+(bc>=0?'up':'dn'));

    if(d.pcr_n){
      var pcr=parseFloat(d.pcr_n);
      var bias = pcr>=1.0?'Bullish':(pcr>=0.8?'Neutral':'Bearish');
      setText('tick-pcr',d.pcr_n); setText('tick-pcr2',d.pcr_n);
      setText('tick-pcr-bias',bias); setText('m-pcr',d.pcr_n);
    }
    if(d.vix && d.vix!=='N/A'){
      setText('tick-vix',d.vix); setText('m-vix',d.vix);
    }
    if(d.ce_oi){
      setText('m-ceoi',(parseFloat(d.ce_oi)/1e7).toFixed(1)+'Cr');
      setText('m-peoi',(parseFloat(d.pe_oi)/1e7).toFixed(1)+'Cr');
    }
  });
}

// ============================================
// SIGNAL
// ============================================
function fetchSignal() {
  if(!UID) return;
  var body = $('sig-body');
  var tm   = $('sig-time');
  if(!body) return;
  body.innerHTML = '<div class="load-box"><div class="spinner"></div><div class="load-msg">Loading ' + CUR_TYPE + ' signal...</div></div>';
  if(tm) tm.textContent = '--';

  xhr('/api/user/signal?uid='+UID+'&type='+CUR_TYPE+'&symbol='+CUR_SYM, function(data){
    if(!data || !data.text){
      body.innerHTML = '<div class="sig-err">&#9888; Signal data nahi mila. Dobara try karo.</div>';
      return;
    }
    SIG_TEXT = data.text;
    if(tm) tm.textContent = getIST().toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:true});
    body.innerHTML = '<div class="sig-out">' + escHtml(data.text) + '</div>';
    parsePremium(data.text);
  });
}

function parsePremium(text){
  var m=text.match(/Current Premium[^0-9]*([0-9]+)/);
  if(m){ var pb=$('p-buy'); if(pb) pb.value=m[1]; }
  var ms=text.match(/Premium SL[^0-9]*([0-9]+)/);
  if(ms){ var ps=$('p-sl'); if(ps) ps.value=ms[1]; }
  var t1=text.match(/TP1[^0-9]*([0-9]+)/);
  var t2=text.match(/TP2[^0-9]*([0-9]+)/);
  var t3=text.match(/TP3[^0-9]*([0-9]+)/);
  if(t1) SIG_PT1=parseInt(t1[1]);
  if(t2) SIG_PT2=parseInt(t2[1]);
  if(t3) SIG_PT3=parseInt(t3[1]);
}

function escHtml(s){
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function copySignal(){
  if(!SIG_TEXT){ toast('Pehle signal load karo!'); return; }
  if(navigator.clipboard){
    navigator.clipboard.writeText(SIG_TEXT).then(function(){ toast('&#128203; Signal Copied!'); });
  } else {
    toast('Copy nahi ho pa raha. Browser allow karo.');
  }
}

// ============================================
// SYMBOL & TYPE SELECTION
// ============================================
function activateSym(sym){
  document.querySelectorAll('.sym-btn').forEach(function(b){ b.classList.remove('active'); });
  var el = $('sym-'+(sym==='NIFTY'?'N':'B'));
  if(el) el.classList.add('active');
  $('tab-N') && $('tab-N').classList.toggle('active', sym==='NIFTY');
  $('tab-B') && $('tab-B').classList.toggle('active', sym==='BANKNIFTY');
}

function activateType(typ){
  document.querySelectorAll('.tbtn').forEach(function(b){ b.classList.remove('active'); });
  var el = $('tb-'+typ);
  if(el) el.classList.add('active');
}

function setSym(sym, el){
  CUR_SYM = sym;
  activateSym(sym);
  syncLotSize();
  updateSigTitle();
  fetchSignal();
}

function switchSym(sym){
  setSym(sym, null);
}

function setType(typ, el){
  CUR_TYPE = typ;
  activateType(typ);
  updateSigTitle();
  fetchSignal();
}

function updateSigTitle(){
  var names={basic:'BASIC',pro:'PRO',smart:'SMART MTF',sr:'S and R'};
  setText('sig-title', (names[CUR_TYPE]||'BASIC') + ' - ' + CUR_SYM);
}

// ============================================
// P&L CALCULATOR
// ============================================
function togPnL(){
  var b=$('pnl-body'), t=$('pnl-tog');
  if(!b) return;
  var open = b.style.display!=='none';
  b.style.display = open?'none':'block';
  if(t) t.textContent = open?'Show':'Hide';
}

function syncLotSize(){
  var ls=parseFloat(LOT[CUR_SYM]||65);
  var lsEl=$('p-ls'); if(lsEl) lsEl.value=ls;
  var sel=$('p-idx');
  if(sel){ for(var i=0;i<sel.options.length;i++) if(parseInt(sel.options[i].value)===ls) sel.selectedIndex=i; }
}

function calcPnL(){
  var buy=parseFloat($('p-buy').value)||0;
  var sell=parseFloat($('p-sell').value)||0;
  var lots=parseInt($('p-lots').value)||1;
  var sl=parseFloat($('p-sl').value)||0;
  var ls=parseInt($('p-ls').value)||65;
  if(!buy){ toast('Buy price daalo!'); return; }
  var qty=lots*ls;
  var invest=buy*qty;
  var slLoss=sl>0?Math.abs(buy-sl)*qty:0;
  var net=sell>0?(sell-buy)*qty:null;
  var nPct=sell>0?((sell-buy)/buy*100).toFixed(2):null;
  var rr=(sell>0&&sl>0)?Math.abs((sell-buy)/(buy-sl)).toFixed(2):'--';

  var rows=[
    ['Investment','Rs '+Math.round(invest).toLocaleString(),'#60a5fa'],
    ['Total Qty',qty,'#94a3b8'],
    ['Lot Size',ls,'#94a3b8'],
    ['Lots',lots,'#94a3b8'],
    ['SL Loss','Rs '+Math.round(slLoss).toLocaleString(),'#f87171'],
    ['R:R',rr,'#a78bfa']
  ];
  var gh='';
  rows.forEach(function(r){ gh+='<div class="ritem"><div class="rlbl">'+r[0]+'</div><div class="rval" style="color:'+r[2]+'">'+r[1]+'</div></div>'; });
  setHTML('pnl-rgrid', gh);

  var scHTML='';
  if(SIG_PT1>0){
    [[' T1 (Rs'+SIG_PT1+')',SIG_PT1],[' T2 (Rs'+SIG_PT2+')',SIG_PT2],[' T3 (Rs'+SIG_PT3+')',SIG_PT3],['SL (Rs'+sl+')',sl]].forEach(function(sc){
      if(sc[1]<=0) return;
      var p=(sc[1]-buy)*qty;
      var pct=((sc[1]-buy)/buy*100).toFixed(1);
      var col=p>=0?'#34d399':'#f87171';
      scHTML+='<div class="scrow"><span style="font-size:.62rem;color:var(--txt2)">'+sc[0]+'</span><span style="color:'+col+'">'+(p>=0?'+':'')+'Rs '+Math.round(Math.abs(p)).toLocaleString()+' ('+pct+'%)</span></div>';
    });
  } else {
    scHTML='<div style="font-size:.62rem;color:var(--muted);text-align:center;padding:8px">Signal refresh karo phir calculate karo</div>';
  }
  setHTML('pnl-scen', scHTML);

  var ne=$('pnl-net'), su=$('pnl-rsum');
  if(net!==null){
    var isP=net>=0;
    ne.textContent=(isP?'+':'')+'Rs '+Math.round(Math.abs(net)).toLocaleString()+' ('+(isP?'+':'')+nPct+'%)';
    ne.style.color=isP?'#34d399':'#ef4444';
    su.className='rsum '+(isP?'rsump':'rsuml');
  } else {
    ne.textContent='Sell price daalo'; ne.style.color='var(--muted)'; su.className='rsum';
  }
  $('pnl-res').classList.add('show');
  toast('Calculated!');
}

// ============================================
// THEME
// ============================================
function toggleTheme(){
  var cur=document.documentElement.getAttribute('data-theme')||'dark';
  applyTheme(cur==='dark'?'light':'dark', false);
}
function onThemeSw(el){ applyTheme(el.checked?'dark':'light', false); }
function applyTheme(t, silent){
  document.documentElement.setAttribute('data-theme',t);
  localStorage.setItem('theme',t);
  var tbtn=$('theme-btn'); if(tbtn) tbtn.textContent=t==='dark'?'\u2600\ufe0f':'\uD83C\uDF19';
  var sw=$('sw-dark'); if(sw) sw.checked=(t==='dark');
  if(!silent) toast(t==='dark'?'Dark Mode':'Light Mode');
}

// ============================================
// SETTINGS
// ============================================
function saveSetting(k,v){ localStorage.setItem(k,v); toast('Saved!'); }

function doLogout(){
  if(confirm('Logout karoge?')){
    localStorage.removeItem('uid');
    localStorage.removeItem('agreed');
    location.reload();
  }
}

function resetAll(){
  if(confirm('Sab settings reset karoge?')){
    localStorage.clear();
    location.reload();
  }
}

// ============================================
// VIDEO CALL - Full WebRTC P2P
// ============================================
var VC = {
  stream: null, peers: {}, micOn: true, camOn: true,
  isHost: false, polling: null, durTimer: null, durSec: 0,
  pollIdx: {offers:0, answers:0, ice:0}, myName: 'User'
};
var STUN = {iceServers:[
  {urls:'stun:stun.l.google.com:19302'},
  {urls:'stun:stun1.l.google.com:19302'}
]};

// Check for active session every 5s (when on video page)
var vcCheckInterval = null;
function startVcCheck(){
  if(vcCheckInterval) clearInterval(vcCheckInterval);
  vcCheckInterval = setInterval(function(){
    if($('pg-video') && $('pg-video').style.display !== 'none'){
      vcCheckStatus();
    }
  }, 5000);
}

function vcCheckStatus(){
  xhr('/api/vc/status', function(d){
    if(!d) return;
    var jbox = $('vc-join-box');
    if(d.active && d.count > 0){
      // Someone is in a session - show join button
      if(jbox && !$('vc-active').style.display !== 'none'){
        jbox.style.display = 'block';
        setText('vc-join-cnt', d.count + '/4');
        var hostName = d.participants && d.participants[0] ? (d.participants[0].name || 'User') : 'Host';
        setText('vc-join-host', hostName);
      }
      // Show in-app notification banner
      showVcNotif('&#128994; Live session active! Join karo.');
    } else {
      if(jbox) jbox.style.display = 'none';
      hideVcNotif();
    }
  });
}

function showVcNotif(msg){
  var n = $('vc-notif');
  if(!n){
    n = document.createElement('div');
    n.id = 'vc-notif';
    n.className = 'vc-notif';
    n.onclick = function(){ goPage('video'); hideVcNotif(); };
    document.body.appendChild(n);
  }
  n.innerHTML = msg + ' <span style="font-size:.6rem;opacity:.7">(tap to join)</span>';
  n.style.display = 'block';
}
function hideVcNotif(){
  var n = $('vc-notif');
  if(n) n.style.display = 'none';
}

function vcGetMedia(cb){
  navigator.mediaDevices.getUserMedia({video:true, audio:true})
    .then(function(s){ cb(s, true, true); })
    .catch(function(e1){
      navigator.mediaDevices.getUserMedia({video:false, audio:true})
        .then(function(s){ toast('Camera nahi mila - sirf audio'); cb(s, false, true); })
        .catch(function(e2){
          navigator.mediaDevices.getUserMedia({video:true, audio:false})
            .then(function(s){ toast('Mic nahi mila - sirf video'); cb(s, true, false); })
            .catch(function(){
              var msg = '';
              if(e1.name==='NotAllowedError') msg='Camera/mic permission do! Browser settings > Site Settings > Allow karo.';
              else if(e1.name==='NotFoundError') msg='Camera ya mic nahi mila device mein.';
              else msg='Media error: '+e1.message;
              alert(msg);
            });
        });
    });
}

function vcStart(){
  vcGetMedia(function(stream, hasV, hasA){
    VC.stream = stream; VC.isHost = true; VC.micOn = hasA; VC.camOn = hasV;
    VC.myName = 'User ' + UID;
    showVcActive();
    // Show local video
    var lv = $('vc-local-video');
    if(lv && hasV){ lv.srcObject = stream; lv.style.display='block'; $('vc-local-avatar').style.display='none'; }
    else { $('vc-local-avatar').style.display='flex'; if(lv) lv.style.display='none'; }
    updateMicUI(); updateCamUI();
    // Register on server
    post('/api/vc/start', {uid:UID, name:VC.myName}, function(d){
      if(d && d.ok){
        toast('Session started! Sabko notification gayi');
        startVcPoll(); startVcTimer();
      } else {
        toast('Server error: '+(d&&d.msg||'failed'));
        vcCleanup();
      }
    });
  });
}

function vcJoin(){
  vcGetMedia(function(stream, hasV, hasA){
    VC.stream = stream; VC.isHost = false; VC.micOn = hasA; VC.camOn = hasV;
    VC.myName = 'User ' + UID;
    showVcActive();
    var lv = $('vc-local-video');
    if(lv && hasV){ lv.srcObject = stream; lv.style.display='block'; $('vc-local-avatar').style.display='none'; }
    else { $('vc-local-avatar').style.display='flex'; if(lv) lv.style.display='none'; }
    updateMicUI(); updateCamUI();
    post('/api/vc/join', {uid:UID, name:VC.myName}, function(d){
      if(!d || !d.ok){ toast(d&&d.msg||'Join failed'); vcCleanup(); return; }
      toast('Joined! ' + d.count + '/4 participants');
      hideVcNotif();
      startVcPoll(); startVcTimer();
      // Create offers for existing participants
      var parts = d.participants || [];
      parts.forEach(function(p){ if(p.uid != UID) vcCreateOffer(p.uid, p.name); });
    });
  });
}

function vcCreateOffer(toUid, toName){
  var pc = new RTCPeerConnection(STUN);
  VC.peers[toUid] = pc;
  if(VC.stream) VC.stream.getTracks().forEach(function(t){ pc.addTrack(t, VC.stream); });
  pc.ontrack = function(e){
    if(e.streams && e.streams[0]) vcShowRemote(e.streams[0], toUid, toName);
    else { var s=new MediaStream(); s.addTrack(e.track); vcShowRemote(s, toUid, toName); }
  };
  pc.onicecandidate = function(e){
    if(e.candidate) post('/api/vc/ice', {from_uid:UID, to_uid:toUid, candidate:e.candidate}, function(){});
  };
  pc.createOffer()
    .then(function(o){ return pc.setLocalDescription(o).then(function(){return o;}); })
    .then(function(o){ post('/api/vc/offer', {from_uid:UID, to_uid:toUid, sdp:o, name:VC.myName}, function(){}); })
    .catch(function(e){ console.log('offer err',e); });
}

function vcHandleOffer(data){
  var pc = new RTCPeerConnection(STUN);
  VC.peers[data.from_uid] = pc;
  if(VC.stream) VC.stream.getTracks().forEach(function(t){ pc.addTrack(t, VC.stream); });
  pc.ontrack = function(e){
    if(e.streams && e.streams[0]) vcShowRemote(e.streams[0], data.from_uid, data.name||'User');
    else { var s=new MediaStream(); s.addTrack(e.track); vcShowRemote(s, data.from_uid, data.name||'User'); }
  };
  pc.onicecandidate = function(e){
    if(e.candidate) post('/api/vc/ice', {from_uid:UID, to_uid:data.from_uid, candidate:e.candidate}, function(){});
  };
  pc.setRemoteDescription(new RTCSessionDescription(data.sdp))
    .then(function(){ return pc.createAnswer(); })
    .then(function(a){ return pc.setLocalDescription(a).then(function(){return a;}); })
    .then(function(a){ post('/api/vc/answer', {from_uid:UID, to_uid:data.from_uid, sdp:a}, function(){}); })
    .catch(function(e){ console.log('answer err',e); });
}

function vcHandleAnswer(data){
  var pc = VC.peers[data.from_uid];
  if(pc) pc.setRemoteDescription(new RTCSessionDescription(data.sdp)).catch(function(){});
}

function vcHandleICE(data){
  var pc = VC.peers[data.from_uid];
  if(pc) pc.addIceCandidate(new RTCIceCandidate(data.candidate)).catch(function(){});
}

function vcShowRemote(stream, uid, name){
  // Track which slot belongs to which uid
  if(!VC._uidSlot) VC._uidSlot = {};
  // If already assigned a slot, reuse it
  var assignedSlot = VC._uidSlot[uid];
  var targetSlot = assignedSlot || 0;
  if(!assignedSlot){
    for(var i=1;i<=3;i++){
      var vid=$('vc-rv-'+i);
      if(vid && !vid.srcObject){
        targetSlot = i;
        VC._uidSlot[uid] = i;
        break;
      }
    }
  }
  if(targetSlot === 0) return; // no slot
  var vid=$('vc-rv-'+targetSlot);
  var av=$('vc-ra-'+targetSlot);
  var nm=$('vc-rn-'+targetSlot);
  if(vid){
    vid.srcObject = stream;
    vid.style.display = 'block';
    // Force play (some mobile browsers need this)
    vid.play().catch(function(){});
  }
  if(av) av.style.display = 'none';
  if(nm) nm.textContent = name || ('User '+uid);
  var slot=$('vc-slot-'+targetSlot);
  if(slot){ slot.style.borderColor='rgba(16,185,129,.4)'; slot.style.border='1px solid rgba(16,185,129,.4)'; }
  toast((name||'User')+' joined the call!');
}

function startVcPoll(){
  VC.polling = setInterval(function(){
    var url='/api/vc/poll?uid='+UID+'&lo='+VC.pollIdx.offers+'&la='+VC.pollIdx.answers+'&li='+VC.pollIdx.ice;
    xhr(url, function(d){
      if(!d||!d.ok) return;
      if(d.offer_idx!==undefined) VC.pollIdx.offers=d.offer_idx;
      if(d.answer_idx!==undefined) VC.pollIdx.answers=d.answer_idx;
      if(d.ice_idx!==undefined) VC.pollIdx.ice=d.ice_idx;
      (d.offers||[]).forEach(vcHandleOffer);
      (d.answers||[]).forEach(vcHandleAnswer);
      (d.ice||[]).forEach(vcHandleICE);
      var cnt=d.count||1;
      setText('vc-pcnt',cnt+'/4'); setText('vc-parts-txt',cnt+'/4');
      if(!d.active && !VC.isHost){ toast('Host ne session end kiya'); vcLeave(); }
    });
  }, 1500);
}

function startVcTimer(){
  VC.durSec=0;
  VC.durTimer = setInterval(function(){
    VC.durSec++;
    var m=Math.floor(VC.durSec/60),s=VC.durSec%60;
    setText('vc-dur',(m<10?'0':'')+m+':'+(s<10?'0':'')+s);
  },1000);
}

function vcToggleMic(){
  if(!VC.stream||!VC.stream.getAudioTracks().length){ toast('Mic nahi hai'); return; }
  VC.micOn=!VC.micOn;
  VC.stream.getAudioTracks().forEach(function(t){t.enabled=VC.micOn;});
  updateMicUI(); toast('Mic '+(VC.micOn?'ON':'OFF'));
}

function vcToggleCam(){
  if(!VC.stream||!VC.stream.getVideoTracks().length){ toast('Camera nahi hai'); return; }
  VC.camOn=!VC.camOn;
  VC.stream.getVideoTracks().forEach(function(t){t.enabled=VC.camOn;});
  var lv=$('vc-local-video'), la=$('vc-local-avatar');
  if(lv) lv.style.display=VC.camOn?'block':'none';
  if(la) la.style.display=VC.camOn?'none':'flex';
  updateCamUI(); toast('Camera '+(VC.camOn?'ON':'OFF'));
}

function updateMicUI(){
  var hasMic=VC.stream&&VC.stream.getAudioTracks().length>0;
  var mic=$('mic-ic');
  if(mic) mic.textContent = hasMic ? (VC.micOn ? 'MIC-ON' : 'MUTED') : 'NO-MIC';
  setText('mic-txt', hasMic ? (VC.micOn ? 'Mic On' : 'Mic Off') : 'No Mic');
  var mi=$('vc-mic-ind');
  if(mi) mi.textContent = (hasMic && VC.micOn) ? '\u25CF' : '\u25CB';
  var mb=$('btn-mic');
  if(mb) mb.style.background = (hasMic&&VC.micOn) ? 'var(--inp)' : 'rgba(239,68,68,.15)';
}

function updateCamUI(){
  var hasCam=VC.stream&&VC.stream.getVideoTracks().length>0;
  var cam=$('cam-ic');
  if(cam) cam.textContent = hasCam ? (VC.camOn ? 'CAM-ON' : 'CAM-OFF') : 'NO-CAM';
  setText('cam-txt', hasCam ? (VC.camOn ? 'Cam On' : 'Cam Off') : 'No Cam');
  var cb=$('btn-cam');
  if(cb) cb.style.background = (hasCam&&VC.camOn) ? 'var(--inp)' : 'rgba(239,68,68,.15)';
}
function vcLeave(){
  post('/api/vc/leave',{uid:UID},function(){});
  vcCleanup();
  toast('Session se leave kar diya');
}

function vcCleanup(){
  if(VC.polling){clearInterval(VC.polling);VC.polling=null;}
  if(VC.durTimer){clearInterval(VC.durTimer);VC.durTimer=null;}
  Object.keys(VC.peers).forEach(function(uid){try{VC.peers[uid].close();}catch(e){}});
  VC.peers={};
  if(VC.stream){VC.stream.getTracks().forEach(function(t){t.stop();});VC.stream=null;}
  VC._uidSlot = {};
  for(var i=1;i<=3;i++){
    var vid=$('vc-rv-'+i),av=$('vc-ra-'+i);
    if(vid){vid.srcObject=null;vid.style.display='none';}
    if(av) av.style.display='flex';
    var slot=$('vc-slot-'+i);
    if(slot){ slot.style.borderColor='rgba(255,255,255,.15)'; slot.style.border='1px dashed rgba(255,255,255,.15)'; }
  }
  var lv=$('vc-local-video');
  if(lv) lv.srcObject=null;
  VC.pollIdx={offers:0,answers:0,ice:0};
  $('vc-wait').style.display='block';
  $('vc-active').style.display='none';
  vcCheckStatus();
}

function showVcActive(){
  $('vc-wait').style.display='none';
  $('vc-active').style.display='block';
  setText('vc-local-label','You'+(VC.isHost?' (Host)':''));
}
</script>
</body>
</html>
"""


OI_SPIKE_THRESHOLD = 1_00_00_000  # 1 Crore


def start_dashboard(bot_instance):
    if not FLASK_AVAILABLE:
        print("⚠️ Flask not installed. Run: pip install flask --break-system-packages")
        return

    app = Flask(__name__)
    app.config['JSON_AS_ASCII'] = False
    app.config['JSONIFY_MIMETYPE'] = 'application/json; charset=utf-8'

    @app.after_request
    def cors(r):
        r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Headers"] = "Content-Type"
        r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return r

    @app.route("/")
    def index():
        from flask import Response
        return Response(USER_DASHBOARD_HTML.encode('utf-8', errors='replace'), content_type='text/html; charset=utf-8')

    @app.route("/user")
    def user_page():
        from flask import Response
        return Response(USER_DASHBOARD_HTML.encode('utf-8', errors='replace'), content_type='text/html; charset=utf-8')

    @app.route("/owner")
    def owner_page():
        from flask import Response
        return Response(OWNER_DASHBOARD_HTML.encode('utf-8', errors='replace'), content_type='text/html; charset=utf-8')

    @app.route("/api/signal")
    def api_signal_owner():
        """Owner panel signal generator"""
        sig_type = request.args.get("type", "smart")
        symbol   = request.args.get("symbol", "NIFTY")
        # Holiday check
        today = date.today()
        if is_market_holiday(today):
            holiday_name = NSE_HOLIDAYS.get(today, "Holiday")
            return jsonify({"text": f"🏖️ AAJ MARKET BAND HAI\n\n📅 {today.strftime('%d %B %Y')}\n🎉 {holiday_name}\n\nAgle trading day pe signal milega."})
        if today.weekday() >= 5:
            day_name = "Saturday" if today.weekday() == 5 else "Sunday"
            return jsonify({"text": f"📅 AAJ {day_name.upper()} HAI — MARKET BAND\nMonday se signal milega."})
        try:
            if sig_type == "basic":
                oc = fetch_option_chain_extended(symbol)
                text = generate_single_swing_setup(symbol, oc["spot"], oc["pcr"], oc["ce_oi"], oc["pe_oi"], oc["oc_map"])
            elif sig_type == "pro":
                oc = fetch_option_chain_extended(symbol)
                text = generate_pro_setup(symbol, oc)
            elif sig_type == "smart":
                text = generate_smart_entry(symbol, user_id=0)
            else:
                text = generate_smart_entry(symbol, user_id=0)
            return jsonify({"text": text})
        except Exception as e:
            return jsonify({"text": f"Error: {e}"})

    @app.route("/api/ping")
    def ping():
        now = time.time()
        active = {str(uid): round(exp-now) for uid, exp in temporary_users.items() if exp > now}
        return jsonify({"ok": True, "active_users": active})

    @app.route("/api/debug-premium")
    def debug_premium():
        """Debug: see raw option chain data"""
        try:
            oc_data = fetch_option_chain_extended("NIFTY")
            spot = oc_data["spot"]
            step = 50
            atm = int(round(spot / step) * step)
            oc_map = oc_data.get("oc_map", {})
            # Get sample keys
            sample_keys = list(oc_map.keys())[:5]
            # Get ATM data
            atm_leg = oc_map.get(str(atm)) or oc_map.get(str(float(atm)))
            atm_info = {}
            if atm_leg:
                for side in ["pe", "PE", "ce", "CE"]:
                    opt = atm_leg.get(side)
                    if opt:
                        atm_info[side] = {k:v for k,v in list(opt.items())[:10]}
            return jsonify({
                "spot": spot,
                "atm": atm,
                "sample_keys": sample_keys,
                "atm_data": atm_info,
                "last_premium": oc_data.get("last_premium"),
                "all_keys_count": len(oc_map)
            })
        except Exception as e:
            return jsonify({"error": str(e)})

    @app.route("/api/stats")
    def api_stats():
        now = time.time()
        active = sum(1 for uid, exp in temporary_users.items() if exp > now and uid not in blocked_users)
        return jsonify({"active_users": active, "blocked_users": len(blocked_users), "unused_keys": len(access_keys)})

    @app.route("/api/users")
    def api_users():
        now = time.time()
        users = []
        seen = set()
        for uid, exp in temporary_users.items():
            seen.add(uid)
            blocked = uid in blocked_users
            rem = exp - now
            if rem > 0:
                d = int(rem // 86400); h = int((rem % 86400) // 3600); m = int((rem % 3600) // 60)
                expiry_str = f"{d}d {h}h {m}m"
            else:
                expiry_str = "Expired"
            users.append({"uid": uid, "expiry": expiry_str, "blocked": blocked})
        for uid in blocked_users:
            if uid not in seen:
                users.append({"uid": uid, "expiry": "—", "blocked": True})
        return jsonify({"users": users})

    @app.route("/api/user/check", methods=["GET", "OPTIONS"])
    def api_user_check():
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        try:
            uid = int(request.args.get("uid", 0))
        except:
            return jsonify({"valid": False, "blocked": False, "msg": "invalid uid"})
        if uid <= 0:
            return jsonify({"valid": False, "blocked": False, "msg": "uid missing"})
        now = time.time()
        # OWNER always gets access
        if uid == OWNER_ID:
            return jsonify({"valid": True, "blocked": False, "expiry": "Lifetime", "msg": "ok", "is_owner": True})
        if uid in blocked_users:
            return jsonify({"valid": False, "blocked": True, "msg": "blocked"})
        if uid not in temporary_users:
            total = len(temporary_users)
            return jsonify({"valid": False, "blocked": False, "msg": f"Access nahi hai. Bot mein /start karo aur key activate karo."})
        if temporary_users[uid] <= now:
            return jsonify({"valid": False, "blocked": False, "msg": "Access expired. Bot mein nayi key activate karo."})
        rem = temporary_users[uid] - now
        d = int(rem // 86400)
        h = int((rem % 86400) // 3600)
        m = int((rem % 3600) // 60)
        return jsonify({"valid": True, "blocked": False, "expiry": f"{d}d {h}h {m}m", "msg": "ok"})

    @app.route("/api/user/signal")
    def api_user_signal():
        try:
            uid = int(request.args.get("uid", 0))
        except:
            return jsonify({"text": "Invalid UID."})
        now = time.time()
        # OWNER bypass
        if uid != OWNER_ID:
            if uid in blocked_users:
                return jsonify({"text": "❌ Aapka account blocked hai. Owner se contact karo."})
            if uid not in temporary_users or temporary_users[uid] <= now:
                return jsonify({"text": "⏳ Access expired ya nahi hai.\n\nBot mein /start karo aur key activate karo.\n\n👑 KETAN AI"})
        sig_type = request.args.get("type", "basic")
        symbol = request.args.get("symbol", "NIFTY")
        # Market holiday check
        today = date.today()
        if is_market_holiday(today):
            holiday_name = NSE_HOLIDAYS.get(today, "Holiday")
            return jsonify({"text": f"🏖️ AAJ MARKET BAND HAI\n\n📅 {today.strftime('%d %B %Y')}\n🎉 {holiday_name}\n\nAgle trading day pe signal milega.\n\n👑 KETAN AI"})
        if today.weekday() >= 5:
            day_name = "Saturday" if today.weekday() == 5 else "Sunday"
            return jsonify({"text": f"📅 AAJ {day_name.upper()} HAI — MARKET BAND\n\nWeekend pe market nahi khulta.\nMonday 9:15 AM se signal milega.\n\n👑 KETAN AI"})
        # Market hours check (IST = UTC+5:30)
        from datetime import timezone
        ist_offset = timedelta(hours=5, minutes=30)
        now_ist = datetime.now(timezone.utc) + ist_offset
        h, m_min = now_ist.hour, now_ist.minute
        market_open = (h > 9 or (h == 9 and m_min >= 15)) and (h < 15 or (h == 15 and m_min <= 30))
        if not market_open:
            return jsonify({"text": f"🕐 MARKET ABHI BAND HAI\n\nMarket hours: 9:15 AM – 3:30 PM IST\nAbhi: {now_ist.strftime('%I:%M %p')} IST\n\nMarket khulne pe signal aayega.\n\n👑 KETAN AI"})
        # Check Dhan API token
        global ACCESS_TOKEN
        if not ACCESS_TOKEN or ACCESS_TOKEN.strip() == "":
            return jsonify({"text": "⚠️ DHAN API TOKEN MISSING\n\nBot mein /settoken command se Dhan token set karo.\n\nPhir signal refresh karo.\n\n👑 KETAN AI"})
        try:
            if sig_type == "basic":
                oc = fetch_option_chain_extended(symbol)
                text = generate_single_swing_setup(symbol, oc["spot"], oc["pcr"], oc["ce_oi"], oc["pe_oi"], oc["oc_map"], user_id=uid)
            elif sig_type == "pro":
                oc = fetch_option_chain_extended(symbol)
                text = generate_pro_setup(symbol, oc, user_id=uid)
            elif sig_type == "smart":
                text = generate_smart_entry(symbol, user_id=uid)
            elif sig_type == "sr":
                text = generate_smart_entry(symbol, user_id=uid)
            else:
                text = generate_smart_entry(symbol, user_id=uid)
            return jsonify({"text": text})
        except Exception as e:
            err_str = str(e)
            if "token" in err_str.lower() or "auth" in err_str.lower() or "401" in err_str or "403" in err_str:
                return jsonify({"text": f"🔐 DHAN TOKEN EXPIRED\n\nBot mein /settoken se naya token set karo.\n\n👑 KETAN AI"})
            return jsonify({"text": f"⚠️ Signal fetch error:\n{err_str[:200]}\n\nDobara try karo.\n\n👑 KETAN AI"})

    @app.route("/api/user/ticker")
    def api_user_ticker():
        try:
            uid = int(request.args.get("uid", 0))
        except:
            return jsonify({})
        now = time.time()
        # OWNER bypass
        if uid != OWNER_ID:
            if uid in blocked_users or uid not in temporary_users or temporary_users[uid] <= now:
                return jsonify({})
        try:
            n  = fetch_option_chain_extended("NIFTY")
            bn = fetch_option_chain_extended("BANKNIFTY")
            vix = fetch_india_vix()
            prev_n  = _ticker_prev.get("nifty", n["spot"])
            prev_bn = _ticker_prev.get("banknifty", bn["spot"])
            n_chg  = round(n["spot"] - prev_n, 2)
            bn_chg = round(bn["spot"] - prev_bn, 2)
            n_chg_pct  = round((n_chg / prev_n) * 100, 2) if prev_n else 0
            bn_chg_pct = round((bn_chg / prev_bn) * 100, 2) if prev_bn else 0
            _ticker_prev["nifty"] = n["spot"]
            _ticker_prev["banknifty"] = bn["spot"]
            return jsonify({
                "nifty":     str(round(n["spot"], 2)),
                "banknifty": str(round(bn["spot"], 2)),
                "pcr_n":     str(round(n["pcr"], 2)),
                "pcr_bn":    str(round(bn["pcr"], 2)),
                "vix":       str(round(vix, 2)) if vix else "N/A",
                "nifty_chg":    n_chg,
                "bn_chg":       bn_chg,
                "nifty_chg_pct":  n_chg_pct,
                "bn_chg_pct":     bn_chg_pct,
                "ce_oi":   str(n.get("ce_oi", 0)),
                "pe_oi":   str(n.get("pe_oi", 0)),
            })
        except Exception as e:
            return jsonify({"error": str(e)})

    @app.route("/api/user/alerts")
    def api_user_alerts():
        try:
            uid = int(request.args.get("uid", 0))
            since = float(request.args.get("since", 0))
        except:
            return jsonify({"alerts": []})
        now = time.time()
        if uid != OWNER_ID:
            if uid in blocked_users or uid not in temporary_users or temporary_users[uid] <= now:
                return jsonify({"alerts": []})
        alerts = [a for a in oi_push_alerts if a["ts"] > since] if 'oi_push_alerts' in globals() else []
        return jsonify({"alerts": alerts, "server_time": now})



    @app.route("/api/genkey", methods=["POST", "OPTIONS"])
    def api_genkey():
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        data = request.get_json(force=True, silent=True) or {}
        days = int(data.get("days", 1))
        key = generate_key_for_days(days)
        return jsonify({"key": key, "days": days})

    @app.route("/api/sendkey", methods=["POST", "OPTIONS"])
    def api_sendkey():
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        data = request.get_json(force=True, silent=True) or {}
        uid = int(data.get("uid", 0))
        days = int(data.get("days", 1))
        if not uid:
            return jsonify({"ok": False, "error": "uid missing"})
        try:
            seconds = days * 86400
            temporary_users[uid] = time.time() + seconds
            save_data()
            try:
                bot_instance.send_message(
                    uid,
                    f"✅ *Access activated!*\n⏳ *{days} day(s)*\n\n👉 /start karo",
                    parse_mode="Markdown"
                )
            except:
                pass
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/api/block", methods=["POST", "OPTIONS"])
    def api_block():
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        data = request.get_json(force=True, silent=True) or {}
        uid = int(data.get("uid", 0))
        block = data.get("block", True)
        if block:
            blocked_users.add(uid)
            temporary_users.pop(uid, None)
        else:
            blocked_users.discard(uid)
        save_data()
        return jsonify({"ok": True})

    @app.route("/api/broadcast", methods=["POST", "OPTIONS"])
    def api_broadcast():
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        data = request.get_json(force=True, silent=True) or {}
        msg = data.get("message", "")
        if not msg:
            return jsonify({"ok": False})
        now = time.time()
        count = 0
        for uid, exp in list(temporary_users.items()):
            if exp > now and uid not in blocked_users:
                try:
                    bot_instance.send_message(uid, msg)
                    count += 1
                except:
                    pass
        return jsonify({"ok": True, "count": count})

    @app.route("/api/token", methods=["POST", "OPTIONS"])
    def api_update_token():
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        data = request.get_json(force=True, silent=True) or {}
        token = data.get("token", "").strip()
        if not token:
            return jsonify({"ok": False, "error": "Token missing"})
        global ACCESS_TOKEN
        ACCESS_TOKEN = token
        # Also save to file for persistence
        try:
            cfg = {}
            if os.path.exists("config.json"):
                with open("config.json", "r") as f:
                    cfg = json.load(f)
            cfg["ACCESS_TOKEN"] = token
            with open("config.json", "w") as f:
                json.dump(cfg, f)
        except:
            pass
        return jsonify({"ok": True, "msg": "Token updated!"})


    # =====================================================
    # VIDEO CALL SIGNALING (WebRTC)
    # =====================================================
    import uuid as _uuid

    _vc_room = {
        "active": False,
        "host_uid": None,
        "participants": {},   # uid -> {name, joined_at}
        "offers":   [],       # list of {from_uid, to_uid, sdp}
        "answers":  [],       # list of {from_uid, to_uid, sdp}
        "ice":      [],       # list of {from_uid, to_uid, candidate}
        "started_at": 0,
    }

    def _vc_cleanup_old():
        import time
        # Auto-close room if idle > 2 hours
        if _vc_room["active"] and time.time() - _vc_room["started_at"] > 7200:
            _vc_room["active"] = False
            _vc_room["participants"] = {}
            _vc_room["offers"] = []
            _vc_room["answers"] = []
            _vc_room["ice"] = []

    @app.route("/api/vc/start", methods=["POST", "OPTIONS"])
    def vc_start():
        import time
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        try:
            uid = int(request.json.get("uid", 0))
            name = str(request.json.get("name", "User"))
        except:
            return jsonify({"ok": False, "msg": "invalid params"})
        now = time.time()
        if uid not in temporary_users or temporary_users.get(uid, 0) <= now:
            return jsonify({"ok": False, "msg": "access expired"})
        # Start or rejoin room
        _vc_room["active"] = True
        _vc_room["host_uid"] = uid
        _vc_room["started_at"] = now
        _vc_room["participants"][str(uid)] = {"name": name, "uid": uid, "joined_at": now}
        _vc_room["offers"] = []
        _vc_room["answers"] = []
        _vc_room["ice"] = []
        # Notify all active users via Telegram
        msg = (
            f"\U0001F4DE *LIVE VIDEO SESSION STARTED!*\n\n"
            f"\U0001F464 Host: {name}\n"
            f"\U0001F465 Participants: 1/4\n\n"
            f"App mein jao aur *Video* tab pe click karo join karne ke liye!\n\n"
            f"\U0001F451 KETAN AI"
        )
        try:
            _bot = bot_instance
            for tuid, exp in list(temporary_users.items()):
                if tuid != uid and exp > now and tuid not in blocked_users:
                    try:
                        _bot.send_message(
                            chat_id=tuid,
                            text=msg,
                            parse_mode="Markdown"
                        )
                    except:
                        pass
        except Exception as e:
            pass
        return jsonify({"ok": True, "room": _vc_room["active"], "count": len(_vc_room["participants"])})

    @app.route("/api/vc/join", methods=["POST", "OPTIONS"])
    def vc_join():
        import time
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        try:
            uid = int(request.json.get("uid", 0))
            name = str(request.json.get("name", "User"))
        except:
            return jsonify({"ok": False, "msg": "invalid"})
        now = time.time()
        if not _vc_room["active"]:
            return jsonify({"ok": False, "msg": "No active session. Koi session nahi chal raha."})
        if len(_vc_room["participants"]) >= 4:
            return jsonify({"ok": False, "msg": "Room full! Max 4 users."})
        _vc_room["participants"][str(uid)] = {"name": name, "uid": uid, "joined_at": now}
        return jsonify({
            "ok": True,
            "count": len(_vc_room["participants"]),
            "participants": list(_vc_room["participants"].values()),
            "host_uid": _vc_room["host_uid"]
        })

    @app.route("/api/vc/leave", methods=["POST", "OPTIONS"])
    def vc_leave():
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        try:
            uid = int(request.json.get("uid", 0))
        except:
            return jsonify({"ok": False})
        _vc_room["participants"].pop(str(uid), None)
        if len(_vc_room["participants"]) == 0 or str(uid) == str(_vc_room.get("host_uid")):
            _vc_room["active"] = False
            _vc_room["participants"] = {}
            _vc_room["offers"] = []
            _vc_room["answers"] = []
            _vc_room["ice"] = []
        return jsonify({"ok": True})

    @app.route("/api/vc/offer", methods=["POST", "OPTIONS"])
    def vc_offer():
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        try:
            data = request.json
            _vc_room["offers"].append(data)
            if len(_vc_room["offers"]) > 50:
                _vc_room["offers"] = _vc_room["offers"][-50:]
        except:
            pass
        return jsonify({"ok": True})

    @app.route("/api/vc/answer", methods=["POST", "OPTIONS"])
    def vc_answer():
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        try:
            data = request.json
            _vc_room["answers"].append(data)
            if len(_vc_room["answers"]) > 50:
                _vc_room["answers"] = _vc_room["answers"][-50:]
        except:
            pass
        return jsonify({"ok": True})

    @app.route("/api/vc/ice", methods=["POST", "OPTIONS"])
    def vc_ice():
        if request.method == "OPTIONS":
            return jsonify({"ok": True})
        try:
            data = request.json
            _vc_room["ice"].append(data)
            if len(_vc_room["ice"]) > 200:
                _vc_room["ice"] = _vc_room["ice"][-200:]
        except:
            pass
        return jsonify({"ok": True})

    @app.route("/api/vc/poll")
    def vc_poll():
        """Poll for new signals - called every 1s by each participant"""
        _vc_cleanup_old()
        try:
            uid = int(request.args.get("uid", 0))
            last_offer  = int(request.args.get("lo", 0))
            last_answer = int(request.args.get("la", 0))
            last_ice    = int(request.args.get("li", 0))
        except:
            return jsonify({"ok": False})
        # Return signals destined for this uid
        my_offers  = [o for o in _vc_room["offers"][last_offer:]  if str(o.get("to_uid")) == str(uid)]
        my_answers = [a for a in _vc_room["answers"][last_answer:] if str(a.get("to_uid")) == str(uid)]
        my_ice     = [i for i in _vc_room["ice"][last_ice:]       if str(i.get("to_uid")) == str(uid)]
        return jsonify({
            "ok": True,
            "active": _vc_room["active"],
            "count": len(_vc_room["participants"]),
            "participants": list(_vc_room["participants"].values()),
            "offers":  my_offers,
            "answers": my_answers,
            "ice":     my_ice,
            "offer_idx":  len(_vc_room["offers"]),
            "answer_idx": len(_vc_room["answers"]),
            "ice_idx":    len(_vc_room["ice"]),
        })

    @app.route("/api/vc/status")
    def vc_status():
        _vc_cleanup_old()
        import time
        return jsonify({
            "active": _vc_room["active"],
            "count": len(_vc_room["participants"]),
            "participants": list(_vc_room["participants"].values()),
            "host_uid": _vc_room["host_uid"],
        })

    def run():
        import os
        port = int(os.environ.get("PORT", 5000))
        try:
            app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
        except Exception as e:
            print(f"❌ Flask error: {e}")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    import time as _t; _t.sleep(1)
    print("✅ Dashboard: http://localhost:5000")
    print("✅ User URL:  http://localhost:5000/user")
    print("✅ Owner URL: http://localhost:5000/owner")


# ======================================================
# MISSING GLOBALS (needed by Flask)
# ======================================================
oi_push_alerts = []
_oi_snapshot = {}   # For OI spike detection
_ticker_prev  = {}  # For price change calculation
OI_SPIKE_THRESHOLD = 1_00_00_000  # 1 Crore



# ======================================================
# OI SPIKE MONITOR
# ======================================================
def check_oi_spikes(bot_instance):
    """Check OI spikes every 60 seconds - alert if > 1 Crore change"""
    global oi_push_alerts
    for symbol in ["NIFTY", "BANKNIFTY"]:
        try:
            oc = fetch_option_chain_extended(symbol)
            ce_oi = oc["ce_oi"]
            pe_oi = oc["pe_oi"]
            prev = _oi_snapshot.get(symbol)
            _oi_snapshot[symbol] = {"ce": ce_oi, "pe": pe_oi}
            if not prev:
                continue
            ce_chg = ce_oi - prev["ce"]
            pe_chg = pe_oi - prev["pe"]
            alerts = []
            if abs(ce_chg) >= OI_SPIKE_THRESHOLD:
                side = "CALL (CE)" if ce_chg > 0 else "CALL (CE) EXIT"
                emoji = "🔴" if ce_chg > 0 else "📉"
                alerts.append({"symbol": symbol, "side": "CE", "change": ce_chg, "emoji": emoji, "label": side})
            if abs(pe_chg) >= OI_SPIKE_THRESHOLD:
                side = "PUT (PE)" if pe_chg > 0 else "PUT (PE) EXIT"
                emoji = "🟢" if pe_chg > 0 else "📈"
                alerts.append({"symbol": symbol, "side": "PE", "change": pe_chg, "emoji": emoji, "label": side})
            for a in alerts:
                chg_cr = round(abs(a["change"]) / 1e7, 2)
                msg = (f"🚨 OI SPIKE ALERT!\n"
                       f"━━━━━━━━━━━━━━━━\n"
                       f"📊 {a['symbol']} — {a['label']}\n"
                       f"{a['emoji']} Change: {chg_cr} Cr\n"
                       f"━━━━━━━━━━━━━━━━\n"
                       f"👑 KETAN AI")
                try:
                    bot_instance.send_message(OWNER_ID, msg, parse_mode="Markdown")
                except Exception:
                    pass
                now = time.time()
                for uid, exp in list(temporary_users.items()):
                    if exp > now and uid not in blocked_users and uid != OWNER_ID:
                        try:
                            bot_instance.send_message(uid, msg, parse_mode="Markdown")
                        except Exception:
                            pass
                push_alert = {
                    "id": f"{a['symbol']}_{a['side']}_{int(time.time())}",
                    "symbol": a["symbol"],
                    "side": a["side"],
                    "change_cr": chg_cr,
                    "emoji": a["emoji"],
                    "label": a["label"],
                    "ts": time.time()
                }
                oi_push_alerts.insert(0, push_alert)
                if len(oi_push_alerts) > 50:
                    oi_push_alerts = oi_push_alerts[:50]
        except Exception:
            pass


def start_oi_monitor(bot_instance):
    """Start OI spike monitoring in background"""
    def loop():
        while True:
            try:
                check_oi_spikes(bot_instance)
            except Exception:
                pass
            time.sleep(60)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print("✅ OI Spike Monitor started (1 Cr threshold)")


def main():
    global TOKEN

    load_data()

    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN missing.")
        print("Termux mein pehle run karo:")
        print("export TELEGRAM_BOT_TOKEN='YOUR_BOT_TOKEN'")
        print("phir: python bot-2.py")
        return

    # One event loop is shared by Telegram + Flask/OI background threads.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    application = ApplicationBuilder().token(TOKEN).build()
    bot_adapter = SyncBotAdapter(application.bot, loop)

    application.add_handler(
        CommandHandler("start", make_sync_callback(start, bot_adapter))
    )
    application.add_handler(
        CallbackQueryHandler(make_sync_callback(handle_button_callback, bot_adapter))
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            make_sync_callback(handle_text_message, bot_adapter)
        )
    )

    # Start Flask dashboard using the synchronous Telegram adapter.
    start_dashboard(bot_adapter)

    # Start OI monitor using the same adapter.
    start_oi_monitor(bot_adapter)

    print("✅ Bot started! Telegram + Dashboard both running.")
    print("🌐 Dashboard: http://localhost:5000/user")

    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
        )
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
    except Exception as e:
        print(f"❌ Telegram polling error: {e}")
        raise

if __name__ == "__main__":
    main()
