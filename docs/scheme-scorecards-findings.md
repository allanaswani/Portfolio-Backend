# Scheme scorecards — how the workbooks work, and what is wrong in them

Read cell by cell, formulas and values, on 2026-10-28:

- `Scheme_Scorecards - Template 2026 V3.xlsm` — the cards
- `2026_Actuals_Scheme_Scorecards.xlsx` — the figures the cards look up

Review month on both: **June 2026** (`K5 = 6` on every card, `Constants!B2 = 6`).

## Who is on them

| Sales code | Name | Role | Card sheet |
|---|---|---|---|
| GO3528 | George Ochieng | SCHEMES RM | SCHEMES_RM |
| KN4028 | Kipkirui Norman | SCHEMES RM | SCHEMES_RM |
| DK4239 | Dennis Kimathi | SCHEMES RM (joined month 2: `prorate_new = 2`) | SCHEMES_RM |
| PMM3540 | Philip Manyengo | SCHEMES RM | SCHEMES_RM |
| PK3816 | Phiedis Kyengo | PROJECT ADMIN | PROJECT_ADMIN |
| BJ3384 | Benedicto Juma | SCHEMES ADMIN | SCHEMES_ADMIN |
| NN3533 | Nicodemus Ngila | HEAD OF SCHEMES (reports to Kibet Kitur, GM Sales) | HOD_SCHEMES |

## The mechanics

- **Lookup is by NAME**, never by code:
  `VLOOKUP($C$2, INDIRECT("[2026_Actuals...]"&K&"!$c$3:$q$9"), $K$5+3, 0)`.
  Column C is the name; the month is column `K5 + 3` of the range (Jan = F).
- Each actuals sheet stacks **7-row blocks** (rows 3–9, 13–19, 23–29, 33–39,
  43–49); which block a line reads is in its formula.
- **YTD target** = FY target × month / 12 (linear by month, not by day).
- **Joiners** (SCHEMES_RM only): `L = prorate_new` off the List sheet;
  FY = annual × (12 − L)/12 and YTD = annual × (month − L)/12.
- **Scoring**, by line type:
  - ratio, capped at **1.2**: money, counts, utilisation, penetration
  - ratio, capped at **1.0**: customer experience, training, leave
    (and Scheme RM productivity on SCHEMES_ADMIN only)
  - **pass/fail**: FID `<= 3%`, NPL and PAR `<= 5%`
  - **audit band** (SCHEMES_ADMIN, SCHEMES_RM, HOD): `<= 1.65` → 1,
    `< 2.49` → 0.8, else 0
- Property value target = number of properties × **8,200,000**.
- Revenue: actual = scheme NII + NFI accruals Jan–Jun 2026 (160,923,357.62);
  target = 2025 full year × **1.15** (admins) or × **1.10** (HOD).
- Disbursements: RMs = cumulative **Commercial** drawdowns
  (`RATE = IF(FINAL_INTEREST > 9.5, "Commercial", "Non-Commercial")`) credited
  to the scheme RM through the employer → scheme mapping, not the seller.
  Admins and HOD = all scheme drawdowns including DSR (1,724,577,866.76).
- PAR here is **WATCH grade / total**; NPL is SUBSTD + DOUBTFUL + LOSS / total.
- Utilisation = average per RM of each scheme's `(book − blocked) / book`;
  HOD = average of the RMs.

## Faults in the template — they change people's scores

1. **HOD revenue is outside the card.** E6 (Revenue, 5%) is not in
   `E28 = SUM(E7:E27)`, which already makes 100%, and `J28 = SUM(J7:J27)`
   skips J6. The card carries 105% of weight and his revenue never counts.
2. **HOD Deposit Growth's actual is a typed copy of the revenue figure**
   (H8 = 160,923,357.62, the same as H6) — not a lookup.
3. **HOD Strategic Initiatives (10%) has no score formula** (I20 empty), so it
   is 0 every month; INITIATIVES_HOD has no scores at all.
4. **HOD "Scheme RM Weighted Productivity" reads HOD's own row, which is 0.**
   The team's average of the RM rows is about 0.63.
5. **Group Synergies read the wrong blocks.** Blocks are VIC (1), Number of
   Property (2), Value (3). On SCHEMES_RM, *Value* reads the VIC block and
   *VIC non-life* reads the Value block — a count of 1 scored against a
   10.9m value target (0.00000009). On PROJECT_ADMIN and HOD all four lines
   read the VIC block. There is no life/non-life split in the data at all.
6. **Scheme penetration is swapped between George and Kipkirui** — their
   workings are 6/10 and 7/10, the cells say 0.7 and 0.6. Denominators do not
   match the targets either ("top 20" over /10; HOD "top 35" over /18).
7. **Deposit growth double-counts KeNHA's 60m** — Philip in the first inflow
   table, Kipkirui in the second (Kipkirui's 95m = 30 + 5 + 60). The admins'
   and HOD's 506,895,862 matches neither the inflow total (394.8m) nor the
   portfolio growth pivot (426.5m).
8. **Sign-ups are typed, and wrong by one each**: the list names 2 schemes for
   Kipkirui and 8 for Dennis; the cells say 3 and 9. The admins' total is
   patched with `-1`.
9. **Monthly_Summary pairs scores with the wrong people** (rows shifted —
   Benedicto Juma shows George's 0.5998); Phiedis is missing from it.
   `Monthly_Summ_2026` and `Summary_Run_Log` are correct.
10. **PROJECT_ADMIN Audit is a ratio** (1.64 / 1.65 = 0.99, as though higher
    were better); the other three cards use the band.
11. SCHEMES_ADMIN "Timeliness of collections" (H15 = 0.9) is typed, not looked
    up; Loan Collection and Portfolio Revenue Growth sheets are empty with
    `#REF!` zones.
12. Leave target is prorated (0.5 by June) on three cards and not on HOD (1).
13. Names do not agree across sheets: Dennis **Kimathi** on the cards,
    Dennis **Mutembei** in NPL, deposits, FID and sign-ups; "Norman Kipkirui",
    "Benedicto Juma Harambee". Dennis's PF is typed as `7` on Signs_ups.
14. Cosmetic: PROJECT_ADMIN's title reads "SCHEMES ADMIN SCORECARD"; HOD's
    performance score is in J2, the others in I2; `M6 = 15*(12-S6)/12` refers
    to an empty S6.

## What the warehouse can measure instead of a typed cell

- deposits — `Scheme Deposits Portfolio` is `rm_code`-keyed balances (DK4239…)
- disbursements — `drawdown_daily` with the 9.5% Commercial rule and the
  employer → scheme RM mapping
- NPL / PAR — the IFRS grades per scheme
- revenue — the detailed revenue extract, scheme accounts
- training — the HR training return by PF

FID, reconciliation accuracy, call-back timeliness, scheme statements,
empanelment and sign-ups are desk returns: loaded, not measured.
