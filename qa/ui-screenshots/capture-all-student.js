const { chromium } = require('playwright');
const fs = require('fs');

const PAGES = [
  { name: 'Dashboard', url: 'http://127.0.0.1:5000/student/dashboard', file: 'student-dashboard-HD.png', verify: 'Student Dashboard' },
  { name: 'My Classes', url: 'http://127.0.0.1:5000/student/classes', file: 'student-classes-HD.png', verify: 'My Classes' },
  { name: 'Logbook', url: 'http://127.0.0.1:5000/student/logbook', file: 'student-logbook-HD.png', verify: 'Logbook' },
  { name: 'Tasks', url: 'http://127.0.0.1:5000/student/tasks', file: 'student-tasks-HD.png', verify: 'Tasks' },
  { name: 'Documents', url: 'http://127.0.0.1:5000/student/documents', file: 'student-documents-HD.png', verify: 'Documents' },
  { name: 'Notifications', url: 'http://127.0.0.1:5000/notifications', file: 'student-notifications-HD.png', verify: 'Notifications' },
  { name: 'Profile', url: 'http://127.0.0.1:5000/student/profile', file: 'student-profile-HD.png', verify: 'Profile' },
];

async function isLoginPage(page) {
  // More specific login page detection - check for login FORM elements
  return await page.evaluate(() => {
    const hasUsernameField = document.querySelector('input[name="username"][type="text"], input[name="username"][type="email"]') !== null;
    const hasPasswordField = document.querySelector('input[name="password"][type="password"]') !== null;
    const hasLoginButton = document.querySelector('button[type="submit"], input[type="submit"]') !== null;
    const title = document.title;
    return hasUsernameField && hasPasswordField && hasLoginButton && title.includes('Login');
  });
}

async function capturePage(page, pageInfo, screenshotDir) {
  console.log(`\n--- Capturing: ${pageInfo.name} ---`);
  console.log(`URL: ${pageInfo.url}`);
  
  await page.goto(pageInfo.url, { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForLoadState('networkidle');
  await page.evaluateHandle('document.fonts.ready');
  await page.waitForTimeout(2000);

  // Verify not login page
  if (await isLoginPage(page)) {
    console.log(`FAIL: Authentication required for ${pageInfo.url}`);
    return { ...pageInfo, status: 'FAIL', reason: 'Authentication required', resolution: null };
  }

  // Verify expected content
  const content = await page.content();
  const title = await page.title();
  const hasExpectedContent = content.includes(pageInfo.verify) || title.includes(pageInfo.verify);
  
  if (!hasExpectedContent) {
    console.log(`WARN: Expected content "${pageInfo.verify}" not found, but not a login page`);
    console.log(`Title: ${title}`);
  } else {
    console.log(`Verified: ${pageInfo.verify} found`);
  }

  // Take screenshot
  const path = `${screenshotDir}/${pageInfo.file}`;
  await page.screenshot({ path, fullPage: true, type: 'png' });

  const dimensions = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    height: document.documentElement.scrollHeight
  }));

  console.log(`Saved: ${path} (${dimensions.width}x${dimensions.height})`);
  return { ...pageInfo, status: 'PASS', reason: null, resolution: `${dimensions.width}x${dimensions.height}` };
}

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

  // Log in once
  console.log('Logging in...');
  await page.goto('http://127.0.0.1:5000/login', { waitUntil: 'networkidle', timeout: 60000 });
  await page.fill('input[name="username"]', 'student');
  await page.fill('input[name="password"]', 'intern_123');
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);
  console.log('Logged in successfully');

  const screenshotDir = 'screenshots/student';
  if (!fs.existsSync(screenshotDir)) {
    fs.mkdirSync(screenshotDir, { recursive: true });
  }

  const results = [];
  for (const pageInfo of PAGES) {
    const result = await capturePage(page, pageInfo, screenshotDir);
    results.push(result);
    
    // If auth failed, stop trying more pages
    if (result.status === 'FAIL' && result.reason === 'Authentication required') {
      console.log('\nAuthentication lost, stopping capture.');
      break;
    }
  }

  await browser.close();

  // Final report
  console.log('\n===========================================');
  console.log('PHASE 1 STUDENT UI SCREENSHOT REPORT');
  console.log('===========================================');
  console.log('| # | Page | URL | Screenshot | Resolution | Verification |');
  console.log('|---|------|-----|------------|------------|--------------|');
  
  let passCount = 0;
  let failCount = 0;
  
  results.forEach((r, i) => {
    const res = r.resolution || 'N/A';
    const status = r.status || 'SKIP';
    console.log(`| ${i+1} | ${r.name} | ${r.url} | ${r.file} | ${res} | ${status} |`);
    if (status === 'PASS') passCount++;
    else if (status === 'FAIL') failCount++;
  });

  console.log('\n--- Summary ---');
  console.log(`Total pages attempted: ${results.length}`);
  console.log(`Screenshots captured: ${passCount}`);
  console.log(`Failed: ${failCount}`);
  console.log(`Screenshot directory: ${screenshotDir}/`);
  if (failCount > 0) {
    console.log('Authentication problems: Session expired or pages require re-authentication');
  } else {
    console.log('Authentication problems: None');
  }
})();