#!/usr/bin/env node
/**
 * Lexi iMessage Bridge
 * Polls your Mac's Messages database for new inbound messages,
 * forwards them to the Lexi server, and sends replies back via imsg.
 *
 * Usage:
 *   LEXI_SERVER_URL=https://your-server.com node lexi_bridge.js
 */

const { execFileSync, execSync } = require("child_process");
const https = require("https");
const http = require("http");

const LEXI_SERVER = (process.env.LEXI_SERVER_URL || "http://localhost:8000").replace(/\/$/, "");
const MESSAGES_DB = process.env.MESSAGES_DB || `${process.env.HOME}/Library/Messages/chat.db`;
const IMSG = process.env.IMSG_PATH || "imsg";
const POLL_MS = 2000;

// ── Startup checks ────────────────────────────────────────────────────────

function checkDeps() {
  try {
    execSync(`which ${IMSG}`, { stdio: "pipe" });
  } catch {
    console.error(`\n❌  imsg not found. Install it with:\n   brew install steipete/formulae/imsg\n`);
    process.exit(1);
  }
  try {
    execFileSync("sqlite3", [MESSAGES_DB, "SELECT 1;"], { stdio: "pipe" });
  } catch (e) {
    console.error(`\n❌  Cannot read Messages database at:\n   ${MESSAGES_DB}`);
    console.error("   → Open System Settings → Privacy & Security → Full Disk Access");
    console.error("   → Add Terminal (or your terminal app)\n");
    process.exit(1);
  }
}

// ── Polling ────────────────────────────────────────────────────────────────

let lastRowId = 0;

function initLastRowId() {
  try {
    const out = execFileSync("sqlite3", [MESSAGES_DB, "SELECT IFNULL(MAX(ROWID),0) FROM message;"], {
      stdio: ["pipe", "pipe", "pipe"],
    })
      .toString()
      .trim();
    lastRowId = parseInt(out, 10) || 0;
    console.log(`Starting from message rowid ${lastRowId}`);
  } catch (e) {
    console.error("Could not initialize rowid:", e.message);
  }
}

function pollMessages() {
  const sql = `
    SELECT m.ROWID, h.id, m.text
    FROM message m
    JOIN handle h ON m.handle_id = h.ROWID
    WHERE m.ROWID > ${lastRowId}
      AND m.is_from_me = 0
      AND m.text IS NOT NULL
      AND length(trim(m.text)) > 0
    ORDER BY m.ROWID ASC;
  `;
  try {
    const out = execFileSync("sqlite3", ["-separator", "\t", MESSAGES_DB, sql], {
      stdio: ["pipe", "pipe", "pipe"],
    })
      .toString()
      .trim();

    if (!out) return;

    for (const line of out.split("\n")) {
      const parts = line.split("\t");
      if (parts.length < 3) continue;
      const [rowid, handle, ...textParts] = parts;
      const text = textParts.join("\t").trim();
      if (!text) continue;
      lastRowId = Math.max(lastRowId, parseInt(rowid, 10));
      console.log(`\n📨  [${handle}]: ${text.slice(0, 80)}${text.length > 80 ? "…" : ""}`);
      forwardToLexi(handle, text);
    }
  } catch {
    // DB temporarily locked — skip this tick
  }
}

// ── HTTP forward ──────────────────────────────────────────────────────────

function forwardToLexi(handle, text) {
  const payload = JSON.stringify({ from: handle, text });
  const url = new URL(`${LEXI_SERVER}/webhooks/imessage`);
  const lib = url.protocol === "https:" ? https : http;

  const req = lib.request(
    {
      hostname: url.hostname,
      port: url.port || (url.protocol === "https:" ? 443 : 80),
      path: url.pathname,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
      },
    },
    (res) => {
      let data = "";
      res.on("data", (c) => (data += c));
      res.on("end", () => {
        try {
          const result = JSON.parse(data);
          if (result.reply) {
            sendReply(handle, result.reply);
          } else {
            console.error("No reply in response:", data.slice(0, 200));
          }
        } catch {
          console.error("Bad server response:", data.slice(0, 200));
        }
      });
    }
  );

  req.on("error", (e) => console.error("Server request failed:", e.message));
  req.write(payload);
  req.end();
}

// ── Reply via imsg ────────────────────────────────────────────────────────

function sendReply(handle, text) {
  try {
    execFileSync(IMSG, ["send", handle, text], { timeout: 15000 });
    console.log(`✅  Replied to ${handle}`);
  } catch (e) {
    console.error(`❌  Failed to send reply to ${handle}:`, e.message);
    console.error("   → Check Automation permission: System Settings → Privacy → Automation → Messages");
  }
}

// ── Main ──────────────────────────────────────────────────────────────────

checkDeps();
initLastRowId();

console.log(`\n╔══════════════════════════════════════════╗`);
console.log(`║       Lexi iMessage Bridge — Active      ║`);
console.log(`╠══════════════════════════════════════════╣`);
console.log(`║  Server : ${LEXI_SERVER.padEnd(31)}║`);
console.log(`║  DB     : ${("..."+MESSAGES_DB.slice(-28)).padEnd(31)}║`);
console.log(`║  Poll   : every ${POLL_MS}ms                  ║`);
console.log(`╚══════════════════════════════════════════╝\n`);
console.log("Waiting for iMessages… (Ctrl+C to stop)\n");

setInterval(pollMessages, POLL_MS);
