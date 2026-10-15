# SimpleAI transport mode comparison: seeds 0–9

Executed on 2026-09-24 with OpenTTDLab 0.0.75, OpenTTD 13.4, OpenGFX 7.1,
Python 3.14.6, a generated 256×256 scenario (version 1), and 730 simulated days per run.
Both policies used SimpleAI 14, MD5 `b3137bbd0c73641cf510ead06e36dab6`.
The `simple-multimodal` policy enabled rail, road, and air; `simple-road-only`
enabled road and disabled rail and air. Each policy ran once for every seed from 0 to 9.
All 20 runs succeeded and were persisted individually as experiment runs 6–25.

Reproduce the batch with:

```bash
uv run transport-experiment compare --scenario generated-256-square \
  --strategies multimodal,road-only --seeds 0:10 --days 730
```

## Individual runs

Money is the final company balance in GBP. Cargo is units delivered in the final
savegame's current economy period, not cumulative deliveries over 730 days.
The generated JSON report also contains loan, current-period income and expenses for
every run.

| Seed | Multimodal run | Money | Cargo | Road-only run | Money | Cargo |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 6 | 523 | 500 | 7 | 19,628 | 353 |
| 1 | 8 | 122,011 | 1,115 | 9 | 13,698 | 366 |
| 2 | 10 | 14,007 | 512 | 11 | 13,652 | 529 |
| 3 | 12 | 110,260 | 1,061 | 13 | 96,533 | 617 |
| 4 | 14 | 20,295 | 761 | 15 | 16,737 | 391 |
| 5 | 16 | −194 | 872 | 17 | 17,229 | 558 |
| 6 | 18 | 18,588 | 658 | 19 | 10,690 | 431 |
| 7 | 20 | 89,753 | 563 | 21 | 15,292 | 391 |
| 8 | 22 | −9,991 | 0 | 23 | 15,037 | 610 |
| 9 | 24 | 497 | 515 | 25 | 19,622 | 440 |

## Descriptive summaries

Statistics use all ten individual runs per policy. Standard deviation is the
sample standard deviation. Values below are rounded to two decimal places.

| Metric | Policy | Mean | Median | Min | Max | Std. dev. |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Company money (GBP) | Multimodal | 36,574.90 | 16,297.50 | −9,991 | 122,011 | 50,306.10 |
| Company money (GBP) | Road-only | 23,811.80 | 16,014.50 | 10,690 | 96,533 | 25,699.30 |
| Company loan (GBP) | Multimodal | 289,000 | 300,000 | 230,000 | 300,000 | 22,335.80 |
| Company loan (GBP) | Road-only | 226,000 | 225,000 | 200,000 | 260,000 | 21,705.10 |
| Current-period income (GBP) | Multimodal | 31,004.80 | 34,391 | 0 | 51,703 | 15,098.70 |
| Current-period income (GBP) | Road-only | 16,122 | 15,588.50 | 10,272 | 22,916 | 3,652.06 |
| Current-period expenses (GBP) | Multimodal | −4,075.30 | −4,708.50 | −5,483 | −1,031 | 1,430.20 |
| Current-period expenses (GBP) | Road-only | −3,007.70 | −3,012.50 | −3,496 | −2,665 | 266.70 |
| Current-period cargo delivered | Multimodal | 655.70 | 610.50 | 0 | 1,115 | 322.55 |
| Current-period cargo delivered | Road-only | 468.60 | 435.50 | 353 | 617 | 101.01 |

The multimodal policy had higher mean final-period cargo delivery and income, but
also much wider outcomes, including a seed with no final-period cargo delivered.
These descriptive results do not establish statistical significance or general
superiority. The next research step is to inspect network and vehicle outcomes by
seed, then repeat with more seeds and a predeclared comparison metric.
