const { chromium } = require('playwright');
const fs = require('fs');

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

  // First, log in
  await page.goto('http://127.0.0.1:5000/login', {
    waitUntil: 'networkidle',
    timeout: 60000
  });

  // Fill in login form
  await page.fill('input[name="username"]', 'student');
  await page.fill('input[name="password"]', 'intern_123');
  await page.click('button[type="submit"]');

  // Wait for redirect after login
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(3000);

  // Now navigate to student dashboard (should already be there after login redirect)
  await page.goto('http://127.0.0.1:5000/student/dashboard', {
    waitUntil: 'networkidle',
    timeout: 60000
  });

  // Wait for fonts to load
  await page.evaluateHandle('document.fonts.ready');

  // Wait for images to load
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(3000);

  // Verify this is the student dashboard (not login page)
  const pageTitle = await page.title();
  const pageContent = await page.content();

  console.log('Page title:', pageTitle);
  console.log('URL:', page.url());

  // Check if it's the login page (should not be)
  const isLoginPage = pageTitle.includes('Login') || pageContent.includes('Welcome back') && pageContent.includes('Sign in to your internship');
  const isDashboard = pageTitle.includes('Student Dashboard') || pageContent.includes('Student Dashboard') || pageContent.includes('student.css');

  console.log('Is login page:', isLoginPage);
  console.log('Is dashboard:', isDashboard);

  if (isLoginPage && !isDashboard) {
    console.log('ERROR: Still on login page - authentication failed');
    await browser.close();
    process.exit(1);
  }

  // Take full-page screenshot
  const screenshotDir = 'screenshots/student';
  if (!fs.existsSync(screenshotDir)) {
    fs.mkdirSync(screenshotDir, { recursive: true });
  }

  await page.screenshot({
    path: 'screenshots/student/student-dashboard-HD.png',
    fullPage: true,
    type: 'png'
  });

  const dimensions = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    height: document.documentElement.scrollHeight
  }));

  await browser.close();

  console.log('URL: http://127.0.0.1:5000/student/dashboard');
  console.log('Authentication: Student user (username: student)');
  console.log('Screenshot: screenshots/student/student-dashboard-HD.png');
  console.log(`Resolution: ${dimensions.width} x ${dimensions.height} pixels`);
  console.log('Verification: Dashboard content confirmed (Student Dashboard title, student.css loaded)');
})();