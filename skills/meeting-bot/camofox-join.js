#!/usr/bin/env node
/**
 * Camofox Meeting Joiner v3
 * Uses Playwright + Camoufox directly for Google Meet with cookie auth
 * Includes attendance monitoring
 */

const os = require("os");
const path = require("path");
const fs = require("fs");
const { execSync } = require("child_process");

// Path to your server's Camoufox installation — adjust if yours is installed elsewhere
const CAMOFOX_DIR = process.env.CAMOFOX_DIR || path.join(os.homedir(), ".openclaw/workspace/camofox-browser");
const { launchOptions } = require(CAMOFOX_DIR + "/node_modules/camoufox-js");
const { firefox } = require(CAMOFOX_DIR + "/node_modules/playwright-core");
const { config, TOOLKIT_ROOT } = require("../../lib/config");

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Shell-escape a string using POSIX single-quote wrapping.
 * This prevents shell injection when interpolating into shell commands.
 */
function shellEscape(s) {
    return "'" + String(s).replace(/'/g, "'\\''") + "'";
}

/**
 * Escape XML special characters to prevent XML injection in TwiML.
 */
function xmlEscape(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
}

// .env loading is handled by the shared config loader (../../lib/config)

const MEETING_URL = process.argv[2] || process.env.MEETING_URL;
const META_PATH = process.argv[3] || null;
const COOKIES_PATH = path.join(__dirname, "google-cookies.json");
const SCREENSHOT_DIR = "/tmp";

// Allowed meeting provider domains (prevent SSRF)
const ALLOWED_DOMAINS = new Set([
    "meet.google.com",
    "zoom.us",
    "teams.microsoft.com",
    "teams.live.com",
]);

if (!MEETING_URL) {
    console.error("Error: No meeting URL provided");
    console.error("Usage: node camofox-join.js <meeting-url> [metadata-file]");
    process.exit(1);
}

// Validate meeting URL domain
try {
    const meetingHost = new URL(MEETING_URL).hostname;
    if (!ALLOWED_DOMAINS.has(meetingHost)) {
        console.error("Error: Invalid meeting URL domain: " + meetingHost);
        console.error("Allowed domains: " + Array.from(ALLOWED_DOMAINS).join(", "));
        process.exit(1);
    }
} catch (e) {
    console.error("Error: Invalid meeting URL: " + e.message);
    process.exit(1);
}

// Team member mapping: email -> { name, phone } (built from shared config)
const TEAM = {};
config.team.members.forEach(m => {
    TEAM[m.email] = { name: m.name.split(" ")[0], phone: m.phone };
});

// Load meeting metadata if provided
let meetingMeta = null;
if (META_PATH && fs.existsSync(META_PATH)) {
    try {
        meetingMeta = JSON.parse(fs.readFileSync(META_PATH, "utf8"));
        console.log("Loaded meeting metadata: " + meetingMeta.title);
    } catch (e) {
        console.log("Failed to load metadata: " + e.message);
    }
}

function convertCookies(cookies) {
    return cookies.map(c => {
        const cookie = {
            name: c.name,
            value: c.value,
            domain: c.domain,
            path: c.path || "/",
            httpOnly: !!c.httpOnly,
            secure: !!c.secure,
        };
        if (c.expirationDate && c.expirationDate > 0) {
            cookie.expires = c.expirationDate;
        }
        const ss = (c.sameSite || "").toLowerCase();
        if (ss === "strict") cookie.sameSite = "Strict";
        else if (ss === "lax") cookie.sameSite = "Lax";
        else cookie.sameSite = "None";
        return cookie;
    });
}

/**
 * Dump all buttons on page for debugging selectors
 */
async function dumpButtons(page, context) {
    const buttons = await page.evaluate(() => {
        const els = document.querySelectorAll("button, [role=button]");
        return Array.from(els).map(el => ({
            text: (el.textContent || "").trim().substring(0, 60),
            aria: el.getAttribute("aria-label") || "",
            tooltip: el.getAttribute("data-tooltip") || "",
            id: el.id || "",
        })).filter(b => b.text || b.aria || b.tooltip);
    });
    console.log("DEBUG [" + context + "] buttons on page:");
    buttons.forEach(b => console.log("  " + JSON.stringify(b)));
    return buttons;
}

/**
 * Read participant names from the Google Meet People panel.
 * The panel has sections: "Contributors" (in-meeting) and "Requested".
 * We look for names under "Contributors" to see who is actually in the call.
 *
 * The People button is in the TOP-RIGHT icon bar (avatar with participant count badge).
 * Be careful NOT to click the Chat button (bottom-right) which also has "people"-ish text.
 */
async function readParticipants(page) {
    try {
        // First dump all buttons so we can debug
        await dumpButtons(page, "before-people-click");

        // The People button has text like "People1" or "People2" (text + count, no aria-label).
        // From debug dump: {"text":"People1","aria":"","tooltip":"","id":""}
        let opened = await page.evaluate(() => {
            const btns = Array.from(document.querySelectorAll("button, [role=button]"));

            // Priority 1: button whose text starts with "People" followed by a digit
            let found = btns.find(b => {
                const text = (b.textContent || "").trim();
                return /^People\d+$/i.test(text);
            });

            // Priority 2: button whose text is exactly "People"
            if (!found) {
                found = btns.find(b => {
                    const text = (b.textContent || "").trim().toLowerCase();
                    return text === "people";
                });
            }

            // Priority 3: aria-label with "participant" or "in call" (NOT chat)
            if (!found) {
                found = btns.find(b => {
                    const aria = (b.getAttribute("aria-label") || "").toLowerCase();
                    const text = (b.textContent || "").toLowerCase();
                    if (text.includes("chat") || aria.includes("chat")) return false;
                    return aria.includes("participant") || aria.includes("in call") ||
                           aria.includes("show everyone");
                });
            }

            if (found) {
                console.log("Clicking people button: text=" + found.textContent.trim());
                found.click();
                return true;
            }
            return false;
        });

        if (!opened) {
            console.log("Attendance: People button not found");
            await screenshot_global("attendance-no-people-btn");
            return [];
        }

        console.log("Attendance: Clicked People button");
        await sleep(3000);
        await screenshot_global("attendance-panel");

        // Simple approach: grab ALL page text with People panel open.
        // We'll check if each team member's name appears anywhere in the text.
        // This avoids the DOM parsing complexity entirely.
        const pageText = await page.evaluate(() => {
            return (document.body.innerText || "").toLowerCase();
        });

        console.log("Attendance: Page text includes '" + config.assistant.name.toLowerCase() + "': " + pageText.includes(config.assistant.name.toLowerCase()));

        // Close the people panel
        try {
            await page.keyboard.press("Escape");
        } catch (e) {}
        await sleep(500);

        // Return the full page text as a string (not array)
        return pageText;
    } catch (e) {
        console.log("Attendance: Error reading participants: " + e.message);
        return "";
    }
}

// Global screenshot reference (set inside main IIFE)
let screenshot_global = async () => {};

/**
 * Call someone via Twilio and play a TTS message telling them to join the meeting.
 * Uses curl + Twilio REST API with API Key auth.
 * Env vars: TWILIO_ACCOUNT_SID, TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET, TWILIO_FROM_NUMBER
 */
async function twilioCall(phone, personName, meetingTitle) {
    try {
        const accountSid = process.env.TWILIO_ACCOUNT_SID;
        const apiKey = process.env.TWILIO_API_KEY_SID;
        const apiSecret = process.env.TWILIO_API_KEY_SECRET;
        const fromNumber = process.env.TWILIO_FROM_NUMBER;

        if (!accountSid || !apiKey || !apiSecret || !fromNumber) {
            console.log("Attendance: Twilio credentials not configured, skipping call");
            return false;
        }

        const safeName = xmlEscape(personName);
        const safeTitle = xmlEscape(meetingTitle);
        const twiml = `<Response><Say voice="alice">Hey ${safeName}, you are late to ${safeTitle}. Everyone is waiting for you. Please join now.</Say><Pause length="2"/><Say voice="alice">Again, ${safeName}, please join ${safeTitle} right now.</Say></Response>`;

        console.log("Attendance: Calling " + personName + " at " + phone + " via Twilio");

        // Use Node.js https instead of execSync+curl to avoid shell injection
        const https = require("https");
        const querystring = require("querystring");
        const postData = querystring.stringify({
            To: phone,
            From: fromNumber,
            Twiml: twiml,
        });
        const auth = Buffer.from(apiKey + ":" + apiSecret).toString("base64");
        const options = {
            hostname: "api.twilio.com",
            path: `/2010-04-01/Accounts/${encodeURIComponent(accountSid)}/Calls.json`,
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic " + auth,
                "Content-Length": Buffer.byteLength(postData),
            },
            timeout: 30000,
        };

        const result = await new Promise((resolve) => {
            const req = https.request(options, (res) => {
                let body = "";
                res.on("data", (chunk) => body += chunk);
                res.on("end", () => resolve(body));
            });
            req.on("error", (err) => resolve(JSON.stringify({ message: err.message })));
            req.on("timeout", () => { req.destroy(); resolve(JSON.stringify({ message: "timeout" })); });
            req.write(postData);
            req.end();
        });

        try {
            const resp = JSON.parse(result);
            if (resp.sid) {
                console.log("Attendance: Twilio call queued - SID: " + resp.sid + " status: " + resp.status);
                return true;
            } else if (resp.message) {
                console.log("Attendance: Twilio error: " + resp.message);
                return false;
            }
        } catch (e) {
            console.log("Attendance: Twilio response: " + result.substring(0, 200));
        }
        return true;
    } catch (e) {
        console.log("Attendance: Twilio call failed for " + phone + ": " + e.message);
        return false;
    }
}

