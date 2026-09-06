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

  // 1. Student function states capture
  console.log('Capturing student function states...');
  await page.goto('http://127.0.0.1:5000/login', { waitUntil: 'networkidle' });
  await page.fill('input[name="username"]', 'student');
  await page.fill('input[name="password"]', 'intern_123');
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');

  // Sidebar collapsed state
  await page.goto('http://127.0.0.1:5000/student/dashboard', { waitUntil: 'networkidle' });
  const collapseBtn = await page.$('.nx-collapse-toggle, .sidebar-toggle, button[aria-label="Toggle sidebar"]');
  if (collapseBtn) {
    await collapseBtn.click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: 'screenshots/student/interactions/navigation/sidebar-collapsed-state-HD.png', fullPage: true });
  }

  // Logbook Add Entry disabled state (when no active session)
  // Let's check logbook page
  await page.goto('http://127.0.0.1:5000/student/logbook', { waitUntil: 'networkidle' });
  await page.screenshot({ path: 'screenshots/student/interactions/logbook/logbook-add-entry-state-HD.png', fullPage: true });

  // 2. Supervisor function states capture
  console.log('Capturing supervisor function states...');
  await page.goto('http://127.0.0.1:5000/login', { waitUntil: 'networkidle' });
  await page.fill('input[name="username"]', 'sup_cross_2da523');
  await page.fill('input[name="password"]', 'pass12345');
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');

  await page.goto('http://127.0.0.1:5000/supervisor/classes', { waitUntil: 'networkidle' });
  await page.screenshot({ path: 'screenshots/supervisor/supervisor-classes-state-HD.png', fullPage: true });

  // 3. Admin function states capture
  console.log('Capturing admin function states...');
  await page.goto('http://127.0.0.1:5000/login', { waitUntil: 'networkidle' });
  await page.fill('input[name="username"]', 'admin');
  await page.fill('input[name="password"]', 'AdminPassword123!');
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');

  await page.goto('http://127.0.0.1:5000/admin/trash', { waitUntil: 'networkidle' });
  await page.screenshot({ path: 'screenshots/admin/admin-trash-state-HD.png', fullPage: true });

  await browser.close();
  console.log('Additional function state screenshots captured.');
})();
