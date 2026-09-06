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
  console.log('Before login - Title:', await page.title());
  
  await page.fill('input[name="username"]', 'student');
  await page.fill('input[name="password"]', 'intern_123');
  await page.click('button[type="submit"]');
  
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(3000);
  
  console.log('After login - URL:', page.url());
  console.log('After login - Title:', await page.title());
  
  const content = await page.content();
  console.log('Content preview:', content.substring(0, 500));
  
  // Check for login indicators
  const indicators = ['Welcome back', 'Username or email', 'Password', 'Login', 'Nexora - Login'];
  indicators.forEach(ind => {
    if (content.includes(ind)) console.log(`FOUND: "${ind}"`);
  });

  await browser.close();
})();