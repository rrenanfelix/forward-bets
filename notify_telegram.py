#!/usr/bin/env python3
"""Envia notificação no Telegram com os picks do dia + acumulado.

Modos:
  python3 notify_telegram.py picks    # picks de hoje + amanhã
  python3 notify_telegram.py results  # resultados do dia anterior
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).parent
BETS_FILE = ROOT / "forward_bets.json"
STAKE = 100

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send(text: str):
    if not TOKEN or not CHAT_ID:
        print("ERRO: TELEGRAM_BOT_TOKEN/CHAT_ID não configurados")
        sys.exit(1)
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if r.status_code != 200:
        print(f"ERRO Telegram: {r.status_code} - {r.text}")
        sys.exit(1)
    print("Mensagem enviada.")


def fmt_money(n):
    sign = "+" if n >= 0 else "-"
    return f"{sign}R$ {abs(n):.2f}".replace(".", ",")


def picks_message():
    bets = json.loads(BETS_FILE.read_text())
    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)

    out = ["<b>🎯 Picks do dia</b>\n"]

    for d in (today, tomorrow):
        d_str = d.isoformat()
        picks = [b for b in bets if b.get("top10_day") == d_str and b["status"] == "pending"]
        if not picks:
            continue
        picks.sort(key=lambda b: b["kickoff_utc"])
        date_label = d.strftime("%d/%m (%a)")
        out.append(f"\n<b>📅 {date_label}</b> — {len(picks)} picks")
        for b in picks:
            ko = datetime.fromisoformat(b["kickoff_utc"].replace("Z", "+00:00")) - timedelta(hours=3)
            time_str = ko.strftime("%H:%M")
            ev = b["ev_teorico"] * 100
            out.append(
                f"⚽ <b>{time_str}</b> {b['league_name']}\n"
                f"   {b['home']} × {b['away']}\n"
                f"   <b>{b['market'].upper()}</b> @ {b['odd_entry']:.2f} | EV {ev:+.1f}%"
            )

    settled = [b for b in bets if b.get("is_top10") and b["status"] in ("won", "lost")]
    if settled:
        won = sum(1 for b in settled if b["status"] == "won")
        pnl = sum(STAKE * (b["odd_entry"] - 1) if b["status"] == "won" else -STAKE for b in settled)
        roi = 100 * pnl / (len(settled) * STAKE)
        out.append(
            f"\n📊 <b>Acumulado Picks</b>\n"
            f"   {len(settled)} resolvidas | hit {100*won/len(settled):.1f}%\n"
            f"   P&amp;L {fmt_money(pnl)} | ROI {roi:+.1f}%"
        )

    if len(out) == 1:
        out.append("\nSem picks selecionados pra hoje/amanhã.")
    return "\n".join(out)


def results_message():
    bets = json.loads(BETS_FILE.read_text())
    today_brt = datetime.now(timezone.utc) - timedelta(hours=3)
    yesterday_brt = (today_brt - timedelta(days=1)).date().isoformat()

    picks = [b for b in bets if b.get("top10_day") == yesterday_brt and b["status"] in ("won", "lost")]
    if not picks:
        return None

    picks.sort(key=lambda b: b["kickoff_utc"])
    won = sum(1 for b in picks if b["status"] == "won")
    pnl = sum(STAKE * (b["odd_entry"] - 1) if b["status"] == "won" else -STAKE for b in picks)
    roi = 100 * pnl / (len(picks) * STAKE)

    date_label = datetime.fromisoformat(yesterday_brt).strftime("%d/%m (%a)")
    out = [f"<b>📈 Resultados {date_label}</b>\n"]
    for b in picks:
        h, a = b.get("result_home", "?"), b.get("result_away", "?")
        m = STAKE * (b["odd_entry"] - 1) if b["status"] == "won" else -STAKE
        sym = "✅" if b["status"] == "won" else "❌"
        out.append(
            f"{sym} {b['home']} {h}×{a} {b['away']}\n"
            f"   {b['market'].upper()} @ {b['odd_entry']:.2f} → <b>{fmt_money(m)}</b>"
        )

    out.append(
        f"\n<b>Total dia</b>\n"
        f"   {len(picks)} entradas | hit {100*won/len(picks):.1f}%\n"
        f"   P&amp;L {fmt_money(pnl)} | ROI {roi:+.1f}%"
    )

    settled_all = [b for b in bets if b.get("is_top10") and b["status"] in ("won", "lost")]
    if settled_all:
        won_all = sum(1 for b in settled_all if b["status"] == "won")
        pnl_all = sum(STAKE * (b["odd_entry"] - 1) if b["status"] == "won" else -STAKE for b in settled_all)
        roi_all = 100 * pnl_all / (len(settled_all) * STAKE)
        out.append(
            f"\n<b>Acumulado geral</b>\n"
            f"   {len(settled_all)} entradas | hit {100*won_all/len(settled_all):.1f}%\n"
            f"   P&amp;L {fmt_money(pnl_all)} | ROI {roi_all:+.1f}%"
        )

    return "\n".join(out)


def main():
    if len(sys.argv) < 2:
        print("Uso: notify_telegram.py picks|results")
        sys.exit(1)
    mode = sys.argv[1]
    if mode == "picks":
        msg = picks_message()
    elif mode == "results":
        msg = results_message()
        if not msg:
            print("Sem resultados pra notificar.")
            return
    else:
        print(f"Modo inválido: {mode}")
        sys.exit(1)
    send(msg)


if __name__ == "__main__":
    main()
