"use strict";
/**
 * Shared JS configuration — reads from config.yaml (same source as lib/config.py).
 *
 * Usage:
 *   const { config, TOOLKIT_ROOT } = require("../../lib/config");
 *   config.assistant.name   // "Christina"
 *   config.team.members     // [{name, email, phone, ...}, ...]
 *   config.teamMembers      // backward-compat flat array with hubspotOwnerId
 */

const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

// Resolve toolkit root: TOOLKIT_ROOT env, or two levels up from this file
const TOOLKIT_ROOT = process.env.TOOLKIT_ROOT || path.resolve(__dirname, "..");

// Load .env file into process.env (same logic as config.py)
function loadEnv() {
    const envPaths = [
        path.join(TOOLKIT_ROOT, ".env"),
        path.join(process.env.HOME || "/root", ".env"),
    ];
    for (const envPath of envPaths) {
        if (fs.existsSync(envPath)) {
            const content = fs.readFileSync(envPath, "utf8");
            for (const line of content.split("\n")) {
                const trimmed = line.trim().replace(/^export\s+/, "");
                if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
                const eqIndex = trimmed.indexOf("=");
                const key = trimmed.substring(0, eqIndex).trim();
                let val = trimmed.substring(eqIndex + 1).trim();
                // Strip surrounding quotes
                if ((val.startsWith('"') && val.endsWith('"')) ||
                    (val.startsWith("'") && val.endsWith("'"))) {
                    val = val.slice(1, -1);
                }
                if (!(key in process.env)) {
                    process.env[key] = val;
                }
            }
            break;
        }
    }
}

// Load config.yaml via Python (avoids adding js-yaml dependency)
function loadYaml() {
    const configPaths = [
        process.env.TOOLKIT_CONFIG,
        path.join(TOOLKIT_ROOT, "config.yaml"),
    ].filter(Boolean);

    for (const configPath of configPaths) {
        if (fs.existsSync(configPath)) {
            try {
                // Security: use execFileSync to prevent shell injection via configPath
                const json = execFileSync("python3", [
                    "-c", "import yaml, json, sys; print(json.dumps(yaml.safe_load(open(sys.argv[1]))))",
                    configPath,
                ], { encoding: "utf8", timeout: 5000 }).trim();
                return JSON.parse(json);
            } catch (e) {
                console.error(`Failed to parse ${configPath}: ${e.message}`);
            }
        }
    }
    throw new Error(
        `Config not found. Copy config.example.yaml to ${path.join(TOOLKIT_ROOT, "config.yaml")} and fill in your values.`
    );
}

loadEnv();
const yamlConfig = loadYaml();

const config = {
    assistant: {
        name: yamlConfig.assistant.name,
        email: yamlConfig.assistant.email,
    },
    team: {
        domain: yamlConfig.team.domain,
        members: (yamlConfig.team.members || []).map(m => ({
            name: m.name,
            email: m.email,
            phone: m.phone,
            timezone: m.timezone,
            hubspot_owner_id: m.hubspot_owner_id || "",
            reminders_enabled: m.reminders_enabled !== false,
        })),
    },
    // Backward-compat flat array for christina-scheduler
    teamMembers: (yamlConfig.team.members || []).map(m => ({
        name: m.name,
        email: m.email,
        hubspotOwnerId: m.hubspot_owner_id || "",
        phoneNumber: m.phone,
    })),
    christinaEmail: yamlConfig.assistant.email,
    groundupDomain: `@${yamlConfig.team.domain}`,
    gogKeyringPassword: process.env.GOG_KEYRING_PASSWORD || "",
    anthropicApiKey: process.env.ANTHROPIC_API_KEY || "",
    matonApiKey: process.env.MATON_API_KEY || "",
    whatsappAccount: process.env.WHATSAPP_ACCOUNT || yamlConfig.assistant.whatsapp_account || "main",
};

exports.TOOLKIT_ROOT = TOOLKIT_ROOT;
exports.config = config;
