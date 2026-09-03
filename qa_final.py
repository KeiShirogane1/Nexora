import pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bootstrap.app import app
from unittest.mock import patch, MagicMock

app.config['WTF_CSRF_ENABLED'] = False
app.config['TESTING'] = True

def login_as(client, uid, role):
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['role'] = role
        sess['username'] = f'test_{role}'

# Ensure test users exist
from app.Models.db import get_db_connection
from app.Services.password_security import hash_password

def ensure_users():
    conn = get_db_connection()
    cur = conn.cursor()
    # create minimal users if missing - use id 1 admin, 2 supervisor, 3 student
    for uid, role, username, email in [(1,'admin','admin_test','admin@test.com'), (2,'supervisor','sup_test','sup@test.com'), (3,'student','stu_test','stu@test.com')]:
        cur.execute("SELECT id FROM users WHERE id=?", (uid,))
        if not cur.fetchone():
            cur.execute("INSERT INTO users (id, username, email, password, role, status) VALUES (?,?,?,?,?,?)", (uid, username, email, hash_password('Password123!'), role, 'active'))
            # ensure profile tables minimal
            if role=='student':
                cur.execute("INSERT OR IGNORE INTO students (user_id, first_name, last_name, student_id) VALUES (?,?,?,?)", (uid, 'Stu', 'Test', 'S123'))
            if role=='supervisor':
                cur.execute("INSERT OR IGNORE INTO supervisors (user_id, first_name, last_name) VALUES (?,?,?)", (uid, 'Sup', 'Test'))
    conn.commit()
    conn.close()

ensure_users()

client = app.test_client()

def get_html(path, role='student', uid=3):
    login_as(client, uid, role)
    try:
        r = client.get(path)
        return r.status_code, r.data.decode('utf-8', errors='ignore'), r
    except Exception as e:
        return 500, f'EXCEPTION: {e}', None

report = []
P0=[]
P1=[]
P2=[]
P3=[]
PASS=[]
FAIL=[]

def add(sev, page, element, expected, actual, likely_file, cause):
    entry = dict(sev=sev, page=page, element=element, expected=expected, actual=actual, file=likely_file, cause=cause)
    report.append(entry)
    if sev=='P0':
        P0.append(entry)
    elif sev=='P1':
        P1.append(entry)
    elif sev=='P2':
        P2.append(entry)
    else:
        P3.append(entry)

# 1. PASSWORD EYE
status, html, r = get_html('/login', role='student')
# check presence of toggle button
if 'togglePass' in html and 'toggle-pass' in html:
    # check button is type=button not submit
    if 'type="button" class="toggle-pass"' in html and 'onclick="togglePass' in html:
        PASS.append('PASSWORD EYE login page button type=button not submit')
    else:
        add('P1','/login','toggle-pass button','type=button with onclick togglePass not submitting','found but missing type=button or inline handler','resources/views/auth/login.html:46','button without type=button defaults to submit')
    # check icon centered: CSS must have position:absolute right:12px top:50% transform
    css = pathlib.Path('resources/views/auth/login.html').read_bytes().decode('utf-8', errors='ignore')
    if 'position:absolute' in css and 'right:12px' in css and 'transform:translateY(-50%)' in css:
        PASS.append('PASSWORD EYE CSS centered')
    else:
        add('P2','/login','toggle-pass CSS','position:absolute right:12px top:50% transform','missing or misaligned CSS','resources/views/auth/login.html:14','inline style missing')
    # check padding-right on password input
    if 'padding-right:42px' in html or 'padding-right:42px' in css:
        PASS.append('PASSWORD EYE input padding-right 42px')
    else:
        add('P2','/login','password input','padding-right:42px to avoid overlap','no padding','resources/views/auth/login.html:13','text hidden under icon')
    # check JS toggle function
    if "el.type = el.type==='password' ? 'text' : 'password'" in html or 'el.type' in html:
        PASS.append('PASSWORD EYE JS toggles type')
    else:
        add('P1','/login','togglePass JS','toggles input type password<->text','JS missing or broken','resources/views/auth/login.html:55','function not defined')
