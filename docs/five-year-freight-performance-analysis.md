# Five-year freight performance: Attempt 19

Analysis uses original [Attempt 19](../artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19/), separately [verified offline recovery](../artifacts/experiments/attempt19-offline-recovery/verification.json), and existing [P07 JSON](../artifacts/experiments/p07-attempt19-five-year-offline/summary.json), [CSV](../artifacts/experiments/p07-attempt19-five-year-offline/metrics.csv), and [eleven charts](../artifacts/experiments/p07-attempt19-five-year-offline/charts.html). Historical native status remains **FAILED**. Offline evidence verification **PASSED**. This analysis requires no native launch or Admin connection.

## Observed output

Service labels follow P07: S1 route `021fcc0d…`, vehicle 4; S2 `1ca7d46d…`, vehicle 5; S3 `2ad5b0f8…`, vehicle 6. Each has one 20-unit vehicle.

| Economy anniversary interval | S1 cargo | S2 cargo | S3 cargo | Network cargo | Network revenue |
|---|---:|---:|---:|---:|---:|
| 1 | 200 | 200 | 180 | 580 | £9,920 |
| 2 | 200 | 200 | 200 | 600 | £10,259 |
| 3 | 200 | 200 | 200 | 600 | £10,258 |
| 4 | 220 | 180 | 200 | 600 | £10,241 |
| 5 | 200 | 200 | 200 | 600 | £10,257 |
| Total | 1,020 | 980 | 980 | 2,980 | £50,935 |

**Revenue per service in every interval is UNKNOWN**: the service revenue field is null. Network income cannot be divided by cargo shares or reconstructed from vehicle profit without inventing attribution. The intervals contain 365/366/366/364/365 observed days, totaling 1,826; anniversary targets do not imply exact sampling on the target day.

The network averages 1.632 cargo units and £27.894 revenue per economy day. S1 averages 0.559 cargo/day; S2 and S3 each 0.537. S1's small lead does not establish a better investment: routes started at different phases and service-level revenue/cost attribution is unavailable.

The 60 monthly sampled intervals have network cargo 0–60 and revenue £0–£1,028. Each service delivers 0–20 per interval. Zero-delivery intervals: S1 nine, S2 eleven, S3 nine; network one. These are delivery counts, not vehicle idle periods. Monthly rows cover economy dates 712299–714108, versus the whole-run endpoint 714125. Their totals are 2,940 cargo and £50,267: the final 17-day tail contains 40 cargo and £668. Do not sum overlapping monthly, quarterly and annual rows together.

## Bottlenecks: observations and interpretations

| Measure | S1 | S2 | S3 |
|---|---:|---:|---:|
| Source waiting cargo at end | 305 | 572 | 574 |
| Maximum sampled waiting cargo | 612 | 979 | 779 |
| Samples with waiting cargo > 0 / 1,605 | 1,595 | 1,596 | 1,594 |
| Samples loaded to capacity / 1,605 | 796 | 800 | 801 |
| Samples with zero load / 1,605 | 733 | 735 | 725 |
| Samples with speed zero / 1,605 | 104 | 94 | 102 |
| Coalesced unloading episodes | 51 | 49 | 49 |
| Episode-start spacing, economy days | 35–37 | 36–38 | 36–39 |
| Construction and purchase CAPEX | £9,358 | £9,515 | £9,586 |

An unloading episode groups consecutive snapshots with positive delivered-cargo increments. Every resulting episode delivers 20 units. Individual increments can be 5, 10 or 15 during unloading and must not be counted as separate trips. These are derived observed episodes; the native `completed_delivery_cycles` field remains null. Sampling makes their spacing approximate delivery cadence, not exact journey duration.

Persistent waiting cargo, repeated full unloading batches and roughly monthly delivery cadence support **insufficient effective carrying capacity/frequency relative to available station cargo** as the leading hypothesis. S2/S3 have higher endpoint queues than S1 and deserve priority in a controlled allocation comparison. Queue values fluctuate: neither cumulative production nor lost cargo can be inferred from the endpoint queue.

Zero-load snapshots can include empty return travel; zero speed can include loading/unloading. Neither proves avoidable idle time. No departure/arrival duration series establishes travel time, and no occupancy/traffic counter establishes road, depot or station saturation. All three infrastructures carried freight, but numerical infrastructure utilization and congestion are UNKNOWN. Road investment is therefore a lower-evidence alternative than changing capacity/allocation.

## Finance boundary

Setup: `£500,000 - £28,459 CAPEX - £335 measured aggregate expenses - £50 unattributed decrease = £471,156` operating opening cash.

Operating window: `£471,156 + £50,935 revenue - £16,312 measured unallocated expenses - £1,500 unattributed decrease = £504,279` closing cash. Observed net cash movement is +£33,123, not net profit. Loan principal remains £100,000. Count CAPEX once, outside the operating window. Actual vehicle OPEX, interest attribution, other expense categories, service profit, ROI, cost recovery and break-even remain UNKNOWN. Vehicle profit fields and annual running-cost rates do not fill those gaps.

## Decision and next experiment

The [controlled P08/P05 comparison](five-year-freight-controlled-alternatives.md) tests explicit fleet capacities, allocations and infrastructure costs. Recurring service frequency and physical upgrades require additional model inputs. Candidate feasibility and objective changes describe the supplied controlled model; they do not predict a measured native gain. Keep optimizer defaults unchanged and do not tune automatically from this one run.

The strongest next experiment is a matched baseline versus increased effective fleet capacity on S2/S3, holding source world, observation horizon and route geometry fixed. Compare delivered cargo, source waiting cargo, unloading cadence, full-load observations and attributable finance. First compare existing controlled alternatives; any future native comparison requires separate authorization and richer timing/expense attribution. This document authorizes no launch.

## Reproduction

Replay retained evidence and regenerate existing P07 outputs to a separate directory:

```bash
.venv/bin/python -m app.experiments.cli analyze-continuous-freight \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19 \
  --recovery-directory artifacts/experiments/attempt19-offline-recovery \
  --output /tmp/attempt19-performance-p07
```

Inspect exact annual/monthly rows and reproduce bottleneck counts without modifying evidence:

```bash
.venv/bin/python - <<'PY'
import json
from collections import Counter
from pathlib import Path
p = json.loads(Path('artifacts/experiments/p07-attempt19-five-year-offline/summary.json').read_text())
for row in p['periods']:
    if row['period'] in ('annual', 'monthly'):
        print(row['period'], row['index'], row['scope'], row['elapsed_economy_days'],
              row['delivered_cargo'], row['revenue'])
for n in range(3):
    ss = [s['services'][n] for s in p['snapshots']]
    episodes, previous = [], -3
    for i in range(1, len(ss)):
        delta = ss[i]['delivered'] - ss[i - 1]['delivered']
        if delta > 0:
            if i > previous + 1:
                episodes.append([p['snapshots'][i]['elapsed_economy_days'], delta])
            else:
                episodes[-1][1] += delta
            previous = i
    waiting = [s['station_waiting'] for s in ss]
    gaps = [b[0] - a[0] for a, b in zip(episodes, episodes[1:])]
    print('service', n + 1, 'waiting end/max/positive', waiting[-1], max(waiting),
          sum(x > 0 for x in waiting), 'full/empty/stopped',
          sum(s['cargo_load'] == s['capacity'] for s in ss),
          sum(s['cargo_load'] == 0 for s in ss),
          sum(s['snapshot'][10] == 0 for s in ss),
          'episodes', len(episodes), 'batch sizes', Counter(x[1] for x in episodes),
          'spacing', min(gaps), max(gaps))
print(p['finance'])
PY
```
