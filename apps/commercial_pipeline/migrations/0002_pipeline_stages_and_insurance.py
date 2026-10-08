"""The stages, products and VIC/non-VIC split from the Commercial RM's
"Additional System requirements.xlsx".

Most of this is choices, which Postgres does not store at all - ``sqlmigrate``
reports eight of the ten operations as no-ops. Only four statements touch the
database:

* ``insurance_type`` added to the table and to its history table;
* ``deposit_product`` widened from varchar(8) to varchar(16), because
  'CASH_MARGIN' does not fit in eight characters.

The two ADD COLUMNs are the ones that can fail, and on this fleet they can:
``docs`` records tables whose columns do not match what ``django_migrations``
claims was applied, and migration 0019 of ``staff_management`` died on the host
with "relation already exists" for exactly this reason. So they run through
``adopt()``, which looks at ``pg_attribute`` first and adds only what is
missing. The widening is left to Django: ``ALTER COLUMN TYPE varchar(16)`` on a
column that is already varchar(16) is a no-op, and on Postgres 12 widening a
varchar is a catalogue change with no table rewrite.

The last operation is the sheet's "Remove-Disbursed": rows whose broad stage is
the retired ``disbursed`` move to ``disbursement``, which is the same point in
the journey under the name the desk now uses. The specific stage is left alone,
so nothing is lost - ``RETIRED_STAGES`` keeps it valid.
"""

from django.db import migrations, models

TABLES = ("commercial_pipeline_entry", "commercial_pipeline_entry_history")


def _columns(cursor, table):
    """The column names of ``table``, or None when there is no such table."""
    cursor.execute("SELECT to_regclass(%s)", [table])
    if cursor.fetchone()[0] is None:
        return None
    cursor.execute(
        "SELECT attname FROM pg_attribute "
        "WHERE attrelid = to_regclass(%s) AND attnum > 0 AND NOT attisdropped",
        [table])
    return {row[0] for row in cursor.fetchall()}


def adopt(apps, schema_editor):
    """Add insurance_type only where it is actually absent."""
    cursor = schema_editor.connection.cursor()
    for table in TABLES:
        found = _columns(cursor, table)
        if found is None:
            # 0001 never ran here. Nothing to adopt, and nothing this migration
            # can sensibly do about it - say so rather than fail obscurely.
            raise RuntimeError(
                f"{table} does not exist. Run migrate commercial_pipeline 0001 "
                f"first, or check django_migrations for a shadowing row.")
        if "insurance_type" in found:
            print(f"\n  {table}: insurance_type is already there.")
            continue
        cursor.execute(
            f'ALTER TABLE "{table}" ADD COLUMN "insurance_type" '
            f"varchar(8) DEFAULT '' NOT NULL")
        print(f"\n  {table}: added insurance_type.")


