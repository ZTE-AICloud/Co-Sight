import fs from "node:fs";

export function readJsonl(filePath) {
  const text = fs.readFileSync(filePath, "utf8");
  const events = [];
  const errors = [];
  const lines = text.split(/\r?\n/);

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line.trim()) continue;
    try {
      const event = JSON.parse(line);
      event.__line = i + 1;
      events.push(event);
    } catch (error) {
      errors.push({ line: i + 1, message: error.message });
    }
  }

  return { events, errors };
}

export function firstTimestamp(events) {
  return events.find((event) => event.timestamp)?.timestamp ?? null;
}

export function lastTimestamp(events) {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    if (events[i].timestamp) return events[i].timestamp;
  }
  return null;
}