/**
 * Send WhatsApp message via openclaw CLI
 */
function sendWhatsApp(phone, message) {
    try {
        const msgFile = "/tmp/wa-msg-" + Date.now() + "-" + Math.random().toString(36).slice(2) + ".txt";
        fs.writeFileSync(msgFile, message, { mode: 0o600 });
        const cmd = `source "$HOME/.env" && openclaw message send --channel whatsapp --target ${shellEscape(phone)} --message "$(cat ${shellEscape(msgFile)})"`;
        console.log("Attendance: Sending WhatsApp to " + phone);
        execSync(cmd, { shell: "/bin/bash", timeout: 30000, stdio: "pipe" });
        console.log("Attendance: WhatsApp sent to " + phone);
        try { fs.unlinkSync(msgFile); } catch (_) {}
        return true;
    } catch (e) {
        console.log("Attendance: WhatsApp failed for " + phone + ": " + e.message);
        return false;
    }
}

/**
 * Invite someone into the meeting via Google Meet's "Add people" dialog.
 * From testing: this workspace only has "Invite" tab (no "Call" tab for dial-out).
 * So we type their email, send the invite (triggers Google notification on their phone),
 * and also send WhatsApp as backup.
 */
async function inviteIntoMeeting(page, email, personName) {
    try {
        console.log("Attendance: Inviting " + personName + " (" + email + ") via Google Meet");

        // First open the People panel (Add people button is inside it)
        const peopleOpened = await page.evaluate(() => {
            const btns = Array.from(document.querySelectorAll("button, [role=button]"));
            const found = btns.find(b => /^People\d*$/i.test((b.textContent || "").trim()));
            if (found) { found.click(); return true; }
            return false;
        });
        if (peopleOpened) await sleep(2000);

        // Now click "Add people" button inside the People panel
        let opened = await page.evaluate(() => {
            const btns = Array.from(document.querySelectorAll("button, [role=button]"));
            const found = btns.find(b => {
                const text = (b.textContent || "").toLowerCase();
                const aria = (b.getAttribute("aria-label") || "").toLowerCase();
                return text.includes("add people") || aria.includes("add people");
            });
            if (found) { found.click(); return true; }
            return false;
        });

        if (!opened) {
            console.log("Attendance: Add people button not found");
            await dumpButtons(page, "inviteIntoMeeting");
            return false;
        }
        await sleep(2000);

        // Type the person's email in the "Enter name or email" input
        const input = await page.$('input[placeholder*="name or email" i]') ||
                      await page.$('input[placeholder*="email" i]') ||
                      await page.$('input[type="text"]') ||
                      await page.$('input[type="email"]');

        if (!input) {
            console.log("Attendance: Email input not found in Add people dialog");
            await screenshot_global("attendance-no-email-input");
            await page.keyboard.press("Escape");
            return false;
        }

        await input.click();
        await input.fill(email);
        await sleep(1500);

        // The suggestion list should show the person - click their checkbox or name
        const selected = await page.evaluate((targetEmail) => {
            // Look for checkbox or suggestion item matching the email
            const items = document.querySelectorAll('[role="option"], [role="listitem"], [data-email]');
            for (const item of items) {
                const text = (item.textContent || "").toLowerCase();
                if (text.includes(targetEmail.toLowerCase()) || text.includes(targetEmail.split("@")[0])) {
                    // Click the checkbox inside or the item itself
                    const checkbox = item.querySelector('input[type="checkbox"], [role="checkbox"]');
                    if (checkbox) { checkbox.click(); return "checkbox"; }
                    item.click();
                    return "item";
                }
            }
            // If no suggestion appeared, press Enter to add the typed email
            return "enter";
        }, email);

        if (selected === "enter") {
            await page.keyboard.press("Enter");
            console.log("Attendance: Pressed Enter to add email");
        } else {
            console.log("Attendance: Selected suggestion (" + selected + ")");
        }
        await sleep(1000);

        // Click "Send invite" or "Send email" button
        const invited = await page.evaluate(() => {
            const btns = Array.from(document.querySelectorAll("button, [role=button]"));
            const sendBtn = btns.find(b => {
                const text = (b.textContent || "").trim().toLowerCase();
                return text.includes("send") || text.includes("invite");
            });
            if (sendBtn) { sendBtn.click(); return true; }
            return false;
        });

        if (invited) {
            console.log("Attendance: Sent Google Meet invite to " + personName);
            await sleep(1000);
            await screenshot_global("attendance-invited-" + personName.toLowerCase());
            return true;
        } else {
            console.log("Attendance: Send/Invite button not found");
            await screenshot_global("attendance-no-send-btn");
            await page.keyboard.press("Escape");
            return false;
        }
    } catch (e) {
        console.log("Attendance: Invite failed for " + personName + ": " + e.message);
        try { await page.keyboard.press("Escape"); } catch (_) {}
        return false;
    }
}

