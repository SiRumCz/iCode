/** Build a Cursor-style markdown transcript from chat timeline rows. */

export interface TranscriptMessage {
  role?: string;
  content?: string;
  title?: string;
}

function fence(body: string, lang = ""): string {
  const text = (body || "").replace(/\n+$/, "");
  let ticks = "```";
  while (text.includes(ticks)) {
    ticks += "`";
  }
  return `${ticks}${lang}\n${text}\n${ticks}`;
}

function toolHeading(title: string): string {
  const head = (title || "tool").trim();
  const start = head.match(/^▶\s*(.+)$/);
  if (start) {
    return `Tool · ${start[1].trim()} (start)`;
  }
  const done = head.match(
    /^■\s*(.+?)\s+(completed|failed|done|cancelled|canceled|error)$/i
  );
  if (done) {
    return `Tool · ${done[1].trim()} (${done[2].toLowerCase()})`;
  }
  const bare = head.match(/^■\s*(.+)$/);
  if (bare) {
    return `Tool · ${bare[1].trim()}`;
  }
  return `Tool · ${head}`;
}

/** Sanitize a session title for use as a default save filename. */
export function transcriptFilename(title: string | undefined): string {
  const base = (title || "icode-transcript")
    .trim()
    .replace(/[^\w.\-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80);
  return `${base || "icode-transcript"}.md`;
}

export function messagesToMarkdown(
  messages: TranscriptMessage[],
  opts?: { title?: string; sessionId?: string }
): string {
  const title = (opts?.title || "iCode Transcript").trim() || "iCode Transcript";
  const when = new Date().toISOString();
  const lines: string[] = [`# ${title}`, "", `_Exported from iCode · ${when}_`];
  if (opts?.sessionId) {
    lines.push(`_Session: \`${opts.sessionId}\`_`);
  }
  lines.push("", "---", "");

  for (const raw of messages) {
    const role = String(raw.role || "").toLowerCase();
    const content = String(raw.content || "");
    const msgTitle = raw.title != null ? String(raw.title) : "";
    if (role === "user") {
      if (!content.trim()) {
        continue;
      }
      lines.push("### User", "", content.trim(), "", "---", "");
    } else if (role === "assistant") {
      if (!content.trim()) {
        continue;
      }
      lines.push("### Assistant", "", content.trim(), "", "---", "");
    } else if (role === "thought" || role === "thinking") {
      if (!content.trim()) {
        continue;
      }
      lines.push("### Thinking", "", content.trim(), "", "---", "");
    } else if (role === "tool") {
      lines.push(`### ${toolHeading(msgTitle || "tool")}`, "");
      if (content.trim()) {
        lines.push(fence(content.trim()), "");
      }
      lines.push("---", "");
    } else if (role === "system") {
      if (!content.trim()) {
        continue;
      }
      lines.push("### System", "", content.trim(), "", "---", "");
    } else if (content.trim()) {
      lines.push("### Note", "", content.trim(), "", "---", "");
    }
  }

  while (lines.length && (lines[lines.length - 1] === "" || lines[lines.length - 1] === "---")) {
    lines.pop();
  }
  lines.push("");
  return lines.join("\n");
}