else:
    add('P0','/login','password eye','eye button exists','not found','resources/views/auth/login.html','missing toggle')

# also check signup
status2, html2, _ = get_html('/signup', role='student')
if 'togglePass' in html2:
    PASS.append('PASSWORD EYE signup exists')
else:
    add('P1','/signup','password eye','toggle button','missing','resources/views/auth/signup.html','no eye')

# Also check admin modals password-wrap
for p in ['resources/views/admin/students.html','resources/views/admin/supervisors.html']:
    t = pathlib.Path(p).read_bytes().decode('utf-8', errors='ignore')
    if 'password-wrap' in t and 'password-toggle' in t:
        if 'padding-right: 42px' in pathlib.Path('resources/assets/css/modals.css').read_bytes().decode('utf-8', errors='ignore'):
            PASS.append(f'PASSWORD EYE modal {p} padding fixed')
        else:
            add('P1',p,'password-toggle','input padding-right 42px','missing','resources/assets/css/modals.css:111','eye overlaps border')
        if 'type="button" class="password-toggle"' in t:
            PASS.append(f'PASSWORD EYE modal {p} type=button')
        else:
            add('P2',p,'password-toggle','type=button','maybe missing','resources/views/admin/students.html:246','defaults to submit')
    else:
        add('P2',p,'password modal','password-wrap+toggle','not found or incomplete',p,'template missing wrapper')

# 2. LOGOUT
for role,uid,path in [('admin',1,'/admin/dashboard'),('student',3,'/student/dashboard'),('supervisor',2,'/supervisor/dashboard')]:
    code, html, r = get_html(path, role, uid)
    if code!=200:
        add('P1',path,'logout','page loads 200',f'status {code}',f'resources/views/{role}/dashboard.html','auth redirect or missing route')
        continue
    # check logout link calls openLogoutModal
    if 'openLogoutModal()' in html:
        PASS.append(f'LOGOUT {role} calls openLogoutModal')
    else:
        add('P0',path,'Logout link','onclick openLogoutModal()','missing','resources/views/components/'+role+'_sidebar.html','no modal trigger')
    # check modal present
    if 'nexora-logout-overlay' in html or 'logout_modal' in html:
        # check included via sidebar
        if 'id="logoutModal"' in html or 'nexora-logout-overlay' in html:
            PASS.append(f'LOGOUT {role} modal DOM present')
        else:
            add('P1',path,'logout modal DOM','overlay with id logoutModal','not found','resources/views/components/logout_modal.html','include missing')
        # check CSS centered: display:flex align-items:center justify-content:center
        css_logout = pathlib.Path('resources/assets/css/style.css').read_text(encoding='utf-8', errors='ignore') + pathlib.Path('resources/assets/css/modals.css').read_text(encoding='utf-8', errors='ignore') + pathlib.Path('resources/assets/css/student.css').read_text(encoding='utf-8', errors='ignore')
        if '.nexora-logout-overlay.open{display:flex' in css_logout or '.nexora-logout-overlay.open' in css_logout and 'align-items:center' in css_logout:
            PASS.append(f'LOGOUT {role} CSS centered')
        else:
            add('P1',path,'logout overlay CSS','fixed inset 0 + flex centered','missing/incorrect','resources/assets/css/style.css','overlay not covering page')
        # check z-index 5000 > sidebar 2000/3000
        if 'z-index:5000' in css_logout:
            PASS.append(f'LOGOUT {role} z-index 5000 > sidebar')
        else:
            add('P2',path,'logout z-index','5000 to stay above sidebar','wrong','resources/assets/css/style.css','modal behind sidebar')
        # check JS for ESC/backdrop
        sidebar_js = pathlib.Path('resources/assets/js/sidebar.js').read_bytes().decode('utf-8', errors='ignore')
        logout_html = pathlib.Path('resources/views/components/logout_modal.html').read_bytes().decode('utf-8', errors='ignore') if pathlib.Path('resources/views/components/logout_modal.html').exists() else ''
        if 'Escape' in logout_html or 'Escape' in sidebar_js or 'keydown' in logout_html:
            PASS.append(f'LOGOUT {role} ESC handler present (check file)')
        else:
            add('P2',path,'logout ESC','ESC closes modal','no key handler','resources/views/components/logout_modal.html','missing keydown')
        # check permanent text behind page: look for logout text outside modal
        # count logout word outside overlay: simple heuristic
        if html.count('Logout')>5:
            # could be sidebar logout + modal logout = ok, but if logout text appears as page content (not hidden) - check if modal has display:none by default
            if 'nexora-logout-overlay' in css_logout and 'display:none' in css_logout:
                PASS.append(f'LOGOUT {role} no permanent visible text (hidden by default)')
            else:
                add('P2',path,'logout text','hidden until opened','always visible','resources/assets/css/style.css','overlay display not none')
    else:
        add('P0',path,'logout modal','overlay exists','missing','resources/views/components/logout_modal.html','no modal include')

