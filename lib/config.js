/**
 * GroundUp Toolkit - Shared Configuration Loader (Node.js)
 *
 * Usage:
 *   const { config } = require('../lib/config');
 *   config.assistant.name     // "Christina"
 *   config.team.members       // [{name, email, phone, ...}]
 *   config.getMemberByEmail("alice@yourco.com")
 */

const fs = require("fs");
const path = require("path");
const yaml = require("js-yaml");

const TOOLKIT_ROOT = process.env.TOOLKIT_ROOT ||
    path.dirname(path.dirname(path.resolve(__filename)));

// Load .env
function loadEnv() {
    const envPaths = [
        path.join(TOOLKIT_ROOT, ".env"),
        path.join(process.env.HOME || "/root", ".env"),
    ];
    for (const envPath of envPaths) {
        if (!fs.existsSync(envPath)) continue;
        const lines = fs.readFileSync(envPath, "utf8").split("\n");
        for (let line of lines) {
            line = line.trim().replace(/^export\s+/, "");
            if (!line || line.startsWith("#") || !line.includes("=")) continue;
            const eqIdx = line.indexOf("=");
            const key = line.substring(0, eqIdx);
            let val = line.substring(eqIdx + 1).replace(/^["']|["']$/g, "");
            if (!process.env[key]) process.env[key] = val;
        }
        break;
    }
}

// Load config.yaml
function loadConfig() {
    const configPath = process.env.TOOLKIT_CONFIG ||
        path.join(TOOLKIT_ROOT, "config.yaml");

    if (!fs.existsSync(configPath)) {
        throw new Error(
            `Config not found at ${configPath}. ` +
            `Copy config.example.yaml to config.yaml and fill in your values.`
        );
    }
    return yaml.load(fs.readFileSync(configPath, "utf8"), { schema: yaml.JSON_SCHEMA });
}

loadEnv();
const data = loadConfig();

const config = {
    ...data,

    getMemberByEmail(email) {
        return data.team.members.find(
            m => m.email.toLowerCase() === email.toLowerCase()
        ) || null;
    },

    getMemberByPhone(phone) {
        const norm = phone.replace(/[\s-]/g, "");
        return data.team.members.find(
            m => m.phone.replace(/[\s-]/g, "") === norm
        ) || null;
    },

    getMemberByName(name) {
        const lower = name.toLowerCase();
        return data.team.members.find(m => {
            const mName = m.name.toLowerCase();
            return mName === lower || mName.split(" ")[0] === lower;
        }) || null;
    },

    get teamEmails() {
        return data.team.members.map(m => m.email);
    },

    get teamPhoneMap() {
        const map = {};
        data.team.members.forEach(m => { map[m.phone] = m.email; });
        return map;
    },

    // Environment secrets
    get anthropicApiKey() { return process.env.ANTHROPIC_API_KEY || ""; },
    get matonApiKey() { return process.env.MATON_API_KEY || ""; },
    get gogKeyringPassword() { return process.env.GOG_KEYRING_PASSWORD || ""; },
    get twilioAccountSid() { return process.env.TWILIO_ACCOUNT_SID || ""; },
    get twilioApiKeySid() { return process.env.TWILIO_API_KEY_SID || ""; },
    get twilioApiKeySecret() { return process.env.TWILIO_API_KEY_SECRET || ""; },
    get twilioFromNumber() { return process.env.TWILIO_FROM_NUMBER || ""; },
};

module.exports = { config, TOOLKIT_ROOT };
