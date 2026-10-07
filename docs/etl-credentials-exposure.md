# ETL credentials in git — findings and a non-breaking plan

Reviewed 7 Oct 2026, `datawarehouse-etls-master`. **No credential values appear
in this document.**

## What was found

`app_settings.py` is the single config every ETL imports. It holds connection
details for the warehouse and for roughly a dozen source systems — Profits
(core banking), CRM prod and UAT, AML, the merchant and biller databases,
school fees, IMT, lendingcore, and an Azure-hosted MySQL.

`.gitignore` line 2 reads `/app_settings.py`. **The file is tracked anyway:**

```bash
git ls-files --error-unmatch app_settings.py   # -> app_settings.py
git rev-list --count HEAD -- app_settings.py   # -> 100 commits
git log -1 --date=short -- app_settings.py     # -> 2026-09-10
```

`.gitignore` has no effect on a file already in the index, so the rule has been
giving false comfort while 100 commits recorded the file contents, the most
recent four weeks ago.

Also tracked:

- `__pycache__/app_settings.cpython-36.pyc` and `...-39.pyc` — compiled modules
  keep string constants, so these carry the same secrets. Removing only the
  `.py` would leave them behind.
- `client_secret_...apps.googleusercontent.com.json` — a Google OAuth client
  secret.
- `customer_ftp_config.yml` — needs checking for FTP credentials.
- A database password in commented-out code in at least `campain_dfs.py`,
  `daily_product_sales.py` and
  `sending_email_digital_business_summary_report.py`.

## Severity

**The repo is not publicly readable.** An unauthenticated
`GET api.github.com/repos/...` returns 404, which is what GitHub returns for a
private repo. Nothing is exposed to the internet as of 7 Oct 2026. This does
**not** establish that it was never public, and that cannot be determined from
the clone.

Two things remain serious:

1. **The remote is a personal GitHub account**, not a bank-owned organisation.
   Every production credential in the estate sits in a repository the bank does
   not administer. If that account changes hands or the person leaves, the bank
   cannot revoke access, audit the collaborator list, or enforce 2FA. This is a
   governance finding independent of the secrets.
2. **Blast radius is unknown until the collaborator list is read.** Anyone with
   read access holds core-banking credentials.

## Do this first — it costs nothing and bounds the problem

```bash
gh api repos/<owner>/<repo> --jq '{private,visibility,created_at,pushed_at,forks_count}'
gh api repos/<owner>/<repo>/collaborators --jq '.[].login'
gh api repos/<owner>/<repo>/forks --jq '.[].full_name'
```

A fork of a private repo keeps its own copy, and removing a collaborator does
not remove their fork. If `forks_count` is not zero, each fork is a separate
disclosure.

## The trap in the obvious fix

`git rm --cached app_settings.py` leaves the file on *your* disk — but the next
`git pull` **deletes it on every other clone, including the production host**,
because it is tracked there too. Every ETL would fail on its next run with an
`ImportError`, and the cause would look nothing like a git operation someone did
days earlier.

So the untracking and the restore must be one action on the host, not two.

## Step 1 — stop it getting worse (no rotation, no ETL downtime)

On the production host, back the live file up **outside the repo** first:

```bash
install -m 600 -o root -g root \
  /data/apps/datascience/etls/app_settings.py \
  /root/etl-app_settings-$(date +%F).py
ls -l /root/etl-app_settings-*.py
```

From a laptop clone, untrack the credential files and push:

```bash
git rm --cached app_settings.py
git rm --cached __pycache__/app_settings.cpython-36.pyc
git rm --cached __pycache__/app_settings.cpython-39.pyc
git rm --cached client_secret_*.apps.googleusercontent.com.json
git commit -m "chore: untrack the credential files .gitignore already claimed to exclude"
git push
```

Then on the host, pull and restore in **one** command so the gap is
sub-second — and do it when no ETL is mid-run:

```bash
cd /data/apps/datascience/etls
git pull && cp -p /root/etl-app_settings-$(date +%F).py app_settings.py
python3.6 -c "import app_settings; print('app_settings imports OK')"
```

Tell every other clone holder to back their copy up before pulling. Add
`client_secret*.json` and `__pycache__/` properly to `.gitignore` while you are
there.

**This stops new commits recording the secrets. It does not un-leak the 100
commits already in history** — anyone with a clone still has every past value.
Only rotation does that.

## Step 2 — rotate, cheapest first

- **The warehouse itself is nearly free to rotate.** The ETLs reach it over
  `127.0.0.1` under `pg_hba` `trust`, so the password in `app_settings.py` is
  not actually what authenticates them. Changing it should be a no-op for the
  ETL fleet — verify on one script rather than assuming.
- **The source systems are the valuable ones** — Profits is core banking. These
  are owned by other teams, so each needs its owner and a window. Rotating one
  may break consumers outside this repo, which is exactly why the list of
  consumers has to come from the owner, not from this review.
- **The Google OAuth client secret** can be rotated in the Google Cloud console
  for the project it belongs to, without touching any other system.

Rotate before deciding anything about rewriting history. Removing a secret from
git does not invalidate it; changing it does.

## Step 3 — move the repo

Into a bank-owned GitHub organisation or the internal GitLab, with the personal
account removed as owner. Treat the history as compromised rather than rewriting
it, unless every clone is known — a `filter-repo` that misses one laptop
achieves nothing but a false clean bill of health.

## Step 4 — make the pattern unrepeatable

`app_settings.py` should read its values from an untracked file or the
environment, so that the config the ETLs import contains no secrets at all and
can be committed safely. That is a change to something which has run for years,
so it belongs after the three steps above, rehearsed on one script first.

## Still to review — the Sybase extraction

`etl_bash/section_01_sybase_extraction.sh` runs three Node scripts that are
**not in this repo**:

```
/data/apps/datascience/node-sybase/loan_tat_data.js
/data/apps/datascience/node-sybase/accounts_tat_data.js
/data/apps/datascience/node-sybase/cards_data.js
```

Check whether that directory is its own git checkout and whether it has a
remote:

```bash
cd /data/apps/datascience/node-sybase
git remote -v
git ls-files | head
grep -rniE "password|user|host|server" --include=*.js . | grep -v node_modules | head
```

If those files hold Sybase credentials inline and are tracked, the same four
steps apply there. The same goes for `reporting_framework/config/databases/`,
which ships only a README in this repo — confirm the real configs under it are
untracked rather than absent by accident.