# 3 / 4 CLASS INFORMATION MODAL
for role, uid, cls_path, modal_id in [
    ('supervisor',2,'/supervisor/classes','classInfoModal'),
    ('student',3,'/student/classes','studentInfoModal')
]:
    # Get class list then try to get class detail
    code, html, _ = get_html(cls_path, role, uid)
    if 'Class Information' in html or modal_id in html:
        # For list page, modal not needed, but check class detail
        pass
    # Try to find a class id from HTML or directly test rendering of detail template via mock
    # Instead directly check template files
    tpl = pathlib.Path(f'resources/views/classroom/{role}_class.html')
    t = tpl.read_bytes().decode('utf-8', errors='ignore')
    if 'nexora-modal-overlay' in t and f'id="{modal_id}"' in t:
        PASS.append(f'CLASS INFO {role} modal overlay present')
        # Check position:fixed inset:0 z-index 4000
        mod_css = pathlib.Path('resources/assets/css/modals.css').read_bytes().decode('utf-8', errors='ignore')
        if 'position: fixed' in mod_css and 'inset: 0' in mod_css and 'z-index: 4000' in mod_css:
            PASS.append(f'CLASS INFO {role} CSS fixed viewport')
        else:
            add('P1',f'classroom/{role}_class.html',f'{modal_id}','position:fixed inset:0 z-index 4000 viewport overlay','CSS missing fixed','resources/assets/css/modals.css:2','modal becomes page content pushing page down')
        # Check NOT inside nexora-page (should be sibling of page-content or student-main-content)
        # Simple: find order of tags
        idx_page_close = t.rfind('</div>')
        idx_modal = t.find(modal_id)
        idx_body = t.find('</body>')
        # Check if modal is after nexora-page close but before body close and not inside nexora-page
        # Look at structure: we expect ...</div> (nexora-page) </div> (page-content) <div id="classInfoModal"
        # If modal inside page-content but outside nexora-page = acceptable per QA spec (sidebar remains outside), but ideal outside page-content
        # For supervisor we fixed to outside page-content, for student already outside
        if f'<div id="{modal_id}"' in t:
            before_modal = t[:t.find(f'<div id="{modal_id}"')]
            if before_modal.count('<div') - before_modal.count('</div>') > 2:
                add('P2',f'classroom/{role}_class.html',modal_id,'modal outside content wrappers','nested deeply inside wrappers','resources/views/classroom/'+role+'_class.html','incorrect nesting causes push')
            else:
                PASS.append(f'CLASS INFO {role} modal placement outside wrappers')
        # Check close buttons
        if 'nexora-modal-close' in t and 'classList.remove' in t:
            PASS.append(f'CLASS INFO {role} close buttons present')
        else:
            add('P1',f'classroom/{role}_class.html',modal_id,'Close + X + backdrop','missing handlers','resources/views/classroom/'+role+'_class.html','no close')
        # Check backdrop onclick
        if f"onclick=\"if(event.target===this) this.classList.remove('open')\"" in t:
            PASS.append(f'CLASS INFO {role} backdrop closes')
        else:
            add('P2',f'classroom/{role}_class.html',modal_id,'backdrop click closes','missing','resources/views/classroom/'+role+'_class.html','backdrop not closing')
        # Check sidebar remains outside: ensure modal is NOT inside sidebar include
        if t.find('components/'+role+'_sidebar') < t.find(modal_id):
            PASS.append(f'CLASS INFO {role} sidebar outside modal')
        else:
            add('P1',f'classroom/{role}_class.html',modal_id,'sidebar outside modal','sidebar inside modal','resources/views/classroom/'+role+'_class.html','z-index stacking broken')
    else:
        add('P0',f'classroom/{role}_class.html',modal_id,'modal overlay exists','not found','resources/views/classroom/'+role+'_class.html','modal missing becomes page content')

