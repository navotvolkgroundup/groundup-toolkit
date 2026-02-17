const puppeteer = require('puppeteer');

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
        await context.overridePermissions('https://meet.google.com/xxx-xxxx-xxx', ['microphone', 'camera', 'notifications']);

        console.log('🌐 Navigating to Meet...');
        await page.goto('https://meet.google.com/xxx-xxxx-xxx', { waitUntil: 'networkidle2', timeout: 60000 });

        await page.waitForTimeout(5000);
        
        console.log('📸 Taking screenshot...');
        const path = require('path');
        await page.screenshot({ path: path.join(__dirname, 'meet-test.png') });
        console.log('✓ Screenshot saved');
        
        console.log('🎙️ Disabling camera/mic...');
        try {
            await page.evaluate(() => {
                const buttons = Array.from(document.querySelectorAll('button'));
                const micBtn = buttons.find(b => b.getAttribute('aria-label')?.toLowerCase().includes('microphone'));
                const camBtn = buttons.find(b => b.getAttribute('aria-label')?.toLowerCase().includes('camera'));
                if (micBtn) micBtn.click();
                if (camBtn) camBtn.click();
            });
        } catch (e) {
            console.log('Could not toggle mic/cam');
        }

        await page.waitForTimeout(2000);

        console.log('🚪 Looking for Join button...');
        await page.screenshot({ path: path.join(__dirname, 'meet-beforejoin.png') });
        
        // Try multiple methods to join
        let joined = false;
        
        // Method 1: Click button with text
        try {
            await page.evaluate(() => {
                const buttons = Array.from(document.querySelectorAll('button, span'));
                const joinBtn = buttons.find(b => {
                    const text = b.textContent?.toLowerCase() || '';
                    return text.includes('join') || text.includes('ask to join');
                });
                if (joinBtn) {
                    joinBtn.click();
                    console.log('Clicked join via text search');
                    return true;
                }
                return false;
            });
            joined = true;
        } catch (e) {}

        // Method 2: Press Enter
        if (!joined) {
            console.log('Trying Enter key...');
            await page.keyboard.press('Enter');
        }

        await page.waitForTimeout(10000);
        console.log('📸 Taking post-join screenshot...');
        await page.screenshot({ path: path.join(__dirname, 'meet-joined.png') });

        console.log('✅ Join attempt complete!');
        console.log('Check screenshots in ' + __dirname);
        
        // Keep browser open for 30 seconds
        console.log('Staying in meeting for 30 seconds...');
        await page.waitForTimeout(30000);

        await browser.close();
    } catch (error) {
        console.error('❌ Error:', error.message);
        console.error(error.stack);
    }
})();
