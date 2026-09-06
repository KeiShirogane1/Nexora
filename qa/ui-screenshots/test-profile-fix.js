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

  // Go to profile
  await page.goto('http://127.0.0.1:5000/student/profile', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(2000);

  const title = await page.title();
  const content = await page.content();
  
  console.log('Title:', title);
  console.log('Has SQLite error:', content.includes('sqlite3.OperationalError') || content.includes('ambiguous column'));
  console.log('Has Profile content:', content.includes('Profile') || content.includes('profile'));
  
  if (content.includes('sqlite3.OperationalError') || content.includes('ambiguous column')) {
    console.log('FAIL: SQLite error still present');
    process.exit(1);
  } else if (title.includes('Profile') || content.includes('Profile')) {
    console.log('SUCCESS: Profile page loads without SQLite error');
  } else {
    console.log('UNKNOWN: Page loaded but unclear if correct');
    console.log('Content preview:', content.substring(0, 500));
  }

  await browser.close();
})();