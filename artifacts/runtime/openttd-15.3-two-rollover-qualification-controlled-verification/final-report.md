# Controlled two-rollover qualification verification

Baseline HEAD: `278a3792b34fdb58085aff4e999dabac482cf21a`.

All previous controlled blockers are closed: thin native clock/lifetime adapters, single-use coordinator, correlated evidence, and independently derived operational accounting.

Final focused checks: 276 passed in 7.70s. Broad regression checks: 2012 passed, 4 skipped in 153.00s (before the final bounded-close fix). Final ordinary serial suite on final source: 2549 passed, 38 skipped in 215.75s. Ruff, format (323 files), scoped typecheck, diff, whitespace and import-boundary checks passed.

Clock request/response maxima: 117/271 bytes. Lifetime request/response maxima: 141/248 bytes. Mandatory four query operations; conservative allowance eight. One shared native accounting instance across all phases.

V1 polling interval 1 second, collection deadline 300 seconds. Paced polls start strictly before the deadline: ceil(300/1)-1=299. Baseline plus four collection guards makes 304 clock requests. Time controls liveness only; native adjacent month transitions establish semantics.

Request ceiling: 304+96+32+96+32+512=1072.
Response ceiling: 82384+49152+7936+49152+7936+171520=368080 bytes.
Query-operation ceiling: 2432+1024+256+1024+256+4096=9088.
One continuous session lifecycle overhead: 2+3+1=6; total post-auth frame ceiling 9094.

M0 baseline -> adjacent M1 first rollover -> M1 structural/lifetime anchor -> adjacent M2 second rollover -> fresh final structural/lifetime observation -> target/lifetime stability -> fresh complete raw production -> final M2 guard -> qualification admission. Failed and completed coordinators cannot resume/restart. Retry and reconnect remain zero.

Native clock uses ScriptDate / GSDate GetCurrentDate, GetYear, GetMonth, GetDayOfMonth and GetDate. Industry construction identity uses ScriptIndustry::GetConstructionDate / GSIndustry.GetConstructionDate and remains CALENDAR-domain data. Qualification uses ECONOMY-domain month evidence. Selected synchronized generated calendar profile and vanilla industries are required; lifetime-age eligibility is explicitly conservative.

Targets derive only from produces; exact T1=T2 and native lifetime equality required. Empty stable target sets are valid. Production query brackets are current-state M2 metadata, distinct from the fully bounded M1 rollover evidence. Complete and qualified remain separate; no incomplete observation can qualify.

1862 pre-task identities checked: six intentional current-source changes; all remaining 1856 exact. Historical complete-raw proof, production Attempt 1 FAILED, Attempt 2 PASS, prior freezes and CONTEXT.md unchanged. Nothing restored or staged. No commit/push.

Native activity: 0 launches / 0 live connections / 0 real requests. No real-proof freeze or runtime credential created.

Controlled qualification is proven. Real two-rollover execution and qualified real production history remain unproven. P08 integration and atomic snapshot claims remain NO.

READY FOR TWO-ROLLOVER QUALIFICATION REAL-PROOF PREPARATION
