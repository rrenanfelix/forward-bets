#!/usr/bin/env python3
"""Pipeline forward: coleta jogos+odds, registra entradas com EV+, fecha resultados.

Uso:
  python3 forward_pipeline.py collect    # roda 1x/dia: vê jogos das próximas 48h e registra entradas EV+
  python3 forward_pipeline.py resolve    # roda 1x/dia: fecha entradas pendentes cujo jogo terminou
  python3 forward_pipeline.py report     # imprime resumo: hit rate, ROI por liga × mercado
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

import requests

ROOT = Path(__file__).parent
STRATEGIES_FILE = ROOT / "forward_strategies.json"
BETS_FILE = ROOT / "forward_bets.json"

API_BASE = "https://v3.football.api-sports.io"
MATCH_WINNER_BET_ID = 1
RATE_DELAY = 0.15
LOOKAHEAD_DAYS = 1


def api_key():
    env = os.environ.get("API_FOOTBALL_KEY")
    if env:
        return env.strip()
    return subprocess.check_output(
        ["security", "find-generic-password", "-a", "renanads", "-s", "api-football", "-w"]
    ).decode().strip()


def load_json(p, default):
    if not p.exists():
        return default
    with p.open() as f:
        return json.load(f)


def save_json(p, data):
    with p.open("w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get(key, path, params):
    r = requests.get(f"{API_BASE}{path}",
                     headers={"x-apisports-key": key}, params=params, timeout=30)
    if r.status_code == 429:
        time.sleep(60)
        r = requests.get(f"{API_BASE}{path}",
                         headers={"x-apisports-key": key}, params=params, timeout=30)
    r.raise_for_status()
    time.sleep(RATE_DELAY)
    return r.json().get("response", [])


def median_1x2(odds_response):
    home, draw, away = [], [], []
    for entry in odds_response:
        for bm in entry.get("bookmakers", []):
            for bet in bm.get("bets", []):
                if bet.get("id") != MATCH_WINNER_BET_ID:
                    continue
                for v in bet.get("values", []):
                    try:
                        odd = float(v.get("odd"))
                    except (ValueError, TypeError):
                        continue
                    val = v.get("value")
                    if val == "Home":
                        home.append(odd)
                    elif val == "Draw":
                        draw.append(odd)
                    elif val == "Away":
                        away.append(odd)
    if not (home and draw and away):
        return None
    return {"home": median(home), "draw": median(draw), "away": median(away)}


def cmd_collect():
    cfg = load_json(STRATEGIES_FILE, {})
    bets = load_json(BETS_FILE, [])
    existing_ids = {b["id"] for b in bets}
    min_ev = cfg.get("min_ev_pct", 5) / 100.0
    key = api_key()
    today = datetime.now(timezone.utc).date()
    dates = [(today + timedelta(days=k)).isoformat() for k in range(LOOKAHEAD_DAYS + 1)]
    new_bets = 0

    for league in cfg["leagues"]:
        league_id = league["id"]
        season = league["season"]
        freq = league["freq"]
        for date in dates:
            try:
                fixtures = get(key, "/fixtures",
                               {"league": league_id, "season": season, "date": date})
            except Exception as e:
                print(f"  erro fixtures liga={league_id} date={date}: {e}")
                continue
            for fx in fixtures:
                fixture_id = fx["fixture"]["id"]
                status = fx.get("fixture", {}).get("status", {}).get("short")
                if status not in ("NS", "TBD", "PST"):
                    continue
                home_name = fx["teams"]["home"]["name"]
                away_name = fx["teams"]["away"]["name"]
                kickoff = fx["fixture"].get("date", "")
                try:
                    odds = get(key, "/odds",
                               {"fixture": fixture_id, "bet": MATCH_WINNER_BET_ID})
                except Exception as e:
                    print(f"  erro odds {fixture_id}: {e}")
                    continue
                med = median_1x2(odds)
                if not med:
                    continue
                for market in ("home", "draw", "away"):
                    bet_id = f"{fixture_id}_{market}"
                    if bet_id in existing_ids:
                        continue
                    p = freq[market]
                    odd = med[market]
                    ev = p * odd - 1
                    if ev < min_ev:
                        continue
                    bets.append({
                        "id": bet_id,
                        "fixture_id": fixture_id,
                        "league_id": league_id,
                        "league_name": f"{league['name']} ({league['country']})",
                        "kickoff_utc": kickoff,
                        "home": home_name,
                        "away": away_name,
                        "market": market,
                        "prob_hist": round(p, 4),
                        "odd_entry": round(odd, 3),
                        "ev_teorico": round(ev, 4),
                        "status": "pending",
                        "result_home": None,
                        "result_away": None,
                        "outcome": None,
                        "pnl": None,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "resolved_at": None,
                    })
                    existing_ids.add(bet_id)
                    new_bets += 1
                    print(f"  + {league['name']} | {home_name} vs {away_name} | {market} @ {odd:.2f} | EV={100*ev:+.1f}%")
    save_json(BETS_FILE, bets)
    print(f"\n[collect] novas entradas: {new_bets} | total no arquivo: {len(bets)}")


def cmd_resolve():
    bets = load_json(BETS_FILE, [])
    pending_by_fix = {}
    for b in bets:
        if b["status"] == "pending":
            pending_by_fix.setdefault(b["fixture_id"], []).append(b)
    if not pending_by_fix:
        print("[resolve] nada pendente")
        return
    key = api_key()
    n_resolved = 0
    for fixture_id, group in pending_by_fix.items():
        try:
            res = get(key, "/fixtures", {"id": fixture_id})
        except Exception as e:
            print(f"  erro fixture {fixture_id}: {e}")
            continue
        if not res:
            continue
        fx = res[0]
        status = fx.get("fixture", {}).get("status", {}).get("short")
        if status not in ("FT", "AET", "PEN"):
            continue
        h = fx["goals"]["home"] or 0
        a = fx["goals"]["away"] or 0
        if h > a:
            outcome = "home"
        elif a > h:
            outcome = "away"
        else:
            outcome = "draw"
        for b in group:
            won = b["market"] == outcome
            b["status"] = "won" if won else "lost"
            b["result_home"] = h
            b["result_away"] = a
            b["outcome"] = outcome
            b["pnl"] = round(b["odd_entry"] - 1, 3) if won else -1.0
            b["resolved_at"] = datetime.now(timezone.utc).isoformat()
            n_resolved += 1
            print(f"  {'✓' if won else '✗'} {b['home']} {h}x{a} {b['away']} | {b['market']} @ {b['odd_entry']:.2f} | pnl={b['pnl']:+.2f}")
    save_json(BETS_FILE, bets)
    print(f"\n[resolve] resolvidas: {n_resolved}")


def cmd_report():
    bets = load_json(BETS_FILE, [])
    settled = [b for b in bets if b["status"] in ("won", "lost")]
    pending = [b for b in bets if b["status"] == "pending"]

    print(f"=== Forward Backtest Report ===")
    print(f"Total entradas: {len(bets)} | resolvidas: {len(settled)} | pendentes: {len(pending)}")

    if not settled:
        print("\nSem entradas resolvidas ainda. Rode `resolve` depois dos jogos terminarem.")
        return

    n = len(settled)
    n_won = sum(1 for b in settled if b["status"] == "won")
    pnl = sum(b["pnl"] for b in settled)
    avg_odd = sum(b["odd_entry"] for b in settled) / n
    avg_ev = sum(b["ev_teorico"] for b in settled) / n
    print(f"\nGlobal:")
    print(f"  n={n} | hit={n_won} ({100*n_won/n:.1f}%) | pnl={pnl:+.2f}u | ROI={100*pnl/n:+.1f}%")
    print(f"  odd média={avg_odd:.2f} | EV teórico médio={100*avg_ev:+.1f}%")

    # Por liga × mercado
    grp = {}
    for b in settled:
        k = f"{b['league_name']} | {b['market']}"
        g = grp.setdefault(k, {"n":0,"won":0,"pnl":0.0,"avg_odd":0.0})
        g["n"] += 1
        g["won"] += 1 if b["status"] == "won" else 0
        g["pnl"] += b["pnl"]
        g["avg_odd"] += b["odd_entry"]
    print(f"\nPor liga × mercado:")
    print(f"  {'estrategia':<60s} {'n':>4s} {'hit%':>6s} {'odd':>6s} {'pnl':>8s} {'ROI%':>7s}")
    rows = []
    for k, g in grp.items():
        if g["n"] == 0: continue
        rows.append((k, g["n"], 100*g["won"]/g["n"], g["avg_odd"]/g["n"], g["pnl"], 100*g["pnl"]/g["n"]))
    for k, n_, hit, odd, pnl_, roi in sorted(rows, key=lambda x: -x[5]):
        print(f"  {k:<60s} {n_:>4d} {hit:>5.1f}% {odd:>6.2f} {pnl_:>+7.2f} {roi:>+6.1f}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["collect", "resolve", "report"])
    args = parser.parse_args()
    if args.mode == "collect":
        cmd_collect()
    elif args.mode == "resolve":
        cmd_resolve()
    else:
        cmd_report()


if __name__ == "__main__":
    main()
