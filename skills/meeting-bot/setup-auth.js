const puppeteer = require('puppeteer');
const fs = require('fs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
    try {
        // NOTE: Email and password should be provided via environment variables
        // or config.yaml rather than hardcoded. See config.example.yaml.
        const BOT_EMAIL = process.env.BOT_EMAIL || 'assistant@yourcompany.com';
        console.log(`🔐 Authenticating as ${BOT_EMAIL}...`);
        
        const browser = await puppeteer.launch({
            headless: true,
            executablePath: '/usr/bin/chromium-browser',
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled'
            ]
        });

        const page = await browser.newPage();
        await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
        
        console.log('📱 Navigating to Google login...');
        await page.goto('https://accounts.google.com/signin/v2/identifier?service=wise&continue=https%3A%2F%2Fmeet.google.com', { 
            waitUntil: 'networkidle2',
            timeout: 60000 
        });
        
        await sleep(3000);
        await page.screenshot({ path: '/tmp/auth-1-login-page.png' });
        
        console.log('📧 Entering email...');
        // Type email
        await page.waitForSelector('input[type=email]', { timeout: 10000 });
        await page.type('input[type=email]', BOT_EMAIL, { delay: 100 });
        await sleep(1000);
        
        // Click Next
        await page.keyboard.press('Enter');
        console.log('✓ Email entered, waiting for password page...');
        
        await sleep(5000);
        await page.screenshot({ path: '/tmp/auth-2-password-page.png' });
        
        console.log('🔑 Entering password...');
        await page.waitForSelector('input[type=password]', { timeout: 15000 });
        await sleep(2000);
        const BOT_PASSWORD = process.env.BOT_PASSWORD || '';
        if (!BOT_PASSWORD) {
            console.error('ERROR: BOT_PASSWORD environment variable not set');
            process.exit(1);
        }
        await page.type('input[type=password]', BOT_PASSWORD, { delay: 100 });
        await sleep(1000);
        
        // Click Next/Sign in
        await page.keyboard.press('Enter');
        console.log('✓ Password entered, signing in...');
        
        // Wait for redirect or 2FA page
        await sleep(10000);
        await page.screenshot({ path: '/tmp/auth-3-after-login.png' });
        
        const url = page.url();
        console.log('Current URL:', url);
        
        if (url.includes('challenge') || url.includes('verify') || url.includes('2fa')) {
            console.log('⚠️  2FA/Verification required!');
            console.log('Check screenshot: /tmp/auth-3-after-login.png');
            console.log('You may need to approve this login on your device');
            console.log('Waiting 60 seconds for verification...');
            await sleep(60000);
            await page.screenshot({ path: '/tmp/auth-4-after-verification.png' });
        }
        
        // Navigate to Meet to ensure we're fully logged in
        console.log('🎥 Navigating to Google Meet...');
        await page.goto('https://meet.google.com/', { waitUntil: 'networkidle2', timeout: 60000 });
        await sleep(5000);
        await page.screenshot({ path: '/tmp/auth-5-meet-page.png' });
        
        console.log('💾 Saving authentication cookies...');
        const cookies = await page.cookies();
        const path = require('path');
        fs.writeFileSync(path.join(__dirname, 'google-cookies.json'), JSON.stringify(cookies, null, 2));
        
        console.log('✅ Authentication complete!');
        console.log('Cookies saved to: google-cookies.json');
        console.log('Total cookies:', cookies.length);
        
        await browser.close();
        
        console.log('');
        console.log('Next: Test joining a meeting with these cookies');
        
    } catch (error) {
        console.error('❌ Error:', error.message);
        console.error(error.stack);
        process.exit(1);
    }
})();
