const { chromium } = require('playwright');
const fs = require('fs');

const INTERACTIONS_DIR = 'screenshots/student/interactions';

const PAGES = {
  dashboard: 'http://127.0.0.1:5000/student/dashboard',
  classes: 'http://127.0.0.1:5000/student/classes',
  logbook: 'http://127.0.0.1:5000/student/logbook',
  tasks: 'http://127.0.0.1:5000/student/tasks',
  documents: 'http://127.0.0.1:5000/student/documents',
  notifications: 'http://127.0.0.1:5000/notifications',
  profile: 'http://127.0.0.1:5000/student/profile',
};

const LOGIN_INDICATORS = ['input[name="username"]', 'input[name="password"]', 'button[type="submit"]'];

async function isLoginPage(page) {
  return await page.evaluate(() => {
    const hasUsername = document.querySelector('input[name="username"]') !== null;
    const hasPassword = document.querySelector('input[name="password"]') !== null;
    const hasSubmit = document.querySelector('button[type="submit"]') !== null;
    return hasUsername && hasPassword && hasSubmit && document.title.includes('Login');
  });
}

async function waitForPage(page, url) {
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForLoadState('networkidle');
  await page.evaluateHandle('document.fonts.ready');
  await page.waitForTimeout(1500);
  if (await isLoginPage(page)) throw new Error('Authentication required');
}

async function capture(page, path) {
  await page.screenshot({ path, fullPage: true, type: 'png' });
  const dims = await page.evaluate(() => ({ w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight }));
  console.log(`  ✓ ${path} (${dims.w}x${dims.h})`);
  return dims;
}

async function tryClick(page, selector, timeout = 3000) {
  try {
    await page.waitForSelector(selector, { timeout, state: 'visible' });
    await page.click(selector);
    await page.waitForTimeout(500);
    return true;
  } catch (e) {
    return false;
  }
}

async function tryFill(page, selector, value, timeout = 3000) {
  try {
    await page.waitForSelector(selector, { timeout, state: 'visible' });
    await page.fill(selector, value);
    await page.waitForTimeout(300);
    return true;
  } catch (e) {
    return false;
  }
}

