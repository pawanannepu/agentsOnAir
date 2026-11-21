# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Foundational polyglot monorepo scaffold using Turborepo and pnpm workspaces (see spec 0001)
- Web console in apps/web built with Next.js 16 App Router, React 19, Tailwind CSS, and Vitest test harness
- Agent engine service in apps/agent built with Python FastAPI and pytest test suite managed by uv
- Local development service definitions in docker-compose.yml for PostgreSQL 16 persistence and Redis 7 task broker
- Monorepo architecture specification defining execution isolation, single writer database ownership, and streaming contracts (see spec 0001)
- PostgreSQL database schema with UUIDv7 primary keys for tenant organizations, repositories, credentials, tasks, task runs, sandbox runs, and immutable audit logs (see spec 0002)
- AES 256 GCM authenticated encryption for repository tokens and provider credentials with unique nonces and tampering protection
- Clean Architecture domain entities and async SQLAlchemy repositories with tenant isolation, run locking, and optimistic concurrency control on checkpoint state
- Reversible Alembic migration featuring partial unique indexes for repository soft delete and PostgreSQL database triggers enforcing append only audit log immutability
- Drizzle ORM read schemas in the web console matching the database schema for cross workspace type safety
