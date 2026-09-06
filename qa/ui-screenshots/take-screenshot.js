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

  await page.goto('http://127.0.0.1:5000/student/dashboard', {
    waitUntil: 'networkidle',
    timeout: 60000
  });

  // Wait for fonts to load
  await page.evaluateHandle('document.fonts.ready');

  // Wait for images to load
  await page.waitForLoadState('networkidle');

  // Take full-page screenshot
  const screenshot = await page.screenshot({
    path: 'qa/ui-screenshots/test/student-dashboard-HD.png',
    fullPage: true,
    type: 'png'
  });

  const dimensions = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    height: document.documentElement.scrollHeight
  }));

  await browser.close();

  console.log('Screenshot path: qa/ui-screenshots/test/student-dashboard-HD.png');
  console.log(`Screenshot dimensions: ${dimensions.width} x ${dimensions.height} pixels`);
  console.log('Viewport dimensions: 1920 x 1080');
  console.log('Device scale factor: 2');
  console.log('Full-page: true');
  console.log('Screenshot successfully created: true');
})();