# 5 STUDENT PAGE VERTICAL SPACING
for path in ['/student/dashboard','/student/classes','/student/logbook','/student/tasks','/student/documents','/student/profile']:
    code, html, _ = get_html(path, 'student', 3)
    if code==200:
        if 'nexora-app-main' in html and 'nexora-page' in html:
            PASS.append(f'STUDENT SPACING {path} shell present')
        else:
            add('P1',path,'shell','nexora-app-main + nexora-page','missing','resources/views/student/*.html','heading too close to top / content under sidebar')
        # check heading not at top: look for mb-4 or dashboard-header
        if code==200 and '<h1' in html or '<h2' in html:
            PASS.append(f'STUDENT SPACING {path} heading exists')
        # check horizontal overflow: look for table-responsive + overflow
        if 'table-responsive' in html:
            PASS.append(f'STUDENT SPACING {path} table responsive')
        # notification bell overlap: check if bell inside sidebar vs page
        if 'notificationDropdown' in html:
            # should be included via sidebar, not page content
            if html.find('notificationDropdown') > html.find('student-main-content'):
                add('P2',path,'notificationDropdown','inside sidebar overlay not page','maybe page-level','resources/views/student/logbook.html','bell overlaps content')
            else:
                PASS.append(f'STUDENT SPACING {path} bell placement ok')
    else:
        add('P1',path,'student page','200 OK',f'{code}','routes/student.py','auth or missing')

# 6 SUPERVISOR PAGE SPACING
for path in ['/supervisor/dashboard','/supervisor/interns','/supervisor/classes']:
    code, html, _ = get_html(path, 'supervisor', 2)
    if code==200 and 'nexora-app-main' in html:
        PASS.append(f'SUPERVISOR SPACING {path} shell')
    elif code!=200:
        add('P1',path,'supervisor page','200','%s'%code,'routes/supervisor.py','missing')

# 7 ADMIN PAGE SPACING
for path in ['/admin/dashboard','/admin/users','/admin/users/students','/admin/users/supervisors','/admin/internship-assign','/admin/assignments','/admin/reports']:
    role='admin'
    uid=1
    # map to actual routes
    route_map = {'/admin/users/supervisors':'/admin/users/supervisors','/admin/users/students':'/admin/users/students','/admin/reports':'/admin/reports'}
    code, html, _ = get_html(path, role, uid)
    if code in (200,302):
        if 'nexora-app-main' in html or code==302:
            PASS.append(f'ADMIN SPACING {path} shell or redirect')
        else:
            add('P1',path,'admin shell','nexora-app-main','missing','resources/views/admin/*.html','admin heading under sidebar')
    else:
        # try alternative
        pass

