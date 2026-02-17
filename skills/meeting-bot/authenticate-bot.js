const puppeteer = require('puppeteer');
const fs = require('fs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
    try {
        // NOTE: Email should be provided via environment variable or config.yaml
        const BOT_EMAIL = process.env.BOT_EMAIL || 'assistant@yourcompany.com';
        console.log(`🔐 Setting up Google authentication for ${BOT_EMAIL}...`);
        
        const browser = await puppeteer.launch({
            headless: false,  // Run visible so we can see what's happening
            executablePath: '/usr/bin/chromium-browser',
            // NOTE: --no-sandbox required when running as root. URL validation in
            // join-meeting + camofox-join.js mitigates SSRF risk. Long-term: use Docker.
            args: ['--no-sandbox', '--disable-setuid-sandbox']
        });

        const page = await browser.newPage();
        
        console.log('📱 Navigating to Google Meet...');
        await page.goto('https://meet.google.com/', { waitUntil: 'networkidle2' });
        
        console.log('⏳ Waiting for you to login...');
        console.log('');
        console.log('INSTRUCTIONS:');
        console.log('1. The browser window should open (headless=false)');
        console.log(`2. Login as ${BOT_EMAIL}`);
        console.log('3. Complete any 2FA if needed');
        console.log('4. Once logged in, wait 10 seconds');
        console.log('5. Press Ctrl+C in this terminal when done');
        console.log('');
        
        // Wait for user to login (5 minutes max)
        await sleep(300000);
        
        console.log('💾 Saving cookies...');
        const cookies = await page.cookies();
        const path = require('path');
        const cookiesPath = path.join(__dirname, 'google-cookies.json');
        fs.writeFileSync(cookiesPath, JSON.stringify(cookies, null, 2), { mode: 0o600 });

        console.log('✅ Authentication saved!');
        console.log('Cookies saved to: ' + cookiesPath);
        
        await browser.close();
    } catch (error) {
        console.error('❌ Error:', error.message);
    }
})();