def unadopt(apps, schema_editor):
    cursor = schema_editor.connection.cursor()
    for table in TABLES:
        cursor.execute(
            f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS "insurance_type"')


def rename_disbursed(apps, schema_editor):
    """"Remove-Disbursed": the stage keeps its meaning, loses its old name.

    The history table is deliberately NOT touched. It records what was true at
    the time, and ``BROAD_STAGE`` still carries ``disbursed`` so those rows
    keep reading properly.
    """
    Entry = apps.get_model("commercial_pipeline", "PipelineEntry")
    moved = Entry.objects.filter(broad_stage="disbursed").update(
        broad_stage="disbursement")
    if moved:
        print(f"\n  {moved} row(s) moved from Disbursed to Disbursement.")


def unrename_disbursed(apps, schema_editor):
    Entry = apps.get_model("commercial_pipeline", "PipelineEntry")
    Entry.objects.filter(broad_stage="disbursement",
                         stage="disbursement").update(broad_stage="disbursed")


class Migration(migrations.Migration):

    dependencies = [
        ('commercial_pipeline', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(adopt, unadopt),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='historicalpipelineentry',
                    name='insurance_type',
                    field=models.CharField(blank=True, choices=[('VIC', 'VIC — all Britam products'), ('NON_VIC', 'Non-VIC — all other insurance covers')], max_length=8, verbose_name='VIC / Non-VIC'),
                ),
                migrations.AddField(
                    model_name='pipelineentry',
                    name='insurance_type',
                    field=models.CharField(blank=True, choices=[('VIC', 'VIC — all Britam products'), ('NON_VIC', 'Non-VIC — all other insurance covers')], max_length=8, verbose_name='VIC / Non-VIC'),
                ),
            ],
        ),
        migrations.AlterField(
            model_name='historicalpipelineentry',
            name='broad_stage',
            field=models.CharField(blank=True, choices=[('discussion', 'Discussion — not yet in I-Apply'), ('rm_only', 'RM Only'), ('application', 'Application — in the system, not yet approved'), ('credit_analysis', 'Credit Analysis'), ('credit_evaluation', 'Credit Evaluation'), ('approved', 'Approved — anywhere after approval'), ('disbursement', 'Disbursement'), ('disbursed', 'Disbursed')], max_length=20),
        ),
        migrations.AlterField(
            model_name='historicalpipelineentry',
            name='deposit_product',
            field=models.CharField(blank=True, choices=[('CASA', 'CASA'), ('FD', 'Fixed deposit'), ('CASH_MARGIN', 'Cash margin'), ('ESCROW', 'Escrow')], max_length=16),
        ),
        migrations.AlterField(
            model_name='historicalpipelineentry',
            name='kind',
            field=models.CharField(choices=[('asset', 'Assets Pipeline'), ('trade', 'Trade Pipeline'), ('deposit', 'Deposits Pipeline'), ('liability', 'Insurance Pipeline')], db_index=True, max_length=12),
        ),
        migrations.AlterField(
            model_name='historicalpipelineentry',
            name='stage',
            field=models.CharField(blank=True, choices=[('discussion', 'Discussion'), ('relationship_manager', 'Relationship Manager (RM)'), ('at_branch', 'At branch'), ('at_credit_analyst', 'At credit analyst'), ('credit_analyst', 'Credit Analyst'), ('credit_origination_manager', 'Credit Origination Manager'), ('at_credit_risk', 'At credit risk'), ('pre', 'PRE'), ('ccm', 'CCM'), ('dcr', 'DCR'), ('bmd', 'BMD'), ('mlc', 'MLC'), ('board', 'Board'), ('branch_rm', 'Branch / RM'), ('offer_letter_generation', 'At offer letter generation'), ('offer_letter_at_branch', 'Offer letter at branch for collection'), ('awaiting_execution', 'Awaiting customer to execute offer letter'), ('valuation', 'Valuation'), ('valuation_adoption', 'Valuation Adoption'), ('instructions_to_lawyers', 'Instructions to Lawyers'), ('charge_preparation', 'Charge preparation'), ('joint_registration', 'Joint Registration'), ('bank_attorneys_execution', 'Bank Attorneys Execution'), ('charge_dispatch', 'Charge dispatch to customer'), ('charge_execution', 'Charge execution by customer'), ('awaiting_registration', 'Awaiting registration process'), ('confirmation_of_securities', 'Confirmation of Securities'), ('disbursement_officer', 'Disbursement Officer'), ('insurance_confirmation', 'Insurance Confirmation'), ('trade_middle_officer', 'Trade Middle Officer'), ('cpc', 'CPC'), ('disbursement', 'Disbursement')], max_length=30),
        ),
        migrations.AlterField(
            model_name='pipelineentry',
            name='broad_stage',
            field=models.CharField(blank=True, choices=[('discussion', 'Discussion — not yet in I-Apply'), ('rm_only', 'RM Only'), ('application', 'Application — in the system, not yet approved'), ('credit_analysis', 'Credit Analysis'), ('credit_evaluation', 'Credit Evaluation'), ('approved', 'Approved — anywhere after approval'), ('disbursement', 'Disbursement'), ('disbursed', 'Disbursed')], max_length=20),
        ),
        migrations.AlterField(
            model_name='pipelineentry',
            name='deposit_product',
            field=models.CharField(blank=True, choices=[('CASA', 'CASA'), ('FD', 'Fixed deposit'), ('CASH_MARGIN', 'Cash margin'), ('ESCROW', 'Escrow')], max_length=16),
        ),
        migrations.AlterField(
            model_name='pipelineentry',
            name='kind',
            field=models.CharField(choices=[('asset', 'Assets Pipeline'), ('trade', 'Trade Pipeline'), ('deposit', 'Deposits Pipeline'), ('liability', 'Insurance Pipeline')], db_index=True, max_length=12),
        ),
        migrations.AlterField(
            model_name='pipelineentry',
            name='stage',
            field=models.CharField(blank=True, choices=[('discussion', 'Discussion'), ('relationship_manager', 'Relationship Manager (RM)'), ('at_branch', 'At branch'), ('at_credit_analyst', 'At credit analyst'), ('credit_analyst', 'Credit Analyst'), ('credit_origination_manager', 'Credit Origination Manager'), ('at_credit_risk', 'At credit risk'), ('pre', 'PRE'), ('ccm', 'CCM'), ('dcr', 'DCR'), ('bmd', 'BMD'), ('mlc', 'MLC'), ('board', 'Board'), ('branch_rm', 'Branch / RM'), ('offer_letter_generation', 'At offer letter generation'), ('offer_letter_at_branch', 'Offer letter at branch for collection'), ('awaiting_execution', 'Awaiting customer to execute offer letter'), ('valuation', 'Valuation'), ('valuation_adoption', 'Valuation Adoption'), ('instructions_to_lawyers', 'Instructions to Lawyers'), ('charge_preparation', 'Charge preparation'), ('joint_registration', 'Joint Registration'), ('bank_attorneys_execution', 'Bank Attorneys Execution'), ('charge_dispatch', 'Charge dispatch to customer'), ('charge_execution', 'Charge execution by customer'), ('awaiting_registration', 'Awaiting registration process'), ('confirmation_of_securities', 'Confirmation of Securities'), ('disbursement_officer', 'Disbursement Officer'), ('insurance_confirmation', 'Insurance Confirmation'), ('trade_middle_officer', 'Trade Middle Officer'), ('cpc', 'CPC'), ('disbursement', 'Disbursement')], max_length=30),
        ),
        migrations.RunPython(rename_disbursed, unrename_disbursed),
    ]
