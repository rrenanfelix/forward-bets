#!/usr/bin/env python3
"""Seleciona TODAS as entradas que passam no filtro (odd + EV) por dia.

Marca as escolhidas em forward_bets.json com:
  is_top10: true        (campo mantido por compat — agora significa "selecionada")
  top10_day: "YYYY-MM-DD"

Entradas já resolvidas (won/lost) são preservadas - não re-seleciona o passado.
"""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
BETS_FILE = ROOT / "forward_bets.json"

# Faixas otimizadas por backtest (ROI histórico):
#   home 2.30-2.60 = +25.6% | draw 3.00-4.00 = +60% | away 3.00-3.60 = +51.6%
#   CORTADO: home >= 2.60 (era -24.9% ROI, buraco negro do mandante meia-boca)
# (odd_min, odd_max, ev_max)
LIMITS = {
    "home": (2.20, 2.60, 0.25),
    "draw": (3.00, 4.20, 0.30),
    "away": (3.00, 3.70, 0.30),
}


# Ter(1)/Qua(2)/Qui(3) = mata-mata europeu (Champions/Europa) = mismatch.
# Backtest: cortar esses dias sobe ROI de +21% pra +28%.
EXCLUDE_WEEKDAYS = {1, 2, 3}


def passes_filter(b):
    omin, omax, evmax = LIMITS[b["market"]]
    return omin <= b["odd_entry"] <= omax and b["ev_teorico"] <= evmax


def is_excluded_weekday(day_str):
    try:
        return datetime.strptime(day_str, "%Y-%m-%d").weekday() in EXCLUDE_WEEKDAYS
    except ValueError:
        return False


def score(b):
    return (
        b["prob_hist"] * 100 * 0.70
        + b["ev_teorico"] * 100 * 0.15
        + (1.0 / b["odd_entry"]) * 100 * 0.15
    )


def kickoff_day(iso: str) -> str:
    """Retorna a data BRT (UTC-3) do kickoff, não a UTC."""
    if not iso:
        return ""
    dt_utc = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    dt_brt = dt_utc - timedelta(hours=3)
    return dt_brt.date().isoformat()


def main():
    bets = json.loads(BETS_FILE.read_text())
    today_utc = datetime.now(timezone.utc).date().isoformat()

    # 1) Limpa marcações pendentes de hoje/futuros — re-seleciona com odds atualizadas.
    # Preserva: (a) entradas já resolvidas (won/lost) e (b) entradas marcadas em dias passados
    # (mesmo se ainda estiverem pending — evita perder picks que ainda não foram resolvidas).
    for b in bets:
        if b["status"] in ("won", "lost"):
            continue
        prev_day = b.get("top10_day")
        if prev_day and prev_day < today_utc:
            continue
        b["is_top10"] = False
        b["top10_day"] = None

    # 2) Agrupa entradas pendentes por dia
    by_day = defaultdict(list)
    for b in bets:
        if b["status"] != "pending":
            continue
        if not passes_filter(b):
            continue
        d = kickoff_day(b["kickoff_utc"])
        if d < today_utc:
            continue  # jogos passados sem resolução ainda — não força top10
        if is_excluded_weekday(d):
            continue  # ter/qua/qui = mismatch europeu, ROI ruim
        by_day[d].append(b)

    # 3) Pra cada dia, marca passantes do filtro com diversificação:
    #    - Máximo 1 pick por (liga, mercado) — evita concentrar 6 draws da Serie B IT
    print(f"{'Dia':<12s} {'candidatos':>11s} {'selecionadas':>13s}")
    print("-" * 45)
    total_picked = 0
    for d in sorted(by_day):
        cands = sorted(by_day[d], key=score, reverse=True)
        seen_keys = set()
        chosen = []
        for b in cands:
            key = (b["league_id"], b["market"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            chosen.append(b)
        for b in chosen:
            b["is_top10"] = True
            b["top10_day"] = d
        total_picked += len(chosen)
        print(f"{d:<12s} {len(cands):>11d} {len(chosen):>13d}")

    BETS_FILE.write_text(json.dumps(bets, ensure_ascii=False, indent=2))
    print(f"\nTotal marcados: {total_picked}")
    print("Salvo em forward_bets.json")


if __name__ == "__main__":
    main()
