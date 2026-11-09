// SPDX-License-Identifier: Apache-2.0
/**
 * @file tuiSegments.ts
 * @description Parses Claude TUI tag markup that appears in user messages —
 * caveats, command invocations, captured stdout/stderr, system reminders —
 * into a flat segment list the renderer can lay out inline. Also strips bare
 * ANSI/SGR escape sequences (e.g. "[1m...[22m") that survive the JSONL pipe
 * so messages render as plain text instead of leaking codes.
 */

export type TuiSegment =
  | { kind: "caveat"; text: string }
  | { kind: "stdout"; text: string }
  | { kind: "stderr"; text: string }
  | { kind: "system-reminder"; text: string }
  | { kind: "persisted-output"; text: string }
  | { kind: "command"; display: string }
  | { kind: "text"; text: string };

const SIMPLE_TAGS: Record<string, TuiSegment["kind"]> = {
  "local-command-caveat": "caveat",
  "local-command-stdout": "stdout",
  "local-command-stderr": "stderr",
  "system-reminder": "system-reminder",
  "persisted-output": "persisted-output",
};

const COMMAND_TAGS = ["command-name", "command-message", "command-args"] as const;

const KNOWN_TAG_RE = new RegExp(
  `<(?:${[...Object.keys(SIMPLE_TAGS), ...COMMAND_TAGS].join("|")})\\b`
);

// Strip both real ESC-prefixed SGR codes and the bare "[Nm" forms that show up
// when the ESC byte is dropped during JSON encoding. Only matches when followed
// by `m` (the SGR terminator), so it does not eat ordinary bracketed text.
const ANSI_RE = /\[[\d;]*m|\[\d+(?:;\d+)*m/g;

export function stripAnsi(text: string): string {
  return text.replace(ANSI_RE, "");
}

interface MatchSpan {
  start: number;
  end: number;
  segment: TuiSegment;
}

function findSimpleTagMatches(input: string): MatchSpan[] {
  const matches: MatchSpan[] = [];
  for (const [tag, kind] of Object.entries(SIMPLE_TAGS)) {
    const re = new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`, "g");
    let m: RegExpExecArray | null;
    while ((m = re.exec(input)) !== null) {
      matches.push({
        start: m.index,
        end: m.index + m[0].length,
        segment: { kind, text: m[1] ?? "" } as TuiSegment,
      });
    }
  }
  return matches;
}

function findCommandBlocks(input: string): MatchSpan[] {
  // A command block is one or more <command-name|message|args> tags possibly
  // separated by whitespace. Group them so a single pill renders even when
  // the tags arrive in name -> message -> args order.
  const re = /(?:<command-(?:name|message|args)>[^<]*<\/command-(?:name|message|args)>\s*){1,3}/g;
  const out: MatchSpan[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(input)) !== null) {
    const block = m[0];
    const name = /<command-name>([^<]*)<\/command-name>/.exec(block)?.[1] ?? "";
    const args = /<command-args>([^<]*)<\/command-args>/.exec(block)?.[1] ?? "";
    if (!name) continue;
    const trimmedArgs = args.trim();
    out.push({
      start: m.index,
      end: m.index + block.length,
      segment: {
        kind: "command",
        display: trimmedArgs ? `${name} ${trimmedArgs}` : name,
      },
    });
  }
  return out;
}

/**
 * Walks a message text and splits out recognized TUI/command segments while
 * preserving the surrounding prose as `text` segments. Returns a single
 * `text` segment for inputs that contain no recognized markup.
 */
export function parseTuiSegments(input: string): TuiSegment[] {
  if (!KNOWN_TAG_RE.test(input)) {
    return [{ kind: "text", text: input }];
  }

  const matches = [...findSimpleTagMatches(input), ...findCommandBlocks(input)].sort(
    (a, b) => a.start - b.start
  );

  const segments: TuiSegment[] = [];
  let cursor = 0;
  for (const m of matches) {
    if (m.start < cursor) continue;
    if (m.start > cursor) {
      const between = input.slice(cursor, m.start);
      if (between.trim()) {
        segments.push({ kind: "text", text: between });
      }
    }
    segments.push(m.segment);
    cursor = m.end;
  }
  if (cursor < input.length) {
    const tail = input.slice(cursor);
    if (tail.trim()) segments.push({ kind: "text", text: tail });
  }

  return segments.length > 0 ? segments : [{ kind: "text", text: input }];
}

/** True if any recognized TUI tag would alter the rendering of this text. */
export function hasTuiTags(input: string): boolean {
  return KNOWN_TAG_RE.test(input);
}
