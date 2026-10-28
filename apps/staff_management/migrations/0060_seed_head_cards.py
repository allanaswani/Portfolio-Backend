"""The heads' cards: SME, Trade, Personal Banking, Sales & IB, Branch Business
and Commercial.

233 of the 454 sales codes on the coverage run were skipped with "role has no
card" - Anna Amasinde (SME HEAD) among them - because only the twelve RM cards
and the ten back-office cards were ever seeded.

Read off ``Portfolio Management - Q3 2026_scorecards.xlsb``, line for line and
weight for weight:

    HEAD_COMMERCIAL   2026 card (Q3_Aug_26), Floyd Mathias
    SME_HEAD          2022 template - no 2026 head card has been issued
    TRADE             2022 template
    PB                2022 template
    SALES AND IB      2022 template
    BRANCH_BUSINESS   2022 template

Built from the 2022 templates on instruction (2026-10-28). Their LINES and
WEIGHTS are used; their 2021/2022 money figures are not, because a 2022 plan is
not anybody's 2026 target. Those targets are per head and load under
Scorecards -> Figures to load. The few a card states as a rule for everybody -
NPS 60%, training hours, leave cleared, 80% productivity - are role targets.

A head's figure is a DEPARTMENT total, never one person's book, so these lines
use their own ``head_*`` KPIs: the RM KPIs would read the head's personal sales
code and score an SME head on a book she does not carry. Each names the sheet
of ``2026_Actual_Template`` where the head's row already is (Anna Amasinde's
revenue contribution, deposit and asset growth, active customers, productivity
and training are all there), so loading the actuals fills them.

Two simplifications, both visible on the card:
* TRADE scores eight strategic initiatives at 5% each. They are one 40% line
  here - one figure for "the initiatives as agreed", loaded like every other
  strategic-initiatives line.
* Christopher Opiyo and Steven Lila are RBBMs. No RBBM card exists in any
  year, so they are NOT put on Branch Business by guess.

Seed-only-if-absent: a role or KPI that already exists is left alone.
"""

from datetime import date

from django.db import migrations

YEAR = 2026

ROLES = {
    "head_commercial": "Head of Commercial",
    "sme_head": "Head of SME",
    "trade_head": "Head of Trade Finance",
    "pb_head": "Head of Personal Banking",
    "sales_ib_head": "Head of Sales and IB",
    "branch_business_head": "Head of Branch Business",
}

#: (kpi_code, name, sheet in 2026_Actual_Template or "", higher_is_better)
KPIS = [
    ("head_revenue", "Revenue", "Revenue_Contribution", True),
    ("head_pbt", "PBT (with FTP, full cost and provisions)", "", True),
    ("head_trade_income", "Trade Income", "Trade_Finance_income", True),
    ("head_trade_interest_income", "Trade Finance Interest Income",
     "Interest_Income", True),
    ("head_commitment_fees", "Commitment Fees", "Credit_Service_Fees", True),
    ("head_deposit_growth", "Deposit Growth", "Deposit_Growth_Retail", True),
    ("head_total_deposit_book", "Total Book (Bank)", "", True),
    ("head_asset_growth", "Asset Growth", "Asset_Growth", True),
    ("head_loan_book", "Loan Book", "", True),
    ("head_trade_loans_growth", "Trade Finance Loans Growth", "", True),
    ("head_trade_volume", "Trade Finance Activity Volume", "", True),
    ("head_disbursement", "Disbursements", "Asset_Drawdown", True),
    ("head_new_customers", "New Customers", "New_Customers", True),
    ("head_focus_accounts", "Focus Accounts", "CASA", True),
    ("head_active_customers", "Active Customers", "Active_Customers", True),
    ("head_digital_migration", "Digital Migration / Active Score",
     "Digital_Migration_Active_Score", True),
    ("head_strategic_initiatives", "Strategic Initiatives",
     "Strategic_Initiatives", True),
    ("head_npl", "NPL", "NPL", False),
    ("head_nps", "NPS", "NPS", True),
    ("head_sla", "SLA / Turnaround", "TAT_Loans", False),
    ("head_branch_audit", "Branch Audit", "Branch_Audit", True),
    ("head_cost_management", "Cost Management", "", False),
    ("head_training", "Training (team)", "training_hours", True),
    ("head_productivity", "Team Productivity", "Productivity", True),
    ("head_interest_expense", "Interest Expense Management",
     "Interest_Expense_Management", False),
    ("head_unutilized_scheme_funds", "Un-utilized Scheme Funds", "", True),
    ("head_new_schemes", "Onboarding New Schemes", "", True),
    ("head_scheme_deposit_growth", "Scheme Deposit Growth", "", True),
    ("head_ib_growth", "IB Growth", "", True),
    ("head_pb_dsr_disbursement", "PB DSR Disbursement", "", True),
    ("head_sme_dsr_disbursement", "SME DSR Disbursement", "", True),
    ("head_dsr_productivity", "DSR Weighted Sales Productivity", "", True),
    ("head_scheme_rm_productivity", "Scheme RM Weighted Productivity", "",
     True),
]

