# Hosting SML ERP on a Hostinger VPS

This guide puts SML ERP on its servers (backlog P1-10, spec 2). Follow it once for the
**test** server and once for the **production** server. Every update after that is one
click (step 9).

You type the commands in a terminal: on Windows, **PowerShell**; on a Mac, **Terminal**.
Lines starting with `$` are commands (type them without the `$`). Where a value is in
`<angle brackets>`, put in your own.

**Passwords and keys stay with you.** Never send them by chat or email, and never put
them in GitHub. The setup creates every secret on the server itself.

---

## What you need

| | Test server | Production server |
| --- | --- | --- |
| Hostinger plan | KVM 2 (2 vCPU, 8 GB) is enough | KVM 4 (4 vCPU, 16 GB, 200 GB) |
| Operating system | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS |
| Location | the data centre closest to Sri Lanka (India) | the same |
| Web address | e.g. `erp-test.<yourdomain>` | e.g. `erp.<yourdomain>` |

You also need the domain (for example `smlengineers.lk`) and access to its DNS settings
(step 7).

## 1. Make an SSH key on your computer (once)

An SSH key is a pair of files that lets you sign in to the server without a password. The
private file stays on your computer; the public one is given to Hostinger.

```
$ ssh-keygen -t ed25519 -C "<your name> SML ERP"
```

Press Enter to accept the place it suggests, and choose a passphrase (a long password that
protects the key). Then show the **public** key:

```
$ cat ~/.ssh/id_ed25519.pub          (Windows: type $env:USERPROFILE\.ssh\id_ed25519.pub)
```

It is one line starting with `ssh-ed25519`. Copy it.

## 2. Create the VPS in Hostinger

In hPanel: **VPS → Create / Manage → Operating system: Ubuntu 24.04**, the location closest
to Sri Lanka, a strong root password (store it in your password manager), and under
**Settings → SSH keys → Add SSH key** paste the public key from step 1.

Note the server's **IP address** (shown on the VPS overview, e.g. `82.180.12.34`).

## 3. Prepare the server (once, about 10 minutes)

Sign in as root with your key and run the setup script:

```
$ ssh root@<IP address>
# curl -fsSL https://raw.githubusercontent.com/SML-Engineers/sml-erp/main/deploy/scripts/server-setup.sh -o setup.sh
# bash setup.sh
```

The repository is private, so if the download is refused, copy the file instead from your
computer: `scp deploy/scripts/server-setup.sh root@<IP address>:setup.sh`.

The script installs security updates (and turns on automatic security updates), Docker,
the firewall (only SSH, HTTP and HTTPS are open) and a user called **deploy** that runs the
ERP. It then switches off password sign-in, so only SSH keys work.

