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
