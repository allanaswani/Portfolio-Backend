# Frontend → Backend endpoint gap

_Regenerated 2026-07-21 by matching every endpoint called in `portfolio-management-frontend/hooks/useAnalytics.ts` against the new backend's registered URL routes (`apps/*/urls.py`, resolved through the mounts in `config/urls.py`)._

**Method note:** paths are normalised before comparison — trailing slash ignored, `${var}` template segments and Django `<int:pk>`/`<str:..>` params both collapsed to `*`, query strings dropped. Only `useAnalytics.ts` is in scope (as in the original report); other hook files (`useUsers`, `useMortgages`, `useScorecardAutomation`, `useClientBriefs`, registry, agent) are not counted. A resolving route proves the URL exists, not that the view returns the right shape.

- Frontend endpoints called: **313**
- Matched in backend: **313**
- Unmatched: **0**

> **Full coverage.** Every endpoint `useAnalytics.ts` calls now resolves against the backend. Previous run (≈6 weeks earlier): 259 called / 153 matched / 106 missing.

## Coverage by module

| Module (frontend prefix) | Backend app | Called | Matched | Unmatched |
|---|---|---|---|---|
| `auth/` | authentication | 1 | 1 | 0 |
| `branch_portfolio/` | branch_portfolio | 31 | 31 | 0 |
| `ceo/` | gceo_dashboard | 47 | 47 | 0 |
| `collections_tl/` | collections_team_leaders | 7 | 7 | 0 |
| `exco/` | exco_portfolio | 5 | 5 | 0 |
| `exco_innitiatives/` | exco_innitiatives | 15 | 15 | 0 |
| `hf_collections/` | hf_collections | 7 | 7 | 0 |
| `hf_rights_issue/` | hf_rights_issue | 2 | 2 | 0 |
| `hfdi/` | hfdi | 43 | 43 | 0 |
| `portfolio/` | portfolio | 38 | 38 | 0 |
| `portfolio_management_enrichment/` | portfolio_management_enrichment | 19 | 19 | 0 |
| `staff_management/` | staff_management | 67 | 67 | 0 |
| `tl_portfolio/` | tl_portfolio | 31 | 31 | 0 |
| **Total** | | **313** | **313** | **0** |

## Closed since the previous report

Ported/added straight from — or in the spirit of — the old backend, not re-invented:

- **`portfolio/loan_trends/<rm_code>`** → `RmLoanTrendsByCodeView`, port of the old `RM_rm_loan_trends_data` (same `loan_trends_data` rows for an explicitly-supplied `sales_code`).
- **`portfolio/deposits/<cust_id>`** → frontend-contract alias onto `CustomerDepositTrendsView` (old `customerDepositTrends`); `cust_id` is a customer pk, same view as `customers/<pk>/deposits`.
- **`exco/` mount (5 endpoints)** — the old backend never shipped an `exco` app (its mount was a commented-out stub), so this is net-new, built **bank-wide** per an explicit scope decision. `fixed_deposits/list` and `customers_list_allocated` reuse the CEO views (`CeoFixedDepositListView`, `CeoCustomersView`); `customer_feedback_list`, `loans-arrears/list` and `prospects` are new whole-bank list views in `apps/exco_portfolio` (the RM querysets minus the `sales_code` filter). The frontend's `retry:false` fallbacks to `ceo/`/`portfolio/`/`tl_portfolio/` remain as a safety net.

## Verdict

**Every endpoint `useAnalytics.ts` calls resolves.** Coverage is a route-existence check, not a response-shape guarantee — the exco bank-wide views in particular should be spot-checked against real data before the Exco dashboard relies on them over its fallbacks.
