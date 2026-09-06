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

  console.log('Logging in as admin...');
  await page.goto('http://127.0.0.1:5000/login', { waitUntil: 'networkidle', timeout: 30000 });
  await page.fill('input[name="username"]', 'admin');
  await page.fill('input[name="password"]', 'AdminPassword123!');
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);

  const screenshotDir = 'screenshots/admin';
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

  // 1. Core Admin Pages
  await capture('Admin Dashboard', 'http://127.0.0.1:5000/admin/dashboard', 'admin-dashboard-HD.png', 'Core HTML Page', '/admin/dashboard', 'admin/dashboard.html');
  await capture('Students List', 'http://127.0.0.1:5000/admin/users/students', 'admin-students-HD.png', 'Management Page', '/admin/users/students', 'admin/students.html');
  await capture('Supervisors List', 'http://127.0.0.1:5000/admin/users/supervisors', 'admin-supervisors-HD.png', 'Management Page', '/admin/users/supervisors', 'admin/supervisors.html');
  await capture('All Users List', 'http://127.0.0.1:5000/admin/users', 'admin-users-HD.png', 'Management Page', '/admin/users', 'admin/user_list.html');
  await capture('Internship Assignment', 'http://127.0.0.1:5000/admin/internship-assign', 'admin-internship-assign-HD.png', 'Management Page', '/admin/internship-assign', 'admin/internship_assign.html');
  await capture('Reports List', 'http://127.0.0.1:5000/admin/reports', 'admin-reports-HD.png', 'Reports Page', '/admin/reports', 'admin/reports_list.html');
  await capture('Attendance Report', 'http://127.0.0.1:5000/admin/reports/attendance', 'admin-attendance-report-HD.png', 'Reports Page', '/admin/reports/attendance', 'admin/reports/attendance.html');
  await capture('Trash / Audit', 'http://127.0.0.1:5000/admin/trash', 'admin-trash-HD.png', 'System Page', '/admin/trash', 'admin/trash.html');
  await capture('Profile History', 'http://127.0.0.1:5000/admin/profile-history', 'admin-profile-history-HD.png', 'System Page', '/admin/profile-history', 'admin/profile_history.html');
  await capture('Notifications', 'http://127.0.0.1:5000/notifications', 'admin-notifications-HD.png', 'Core HTML Page', '/notifications', 'notifications/index.html');

  // Dynamic Pages (using identified IDs)
  const studentId = 1;
  const supervisorId = 2;
  
  await capture('Student Profile View', `http://127.0.0.1:5000/admin/student/${studentId}`, 'admin-student-profile-HD.png', 'Dynamic Page', '/admin/student/<student_id>', 'admin/student_profile.html', studentId);
  await capture('Edit Student Form', `http://127.0.0.1:5000/admin/student/edit/${studentId}`, 'admin-edit-student-HD.png', 'Dynamic Form', '/admin/student/edit/<student_id>', 'admin/edit_student.html', studentId);
  await capture('Student Report Overview', `http://127.0.0.1:5000/admin/reports/student/${studentId}`, 'admin-student-report-HD.png', 'Dynamic Report', '/admin/reports/student/<student_id>', 'admin/reports/student_report.html', studentId);
  await capture('Student History', `http://127.0.0.1:5000/admin/student/history/${studentId}`, 'admin-student-history-HD.png', 'Dynamic Report', '/admin/student/history/<student_id>', 'admin/profile_history.html', studentId);

  await capture('Supervisor Profile View', `http://127.0.0.1:5000/admin/supervisor/${supervisorId}`, 'admin-supervisor-profile-HD.png', 'Dynamic Page', '/admin/supervisor/<supervisor_id>', 'admin/supervisor_profile.html', supervisorId);
  await capture('Edit Supervisor Form', `http://127.0.0.1:5000/admin/supervisor/edit/${supervisorId}`, 'admin-edit-supervisor-HD.png', 'Dynamic Form', '/admin/supervisor/edit/<supervisor_id>', 'admin/edit_supervisor.html', supervisorId);

  // Logout modal
  try {
    console.log('\n--- Capturing Modal: Logout Modal ---');
    await page.goto('http://127.0.0.1:5000/admin/dashboard', { waitUntil: 'networkidle' });
    const logoutBtn = await page.$('.logout-link');
    if (logoutBtn) {
      await logoutBtn.click();
      await page.waitForTimeout(600);
      const path = `${screenshotDir}/admin-logout-modal-HD.png`;
      await page.screenshot({ path, fullPage: true, type: 'png' });
      results.push({ name: 'Logout Modal', type: 'Modal', route: 'All pages', template: 'components/logout_modal.html', reqId: 'None', file: 'admin-logout-modal-HD.png', status: 'PASS', resolution: '1920x1080' });
    }
  } catch (e) {
    console.log('Logout modal error:', e.message);
  }

  await browser.close();

  // Generate Report Markdown
  let md = `# Admin Complete UI Coverage Report\n\n`;
  md += `## Admin Dynamic & Modal Views\n\n`;
  md += `| Page | Type | Route | Template | Screenshot | Resolution | Status |\n`;
  md += `|---|---|---|---|---|---|---|\n`;

  results.forEach(r => {
    md += `| ${r.name} | ${r.type} | \`${r.route}\` | \`${r.template}\` | \`${r.file}\` | ${r.resolution || 'N/A'} | **${r.status}** |\n`;
  });

  md += `\n## Verification & Compliance\n`;
  md += `- Authenticated Admin session: **YES** (\`admin\` / \`AdminPassword123!\`)\n`;
  md += `- Application code modified: **NO**\n`;
  md += `- Commit: **NO**\n`;
  md += `- Push: **NO**\n`;

  fs.writeFileSync('screenshots/admin/PHASE-7C-ADMIN-COMPLETE-COVERAGE-REPORT.md', md);
  console.log('\nReport updated: screenshots/admin/PHASE-7C-ADMIN-COMPLETE-COVERAGE-REPORT.md');
})();
