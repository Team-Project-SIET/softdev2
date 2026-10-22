# Attempt 19 controlled planning alternatives

These offline comparisons reuse Attempt 19's retained P08 candidate scenario and
unchanged P05 optimizer. Each emitted plan passes `validate_execution_plan`.
They establish feasibility against supplied planning constraints, not native
execution, frequency, revenue or throughput improvements. Attempt 19 remains FAILED.

Reproduce without a native launch or Admin connection:

```bash
.venv/bin/python -m app.experiments.freight_alternatives \
  artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19/planning-scenario.json
.venv/bin/pytest -q tests/test_freight_alternatives.py
```

The retained scenario supplies 20 cargo units per service, a 20-unit engine,
three vehicles maximum and £500,000 budget. P05 models one planned trip per
vehicle. Values below are supplied planning-horizon demand and estimated initial
CAPEX; they are not monthly or annual predictions or incremental upgrade quotes.
The baseline £25,607 estimate differs from observed £28,459 command-local CAPEX
by £2,852. This is retrospective cost error, not an investment return or forecast.

| Controlled input | Served planning units | Vehicles | Estimated CAPEX |
|---|---:|---:|---:|
| Retained baseline | 60 | 3 | £25,607 |
| Six-vehicle limit, same demand | 60 | 3 | £25,607 |
| Hypothetical 10-unit capacity, six-vehicle limit | 60 | 6 | £38,894 |
| Hypothetical 40-unit capacity | 60 | 3 | £25,607 |
| 40-unit demand per service, three-vehicle limit | 40 | 2 | £12,870 |
| 40-unit demand per service, six-vehicle limit | 120 | 6 | £38,894 |
| Double infrastructure cost, same candidates | 60 | 3 | £37,927 |
| 40-unit demand on one service, 20 on others, four vehicles | 80 | 4 | £30,036 |

The final row was solved separately for each service; all three allocations
are feasible under the supplied constraints. With 40-unit demands and only
three vehicles, P05 selects S1 alone (`benchmark-4-1-5`, vehicle 4): an indivisible service needs two
vehicles, and the cheaper retained infrastructure wins the CAPEX tie-break.
This selection is not a recommendation to close the other services.

Variant suffixes follow the retained scenario's demand order, not the P07 chart
order. `extra_vehicle_service_0`, `_1`, and `_2` target S3, S2, and S1 respectively.
The JSON `assumption` and `allocation` fields give the exact demand identifiers.

Increasing the vehicle limit alone cannot improve the plan because its supplied
demand stays fixed. A larger hypothetical engine also cannot improve the
baseline objective. The alternative capacities hold price and speed fixed and
have no independently observed engine availability; they are sensitivity inputs.
The allocation variants change demand explicitly and do not automatically
translate waiting cargo into recurring demand.

Existing P05 does not optimize recurring service frequency. Extra vehicles are
feasible allocations, not evidence of shorter headways. Doubling infrastructure
cost tests affordability only: there are no alternative upgrade geometries or
verified capacity constraints in these retained inputs. Physical investment
therefore requires additional P08 facts and candidates before comparison.

Prioritize a separately authorized experiment with one additional observed
20-unit vehicle on a service with persistent waiting cargo. Compare delivery
intervals, loading, orders, cargo queues and delivered units against the retained
baseline before altering defaults. Equal service throughput despite different
waiting levels makes a common loading/order/supply limitation worth investigating;
the retained queue observations do not prove that an extra vehicle resolves it.
Keep OPEX, net profit and ROI unknown.
