#!/usr/bin/env node
/**
 * Lexi iMessage Bridge
 * Uses `imsg watch --json` to stream incoming messages in real time,
 * forwards them to the Lexi server, and sends replies back via imsg.
 *
 * Usage:
 *   LEXI_SERVER_URL=https://your-server.com node lexi_bridge.js
 */

const { spawn, execFileSync, execSync } = require("child_process");
const https = require("https");
const http = require("http");
const readline = require("readline");

const LEXI_SERVER = (process.env.LEXI_SERVER_URL || "http://localhost:8000").replace(/\/$/, "");
const IMSG = process.env.IMSG_PATH || "imsg";

// ── Startup checks ─────────────────────────────────────────────────────────

function checkDeps() {
  try {
    const ver = execSync(`${IMSG} --version 2>&1`).toString().trim();
    console.log(`✓ imsg: ${ver}`);
  } catch {
    console.error(`\n❌  imsg not found. Install it:\n   brew install steipete/tap/imsg\n`);
    process.exit(1);
  }

  try {
    const out = execFileSync(IMSG, ["chats", "--limit", "1", "--json"], { stdio: ["pipe", "pipe", "pipe"] }).toString();
    JSON.parse(out);
    console.log("✓ Messages DB readable");
  } catch (e) {
    console.error("\n❌  Cannot read Messages database.");
    console.error("   → System Settings → Privacy & Security → Full Disk Access → add Terminal");
    console.error("   → Make sure Messages.app is open and signed in\n");
    process.exit(1);
  }
}

// ── Forward to Lexi server ─────────────────────────────────────────────────

function forwardToLexi(handle, text, chatId) {
  const payload = JSON.stringify({ from: handle, text, chat_id: chatId });
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
        "User-Agent": "Lexi-Bridge/1.0",
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

// ── Send reply via imsg ────────────────────────────────────────────────────

function sendReply(handle, text) {
  try {
    execFileSync(IMSG, ["send", "--to", handle, "--text", text], { timeout: 15000 });
    console.log(`✅  Replied to ${handle}`);
  } catch (e) {
    console.error(`❌  Send failed for ${handle}:`, e.message);
    console.error("   → System Settings → Privacy & Security → Automation → Messages");
  }
}

// ── Watch for messages ─────────────────────────────────────────────────────

function startWatcher() {
  const watcher = spawn(IMSG, ["watch", "--json"], { stdio: ["ignore", "pipe", "pipe"] });

  const rl = readline.createInterface({ input: watcher.stdout });

  rl.on("line", (line) => {
    if (!line.trim()) return;
    try {
      const msg = JSON.parse(line);
      // Skip messages sent by us
      if (msg.is_from_me) return;
      const text = (msg.text || "").trim();
      if (!text) return;

      // Resolve the sender handle
      const handle =
        msg.handle ||
        (msg.participants && msg.participants[0]) ||
        msg.chat_identifier ||
        "unknown";

      console.log(`\n📨  [${handle}]: ${text.slice(0, 80)}${text.length > 80 ? "…" : ""}`);
      forwardToLexi(handle, text, msg.chat_id || msg.chat_guid);
    } catch {
      // Non-JSON status lines from imsg — ignore
    }
  });

  watcher.stderr.on("data", (d) => {
    const err = d.toString().trim();
    if (err) console.error("imsg:", err);
  });

  watcher.on("close", (code) => {
    console.error(`\nimsg watch exited (code ${code}), restarting in 3s…`);
    setTimeout(startWatcher, 3000);
  });
}

// ── Main ──────────────────────────────────────────────────────────────────

checkDeps();

console.log(`\n╔══════════════════════════════════════════╗`);
console.log(`║       Lexi iMessage Bridge — Active      ║`);
console.log(`╠══════════════════════════════════════════╣`);
console.log(`║  Server : ${LEXI_SERVER.slice(0, 31).padEnd(31)}║`);
console.log(`║  Mode   : imsg watch --json (streaming)  ║`);
console.log(`╚══════════════════════════════════════════╝\n`);
console.log("Waiting for iMessages… (Ctrl+C to stop)\n");

startWatcher();