**Before closing that window**, open a second terminal and check that you can sign in as
deploy: `ssh deploy@<IP address>`. If it does not work, fix it from the first window (or
Hostinger's browser terminal) before signing out.

## 4. Get the code from GitHub

The server reads the code from GitHub with its own read-only key. As **deploy**:

```
$ ssh deploy@<IP address>
$ ssh-keygen -t ed25519 -f ~/.ssh/github -N "" -C "SML ERP server"
$ cat ~/.ssh/github.pub
```

In GitHub: **SML-Engineers/sml-erp → Settings → Deploy keys → Add deploy key**. Title:
"Test server" (or "Production server"), paste the line, leave **Allow write access** off.

Back on the server:

```
$ printf 'Host github.com\n  IdentityFile ~/.ssh/github\n' >> ~/.ssh/config
$ git clone git@github.com:SML-Engineers/sml-erp.git /srv/sml-erp/app
```

(Answer `yes` when asked about GitHub's fingerprint.)

## 5. The environment file (the server's secrets)

```
$ /srv/sml-erp/app/deploy/scripts/make-env.sh production erp.<yourdomain> <your email>
```

Use `test` and the test address on the test server. This writes
`/srv/sml-erp/.env.production` with new random passwords and keys, readable only by deploy.
The email address receives Let's Encrypt notices about the HTTPS certificate.

**Keep a copy of this file in a safe place** (your password manager). It holds the key
that encrypts the two-factor secrets and the mailbox password inside the database; without
it a restored backup cannot be read. Show it with `cat /srv/sml-erp/.env.production`.

## 6. First start

```
$ /srv/sml-erp/app/deploy/scripts/deploy.sh
```

The first build takes 5 to 10 minutes. It ends with `Done: version … is running.`

## 7. Point the web address to the server, then get the certificate

Where the domain was bought (Hostinger: **Domains → DNS / Nameservers**; a `.lk` domain:
the LK Domain Registry), add one record:

| Type | Name | Points to | TTL |
| --- | --- | --- | --- |
| A | `erp` (or `erp-test`) | the server's IP address | 3600 |

After a few minutes (sometimes an hour) check with `ping erp.<yourdomain>`: it should show
the server's address. Then, on the server:

```
$ /srv/sml-erp/app/deploy/scripts/get-certificate.sh
```

Open `https://erp.<yourdomain>` and you will see the sign-in page with a padlock. The
certificate renews itself.

## 8. The first administrator, and email

```
$ cd /srv/sml-erp/app
$ docker compose -f deploy/docker-compose.prod.yml --env-file /srv/sml-erp/.env.production \
    run --rm backend python manage.py createsuperuser
```

Enter the Admin's email, name and password. Sign in at the web address: the system asks
the Admin to set up the authenticator app. The Admin then adds the other users and roles,
and the company details, in the ERP itself.

**Notification emails** (approvals, reminders) need the company mailbox's SMTP details.
Edit the file (`nano /srv/sml-erp/.env.production`), fill `EMAIL_HOST`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL`, save, and run `deploy.sh` again. (Quotations,
invoices and reports are sent from the mailbox set in **Settings → Document email**.)

**On the test server only**, you can load demo data so people can try every step at once:
`docker compose -f deploy/docker-compose.prod.yml --env-file /srv/sml-erp/.env.production run --rm backend python manage.py load_demo_data`.
It creates a Clerk, Accountant, Director and Cashier (all `@demo.sml.lk`, sharing one
authenticator entry it prints), suppliers, a bank account and vouchers at every stage. It
refuses to run on the production server.

## 9. Updates: one click in GitHub

Once, for each server, in GitHub: **Settings → Environments → New environment**, named
`test` (and `production`), with these **secrets**:

| Secret | Value |
| --- | --- |
| `SSH_HOST` | the server's IP address |
| `SSH_USER` | `deploy` |
| `SSH_PRIVATE_KEY` | a key made only for GitHub (below) |
| `SSH_KNOWN_HOSTS` | the output of `ssh-keyscan <IP address>` |

Make the GitHub key on your computer: `ssh-keygen -t ed25519 -f github-deploy -N ""`. Put
the contents of `github-deploy` (the private file) in `SSH_PRIVATE_KEY`, add the contents
of `github-deploy.pub` as a new line in `/home/deploy/.ssh/authorized_keys` on the server,
then delete both files from your computer.

To update: **Actions → Deploy → Run workflow**, choose the server and the version (`main`,
or a release tag). It refuses any version that is not on main or has not passed every
check. Try each update on **test** first, then run it for **production**.

Without GitHub, the same is `/srv/sml-erp/app/deploy/scripts/deploy.sh` on the server.

## Everyday commands (on the server, as deploy)

```
$ cd /srv/sml-erp/app
$ alias erp='docker compose -f deploy/docker-compose.prod.yml --env-file /srv/sml-erp/.env.production'
$ erp ps                     # what is running
$ erp logs --tail=100 backend   # recent messages (also: worker, scheduler, web, db)
$ erp restart backend        # restart one part
$ curl -k https://localhost/api/v1/health/   # the version and the database status
```

The data (database, scanned files, certificates) is in Docker volumes and survives updates
and restarts. Nightly off-site backups and restoring: [backups.md](backups.md).

## How the server is protected

- Only ports 22 (SSH, keys only), 80 and 443 are open; port 80 only sends people to HTTPS.
  The database, Redis and file storage are reachable from inside the server only.
- HTTPS with TLS 1.2/1.3 and HSTS; strict security headers (no other site can frame the
  ERP; scripts only from the ERP itself).
- Automatic Ubuntu security updates; fail2ban blocks repeated SSH sign-in attempts.
- Debug pages are off; every secret is generated on the server and never committed.
- Each service restarts by itself after a crash or a reboot; logs are size-limited.
