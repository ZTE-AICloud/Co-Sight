---
name: drive-viz
description: Use when shared CSS design tokens are needed for drive visualization HTML. Provides light + dark theme CSS variables covering stage colors (analyze / plan / execute / evaluate), status (gate / running / queued), surfaces, and typography.
user-invocable: false
disable-model-invocation: true
allowed-tools: []
---

# drive-viz

Returns shared CSS design tokens for drive visualization HTML. Other drive skills invoke this (via prose reference in their own SKILL.md body), receive the CSS string, and concatenate it into the `<style>` block of the HTML they generate.

## Invocation

Run and return stdout:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/tokens.py [mode]
```

- `mode` is `"light"` or `"dark"`. Other values raise `ValueError`.
- Output: a stripped CSS string starting with `:root {`.
- Caller-side pattern: pass the returned string straight into `<style>{tokens}</style>`.

## Tokens

| Token | light | dark |
|-------|-------|------|
| `--c-analyze` | `#3b82f6` | `#60a5fa` |
| `--c-plan` | `#a855f7` | `#c084fc` |
| `--c-execute` | `#10b981` | `#34d399` |
| `--c-evaluate` | `#f97316` | `#fb923c` |
| `--c-gate` | `#ef4444` | `#f87171` |
| `--c-back` | `#f59e0b` | `#fbbf24` |
| `--c-success` | `#10b981` | `#10b981` |
| `--c-running` | `#f59e0b` | `#fbbf24` |
| `--c-pending` | `#94a3b8` | `#475569` |
| `--c-user` | `#64748b` | `#94a3b8` |
| `--c-user-fill` | `#f3f4f6` | `#1e293b` |
| `--bg` | `#f6f8fb` | `#0a0f1e` |
| `--card` | `#ffffff` | `#131a2e` |
| `--card-2` | `#fafbfc` | `#1a223b` |
| `--card-3` | — | `#232c47` |
| `--text` | `#0f172a` | `#e2e8f0` |
| `--muted` | `#64748b` | `#94a3b8` |
| `--muted-2` | `#94a3b8` | `#64748b` |
| `--border` | `#e2e8f0` | `#1e293b` |
| `--border-2` | `#cbd5e1` | — |
| `--border-light` | — | `#2a3856` |
| `--track` | `#f1f5f9` | — |
| `--mono` | `ui-monospace, "SF Mono", Consolas, monospace` | `ui-monospace, "SF Mono", Consolas, "Roboto Mono", monospace` |