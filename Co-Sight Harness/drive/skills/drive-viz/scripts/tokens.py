"""drive visualization design tokens — pure CSS constants.

CSS variables shared across all drive visualization HTML outputs (01-replay,
02-runtime-phase, 02-runtime-dag, 03-phase, 03-dag, 04-builder).

Pure constants module — no behavior, no side effects, no I/O. Importing this
module is free.

Per PROP-20260907-002 §5.3 principle: capability skill 不共享代码硬约束,
but this is a constants module (pure data), not behavior code. Sharing is
acceptable. See PROP-20260920-001 §方案 §共享.
"""


LIGHT_TOKENS_CSS = """
:root {
  /* Stage colors */
  --c-analyze: #3b82f6;
  --c-plan: #a855f7;
  --c-execute: #10b981;
  --c-evaluate: #f97316;

  /* Status colors */
  --c-gate: #ef4444;
  --c-success: #10b981;
  --c-running: #f59e0b;
  --c-pending: #94a3b8;
  --c-back: #f59e0b;

  /* User-defined agent colors (vs drive built-in) */
  --c-user: #64748b;
  --c-user-fill: #f3f4f6;

  /* Light theme surfaces */
  --bg: #f6f8fb;
  --card: #ffffff;
  --card-2: #fafbfc;
  --text: #0f172a;
  --muted: #64748b;
  --muted-2: #94a3b8;
  --border: #e2e8f0;
  --border-2: #cbd5e1;
  --track: #f1f5f9;

  /* Typography */
  --mono: ui-monospace, "SF Mono", Consolas, monospace;
}
"""


DARK_TOKENS_CSS = """
:root {
  /* Stage colors (lighter for dark bg readability) */
  --c-analyze: #60a5fa;
  --c-plan: #c084fc;
  --c-execute: #34d399;
  --c-evaluate: #fb923c;

  /* Status colors */
  --c-gate: #f87171;
  --c-success: #10b981;
  --c-running: #fbbf24;
  --c-amber: #fbbf24;
  --c-pending: #475569;
  --c-back: #fbbf24;

  /* User-defined agent colors */
  --c-user: #94a3b8;
  --c-user-fill: #1e293b;

  /* Dark theme surfaces */
  --bg: #0a0f1e;
  --card: #131a2e;
  --card-2: #1a223b;
  --card-3: #232c47;
  --text: #e2e8f0;
  --muted: #94a3b8;
  --muted-2: #64748b;
  --border: #1e293b;
  --border-light: #2a3856;

  /* Typography */
  --mono: ui-monospace, "SF Mono", Consolas, "Roboto Mono", monospace;
}
"""


# Aliases (used by callers that prefer constants over the helper)
TOKENS_CSS_LIGHT = LIGHT_TOKENS_CSS
TOKENS_CSS_DARK = DARK_TOKENS_CSS


def tokens(mode: str = "light") -> str:
    """Return CSS tokens string for the given mode.

    Args:
        mode: 'light' for 01-replay / 03-phase / 03-dag / 04-builder,
              'dark' for 02-runtime-phase / 02-runtime-dag.

    Returns:
        Stripped CSS string containing `:root { --token: value; ... }`.
        Caller concatenates this into a `<style>` block.

    Raises:
        ValueError: if mode is not 'light' or 'dark'.
    """
    if mode == "light":
        return LIGHT_TOKENS_CSS.strip()
    if mode == "dark":
        return DARK_TOKENS_CSS.strip()
    raise ValueError(f"Unknown mode: {mode!r}; expected 'light' or 'dark'")


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "light"
    print(tokens(mode))