/**
 * Process Gemini meeting notes after the meeting ends.
 * Searches the assistant's Gmail for the notes email, parses action items,
 * emails them to team members, and archives the email.
 */
async function processGeminiNotes(meetingTitle) {
    if (!meetingTitle) {
        console.log("Notes: No meeting title, skipping notes processing");
        return;
    }

    console.log("Notes: Waiting 2 minutes for Gemini to generate notes...");
    await sleep(120000);

    // Search for Gemini notes email
    const GOG_ACCOUNT = `--account ${shellEscape(config.assistant.email)}`;
    const searchCmd = `source "$HOME/.env" && gog gmail messages search ${shellEscape("from:gemini-notes@google.com subject:Notes newer_than:1h")} ${GOG_ACCOUNT} --include-body --json --max 5 --no-input`;

    let notesEmail = null;
    for (let attempt = 0; attempt < 3; attempt++) {
        try {
            const result = execSync(searchCmd, { shell: "/bin/bash", timeout: 30000, stdio: "pipe" }).toString();
            const data = JSON.parse(result);
            const messages = data.messages || [];

            // Match by meeting title (Gemini subjects look like: Notes: "meeting title" Feb 11, 2026)
            const titleLower = meetingTitle.toLowerCase();
            notesEmail = messages.find(m => {
                const subject = (m.subject || "").toLowerCase();
                return subject.includes(titleLower);
            });

            // If no exact match, take the most recent one from the last hour
            if (!notesEmail && messages.length > 0) {
                notesEmail = messages[0];
                console.log("Notes: No exact title match, using most recent: " + notesEmail.subject);
            }

            if (notesEmail) break;
        } catch (e) {
            console.log("Notes: Search attempt " + (attempt + 1) + " failed: " + e.message);
        }

        if (attempt < 2) {
            console.log("Notes: No notes email found yet, waiting 1 minute...");
            await sleep(60000);
        }
    }

    if (!notesEmail) {
        console.log("Notes: No Gemini notes email found after 3 attempts, skipping");
        return;
    }

    console.log("Notes: Found notes email: " + notesEmail.subject);
    const body = notesEmail.body || "";
    const threadId = notesEmail.threadId || notesEmail.id;

    // Parse action items from "Suggested next steps" section
    // The section ends at "Meeting records" or "You should review" or "Is the summary"
    const cleanBody = body.replace(/\r\n/g, "\n");
    const nextStepsIdx = cleanBody.toLowerCase().indexOf("suggested next steps");
    let nextStepsText = "";
    if (nextStepsIdx >= 0) {
        let rest = cleanBody.substring(nextStepsIdx + "suggested next steps".length).trim();
        // Cut off at known footer markers
        for (const marker of ["Meeting records", "You should review", "Is the summary"]) {
            const markerIdx = rest.indexOf(marker);
            if (markerIdx > 0) rest = rest.substring(0, markerIdx);
        }
        nextStepsText = rest.trim();
    }

    if (!nextStepsText || nextStepsText.toLowerCase().includes("no suggested next steps")) {
        console.log("Notes: No action items found, archiving email");
        archiveNotesEmail(threadId);
        return;
    }

    // Action items are separated by blank lines; each item may span multiple lines (word-wrapped)
    // Join wrapped lines, then split on blank lines
    const items = nextStepsText
        .split(/\n\s*\n/)                              // split on blank lines
        .map(block => block.replace(/\n/g, " ")        // join wrapped lines
            .replace(/^\s*[\*\-•]\s*/, "")             // remove bullet
            .replace(/\s+/g, " ")                      // normalize whitespace
            .trim())
        .filter(line => line.length > 10);

    console.log("Notes: Found " + items.length + " action item(s)");

    // Map action items to team members
    const memberItems = {};
    for (const item of items) {
        const itemLower = item.toLowerCase();
        for (const [email, info] of Object.entries(TEAM)) {
            const firstName = info.name.toLowerCase();
            if (itemLower.includes(firstName)) {
                if (!memberItems[email]) memberItems[email] = [];
                memberItems[email].push(item);
            }
        }
    }

    const membersWithItems = Object.keys(memberItems);
    if (membersWithItems.length === 0) {
        console.log("Notes: Action items found but none assigned to team members, archiving");
        archiveNotesEmail(threadId);
        return;
    }

    // Send email to each team member with their action items
    const today = new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    for (const [email, actions] of Object.entries(memberItems)) {
        const name = TEAM[email].name;
        const actionList = actions.map(a => "- " + a).join("\n");
        const emailBody = `Hi ${name},\n\nHere are your action items from "${meetingTitle}" (${today}):\n\n${actionList}\n\n-- ${config.assistant.name}`;
        const subject = `Action items from: ${meetingTitle}`;

        try {
            // Write body to temp file to avoid shell escaping issues
            const bodyFile = "/tmp/notes-email-body-" + name.toLowerCase() + ".txt";
            fs.writeFileSync(bodyFile, emailBody);
            const sendCmd = `source "$HOME/.env" && gog gmail send --to ${shellEscape(email)} --subject ${shellEscape(subject)} --body-file ${shellEscape(bodyFile)} ${GOG_ACCOUNT} --force --no-input`;
            execSync(sendCmd, { shell: "/bin/bash", timeout: 30000, stdio: "pipe" });
            console.log("Notes: Sent action items to " + name + " (" + email + ")");
            try { fs.unlinkSync(bodyFile); } catch (_) {}
        } catch (e) {
            console.log("Notes: Failed to email " + name + ": " + e.message);
        }
    }

    // Archive the notes email
    archiveNotesEmail(threadId);
    console.log("Notes: Processing complete");
}

