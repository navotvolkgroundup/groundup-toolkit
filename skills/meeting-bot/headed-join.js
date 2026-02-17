const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');

puppeteer.use(StealthPlugin());

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
    try {
        console.log('🌐 Launching HEADED browser (real browser mode)...');

        const browser = await puppeteer.launch({
            headless: false,  // <- REAL BROWSER MODE
            executablePath: '/usr/bin/chromium-browser',
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--window-size=1920,1080',
                '--use-fake-ui-for-media-stream',
                '--use-fake-device-for-media-stream',
                '--disable-infobars',
                '--disable-session-crashed-bubble',
                '--disable-notifications',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-popup-blocking',
                '--start-maximized',
                '--enable-features=NetworkService,NetworkServiceInProcess'
            ],
            ignoreDefaultArgs: ['--enable-automation'],
            defaultViewport: null
        });

        const page = await browser.newPage();

        console.log('🍪 Loading auth cookies...');
        const path = require('path');
        const cookies = JSON.parse(fs.readFileSync(path.join(__dirname, 'google-cookies.json'), 'utf8'));
        await page.setCookie(...cookies);
        console.log('✓ Loaded', cookies.length, 'cookies');

        await page.setUserAgent('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36');

        const context = browser.defaultBrowserContext();
        await context.overridePermissions('https://meet.google.com', ['microphone', 'camera', 'notifications']);

        // Extra stealth
        await page.evaluateOnNewDocument(() => {
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };

            // More realistic properties
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
        });

        console.log('🌐 Navigating to meeting: https://meet.google.com/xxx-xxxx-xxx');
        await page.goto('https://meet.google.com/xxx-xxxx-xxx', {
            waitUntil: 'networkidle2',
            timeout: 60000
        });

        await sleep(8000);
        await page.screenshot({ path: '/tmp/headed-1-landed.png' });
        console.log('📸 Page:', await page.title());

        console.log('🎙️ Toggling media off...');
        try {
            await page.evaluate(() => {
                const buttons = Array.from(document.querySelectorAll('[data-is-muted="false"]'));
                buttons.forEach(b => b.click());
            });
            await sleep(2000);
        } catch (e) {
            console.log('  ⚠️ Could not toggle media:', e.message);
        }

        console.log('🚪 Looking for Join button...');

        // Wait longer and be more patient
        await page.waitForFunction(() => {
            const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
            return buttons.some(b =>
                b.textContent.includes('Join') ||
                b.textContent.includes('Ask to join') ||
                b.getAttribute('aria-label')?.includes('Join')
            );
        }, { timeout: 30000 });

        await sleep(3000);

        console.log('✓ Found Join button, clicking...');
        const clicked = await page.evaluate(() => {
            const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
            const joinButton = buttons.find(b =>
                b.textContent.includes('Join') ||
                b.textContent.includes('Ask to join') ||
                b.getAttribute('aria-label')?.includes('Join')
            );

            if (joinButton) {
                joinButton.click();
                return true;
            }
            return false;
        });

        console.log('✓ Clicked:', clicked);

        await sleep(10000);
        await page.screenshot({ path: '/tmp/headed-2-after-join.png' });

        // Check if we're in the meeting
        const inMeeting = await page.evaluate(() => {
            return !document.body.textContent.includes('There is a problem connecting');
        });

        if (inMeeting) {
            console.log('✅ Successfully joined meeting!');
            console.log('🎥 Bot is now in the call');
        } else {
            console.log('⚠️ Status unclear - checking...');
            const errorMsg = await page.evaluate(() => document.body.textContent);
            if (errorMsg.includes('problem connecting')) {
                console.log('❌ Connection error occurred');
            }
        }

        console.log('🎙️ Staying in meeting for 2 hours...');
        await sleep(7200000); // 2 hours

        console.log('👋 Leaving meeting after 2 hours');
        await browser.close();

    } catch (error) {
        console.error('❌ Error:', error.message);
        process.exit(1);
    }
})();
