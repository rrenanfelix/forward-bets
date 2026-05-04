# Forward Backtest — Apostas EV+

Pipeline automatizado de seleção de apostas com base em frequências históricas de 30 ligas (208k jogos analisados).

## Como funciona

- **`forward_pipeline.py`** — busca jogos das próximas 48h via API-Football, filtra entradas com EV teórico ≥ 5%, registra em `forward_bets.json`. Subcomandos:
  - `collect` — coleta jogos + odds de hoje + 2 dias
  - `resolve` — fecha resultados de jogos terminados
- **`pick_top10.py`** — seleciona até 10 melhores entradas por dia (filtro estrito de odd + score)
- **`forward_dashboard.html`** — dashboard local pra acompanhar P&L em R$ (stake R$ 100)

## Execução automática

GitHub Actions roda diariamente:
- **01:00 UTC (22:00 BRT)** — `collect` + `pick_top10`
- **06:00 UTC (03:00 BRT)** — `resolve`

Cada run commita o `forward_bets.json` atualizado de volta no repo.

## Dashboard local

```
python3 -m http.server 8765
```
Abre http://localhost:8765/forward_dashboard.html

## Filtro do `pick_top10`

```python
LIMITS = {
    "home": (2.80, 0.25),  # odd_max, ev_max
    "draw": (4.00, 0.25),
    "away": (3.50, 0.25),
}
```

Ranking por score = 0.55·prob_hist + 0.30·EV + 0.15·(1/odd).
