const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');

// Add stealth plugin
puppeteer.use(StealthPlugin());

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
    try {
        console.log('🥷 Launching STEALTH browser...');

        const browser = await puppeteer.launch({
            headless: true,
            executablePath: '/usr/bin/chromium-browser',
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--window-size=1920,1080',
                '--use-fake-ui-for-media-stream',
                '--use-fake-device-for-media-stream',
                '--disable-infobars',
                '--disable-session-crashed-bubble',
                '--disable-notifications',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-popup-blocking'
            ],
            ignoreDefaultArgs: ['--enable-automation']
        });

        const page = await browser.newPage();
        await page.setViewport({ width: 1920, height: 1080 });

        console.log('🍪 Loading auth cookies...');
        const path = require('path');
        const cookies = JSON.parse(fs.readFileSync(path.join(__dirname, 'google-cookies.json'), 'utf8'));
        await page.setCookie(...cookies);
        console.log('✓ Loaded', cookies.length, 'cookies');

        await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36');

        const context = browser.defaultBrowserContext();
        await context.overridePermissions('https://meet.google.com', ['microphone', 'camera', 'notifications']);

        // Extra stealth
        await page.evaluateOnNewDocument(() => {
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        });

        console.log('🌐 Navigating to meeting...');
        await page.goto('https://meet.google.com/xxx-xxxx-xxx', {
            waitUntil: 'networkidle0',
            timeout: 60000
        });

        await sleep(10000);
        await page.screenshot({ path: '/tmp/stealth-1-landed.png' });
        console.log('Page:', await page.title());

        console.log('🎙️ Toggling media...');
        try {
            await page.evaluate(() => {
                const buttons = Array.from(document.querySelectorAll('[data-is-muted="false"]'));
                buttons.forEach(b => b.click());
            });
        } catch (e) {}

        await sleep(3000);

        console.log('🚪 Waiting for Join button...');
        await page.waitForFunction(() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            return buttons.some(b => b.textContent && b.textContent.includes('Join now'));
        }, { timeout: 15000 });

        console.log('✓ Found Join button');

        const clicked = await page.evaluate(() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const joinBtn = buttons.find(b => b.textContent && b.textContent.includes('Join now'));
            if (joinBtn) {
                joinBtn.click();
                return true;
            }
            return false;
        });

        console.log('✓ Clicked:', clicked);

        await sleep(20000);
        await page.screenshot({ path: '/tmp/stealth-2-after-join.png' });

        const inMeeting = await page.evaluate(() => {
            const text = document.body.innerText.toLowerCase();
            return text.includes('leave call') || text.includes('end call');
        });

        console.log('');
        if (inMeeting) {
            console.log('✅ SUCCESS! IN MEETING!');
        } else {
            console.log('⚠️ Status unclear');
        }
        console.log('🎙️ Staying 2 hours...');
        console.log('');

        await sleep(7200000);
        await browser.close();

    } catch (error) {
        console.error('❌ Error:', error.message);
    }
})();