async function run() {
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true
  });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();

  // Login
  console.log('=== LOGIN ===');
  await page.goto('http://127.0.0.1:5000/login', { waitUntil: 'networkidle', timeout: 60000 });
  await page.fill('input[name="username"]', 'student');
  await page.fill('input[name="password"]', 'intern_123');
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);
  console.log('Logged in ✓\n');

  const results = {
    attempted: 0,
    captured: 0,
    failed: 0,
    broken: 0,
    modals: 0,
    dropdowns: 0,
    searchStates: 0,
    filterStates: 0,
    sidebarStates: 0,
    screenshots: [],
    brokenInteractions: []
  };

  async function record(page, category, name, desc, fn) {
    results.attempted++;
    try {
      await fn();
      results.captured++;
      results.screenshots.push({ category, name, desc });
    } catch (e) {
      results.failed++;
      results.brokenInteractions.push({ page: category, element: name, expected: desc, actual: e.message });
      console.log(`  ✗ ${category}/${name}: ${e.message}`);
    }
  }

  // ==================== TASKS ====================
  console.log('=== TASKS ===');
  await waitForPage(page, PAGES.tasks);

  await record(page, 'tasks', 'normal', 'Normal tasks page', async () => {
    await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-normal.png`);
  });

  await record(page, 'tasks', 'search-focused', 'Search input focused', async () => {
    const sel = 'input[type="search"], input[placeholder*="search" i], input[name*="search" i]';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-search-focused.png`);
      results.searchStates++;
    } else throw new Error('Search input not found');
  });

  await record(page, 'tasks', 'search-with-text', 'Search with text', async () => {
    const sel = 'input[type="search"], input[placeholder*="search" i], input[name*="search" i]';
    if (await tryFill(page, sel, 'test')) {
      await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-search-text.png`);
      results.searchStates++;
    } else throw new Error('Search input not found');
  });

  await record(page, 'tasks', 'filter-opened', 'Filter dropdown opened', async () => {
    const sel = 'button:has-text("Filter"), select[name*="filter" i], button[aria-label*="filter" i]';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-filter-opened.png`);
      results.filterStates++;
    } else throw new Error('Filter control not found');
  });

  await record(page, 'tasks', 'filter-selected', 'Filter option selected', async () => {
    const sel = 'option, [role="option"], .dropdown-item';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-filter-selected.png`);
      results.filterStates++;
    } else throw new Error('Filter option not found');
  });

  await record(page, 'tasks', 'task-menu-opened', 'Task action menu opened', async () => {
    const sel = 'button[aria-label*="menu" i], button[aria-label*="action" i], .dropdown-toggle, .task-menu, [data-bs-toggle="dropdown"]';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-menu-opened.png`);
      results.dropdowns++;
    } else throw new Error('Task menu not found');
  });

  await record(page, 'tasks', 'task-details', 'Task details view', async () => {
    const sel = 'a[href*="task"], button:has-text("View"), button:has-text("Details"), .task-title a';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-details.png`);
    } else throw new Error('Task details link not found');
  });

  await record(page, 'tasks', 'submission-ui', 'Submission UI', async () => {
    const sel = 'button:has-text("Submit"), a:has-text("Submit"), button:has-text("Upload")';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-submission.png`);
    } else throw new Error('Submission UI not found');
  });

  await record(page, 'tasks', 'confirmation-modal', 'Confirmation modal', async () => {
    const sel = 'button:has-text("Delete"), button:has-text("Remove"), button:has-text("Confirm")';
    if (await tryClick(page, sel)) {
      await page.waitForTimeout(300);
      await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-confirm-modal.png`);
      results.modals++;
      await page.keyboard.press('Escape');
    } else throw new Error('Confirmation trigger not found');
  });

  await record(page, 'tasks', 'success-toast', 'Success toast/alert', async () => {
    const sel = '.toast, .alert-success, .toast-success, [role="alert"]';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-success-toast.png`);
    } else throw new Error('Success toast not visible');
  });

  await record(page, 'tasks', 'error-validation', 'Error/validation state', async () => {
    const sel = '.alert-danger, .text-danger, .error, .invalid-feedback, [aria-invalid="true"]';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-error.png`);
    } else throw new Error('Error state not visible');
  });

  await record(page, 'tasks', 'empty-state', 'Empty state', async () => {
    const sel = '.empty-state, .no-data, :has-text("No tasks"), :has-text("empty")';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/tasks/tasks-empty.png`);
    } else throw new Error('Empty state not visible');
  });

  // ==================== DOCUMENTS ====================
  console.log('\n=== DOCUMENTS ===');
  await waitForPage(page, PAGES.documents);

  await record(page, 'documents', 'normal', 'Normal documents page', async () => {
    await capture(page, `${INTERACTIONS_DIR}/documents/documents-normal.png`);
  });

  await record(page, 'documents', 'upload-ui', 'Upload UI visible', async () => {
    const sel = 'input[type="file"], button:has-text("Upload"), a:has-text("Upload")';
    if (await page.$(sel)) {
      await capture(page, `${INTERACTIONS_DIR}/documents/documents-upload-ui.png`);
    } else throw new Error('Upload UI not found');
  });

  await record(page, 'documents', 'upload-modal', 'Upload modal opened', async () => {
    const sel = 'button:has-text("Upload"), a:has-text("Upload"), button[data-bs-target*="upload" i]';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/documents/documents-upload-modal.png`);
      results.modals++;
      await page.keyboard.press('Escape');
    } else throw new Error('Upload modal trigger not found');
  });

  await record(page, 'documents', 'file-picker', 'File picker/upload state', async () => {
    const sel = 'input[type="file"]';
    const input = await page.$(sel);
    if (input) {
      await capture(page, `${INTERACTIONS_DIR}/documents/documents-file-picker.png`);
    } else throw new Error('File input not found');
  });

  await record(page, 'documents', 'validation-error', 'Validation error', async () => {
    const sel = '.alert-danger, .text-danger, .error, .invalid-feedback';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/documents/documents-validation-error.png`);
    } else throw new Error('Validation error not visible');
  });

  await record(page, 'documents', 'upload-success', 'Upload success state', async () => {
    const sel = '.alert-success, .toast-success, .toast:has-text("success" i)';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/documents/documents-upload-success.png`);
    } else throw new Error('Success state not visible');
  });

  await record(page, 'documents', 'action-menu', 'Document action menu', async () => {
    const sel = 'button[aria-label*="menu" i], [data-bs-toggle="dropdown"], .dropdown-toggle';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/documents/documents-action-menu.png`);
      results.dropdowns++;
      await page.keyboard.press('Escape');
    } else throw new Error('Action menu not found');
  });

  await record(page, 'documents', 'delete-modal', 'Delete confirmation modal', async () => {
    const sel = 'button:has-text("Delete"), button:has-text("Remove")';
    if (await tryClick(page, sel)) {
      await page.waitForTimeout(300);
      await capture(page, `${INTERACTIONS_DIR}/documents/documents-delete-modal.png`);
      results.modals++;
      await page.keyboard.press('Escape');
    } else throw new Error('Delete button not found');
  });

  await record(page, 'documents', 'empty-state', 'Empty documents state', async () => {
    const sel = '.empty-state, .no-data, :has-text("No documents"), :has-text("empty")';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/documents/documents-empty.png`);
    } else throw new Error('Empty state not visible');
  });

  // ==================== LOGBOOK ====================
  console.log('\n=== LOGBOOK ===');
  await waitForPage(page, PAGES.logbook);

  await record(page, 'logbook', 'normal', 'Normal logbook page', async () => {
    await capture(page, `${INTERACTIONS_DIR}/logbook/logbook-normal.png`);
  });

  await record(page, 'logbook', 'add-log-ui', 'Add/edit log UI', async () => {
    const sel = 'button:has-text("Add"), button:has-text("New"), a:has-text("Add"), button:has-text("Create")';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/logbook/logbook-add-ui.png`);
    } else throw new Error('Add log button not found');
  });

  await record(page, 'logbook', 'edit-modal', 'Edit log modal/page', async () => {
    const sel = 'button:has-text("Edit"), a:has-text("Edit"), button[aria-label*="edit" i]';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/logbook/logbook-edit-modal.png`);
      results.modals++;
      await page.keyboard.press('Escape');
    } else throw new Error('Edit button not found');
  });

  await record(page, 'logbook', 'date-calendar', 'Date/calendar interaction', async () => {
    const sel = 'input[type="date"], input[type="datetime-local"], .datepicker, [data-datepicker]';
    if (await page.$(sel)) {
      await capture(page, `${INTERACTIONS_DIR}/logbook/logbook-date-picker.png`);
    } else throw new Error('Date picker not found');
  });

  await record(page, 'logbook', 'session-details', 'Session details view', async () => {
    const sel = 'a:has-text("View"), button:has-text("View"), .log-entry a';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/logbook/logbook-session-details.png`);
    } else throw new Error('Session details not found');
  });

  await record(page, 'logbook', 'validation-state', 'Validation state', async () => {
    const sel = '.alert-danger, .text-danger, .error, .invalid-feedback';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/logbook/logbook-validation.png`);
    } else throw new Error('Validation state not visible');
  });

  await record(page, 'logbook', 'success-error', 'Success/error state', async () => {
    const sel = '.alert-success, .alert-danger, .toast-success, .toast-error';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/logbook/logbook-success-error.png`);
    } else throw new Error('Success/error state not visible');
  });

  // ==================== PROFILE ====================
  console.log('\n=== PROFILE ===');
  await waitForPage(page, PAGES.profile);

  await record(page, 'profile', 'normal', 'Normal profile page', async () => {
    await capture(page, `${INTERACTIONS_DIR}/profile/profile-normal.png`);
  });

  await record(page, 'profile', 'edit-mode', 'Profile edit mode', async () => {
    const sel = 'button:has-text("Edit"), a:has-text("Edit"), button[aria-label*="edit" i]';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/profile/profile-edit.png`);
    } else throw new Error('Edit button not found');
  });

  await record(page, 'profile', 'editable-form', 'Editable form fields', async () => {
    const sel = 'input:not([readonly]):not([disabled]), textarea:not([readonly]), select:not([disabled])';
    const inputs = await page.$$(sel);
    if (inputs.length > 0) {
      await capture(page, `${INTERACTIONS_DIR}/profile/profile-form.png`);
    } else throw new Error('No editable fields found');
  });

  await record(page, 'profile', 'validation', 'Validation state', async () => {
    const sel = '.alert-danger, .text-danger, .error, .invalid-feedback, [aria-invalid="true"]';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/profile/profile-validation.png`);
    } else throw new Error('Validation state not visible');
  });

  await record(page, 'profile', 'save-success', 'Save success', async () => {
    const sel = '.alert-success, .toast-success, :has-text("saved" i), :has-text("updated" i)';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/profile/profile-save-success.png`);
    } else throw new Error('Save success not visible');
  });

  await record(page, 'profile', 'save-error', 'Save error', async () => {
    const sel = '.alert-danger, .toast-error, :has-text("error" i), :has-text("failed" i)';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/profile/profile-save-error.png`);
    } else throw new Error('Save error not visible');
  });

  await record(page, 'profile', 'profile-menu', 'Profile/user menu dropdown', async () => {
    const sel = 'button[aria-label*="user" i], button[aria-label*="profile" i], .user-menu, .dropdown-toggle:has-text("Profile")';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/profile/profile-menu.png`);
      results.dropdowns++;
      await page.keyboard.press('Escape');
    } else throw new Error('Profile menu not found');
  });

  // ==================== CLASSES ====================
  console.log('\n=== CLASSES ===');
  await waitForPage(page, PAGES.classes);

  await record(page, 'classes', 'normal', 'Normal classes page', async () => {
    await capture(page, `${INTERACTIONS_DIR}/classes/classes-normal.png`);
  });

  await record(page, 'classes', 'card-interaction', 'Class card interaction', async () => {
    const sel = '.class-card, .card:has-text("Class"), [data-class-id]';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/classes/classes-card-interaction.png`);
    } else throw new Error('Class card not found');
  });

  await record(page, 'classes', 'class-details', 'Class details', async () => {
    const sel = 'a[href*="class"], button:has-text("View"), .class-title a';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/classes/classes-details.png`);
    } else throw new Error('Class details link not found');
  });

  await record(page, 'classes', 'join-ui', 'Join class UI', async () => {
    const sel = 'button:has-text("Join"), a:has-text("Join"), button:has-text("Enroll")';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/classes/classes-join-ui.png`);
    } else throw new Error('Join class UI not found');
  });

  await record(page, 'classes', 'join-modal', 'Join class modal', async () => {
    const sel = 'button[data-bs-target*="join" i], button:has-text("Join Class")';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/classes/classes-join-modal.png`);
      results.modals++;
      await page.keyboard.press('Escape');
    } else throw new Error('Join modal trigger not found');
  });

  await record(page, 'classes', 'validation', 'Validation/error', async () => {
    const sel = '.alert-danger, .text-danger, .error, .invalid-feedback';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/classes/classes-validation.png`);
    } else throw new Error('Validation not visible');
  });

  await record(page, 'classes', 'success', 'Join success', async () => {
    const sel = '.alert-success, .toast-success, :has-text("joined" i), :has-text("enrolled" i)';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/classes/classes-success.png`);
    } else throw new Error('Success state not visible');
  });

  await record(page, 'classes', 'empty', 'Empty classes state', async () => {
    const sel = '.empty-state, .no-data, :has-text("No classes"), :has-text("empty")';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/classes/classes-empty.png`);
    } else throw new Error('Empty state not visible');
  });

  // ==================== NOTIFICATIONS ====================
  console.log('\n=== NOTIFICATIONS ===');
  await waitForPage(page, PAGES.notifications);

  await record(page, 'notifications', 'normal', 'Normal notifications page', async () => {
    await capture(page, `${INTERACTIONS_DIR}/notifications/notifications-normal.png`);
  });

  await record(page, 'notifications', 'notification-opened', 'Notification opened', async () => {
    const sel = '.notification-item a, .notification a, button:has-text("View"), a[href*="notification"]';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/notifications/notifications-opened.png`);
    } else throw new Error('Notification link not found');
  });

  await record(page, 'notifications', 'notification-menu', 'Notification action menu', async () => {
    const sel = '.notification-item [data-bs-toggle="dropdown"], .notification-item button[aria-label*="menu" i]';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/notifications/notifications-menu.png`);
      results.dropdowns++;
      await page.keyboard.press('Escape');
    } else throw new Error('Notification menu not found');
  });

  await record(page, 'notifications', 'unread-state', 'Unread notification', async () => {
    const sel = '.unread, .notification-unread, [data-unread="true"], .badge:has-text("unread" i)';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/notifications/notifications-unread.png`);
    } else throw new Error('Unread state not visible');
  });

  await record(page, 'notifications', 'mark-read', 'Mark as read interaction', async () => {
    const sel = 'button:has-text("Mark as read"), button:has-text("Read"), button[aria-label*="read" i]';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/notifications/notifications-mark-read.png`);
    } else throw new Error('Mark read button not found');
  });

  await record(page, 'notifications', 'empty', 'Empty notifications', async () => {
    const sel = '.empty-state, .no-data, :has-text("No notifications"), :has-text("empty")';
    const found = await page.$(sel);
    if (found) {
      await capture(page, `${INTERACTIONS_DIR}/notifications/notifications-empty.png`);
    } else throw new Error('Empty state not visible');
  });

  // ==================== NAVIGATION ====================
  console.log('\n=== NAVIGATION / SIDEBAR ===');
  
  for (const [key, url] of Object.entries(PAGES)) {
    await waitForPage(page, url);
    await record(page, 'navigation', `active-${key}`, `Sidebar active ${key}`, async () => {
      await capture(page, `${INTERACTIONS_DIR}/navigation/sidebar-active-${key}.png`);
      results.sidebarStates++;
    });
  }

  await record(page, 'navigation', 'sidebar-expanded', 'Sidebar expanded (default)', async () => {
    await waitForPage(page, PAGES.dashboard);
    await capture(page, `${INTERACTIONS_DIR}/navigation/sidebar-expanded.png`);
    results.sidebarStates++;
  });

  await record(page, 'navigation', 'sidebar-collapsed', 'Sidebar collapsed', async () => {
    const sel = 'button[aria-label*="collapse" i], button[aria-label*="toggle" i], .sidebar-toggle, .navbar-toggler';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/navigation/sidebar-collapsed.png`);
      results.sidebarStates++;
      await tryClick(page, sel); // expand back
    } else throw new Error('Sidebar toggle not found');
  });

  await record(page, 'navigation', 'search-focused', 'Global search focused', async () => {
    const sel = 'input[type="search"], input[placeholder*="search" i], .global-search input';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/navigation/search-focused.png`);
      results.searchStates++;
    } else throw new Error('Global search not found');
  });

  await record(page, 'navigation', 'notifications-dropdown', 'Notification dropdown', async () => {
    const sel = 'button[aria-label*="notification" i], .notification-bell, [data-bs-target*="notification" i]';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/navigation/notifications-dropdown.png`);
      results.dropdowns++;
      results.modals++;
      await page.keyboard.press('Escape');
    } else throw new Error('Notification dropdown not found');
  });

  await record(page, 'navigation', 'profile-menu', 'Profile/user menu', async () => {
    const sel = 'button[aria-label*="user" i], .user-menu-toggle, .dropdown-toggle:has(img)';
    if (await tryClick(page, sel)) {
      await capture(page, `${INTERACTIONS_DIR}/navigation/profile-menu.png`);
      results.dropdowns++;
      await page.keyboard.press('Escape');
    } else throw new Error('Profile menu not found');
  });

  await browser.close();

  // Final Report
  console.log('\n===========================================');
  console.log('PHASE 2 STUDENT INTERACTIVE UI SCREENSHOT REPORT');
  console.log('===========================================');
  console.log(`Total interactive states attempted: ${results.attempted}`);
  console.log(`Total successfully captured: ${results.captured}`);
  console.log(`Total failed: ${results.failed}`);
  console.log(`Total broken interactions: ${results.broken}`);
  console.log(`Total modals captured: ${results.modals}`);
  console.log(`Total dropdowns captured: ${results.dropdowns}`);
  console.log(`Total search states: ${results.searchStates}`);
  console.log(`Total filter states: ${results.filterStates}`);
  console.log(`Total sidebar states: ${results.sidebarStates}`);
  console.log('\n--- Generated Screenshots ---');
  results.screenshots.forEach(s => console.log(`  screenshots/student/interactions/${s.category}/${s.name}.png`));
  console.log('\n--- Broken Interactions ---');
  if (results.brokenInteractions.length === 0) {
    console.log('  None');
  } else {
    results.brokenInteractions.forEach(b => {
      console.log(`  BROKEN INTERACTION:`);
      console.log(`    Page: ${b.page}`);
      console.log(`    Element: ${b.element}`);
      console.log(`    Expected: ${b.expected}`);
      console.log(`    Actual: ${b.actual}`);
    });
  }
}

run().catch(console.error);