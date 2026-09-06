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

  const results = {};

  // 1. Profile - P0 regression check
  console.log('=== PROFILE P0 CHECK ===');
  await page.goto('http://127.0.0.1:5000/student/profile', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(2000);
  const profileTitle = await page.title();
  const profileContent = await page.content();
  results.profileP0 = {
    title: profileTitle,
    hasSqlError: profileContent.includes('sqlite3.OperationalError') || profileContent.includes('ambiguous column'),
    hasProfileData: profileContent.includes('Profile') || profileContent.includes('profile'),
    hasCompletion: profileContent.includes('Profile Completion') || profileContent.includes('profile_completion')
  };
  console.log('Profile P0:', results.profileP0);

  // 2. Sidebar navigation check
  console.log('\n=== SIDEBAR NAVIGATION ===');
  const navLinks = await page.evaluate(() => {
    const links = document.querySelectorAll('.nx-nav a');
    return Array.from(links).map(a => ({ href: a.href, text: a.innerText.trim(), active: a.classList.contains('active') }));
  });
  results.sidebarNav = navLinks;
  console.log('Sidebar links:', navLinks.map(l => l.text + (l.active ? ' (active)' : '')));

  // 3. Sidebar collapse check
  console.log('\n=== SIDEBAR COLLAPSE ===');
  const collapseBtn = await page.$('.nx-collapse-toggle');
  if (collapseBtn) {
    await collapseBtn.click();
    await page.waitForTimeout(500);
    const isCollapsed = await page.evaluate(() => document.querySelector('.nx-sidebar')?.classList.contains('nx-collapsed'));
    results.sidebarCollapse = isCollapsed;
    console.log('Sidebar collapsed:', isCollapsed);
    // Expand back
    await collapseBtn.click();
    await page.waitForTimeout(500);
  } else {
    results.sidebarCollapse = false;
    console.log('Collapse button not found');
  }

  // 4. Topbar check
  console.log('\n=== TOPBAR ===');
  const topbar = await page.$('.student-tasks-topbar, .student-global-topbar, .nx-top, .classes-top');
  results.topbar = !!topbar;
  console.log('Topbar present:', !!topbar);

  // 5. Tasks tabs check
  console.log('\n=== TASKS TABS ===');
  await page.goto('http://127.0.0.1:5000/student/tasks', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(1500);
  const tabs = await page.$$('.student-tasks-tab');
  results.tasksTabs = tabs.length;
  console.log('Task tabs found:', tabs.length);

  // 6. Join Class modal check
  console.log('\n=== JOIN CLASS MODAL ===');
  await page.goto('http://127.0.0.1:5000/student/classes', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(1500);
  const joinBtn = await page.$('a[href*="join_class"], button:has-text("Join")');
  if (joinBtn) {
    await joinBtn.click();
    await page.waitForTimeout(1000);
    const modal = await page.$('.modal, .modal-dialog, [role="dialog"], .join-modal');
    results.joinModal = !!modal;
    console.log('Join modal opened:', !!modal);
    if (modal) await page.keyboard.press('Escape');
  } else {
    results.joinModal = 'no-trigger';
    console.log('Join button not found');
  }

  // 7. Upload Document modal check
  console.log('\n=== UPLOAD DOCUMENT ===');
  await page.goto('http://127.0.0.1:5000/student/documents', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(1500);
  const uploadInput = await page.$('input[type="file"]');
  results.uploadInput = !!uploadInput;
  console.log('File input present:', !!uploadInput);

  // 8. Logbook entry check
  console.log('\n=== LOGBOOK ENTRY ===');
  await page.goto('http://127.0.0.1:5000/student/logbook', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(1500);
  const logForm = await page.$('.student-logbook-new-entry, form[action*="/log/add"]');
  results.logbookEntry = !!logForm;
  console.log('Log entry form present:', !!logForm);

  // 9. Profile cropper check
  console.log('\n=== PROFILE CROPPER ===');
  await page.goto('http://127.0.0.1:5000/student/profile', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(1500);
  const cropperScript = await page.evaluate(() => typeof Cropper !== 'undefined');
  const avatarBtn = await page.$('.profile-avatar-button, button[onclick*="profileUpload"]');
  results.cropper = { scriptLoaded: cropperScript, avatarButton: !!avatarBtn };
  console.log('Cropper script loaded:', cropperScript, 'Avatar button:', !!avatarBtn);

  // 10. Notifications mark-read
  console.log('\n=== NOTIFICATIONS MARK READ ===');
  await page.goto('http://127.0.0.1:5000/notifications', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(1500);
  const markAllBtn = await page.$('button[onclick*="markAllNotificationsRead"]');
  results.markAllRead = !!markAllBtn;
  console.log('Mark all as read button:', !!markAllBtn);

  await browser.close();

  console.log('\n=== SUMMARY ===');
  console.log(JSON.stringify(results, null, 2));
})();