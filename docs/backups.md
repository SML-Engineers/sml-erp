# Backups and restoring

Every night at 01:30 the server makes an encrypted backup of SML ERP and sends it to storage
**outside Hostinger**, so a problem with the server or the Hostinger account cannot take the
backups with it (backlog P1-11, spec 2). Set this up once per server, after
[hosting.md](hosting.md).

## What is backed up

| | How |
| --- | --- |
| The database (every voucher, payment, journal entry, log…) | a full dump, taken while the ERP keeps running |
| Scanned invoices and every other stored file | a plain copy of each file |
| The server's environment file | it holds the key to encrypted data in the database |

All of it is **encrypted on the server** before it leaves, with a password only you hold.
Only what changed since the night before is sent, so after the first night it is quick.

**Kept:** one backup per day for 30 days, plus the last backup of each month for 12 months
(settings `KEEP_DAILY` and `KEEP_MONTHLY`). Once a week the backup storage is checked
(part of the data is read back and verified).

## 1. Choose where the backups go

Any S3-compatible storage works. Two good, low-cost choices:

| | Backblaze B2 | Cloudflare R2 |
| --- | --- | --- |
| Price | about US$6 per TB per month; the first 10 GB free | about US$15 per TB per month; the first 10 GB free |
| What to create | a **private bucket** (e.g. `sml-erp-backups`) and an **application key** for that bucket only | a **bucket** and an **API token** with Object Read & Write on that bucket only |
| Address to use | `s3:https://s3.<region>.backblazeb2.com/sml-erp-backups/production` (the region is shown on the bucket) | `s3:https://<account id>.r2.cloudflarestorage.com/sml-erp-backups/production` |

The ERP's data will be a few GB for years, so the cost is a few dollars a month at most.
Use the folder `production` for the production server and `test` for the test server.

## 2. The backup settings file

On the server, as deploy:

```
$ /srv/sml-erp/app/deploy/scripts/make-backup-env.sh s3:https://<address from step 1>
$ nano /srv/sml-erp/backup.env
```

Fill in `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` with the key from step 1, and save.

**Copy the `RESTIC_PASSWORD` line into your password manager now.** Without it, nobody can
open the backups, including you. Keep it together with the copy of the environment file
(hosting.md, step 5) and the storage provider's sign-in.

## 3. Check it works

```
$ CHECK=1 /srv/sml-erp/app/deploy/scripts/backup.sh
```

It ends with `Backup finished.` From now on it runs every night by itself. To see the last
nights: `journalctl -u sml-erp-backup --since "3 days ago"`, and the date of the last good
backup: `cat /srv/sml-erp/backups/last-success`.

**Recommended: be told if a backup does not happen.** Create a free check at
[healthchecks.io](https://healthchecks.io) (period 1 day, grace 2 hours), put its address in
`HEALTHCHECK_URL` in `backup.env`, and it emails you whenever a night's backup fails or does
not run.

## Restoring

`restore.sh` **replaces** the database and files on the server with those of a backup. The
ERP is stopped for a few minutes while it runs.

```
$ /srv/sml-erp/app/deploy/scripts/restore.sh            # list the backups, newest last
$ /srv/sml-erp/app/deploy/scripts/restore.sh latest     # restore the newest
$ /srv/sml-erp/app/deploy/scripts/restore.sh 4f2a9c1e   # or a chosen one, by its ID
```

It asks you to type `RESTORE` before changing anything, then fetches the backup, puts the
database and the files back, starts the ERP and checks that it answers.

**On a new server** (the old one is lost): follow hosting.md steps 1 to 6, but in step 5
put back your saved copy of the environment file instead of making a new one. Then create
`backup.env` with the same `RESTIC_REPOSITORY`, `RESTIC_PASSWORD` and storage key, and run
`restore.sh latest`. If you no longer have the environment file, `restore.sh` restores it
inside the backup (`/srv/sml-erp/backups/restore/backup/config/env.production`) and tells you
what to copy.

## Monthly restore test (spec 2)

Once a month, on the **test** server, restore the production backup and check it:

1. In the test server's `backup.env`, temporarily set `RESTIC_REPOSITORY` to the
   **production** folder (and its storage key and password).
2. `restore.sh latest`, then sign in to the test ERP and look at a few recent vouchers and
   their scanned invoices.
3. Put the test server's own `backup.env` values back.

Write the date and the result in the IT log. The automatic checks on every change to the ERP
also run a full backup, delete everything and restore it, and fail if anything is missing.