/**
 * Archive a Gemini notes email (remove from inbox, mark as read, add processed label)
 */
function archiveNotesEmail(threadId) {
    try {
        const GOG_ACCOUNT = `--account ${shellEscape(config.assistant.email)}`;
        const archiveCmd = `source "$HOME/.env" && gog gmail thread modify ${shellEscape(threadId)} --remove INBOX,UNREAD --add ${shellEscape(config.assistant.name + "-Processed")} ${GOG_ACCOUNT} --force --no-input`;
        execSync(archiveCmd, { shell: "/bin/bash", timeout: 30000, stdio: "pipe" });
        console.log("Notes: Archived email (thread " + threadId + ")");
    } catch (e) {
        console.log("Notes: Failed to archive email: " + e.message);
    }
}

/**
 * Check if a team member name appears in the page text.
 * pageText is the full page innerText (lowercased) with People panel open.
 * We check for first name (e.g. "alice", "bob") which is unique enough.
 */
function isPresent(pageText, memberName) {
    if (typeof pageText !== "string") return false;
    const firstName = memberName.toLowerCase().split(" ")[0];
    return pageText.includes(firstName);
}

/**
 * Get expected attendees from metadata (only team members)
 */
function getExpectedAttendees() {
    if (!meetingMeta || !meetingMeta.attendees) return [];
    return meetingMeta.attendees
        .filter(a => TEAM[a.email])
        .map(a => ({
            email: a.email,
            name: TEAM[a.email].name,
            phone: TEAM[a.email].phone,
        }));
}