#: role -> [(perspective, kpi_code, wording on the card, weight, role target)]
LINES = {
    # 2026_COMMERCIAL RM OBJECTIVES, Floyd Mathias, Q3_Aug_26.
    "head_commercial": [
        ("Grow Revenue (25.0%)", "head_revenue",
         "Increase Revenue per Customer - grow by 20%", 0.10, None),
        ("Grow Revenue (25.0%)", "head_trade_income",
         "Trade Income - grow by 20%", 0.05, None),
        ("Grow Revenue (25.0%)", "head_commitment_fees",
         "Commitment fees - New Fees - grow by 20%", 0.10, None),
        ("Acquisition (15.0%)", "head_deposit_growth",
         "Grow Deposits - grow by 20%", 0.10, None),
        ("Acquisition (15.0%)", "head_new_customers",
         "New Commercial Customers - as per assigned target", 0.05, None),
        ("Loan Drawdowns (40.0%)", "head_disbursement",
         "Disbursements - as per assigned target", 0.40, None),
        ("NPL (5.0%)", "head_npl", "NPL Management - reduce by 20%",
         0.05, None),
        ("NPS (5.0%)", "head_nps", "Overall customer service satisfaction",
         0.05, 0.6),
        ("Staff Engagement (10.0%)", "head_training",
         "Training hours for team", 0.05, None),
        ("Staff Engagement (10.0%)", "head_productivity",
         "Staff productivity - measures growth in revenue, >80%", 0.025, 0.8),
        ("Staff Engagement (10.0%)", "leave_management",
         "Clear leave days before EOY", 0.025, 1.0),
    ],
    # SME_HEAD, 2022 template (Simon Waruingi's, HEAD OF SME AND COMMERCIAL).
    "sme_head": [
        ("Grow Revenue (20.0%)", "head_revenue",
         "Gross Revenue Contribution (NII + NFI)", 0.05, None),
        ("Grow Revenue (20.0%)", "head_trade_income",
         "Trade Income - grow in line with assigned targets", 0.05, None),
        ("Grow Revenue (20.0%)", "head_pbt",
         "PBT - SME (has FTP) with full cost and provisions", 0.10, None),
        ("Balance Sheet Growth (30.0%)", "head_deposit_growth",
         "Deposit Growth", 0.20, None),
        ("Balance Sheet Growth (30.0%)", "head_asset_growth",
         "Asset Book growth (without auction shortfalls)", 0.10, None),
        ("Customers (12.5%)", "head_active_customers",
         "Active Customers (New and Activated Dormancy)", 0.075, None),
        ("Customers (12.5%)", "head_digital_migration",
         "Digital Migration / Active Score", 0.05, None),
        ("Strategic Initiatives (15.0%)", "head_strategic_initiatives",
         "Completion of strategic initiatives as per agreed timelines",
         0.15, None),
        ("NPL (5.0%)", "head_npl", "Reduce NPL ratio - SME, by 20%",
         0.05, None),
        ("NPS (10.0%)", "head_nps", "Overall customer service satisfaction",
         0.10, 0.6),
        ("Staff Engagement (7.5%)", "head_training",
         "Training hours for team", 0.025, 48),
        ("Staff Engagement (7.5%)", "head_productivity",
         "Ensure 80% of staff are above 80% performance", 0.025, 0.8),
        ("Staff Engagement (7.5%)", "leave_management",
         "Clear leave days before EOY", 0.025, 1.0),
    ],
    # TRADE, 2022 template (John Gichuki, Head of Trade Finance).
    "trade_head": [
        ("Grow Revenue (30.0%)", "head_trade_income",
         "Non Funded Income - Commission", 0.25, None),
        ("Grow Revenue (30.0%)", "head_trade_interest_income",
         "Trade Finance related Interest Income", 0.05, None),
        ("Balance Sheet Growth (15.0%)", "head_trade_loans_growth",
         "Trade Finance Loans Growth", 0.05, None),
        ("Balance Sheet Growth (15.0%)", "head_trade_volume",
         "Trade Finance Activity Volume", 0.05, None),
        ("Balance Sheet Growth (15.0%)", "head_deposit_growth",
         "Deposits Liability Growth", 0.05, None),
        ("Customers (10.0%)", "head_sla",
         "SLA Enhancement - clear process and SLA across trade "
         "transactions", 0.05, None),
        ("Customers (10.0%)", "head_nps",
         "NPS - overall customer service satisfaction", 0.05, 0.6),
        ("Strategic Initiatives (40.0%)", "head_strategic_initiatives",
         "Eight key initiatives - training pack, branch training, middle "
         "office, product mapping, ecosystem enablers, confirmation limits, "
         "customer event, 80/20 revenue mix", 0.40, None),
        ("Staff Leave Management (5.0%)", "leave_management",
         "Adherence to the leave policy", 0.05, 1.0),
    ],
    # PB, 2022 template (Jane Gacheri Imana, Head of Personal Banking).
    "pb_head": [
        ("Grow Revenue (20.0%)", "head_revenue",
         "Gross interest income less interest expense plus NFI (ex rent)",
         0.10, None),
        ("Grow Revenue (20.0%)", "head_pbt",
         "PBT for PB (has FTP) with full cost and provisions", 0.10, None),
        ("Balance Sheet Growth (30.0%)", "head_deposit_growth",
         "Deposit Growth", 0.20, None),
        ("Balance Sheet Growth (30.0%)", "head_asset_growth",
         "Asset Growth", 0.05, None),
        ("Balance Sheet Growth (30.0%)", "head_disbursement",
         "Asset Disbursement", 0.05, None),
        ("Customers (12.5%)", "head_active_customers",
         "Active Customers (New and Activated Dormancy)", 0.075, None),
        ("Customers (12.5%)", "head_digital_migration",
         "Digital Migration / Active Score", 0.05, None),
        ("Strategic Initiatives (15.0%)", "head_strategic_initiatives",
         "Completion of strategic initiatives as per agreed timelines",
         0.15, None),
        ("NPL (5.0%)", "head_npl", "Reduce NPL ratio - PB, by 20%",
         0.05, None),
        ("NPS (5.0%)", "head_nps", "Overall customer service satisfaction",
         0.05, 0.6),
        ("Staff Engagement (12.5%)", "head_training",
         "32 training hours by each team member", 0.05, 32),
        ("Staff Engagement (12.5%)", "head_productivity",
         "Ensure 80% of staff are above 70% performance", 0.05, 0.8),
        ("Staff Engagement (12.5%)", "leave_management",
         "Clear leave days before EOY", 0.025, 1.0),
    ],
    # SALES AND IB, 2022 template (Mike Kibet Kitur).
    "sales_ib_head": [
        ("Scheme Business (15.0%)", "head_unutilized_scheme_funds",
         "Un-utilized Scheme Funds", 0.025, None),
        ("Scheme Business (15.0%)", "head_interest_expense",
         "Interest Expense Management - 10% reduction on overall rate",
         0.025, None),
        ("Scheme Business (15.0%)", "head_new_schemes",
         "Onboarding New Schemes", 0.10, None),
        ("Deposit Growth (20.0%)", "head_scheme_deposit_growth",
         "Scheme Growth", 0.10, None),
        ("Deposit Growth (20.0%)", "head_ib_growth", "IB Growth", 0.10, None),
        ("Disbursement (15.0%)", "head_pb_dsr_disbursement",
         "PB DSR Disbursement - 13% and above", 0.10, None),
        ("Disbursement (15.0%)", "head_sme_dsr_disbursement",
         "SME DSR Disbursement - 13% and above", 0.05, None),
        ("Customers - DSR (15.0%)", "head_new_customers",
         "New Customers", 0.075, None),
        ("Customers - DSR (15.0%)", "head_focus_accounts",
         "Focus Accounts - 80% of new customers", 0.075, None),
        ("Strategic Initiatives (15.0%)", "head_strategic_initiatives",
         "Completion of strategic initiatives as per agreed timelines",
         0.15, None),
        ("Team Productivity (5.0%)", "head_dsr_productivity",
         "Weighted sales productivity (DSR) - over 80%", 0.025, 0.8),
        ("Team Productivity (5.0%)", "head_scheme_rm_productivity",
         "Scheme RM weighted productivity - over 80%", 0.025, 0.8),
        ("NPS (10.0%)", "head_nps", "Overall customer service satisfaction",
         0.10, 0.6),
        ("Staff Engagement (5.0%)", "head_training",
         "32 training hours by each team member", 0.025, 32),
        ("Staff Engagement (5.0%)", "leave_management",
         "Clear leave days before EOY", 0.025, 1.0),
    ],
    # BRANCH_BUSINESS, 2022 template (Jerusha Igombo).
    "branch_business_head": [
        ("Grow Revenue (17.5%)", "head_revenue",
         "Gross interest income less interest expense plus NFI (ex rent)",
         0.05, None),
        ("Grow Revenue (17.5%)", "head_trade_income",
         "Trade Income from Branches (30% of total trade income)",
         0.025, None),
        ("Grow Revenue (17.5%)", "head_pbt",
         "PBT - Retail (has FTP), cost and provisions", 0.05, None),
        ("Grow Revenue (17.5%)", "head_cost_management",
         "Branch Business Cost Management - reduce budgeted cost by 10%",
         0.05, None),
        ("Deposit Growth (20.0%)", "head_deposit_growth",
         "Deposit Growth - Retail", 0.15, None),
        ("Deposit Growth (20.0%)", "head_total_deposit_book",
         "Total Book (Bank)", 0.05, None),
        ("Loan Book (10.0%)", "head_loan_book", "Loan Book Retail",
         0.10, None),
        ("Customers (17.5%)", "head_new_customers", "New Customers",
         0.05, None),
        ("Customers (17.5%)", "head_active_customers",
         "Active Customers (New + Activation + Dormancy Activation)",
         0.075, None),
        ("Customers (17.5%)", "head_digital_migration",
         "Digital Migration / Active Score", 0.05, None),
        ("Strategic Initiatives (15.0%)", "head_strategic_initiatives",
         "Completion of strategic initiatives as per agreed timelines",
         0.15, None),
        ("Audit (2.5%)", "head_branch_audit",
         "Branch Audit - all branches OT and above", 0.025, 1.0),
        ("NPL (5.0%)", "head_npl", "Reduce NPL ratio - Branches, by 20%",
         0.05, None),
        ("NPS (5.0%)", "head_nps", "Overall customer service satisfaction",
         0.05, 0.6),
        ("Staff Engagement (7.5%)", "head_training",
         "32 training hours by each team member", 0.025, 32),
        ("Staff Engagement (7.5%)", "head_productivity",
         "BBM weighted sales productivity - 80% of staff above 80%",
         0.025, 0.8),
        ("Staff Engagement (7.5%)", "leave_management",
         "Clear leave days before EOY", 0.025, 1.0),
    ],
}


