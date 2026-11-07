# Knowledge Studio Web

Vue 3.5 + Element Plus frontend for Knowledge Studio.

## Setup

Node **≥ 22.22** is required for building and unit tests.

```bash
npm ci
```

Copy `.env.example` to `.env.local` when you need local overrides. The
`.env.local` file is gitignored. Set `VUE_APP_API` to the backend origin when the
API is not served from the same host as the dev server.

## Development

```bash
npm run serve
```

The dev server listens on `http://localhost:8808` by default. `npm run local`
uses the `local` mode and reads the same `.env.local` overrides.

## Build

```bash
npm run build
```

The production bundle is written to `dist/`. The deployment image is built from
`Dockerfile`: nginx serves the static files and proxies `/api/co-knowledge/v1`
to the backend. Fonts are emitted to `dist/fonts/` by the Vue CLI/webpack build.

## Stack

| Layer | Components |
|---|---|
| Runtime | Vue 3.5.26 · Element Plus 2.14.7 · Vue Router 4.6.4 · Vuex 4.1.0 |
| Canvas / graph | @antv/x6 2.19.2 · vis-network 9.1.13 |
| Build / test | @vue/cli-service 5.0.9 · Vitest 5.0.4 |

## Project structure

```text
src/
├── app/              # bootstrap, router, store, i18n, directives, layout shell
├── pages/            # route-level pages, one folder per domain
├── features/         # domain implementations: api/components/composables/lib
│   ├── knowledge-base/
│   ├── graph/
│   ├── workflow/
│   ├── chat/
│   ├── model/
│   ├── operators/
│   ├── agent/
│   └── auth/
├── shared/           # api client, UI kit, layout, lib, composables, constants, types
├── styles/
└── assets/
```

Rules:

- Pages orchestrate only; feature code lives under `features/<domain>/`.
- A feature exposes its public surface through its folder; avoid deep cross-feature imports.
- `shared/lib` must not import Vue; `shared/ui` must not import any feature.
- Import paths use the `@/` alias (`@` -> `src`).

The router uses hash history; page URLs look like `/#/knowledge`, `/#/flow`,
`/#/chat`, `/#/operators`, `/#/models`, `/#/access` and `/#/keys`.

## Lint and tests

```bash
npm run lint
npm run test:unit
```

Current baseline: **898 passed / 83 files**. See
[`tests/unit/README.md`](tests/unit/README.md) for the component-test harness.