(async () => {
    let browser;
    let context;
    let page;

    async function screenshot(name) {
        try {
            const p = path.join(SCREENSHOT_DIR, "camofox-meet-" + name + ".png");
            await page.screenshot({ path: p });
            console.log("Screenshot: " + p);
        } catch (e) {
            console.log("Screenshot failed: " + e.message);
        }
    }
    screenshot_global = screenshot;

    try {
        console.log("Launching Camoufox browser...");
        const opts = await launchOptions({
            headless: true,
            os: "linux",
            humanize: true,
            enable_cache: true,
        });
        browser = await firefox.launch(opts);
        console.log("Browser launched");

        context = await browser.newContext({
            viewport: { width: 1920, height: 1080 },
            locale: "en-US",
        });

        if (fs.existsSync(COOKIES_PATH)) {
            const raw = JSON.parse(fs.readFileSync(COOKIES_PATH, "utf8"));
            const cookies = convertCookies(raw);
            await context.addCookies(cookies);
            console.log("Loaded " + cookies.length + " auth cookies");
        } else {
            console.log("WARNING: No cookies file found at " + COOKIES_PATH);
        }

        page = await context.newPage();

        console.log("Navigating to: " + MEETING_URL);
        await page.goto(MEETING_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
        await sleep(5000);

        const title = await page.title();
        console.log("Page loaded: " + title);
        await screenshot("1-loaded");

        const url = page.url();
        if (url.includes("accounts.google.com")) {
            console.log("ERROR: Redirected to Google login - cookies may be expired");
            await screenshot("error-login");
            process.exit(1);
        }

        console.log("Muting microphone and camera...");
        try {
            await page.keyboard.press("Control+e");
            await sleep(500);
            await page.keyboard.press("Control+d");
            await sleep(1000);
        } catch (e) {
            console.log("Keyboard mute: " + e.message);
        }

        try {
            const muteButtons = await page.$$('[data-is-muted="false"]');
            for (const btn of muteButtons) {
                await btn.click();
                await sleep(300);
            }
            if (muteButtons.length > 0) {
                console.log("Clicked " + muteButtons.length + " mute button(s)");
            }
        } catch (e) {}

        await screenshot("2-premute");

        // Click "Start" on Gemini note-taking before joining
        console.log("Enabling Gemini note-taking...");
        try {
            const sidebarClicked = await page.evaluate(() => {
                const allButtons = Array.from(document.querySelectorAll("button, [role=button]"));
                const startBtn = allButtons.find(b => {
                    const text = (b.textContent || "").trim();
                    return text === "Start" || text === "start";
                });
                if (startBtn) { startBtn.click(); return true; }
                return false;
            });

            if (sidebarClicked) {
                console.log("Clicked sidebar Start - waiting for confirmation dialog...");
                await sleep(2000);

                const dialogConfirmed = await page.evaluate(() => {
                    const allButtons = Array.from(document.querySelectorAll("button, [role=button]"));
                    const startButtons = allButtons.filter(b => {
                        const text = (b.textContent || "").trim();
                        return text === "Start" || text === "start";
                    });
                    if (startButtons.length > 0) {
                        startButtons[startButtons.length - 1].click();
                        return startButtons.length;
                    }
                    return 0;
                });

                if (dialogConfirmed) {
                    console.log("Confirmed Gemini note-taking (found " + dialogConfirmed + " Start buttons, clicked last)");
                    await sleep(2000);
                } else {
                    console.log("Gemini confirmation dialog Start button not found");
                }
            } else {
                console.log("Gemini note-taking not available on this meeting");
            }
        } catch (e) {
            console.log("Gemini note-taking: " + e.message);
        }
        await screenshot("2b-gemini");

        console.log("Looking for Join button...");
        let joined = false;

        try {
            await page.waitForFunction(() => {
                const buttons = Array.from(document.querySelectorAll("button, [role=button]"));
                return buttons.some(b =>
                    b.textContent.includes("Join now") ||
                    b.textContent.includes("Ask to join") ||
                    b.textContent.includes("Join") ||
                    (b.getAttribute("aria-label") || "").includes("Join")
                );
            }, { timeout: 30000 });

            await sleep(1000);

            joined = await page.evaluate(() => {
                const buttons = Array.from(document.querySelectorAll("button, [role=button]"));
                const joinNow = buttons.find(b => b.textContent.includes("Join now"));
                const askJoin = buttons.find(b => b.textContent.includes("Ask to join"));
                const anyJoin = buttons.find(b =>
                    b.textContent.includes("Join") ||
                    (b.getAttribute("aria-label") || "").includes("Join")
                );
                const btn = joinNow || askJoin || anyJoin;
                if (btn) { btn.click(); return true; }
                return false;
            });
        } catch (e) {
            console.log("Join button wait failed: " + e.message);
        }

        if (joined) {
            console.log("Clicked Join button");
            await sleep(5000);
            await screenshot("3-joined");

            // Verify Gemini note-taking is active after joining
            await sleep(5000);
            try {
                const geminiStatus = await page.evaluate(() => {
                    const els = Array.from(document.querySelectorAll("div[role=button], button"));
                    const taking = els.find(b => (b.textContent || "").includes("taking notes"));
                    const geminiActive = els.find(b => (b.textContent || "").includes("Gemini is taking"));
                    if (taking || geminiActive) return "active";
                    const startBtn = els.find(b => (b.textContent || "").includes("Start taking notes"));
                    if (startBtn) { startBtn.click(); return "started"; }
                    return "not-found";
                });
                if (geminiStatus === "active") {
                    console.log("Gemini is taking notes");
                } else if (geminiStatus === "started") {
                    console.log("Clicked Start taking notes (in-meeting)");
                    await sleep(2000);
                } else {
                    console.log("Gemini note-taking status unclear");
                }
            } catch (e) {
                console.log("Gemini check: " + e.message);
            }
            await screenshot("4-gemini-active");

            console.log("Meeting joined: " + MEETING_URL);
        } else {
            console.log("Could not find Join button");
            await screenshot("error-nojoin");
            process.exit(1);
        }

        console.log("Bot will stay in meeting. Press Ctrl+C to leave.");

        // --- Attendance monitoring setup ---
        const expectedAttendees = getExpectedAttendees();
        const meetingTitle = meetingMeta ? meetingMeta.title : "meeting";
        const meetingStartTime = meetingMeta && meetingMeta.startTime
            ? new Date(meetingMeta.startTime).getTime()
            : Date.now(); // fallback to now if no metadata

        const whatsappSent = {};   // email -> true (3 min reminder sent)
        const escalated = {};     // email -> true (5 min escalation done)
        let attendanceComplete = false;

        if (expectedAttendees.length > 0) {
            console.log("Attendance: Monitoring " + expectedAttendees.length + " team members: " +
                expectedAttendees.map(a => a.name).join(", "));
        } else {
            console.log("Attendance: No team members to monitor (no metadata or no team on invite)");
            attendanceComplete = true;
        }

        let stopping = false;
        process.on("SIGINT", () => { stopping = true; });
        process.on("SIGTERM", () => { stopping = true; });

        const MAX_DURATION_MS = 3 * 60 * 60 * 1000;
        const CHECK_INTERVAL_MS = 30 * 1000; // Check every 30s (was 60s) for better attendance timing
        const startTime = Date.now();

        while (!stopping && Date.now() - startTime < MAX_DURATION_MS) {
            await sleep(CHECK_INTERVAL_MS);

            const currentUrl = page.url();
            if (!currentUrl.includes("meet.google.com")) {
                console.log("Meeting ended (redirected away)");
                break;
            }

            const meetingEnded = await page.evaluate(() => {
                const text = document.body.innerText || "";
                return text.includes("You left the meeting") ||
                       text.includes("The meeting has ended") ||
                       text.includes("Return to home screen") ||
                       text.includes("Rejoin");
            }).catch(() => false);

            if (meetingEnded) {
                console.log("Meeting ended");
                break;
            }

            // --- Attendance checks ---
            if (!attendanceComplete && expectedAttendees.length > 0) {
                const elapsed = Date.now() - meetingStartTime;
                const elapsedMin = elapsed / 60000;

                // +3 minute check: send WhatsApp to missing team members
                if (elapsedMin >= 3 && Object.keys(whatsappSent).length === 0) {
                    console.log("Attendance: Running +3 minute check...");
                    const participants = await readParticipants(page);

                    for (const member of expectedAttendees) {
                        if (!isPresent(participants, member.name)) {
                            console.log("Attendance: " + member.name + " is MISSING at +3 min");
                            const msg = `Hey ${member.name}, you are 3 minutes late to ${meetingTitle}. Come on, everyone is waiting for you`;
                            sendWhatsApp(member.phone, msg);
                            whatsappSent[member.email] = true;
                        } else {
                            console.log("Attendance: " + member.name + " is present");
                        }
                    }

                    if (Object.keys(whatsappSent).length === 0) {
                        console.log("Attendance: Everyone is present at +3 min!");
                        attendanceComplete = true;
                    }
                }

                // +5 minute check: invite missing members + send urgent WhatsApp
                if (elapsedMin >= 5 && Object.keys(whatsappSent).length > 0 && Object.keys(escalated).length === 0) {
                    console.log("Attendance: Running +5 minute check...");
                    const participants = await readParticipants(page);

                    for (const member of expectedAttendees) {
                        // Only escalate people who were WhatsApp'd and still missing
                        if (whatsappSent[member.email] && !isPresent(participants, member.name)) {
                            console.log("Attendance: " + member.name + " STILL missing at +5 min - escalating");

                            // Call them via Twilio
                            await twilioCall(member.phone, member.name, meetingTitle);

                            // Send Google Meet invite notification
                            await inviteIntoMeeting(page, member.email, member.name);

                            // Also send urgent WhatsApp with link
                            const msg = `Hey ${member.name}, it's been 5 minutes! You need to join ${meetingTitle} NOW.\nLink: ${MEETING_URL}`;
                            sendWhatsApp(member.phone, msg);

                            escalated[member.email] = true;
                        } else if (whatsappSent[member.email]) {
                            console.log("Attendance: " + member.name + " joined after WhatsApp reminder");
                        }
                    }

                    attendanceComplete = true;
                    console.log("Attendance: Monitoring complete");
                }
            }
        }

        // Process Gemini meeting notes (search email, parse action items, distribute)
        if (meetingMeta) {
            try {
                await processGeminiNotes(meetingTitle);
            } catch (e) {
                console.log("Notes: Error processing notes: " + e.message);
            }
        }

        console.log("Leaving meeting...");

    } catch (error) {
        console.error("Error: " + error.message);
        if (page) await screenshot("error-fatal");
        process.exit(1);
    } finally {
        if (context) await context.close().catch(() => {});
        if (browser) await browser.close().catch(() => {});
        console.log("Browser closed");
    }
})();
