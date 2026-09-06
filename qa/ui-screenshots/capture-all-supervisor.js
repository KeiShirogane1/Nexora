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

  console.log('Logging in as sup_cross_2da523...');
  await page.goto('http://127.0.0.1:5000/login', { waitUntil: 'networkidle', timeout: 30000 });
  await page.fill('input[name="username"]', 'sup_cross_2da523');
  await page.fill('input[name="password"]', 'pass12345');
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);

  const title = await page.title();
  if (title.includes('Login')) {
      console.log('Login failed!');
      process.exit(1);
  }
  console.log('Logged in successfully');

  const screenshotDir = 'screenshots/supervisor';
  if (!fs.existsSync(screenshotDir)) {
    fs.mkdirSync(screenshotDir, { recursive: true });
  }

  const results = [];

  async function capture(name, url, file, type, route, template, reqId = 'None') {
    console.log(`\n--- Capturing: ${name} (${type}) ---`);
    console.log(`URL: ${url}`);
    try {
      await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(1500);

      const title = await page.title();
      if (title.includes('Login') || title.includes('404')) {
        console.log(`SKIP/FAIL: ${name} (Title: ${title})`);
        results.push({ name, type, route, template, reqId, file, status: 'SKIPPED (Not found/redirect)' });
        return false;
      }

      const path = `${screenshotDir}/${file}`;
      await page.screenshot({ path, fullPage: true, type: 'png' });
      
      const dims = await page.evaluate(() => ({
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight
      }));
      console.log(`Saved: ${path} (${dims.width}x${dims.height})`);
      results.push({ name, type, route, template, reqId, file, status: 'PASS', resolution: `${dims.width}x${dims.height}` });
      return true;
    } catch (e) {
      console.log(`FAIL: ${name} - ${e.message}`);
      results.push({ name, type, route, template, reqId, file, status: 'FAIL', reason: e.message });
      return false;
    }
  }

  // 1. Core Supervisor Pages
  await capture('Dashboard', 'http://127.0.0.1:5000/supervisor/dashboard', 'supervisor-dashboard-HD.png', 'Core HTML Page', '/supervisor/dashboard', 'supervisor/dashboard.html');
  await capture('Assigned Interns', 'http://127.0.0.1:5000/supervisor/interns', 'supervisor-interns-HD.png', 'Core HTML Page', '/supervisor/interns', 'supervisor/interns.html');
  await capture('Supervisor Profile', 'http://127.0.0.1:5000/supervisor/profile', 'supervisor-profile-HD.png', 'Core HTML Page', '/supervisor/profile', 'supervisor/profile.html');
  await capture('Notifications', 'http://127.0.0.1:5000/notifications', 'supervisor-notifications-HD.png', 'Core HTML Page', '/notifications', 'notifications/index.html');
  await capture('My Classes', 'http://127.0.0.1:5000/supervisor/classes', 'supervisor-classes-HD.png', 'Class HTML Page', '/supervisor/classes', 'classroom/supervisor_classes.html');
  await capture('Create Class Form', 'http://127.0.0.1:5000/supervisor/classes/create', 'supervisor-create-class-HD.png', 'Class HTML Page', '/supervisor/classes/create', 'classroom/create_class.html');

  // 2. Class & Classwork pages using Class ID 100598
  const classId = 100598;

  await capture('Individual Class View', `http://127.0.0.1:5000/supervisor/classes/${classId}`, 'supervisor-class-view-HD.png', 'Class HTML Page', '/supervisor/classes/<class_id>', 'classroom/supervisor_class.html', classId);
  await capture('Classwork', `http://127.0.0.1:5000/supervisor/classes/${classId}/classwork`, 'supervisor-classwork-HD.png', 'Classwork Page', '/supervisor/classes/<class_id>/classwork', 'classwork/supervisor_classwork.html', classId);
  await capture('Gradebook', `http://127.0.0.1:5000/supervisor/classes/${classId}/gradebook`, 'supervisor-gradebook-HD.png', 'Gradebook Page', '/supervisor/classes/<class_id>/gradebook', 'classroom/supervisor_gradebook.html', classId);
  await capture('Performance / ML Insights', `http://127.0.0.1:5000/supervisor/classes/${classId}/performance`, 'supervisor-performance-HD.png', 'Performance Page', '/supervisor/classes/<class_id>/performance', 'classroom/supervisor_insights.html', classId);
  await capture('Class Reports', `http://127.0.0.1:5000/supervisor/classes/${classId}/reports`, 'supervisor-reports-HD.png', 'Reports Page', '/supervisor/classes/<class_id>/reports', 'classroom/supervisor_reports.html', classId);

  // Discover assignment ID from classwork page
  await page.goto(`http://127.0.0.1:5000/supervisor/classes/${classId}/classwork`, { waitUntil: 'networkidle' });
  const assignLink = await page.$('a[href*="/assignments/"], a[href*="/classwork/"]');
  let assignmentId = null;
  if (assignLink) {
    const href = await assignLink.getAttribute('href');
    const m = href.match(/\/(?:assignments|classwork)\/(\d+)/);
    if (m) assignmentId = m[1];
  }

  if (assignmentId) {
    await capture('Assignment Details', `http://127.0.0.1:5000/supervisor/classes/${classId}/assignments/${assignmentId}`, 'supervisor-assignment-view-HD.png', 'Assignment Page', '/supervisor/classes/<class_id>/assignments/<assignment_id>', 'classroom/supervisor_assignment.html', `${classId}, ${assignmentId}`);
    await capture('Assignment Submissions List', `http://127.0.0.1:5000/supervisor/classes/${classId}/classwork/${assignmentId}/submissions`, 'supervisor-assignment-submissions-HD.png', 'Submissions Page', '/supervisor/classes/<class_id>/classwork/<assignment_id>/submissions', 'classroom/supervisor_classwork_submissions.html', `${classId}, ${assignmentId}`);
    await capture('Import Scores Form', `http://127.0.0.1:5000/supervisor/classes/${classId}/classwork/${assignmentId}/import`, 'supervisor-import-scores-HD.png', 'Form Page', '/supervisor/classes/<class_id>/classwork/<assignment_id>/import', 'classroom/supervisor_classwork_import.html', `${classId}, ${assignmentId}`);
  }

  // Logout modal
  try {
    await page.goto('http://127.0.0.1:5000/supervisor/dashboard', { waitUntil: 'networkidle' });
    const logoutBtn = await page.$('.logout-link');
    if (logoutBtn) {
      await logoutBtn.click();
      await page.waitForTimeout(600);
      const path = `${screenshotDir}/supervisor-logout-modal-HD.png`;
      await page.screenshot({ path, fullPage: true, type: 'png' });
      results.push({ name: 'Logout Modal', type: 'Modal', route: 'All pages', template: 'components/logout_modal.html', reqId: 'None', file: 'supervisor-logout-modal-HD.png', status: 'PASS', resolution: '1920x1080' });
    }
  } catch (e) {
    console.log('Logout modal error:', e.message);
  }

  await browser.close();

  // Generate Comprehensive Report Markdown
  let md = `# Supervisor Complete UI Coverage Report\n\n`;
  md += `## HTML Pages & Dynamic HTML Pages\n\n`;
  md += `| Page | Type | Route | Template | Screenshot | Resolution | Status |\n`;
  md += `|---|---|---|---|---|---|---|\n`;

  results.forEach(r => {
    md += `| ${r.name} | ${r.type} | \`${r.route}\` | \`${r.template}\` | \`${r.file}\` | ${r.resolution || 'N/A'} | **${r.status}** |\n`;
  });

  md += `\n## Verification & Compliance\n`;
  md += `- Authenticated Supervisor session: **YES** (\`sup_cross_2da523\` / \`pass12345\`) | Class ID: 100598\n`;
  md += `- Application code modified: **NO**\n`;
  md += `- Commit: **NO**\n`;
  md += `- Push: **NO**\n`;

  fs.writeFileSync('screenshots/supervisor/PHASE-7B-SUPERVISOR-COMPLETE-COVERAGE-REPORT.md', md);
  console.log('\nReport updated: screenshots/supervisor/PHASE-7B-SUPERVISOR-COMPLETE-COVERAGE-REPORT.md');
})();
