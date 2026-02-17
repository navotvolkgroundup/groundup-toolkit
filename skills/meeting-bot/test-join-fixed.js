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
        await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36');

        const context = browser.defaultBrowserContext();
        await context.overridePermissions('https://meet.google.com/xxx-xxxx-xxx', ['microphone', 'camera']);

        console.log('🌐 Navigating to Meet...');
        await page.goto('https://meet.google.com/xxx-xxxx-xxx', { waitUntil: 'networkidle2', timeout: 60000 });

        await sleep(5000);
        
        console.log('📸 Screenshot 1: Landing page');
        await page.screenshot({ path: '/tmp/meet-1-landing.png' });
        
        console.log('🚪 Looking for Join button...');
        const html = await page.content();
        console.log('Page title:', await page.title());
        
        // Try clicking join
        try {
            const clicked = await page.evaluate(() => {
                const buttons = Array.from(document.querySelectorAll('button, span, div[role=button]'));
                console.log('Found', buttons.length, 'buttons');
                
                for (const btn of buttons) {
                    const text = (btn.textContent || '').toLowerCase();
                    const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
                    
                    if (text.includes('join') || text.includes('ask to join') || aria.includes('join')) {
                        console.log('Clicking:', text || aria);
                        btn.click();
                        return true;
                    }
                }
                return false;
            });
            
            if (clicked) {
                console.log('✓ Clicked join button');
            } else {
                console.log('⚠️  No join button found, pressing Enter');
                await page.keyboard.press('Enter');
            }
        } catch (e) {
            console.log('Error clicking:', e.message);
            await page.keyboard.press('Enter');
        }

        await sleep(10000);
        console.log('📸 Screenshot 2: After join attempt');
        await page.screenshot({ path: '/tmp/meet-2-joined.png' });

        console.log('✅ Test complete! Staying for 20 seconds...');
        await sleep(20000);

        await browser.close();
        console.log('Done!');
    } catch (error) {
        console.error('❌ Error:', error.message);
    }
})();