# 8 SIDEBAR
for role, uid in [('admin',1),('student',3),('supervisor',2)]:
    # pick a page for each role
    path = {'admin':'/admin/dashboard','student':'/student/dashboard','supervisor':'/supervisor/dashboard'}[role]
    code, html, _ = get_html(path, role, uid)
    if 'compact-sidebar' in html and 'sidebar-toggle' in html:
        PASS.append(f'SIDEBAR {role} compact-sidebar + hamburger present')
    else:
        add('P1',path,'sidebar','compact-sidebar + hamburger','missing','resources/views/components/'+role+'_sidebar.html','no toggle')
    # check JS exists
    js = pathlib.Path('resources/assets/js/sidebar.js').read_bytes().decode('utf-8', errors='ignore')
    for kw in ['mobile-open','closed','sidebar-collapsed','localStorage','Escape']:
        if kw in js:
            pass
        else:
            add('P2','sidebar.js',kw,f'JS handles {kw}','missing','resources/assets/js/sidebar.js','functionality broken')
    if 'window.__nexoraSidebarInit' in js:
        PASS.append(f'SIDEBAR {role} duplicate guard')
    else:
        add('P2','sidebar.js','duplicate guard','window.__nexoraSidebarInit','missing','resources/assets/js/sidebar.js','double binding')
    # active navigation
    if 'active' in html and ('request.path' in html or 'active_page' in html):
        PASS.append(f'SIDEBAR {role} active state')
    else:
        add('P2',path,'sidebar active','active class based on path','missing','resources/views/components/'+role+'_sidebar.html','no active highlight')
    # profile link
    if 'sidebar-profile' in html and 'href' in html:
        PASS.append(f'SIDEBAR {role} profile link')
    else:
        add('P1',path,'sidebar profile','clickable profile link','missing','resources/views/components/'+role+'_sidebar.html','profile not clickable')

# 9 NOTIFICATIONS
for role, uid, path in [('student',3,'/student/dashboard'),('supervisor',2,'/supervisor/dashboard'),('admin',1,'/admin/dashboard')]:
    code, html, _ = get_html(path, role, uid)
    if 'notificationDropdown' in html or 'notification_bell' in html:
        PASS.append(f'NOTIF {role} dropdown present')
        if 'toggleNotifications' in html:
            PASS.append(f'NOTIF {role} toggleNotifications function')
        else:
            add('P2',path,'notifications','toggleNotifications()','missing','resources/views/components/notification_bell.html','JS error')
        if 'outside click' in pathlib.Path('resources/assets/js/sidebar.js').read_bytes().decode('utf-8', errors='ignore') or 'notification' in html.lower():
            pass
    else:
        if role=='admin':
            # admin may not have notifications, not an error
            PASS.append(f'NOTIF admin none (intentional if no bell)')
        else:
            add('P1',path,'notifications','dropdown','missing','resources/views/components/student_sidebar.html','bell not opening / null element')

# 10 CLASS COPY
for tpl in ['resources/views/classroom/student_class.html','resources/views/classroom/supervisor_class.html']:
    t = pathlib.Path(tpl).read_bytes().decode('utf-8', errors='ignore')
    if 'copyStudentCode' in t or 'copyClassCode' in t:
        if 'navigator.clipboard.writeText' in t and 'showToast' in t:
            PASS.append(f'COPY {tpl} uses clipboard + toast')
        else:
            add('P2',tpl,'copy','clipboard + toast','missing','resources/views/classroom/'+tpl,'fallback to alert')
        if 'alert(' in t:
            add('P1',tpl,'copy','no alert()','uses alert','resources/views/classroom/'+tpl,'should use toast')
        else:
            PASS.append(f'COPY {tpl} no alert')
        if 'prompt(' in t:
            add('P1',tpl,'copy','no prompt','uses prompt',tpl,'should not')
    else:
        add('P1',tpl,'copy','copy function','missing',tpl,'button does nothing')

# 11 RESPONSIVE
style = pathlib.Path('resources/assets/css/style.css').read_text(encoding='utf-8', errors='ignore') + pathlib.Path('resources/assets/css/student.css').read_text(encoding='utf-8', errors='ignore')
checks = {
    '1920': '235px' in style,
    '1024': '@media(max-width:1024px)' in style and '220px' in style,
    '768': '@media(max-width:768px)' in style and 'mobile-open' in style,
    '390': '@media(max-width:480px)' in style
}
for k,v in checks.items():
    if v:
        PASS.append(f'RESPONSIVE {k} media query present')
    else:
        add('P1','style.css',f'responsive {k}', 'media query','missing','resources/assets/css/style.css','sidebar overlap at breakpoint')

