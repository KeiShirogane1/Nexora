const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();

  // Log in
  await page.goto('http://127.0.0.1:5000/login', { waitUntil: 'networkidle', timeout: 60000 });
  await page.fill('input[name="username"]', 'student');
  await page.fill('input[name="password"]', 'intern_123');
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);

  // Go to dashboard
  await page.goto('http://127.0.0.1:5000/student/dashboard', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(2000);

  // Find all sidebar navigation links
  const links = await page.evaluate(() => {
    const results = [];
    document.querySelectorAll('a').forEach(a => {
      if (a.href && (a.href.includes('/student/') || a.href.includes('/profile') || a.href.includes('/account'))) {
        results.push({ href: a.href, text: a.innerText.trim(), title: a.title });
      }
    });
    return results;
  });

  console.log('Student navigation links:');
  links.forEach(l => console.log(`  ${l.text} -> ${l.href}`));

  // Also check for profile-specific links
  const profileLinks = links.filter(l => 
    l.text.toLowerCase().includes('profile') || 
    l.text.toLowerCase().includes('account') ||
    l.text.toLowerCase().includes('settings')
  );
  
  if (profileLinks.length > 0) {
    console.log('\nProfile-related links:');
    profileLinks.forEach(l => console.log(`  ${l.text} -> ${l.href}`));
  }

  await browser.close();
})();