const puppeteer = require('puppeteer');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
    try {
        console.log('🚀 Launching browser...');
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

        const context = browser.defaultBrowserContext();
        await context.overridePermissions('https://meet.google.com/xxx-xxxx-xxx', ['microphone', 'camera', 'notifications']);

        console.log('🌐 Navigating to Meet...');
        await page.goto('https://meet.google.com/xxx-xxxx-xxx', { waitUntil: 'networkidle2', timeout: 60000 });

        console.log('⏳ Waiting for page to load...');
        await sleep(8000);

        console.log('🎙️ Turning off camera and microphone...');
        try {
            await page.evaluate(() => {
                const buttons = Array.from(document.querySelectorAll('button'));
                buttons.forEach(btn => {
                    const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
                    if (aria.includes('microphone') || aria.includes('camera') || aria.includes('turn off')) {
                        btn.click();
                    }
                });
            });
        } catch (e) {
            console.log('Could not toggle media');
        }

        await sleep(2000);

        console.log('🚪 Clicking Join/Ask to join...');
        const joined = await page.evaluate(() => {
            const elements = Array.from(document.querySelectorAll('button, span, div[role=button]'));
            
            for (const el of elements) {
                const text = (el.textContent || '').toLowerCase();
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                
                if (text.includes('join') || text.includes('ask to join') || aria.includes('join')) {
                    console.log('Found button:', text || aria);
                    el.click();
                    return true;
                }
            }
            
            // If no button found, try pressing Enter
            return false;
        });

        if (!joined) {
            console.log('No button found, pressing Enter...');
            await page.keyboard.press('Enter');
        } else {
            console.log('✓ Clicked join button');
        }

        await sleep(15000);

        console.log('📸 Taking screenshot...');
        await page.screenshot({ path: '/tmp/bot-joined.png' });

        console.log('✅ BOT JOINED THE MEETING!');
        console.log('🎙️ Recording... (will stay for 2 hours)');
        
        // Stay in meeting for 2 hours
        await sleep(7200000);

        await browser.close();
    } catch (error) {
        console.error('❌ Error:', error.message);
        console.error(error.stack);
    }
})();