def seed(apps, schema_editor):
    ScKpi = apps.get_model("staff_management", "ScKpi")
    ScRole = apps.get_model("staff_management", "ScRole")
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")

    for code, name in ROLES.items():
        ScRole.objects.get_or_create(
            role_code=code,
            defaults={"role_name": name, "role_type": "MGR",
                      "is_active": True})

    for code, name, sheet, higher in KPIS:
        ScKpi.objects.get_or_create(
            kpi_code=code,
            defaults={
                "kpi_name": name,
                "kpi_description": "Department total - loaded from the "
                                   "actuals workbook or Figures to load",
                "kpi_calculation_mode": "actual_over_target",
                "kpi_rating_type": "prorate",
                "score_cap": "1.20",
                "is_increasing": higher,
                "is_active": True,
                "actuals_sheet": sheet,
                "actuals_block": 1 if sheet else None,
                "negate": False,
                "allocation_column": "",
                "allocation_base_column": "",
                "has_base_value": False,
                "not_configured_reason": "",
            })

    start, end = date(YEAR, 1, 1), date(YEAR, 12, 31)
    made = 0
    for role, lines in LINES.items():
        if Mapping.objects.filter(role_code=role).exists():
            continue
        for order, (perspective, kpi, wording, weight, target) in enumerate(
                lines, start=1):
            Mapping.objects.create(
                role_code=role, kpi_order=order, kpi_code=kpi,
                mapping_category=perspective, kpi_description=wording,
                kpi_weight=weight, kpi_target=target, is_bonus=False,
                effective_from=start, effective_to=end,
                bonus_effective_from=start, bonus_effective_to=end,
                plan_category="p1", target_category="full_year",
                prorate=True)
            made += 1
    print(f"\n  head cards: {len(ROLES)} roles, {made} lines.")


def unseed(apps, schema_editor):
    Mapping = apps.get_model("staff_management", "ScRoleKpiMapping")
    Mapping.objects.filter(role_code__in=list(ROLES)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("staff_management", "0059_weighted_sales_targets_80_percent"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
