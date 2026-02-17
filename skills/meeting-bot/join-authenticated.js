const puppeteer = require('puppeteer');
const fs = require('fs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
    try {
        console.log('🚀 Launching authenticated session...');
        
        const browser = await puppeteer.launch({
            headless: true,
            executablePath: '/usr/bin/chromium-browser',
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--use-fake-ui-for-media-stream',
                '--use-fake-device-for-media-stream',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-gpu'
            ]
        });

        const page = await browser.newPage();
        await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');

        // Load saved cookies
        console.log('🍪 Loading authentication cookies...');
        const path = require('path');
        const cookies = JSON.parse(fs.readFileSync(path.join(__dirname, 'google-cookies.json'), 'utf8'));
        await page.setCookie(...cookies);
        console.log('✓ Loaded', cookies.length, 'cookies');

        const context = browser.defaultBrowserContext();
        await context.overridePermissions('https://meet.google.com/xxx-xxxx-xxx', ['microphone', 'camera', 'notifications']);

        console.log('🌐 Navigating to meeting...');
        await page.goto('https://meet.google.com/xxx-xxxx-xxx', { waitUntil: 'networkidle2', timeout: 60000 });

        await sleep(5000);
        await page.screenshot({ path: '/tmp/auth-meeting-1-landed.png' });
        
        const pageTitle = await page.title();
        console.log('Page title:', pageTitle);

        console.log('🎙️ Turning off camera and mic...');
        await page.evaluate(() => {
            const buttons = Array.from(document.querySelectorAll('[data-is-muted]'));
            buttons.forEach(b => {
                if (b.getAttribute('data-is-muted') === 'false') {
                    b.click();
                }
            });
        });

        await sleep(2000);

        console.log('🚪 Joining meeting...');
        const joined = await page.evaluate(() => {
            const buttons = Array.from(document.querySelectorAll('button, span, div[role=button]'));
            
            for (const btn of buttons) {
                const text = (btn.textContent || '').toLowerCase();
                const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
                
                if (text.includes('join') || text.includes('ask to join') || aria.includes('join now')) {
                    console.log('Clicking:', text || aria);
                    btn.click();
                    return true;
                }
            }
            return false;
        });

        if (!joined) {
            console.log('Trying Enter key...');
            await page.keyboard.press('Enter');
        }

        await sleep(10000);
        await page.screenshot({ path: '/tmp/auth-meeting-2-joined.png' });

        console.log('');
        console.log('✅ BOT JOINED (AUTHENTICATED)!');
        console.log('🎙️ Recording... staying for 2 hours');
        console.log('');
        
        // Stay in meeting
        await sleep(7200000);

        await browser.close();
    } catch (error) {
        console.error('❌ Error:', error.message);
    }
})();