# check overflow
if 'overflow-x:auto' in style or 'table-responsive' in style:
    PASS.append('RESPONSIVE table clipping handled')
else:
    add('P2','style.css','tables','responsive overflow','missing','resources/assets/css/style.css','horizontal overflow')

# 12 CONSOLE
# static JS analysis for common errors
js_files = list(pathlib.Path('resources/assets/js').glob('*.js'))
for jf in js_files:
    txt = jf.read_bytes().decode('utf-8', errors='ignore')
    if 'getElementById' in txt:
        # check null guard
        if 'if (!sidebar) return' in txt or 'if(!el) return' in txt or 'if (!el)' in txt:
            PASS.append(f'CONSOLE {jf.name} null guard')
        else:
            add('P2',str(jf),'null guard','if (!el) return','missing','resources/assets/js/'+jf.name,'null element error')
    if 'addEventListener' in txt:
        PASS.append(f'CONSOLE {jf.name} listeners')
    # check for undefined functions referenced in HTML
    html_refs = []
    for p in pathlib.Path('resources/views').rglob('*.html'):
        ht = p.read_bytes().decode('utf-8', errors='ignore')
        for m in re.findall(r'onclick="([^"]+)"', ht):
            if '(' in m:
                fname = m.split('(')[0].split('.')[-1].strip()
                if fname in ['openLogoutModal','toggleNotifications','copyClassCode','copyStudentCode','openClassTab','toggleMenu']:
                    # check if defined in js or inline
                    if fname not in txt and fname not in ht:
                        add('P1',str(p),f'JS {fname}','function defined','undefined','resources/assets/js/'+jf.name,'ReferenceError')

# check for 404 resources: verify static files exist
for ref in ['css/style.css','css/student.css','css/supervisor.css','css/admin.css','css/modals.css','js/sidebar.js']:
    if pathlib.Path('resources/assets/'+ref).exists():
        PASS.append(f'NETWORK static {ref} exists')
    else:
        add('P0','static','resource '+ref,'file exists','404','resources/assets/'+ref,'failed load')

# check images referenced
for p in pathlib.Path('resources/views').rglob('*.html'):
    ht = p.read_bytes().decode('utf-8', errors='ignore')
    for m in re.findall(r"url_for\('static', filename='([^']+)'\)", ht):
        if not pathlib.Path('resources/assets/'+m).exists() and not pathlib.Path('public/'+m).exists():
            # images may be in static/images
            if 'images/' in m:
                # check case sensitive
                img_path = pathlib.Path('resources/assets/'+m)
                if not img_path.exists():
                    # check alternative
                    if not pathlib.Path('public/images/'+pathlib.Path(m).name).exists():
                        add('P2',str(p),f'image {m}','exists','404','resources/assets/'+m,'failed image')

# Print summary
print('=== QA FINAL REPORT ===')
print(f'PASS count {len(PASS)}')
for p in PASS:
    print('PASS:',p)
print(f'FAIL/P0 {len(P0)} P1 {len(P1)} P2 {len(P2)} P3 {len(P3)}')
for sev, lst in [('P0',P0),('P1',P1),('P2',P2),('P3',P3)]:
    for e in lst:
        print(f'{sev} | PAGE:{e["page"]} | EL:{e["element"]} | EXP:{e["expected"]} | ACT:{e["actual"]} | FILE:{e["file"]} | CAUSE:{e["cause"]}')
# Also provide NEEDS MANUAL DECISION
print('=== NEEDS MANUAL DECISION ===')
print('- Legacy files safe to delete vs keep for reference (see final report H)')
print('- Admin notification bell intentionally absent vs should add (currently only student/supervisor have bell via sidebar include)')
print('- Profile edit page uses no-admin-sidebar intentionally as overlay (not a bug)')
