# 0002 — File storage: SeaweedFS instead of MinIO

**Status:** accepted (P0-01).

## Context

The specification calls for S3-compatible storage for scanned invoices, drawings and
certificates, either AWS S3 or a self-hosted MinIO. MinIO stopped publishing free Docker
images in 2025, and `minio/minio` is no longer available on Docker Hub.

## Decision

Use **SeaweedFS** (Apache 2.0 licence, image `chrislusf/seaweedfs`) as the self-hosted
S3-compatible store, in development and on the Hostinger VPS. Its S3 access key comes from
the environment; anonymous access is disabled.

The application only talks S3 (through `django-storages`), so moving to AWS S3, Cloudflare
R2, Backblaze B2 or another S3-compatible service later is a change of settings, not code.
