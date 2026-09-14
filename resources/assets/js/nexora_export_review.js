(function () {
    'use strict';

    var FILE_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="M8 13h8M8 17h6"></path></svg>';
    var SHEET_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 3h16v18H4z"></path><path d="M4 9h16M10 9v12"></path></svg>';

    function cleanText(value) {
        return String(value || '').replace(/\s+/g, ' ').trim();
    }

    function showToast(message, type) {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type || 'info');
        }
    }

    function plural(count, singular, pluralValue) {
        return count + ' ' + (count === 1 ? singular : (pluralValue || singular + 's'));
    }

    function csvEscape(value) {
        var text = String(value == null ? '' : value);
        return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
    }

    function downloadBlob(blob, name) {
        var url = URL.createObjectURL(blob);
        var anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = name;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        window.setTimeout(function () { URL.revokeObjectURL(url); }, 250);
    }

    function exportCsv(data, filename) {
        var lines = [data.headers.map(csvEscape).join(',')].concat(
            data.rows.map(function (row) { return row.map(csvEscape).join(','); })
        );
        downloadBlob(new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }), filename);
    }

    function loadScript(src, globalName) {
        return new Promise(function (resolve, reject) {
            if (globalName && window[globalName]) {
                resolve();
                return;
            }
            var existing = document.querySelector('script[data-nx-export-src="' + src + '"]');
            if (existing) {
                existing.addEventListener('load', resolve, { once: true });
                existing.addEventListener('error', reject, { once: true });
                return;
            }
            var script = document.createElement('script');
            script.src = src;
            script.dataset.nxExportSrc = src;
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    function exportXlsx(data, filename, sheetName) {
        return loadScript('https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js', 'XLSX').then(function () {
            var sheet = XLSX.utils.aoa_to_sheet([data.headers].concat(data.rows));
            var book = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(book, sheet, sheetName || 'Export');
            XLSX.writeFile(book, filename);
        });
    }

    function exportPdf(data, options) {
        options = options || {};
        return loadScript('https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js').then(function () {
            return loadScript('https://cdn.jsdelivr.net/npm/jspdf-autotable@3.8.4/dist/jspdf.plugin.autotable.min.js');
        }).then(function () {
            var jsPDF = window.jspdf && window.jspdf.jsPDF;
            if (!jsPDF) throw new Error('PDF engine unavailable');
            var doc = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' });
            doc.setFontSize(18);
            doc.text(options.title || 'Nexora Export', 40, 42);
            doc.setFontSize(9);
            doc.setTextColor(100);
            doc.text(options.subtitle || 'Exported from Nexora', 40, 60);
            doc.autoTable({
                head: [data.headers],
                body: data.rows,
                startY: 78,
                styles: { fontSize: 8, cellPadding: 5 },
                headStyles: { fillColor: options.headColor || [37, 99, 235] },
                margin: { left: 40, right: 40 }
            });
            doc.save(options.filename || 'nexora-export.pdf');
        });
    }

    function cloneWithoutListeners(node) {
        if (!node) return null;
        var clone = node.cloneNode(true);
        node.replaceWith(clone);
        clone.dataset.nxExportReviewReady = '1';
        return clone;
    }

    function safeHref(node) {
        if (!node) return '';
        return node.getAttribute('href') || node.href || '';
    }

    function setGridColumns(grid, count) {
        if (!grid) return;
        grid.style.gridTemplateColumns = window.matchMedia('(max-width: 680px)').matches
            ? '1fr'
            : 'repeat(' + Math.max(1, Math.min(3, count)) + ', minmax(0, 1fr))';
    }

    function createReviewModal(config) {
        if (!config || !config.trigger || !config.formats || !config.formats.length) return;
        var old = config.id ? document.getElementById(config.id) : null;
        if (old) old.remove();

        var overlay = document.createElement('div');
        overlay.className = 'nexora-modal-overlay nx-export-modal';
        if (config.id) overlay.id = config.id;
        overlay.setAttribute('aria-hidden', 'true');
        overlay.innerHTML = '' +
            '<div class="nexora-modal" role="dialog" aria-modal="true">' +
                '<div class="nexora-modal-header">' +
                    '<h2 data-nx-export-title></h2>' +
                    '<p data-nx-export-description></p>' +
                    '<button type="button" class="nexora-modal-close" data-nx-export-close aria-label="Close">×</button>' +
                '</div>' +
                '<div class="nexora-modal-body">' +
                    '<div class="nx-export-note"><strong>Target</strong><br><span data-nx-export-target></span><br><br><strong>Scope</strong><br><span data-nx-export-scope></span></div>' +
                    '<div class="nx-export-note"><strong>Included information</strong><br><span data-nx-export-fields></span></div>' +
                    '<div class="nx-export-grid" data-nx-export-grid></div>' +
                    '<p class="nx-export-note" data-nx-export-footnote></p>' +
                '</div>' +
                '<div class="nexora-modal-footer"><button type="button" class="btn-nexora-secondary" data-nx-export-close>Cancel</button></div>' +
            '</div>';

        var titleNode = overlay.querySelector('[data-nx-export-title]');
        var descriptionNode = overlay.querySelector('[data-nx-export-description]');
        var targetNode = overlay.querySelector('[data-nx-export-target]');
        var scopeNode = overlay.querySelector('[data-nx-export-scope]');
        var fieldsNode = overlay.querySelector('[data-nx-export-fields]');
        var grid = overlay.querySelector('[data-nx-export-grid]');
        var footnote = overlay.querySelector('[data-nx-export-footnote]');

        titleNode.textContent = config.title || 'Export';
        descriptionNode.textContent = config.description || 'Review the export target and included information before downloading.';
        targetNode.textContent = typeof config.target === 'function' ? config.target() : (config.target || 'Current page');
        scopeNode.textContent = typeof config.scope === 'function' ? config.scope() : (config.scope || 'Current visible data');
        fieldsNode.textContent = (config.fields || []).join(' · ');
        footnote.textContent = config.note || 'Choose only a format supported by this export. Existing permissions and protected routes remain unchanged.';

        config.formats.forEach(function (format) {
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'nx-export-choice';
            button.dataset.format = format.key || format.label || 'export';
            button.innerHTML = (format.icon === 'sheet' ? SHEET_SVG : FILE_SVG) + '<strong></strong><small></small>';
            button.querySelector('strong').textContent = format.label || 'Export';
            button.querySelector('small').textContent = format.detail || '';
            button.addEventListener('click', function () {
                var original = button.innerHTML;
                button.disabled = true;
                try {
                    if (format.url) {
                        close();
                        window.location.assign(format.url);
                        button.disabled = false;
                        return;
                    }
                    var job = format.run ? format.run() : null;
                    Promise.resolve(job).then(function () {
                        close();
                    }).catch(function (error) {
                        var message = error && error.message ? error.message : 'Unable to create that export.';
                        showToast(message, 'error');
                    }).finally(function () {
                        button.disabled = false;
                        button.innerHTML = original;
                    });
                } catch (error) {
                    button.disabled = false;
                    button.innerHTML = original;
                    showToast(error && error.message ? error.message : 'Unable to create that export.', 'error');
                }
            });
            grid.appendChild(button);
        });

        setGridColumns(grid, config.formats.length);
        document.body.appendChild(overlay);

        function refresh() {
            if (typeof config.target === 'function') targetNode.textContent = config.target();
            if (typeof config.scope === 'function') scopeNode.textContent = config.scope();
            setGridColumns(grid, config.formats.length);
        }

        function open(event) {
            if (event) event.preventDefault();
            refresh();
            overlay.classList.add('open');
            overlay.setAttribute('aria-hidden', 'false');
            document.body.style.overflow = 'hidden';
        }

        function close() {
            overlay.classList.remove('open');
            overlay.setAttribute('aria-hidden', 'true');
            document.body.style.overflow = '';
        }

        config.trigger.addEventListener('click', open);
        overlay.querySelectorAll('[data-nx-export-close]').forEach(function (button) {
            button.addEventListener('click', close);
        });
        overlay.addEventListener('click', function (event) {
            if (event.target === overlay) close();
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && overlay.classList.contains('open')) close();
        });
    }

    function visibleStudentRows() {
        var rows = Array.from(document.querySelectorAll('#studentsTable tbody tr[data-id]')).filter(function (row) {
            return row.style.display !== 'none';
        });
        var headers = ['#', 'Student Name', 'Username', 'Email', 'Program', 'Supervisor', 'Status', 'Joined Date'];
        var body = rows.map(function (row) {
            var cells = row.querySelectorAll('td');
            return [
                cells[1] ? cleanText(cells[1].innerText) : '',
                cells[2] ? cleanText(cells[2].innerText) : '',
                cells[3] ? cleanText(cells[3].innerText) : '',
                cells[4] ? cleanText(cells[4].innerText) : '',
                cells[5] ? cleanText(cells[5].innerText) : '',
                cells[6] ? cleanText(cells[6].innerText) : '',
                cells[7] ? cleanText(cells[7].innerText) : '',
                cells[8] ? cleanText(cells[8].innerText) : ''
            ];
        });
        return { headers: headers, rows: body };
    }

    function visibleSupervisorRows() {
        var rows = Array.from(document.querySelectorAll('#supervisorsTable tbody tr[data-id]')).filter(function (row) {
            return row.style.display !== 'none';
        });
        var headers = ['#', 'Supervisor', 'Email', 'Role / Status', 'Assigned Students'];
        var body = rows.map(function (row) {
            var cells = row.querySelectorAll('td');
            return [
                cells[1] ? cleanText(cells[1].innerText) : '',
                cells[2] ? cleanText(cells[2].innerText) : '',
                cells[3] ? cleanText(cells[3].innerText) : '',
                cells[4] ? cleanText(cells[4].innerText) : '',
                cells[5] ? cleanText(cells[5].innerText) : ''
            ];
        });
        return { headers: headers, rows: body };
    }

    function requireRows(provider, label) {
        var data = provider();
        if (!data.rows.length) throw new Error('No visible ' + label + ' to export.');
        return data;
    }

    function setupAdminStudentExport() {
        var original = document.getElementById('exportBtn');
        if (!original || !document.getElementById('studentsTable')) return;
        var trigger = cloneWithoutListeners(original);
        trigger.title = 'Review visible student export';
        createReviewModal({
            id: 'nxStudentExportReviewModal',
            trigger: trigger,
            title: 'Export Student Directory',
            target: 'Admin · Student Management',
            scope: function () {
                var count = visibleStudentRows().rows.length;
                return plural(count, 'visible student') + '. Current search and filters are applied; hidden rows are excluded.';
            },
            fields: ['#', 'Student Name', 'Username', 'Email', 'Program', 'Supervisor', 'Status', 'Joined Date'],
            formats: [
                {
                    key: 'csv', label: 'CSV', detail: 'nexora-students.csv · visible rows only',
                    run: function () { exportCsv(requireRows(visibleStudentRows, 'students'), 'nexora-students.csv'); }
                },
                {
                    key: 'pdf', label: 'PDF', detail: 'nexora-students.pdf · formatted directory',
                    run: function () {
                        return exportPdf(requireRows(visibleStudentRows, 'students'), {
                            title: 'Nexora Student Directory',
                            subtitle: 'Visible students exported from Student Management',
                            filename: 'nexora-students.pdf',
                            headColor: [231, 81, 45]
                        });
                    }
                }
            ],
            note: 'CSV preserves the visible directory as structured data. PDF creates a formatted read-only directory using the same visible records.'
        });
    }

    function setupAdminSupervisorExport() {
        var original = document.getElementById('exportSupervisorsBtn');
        if (!original || !document.getElementById('supervisorsTable')) return;
        var legacy = document.getElementById('nxSupervisorExportModal');
        if (legacy) legacy.remove();
        var trigger = cloneWithoutListeners(original);
        trigger.title = 'Review visible supervisor export';
        createReviewModal({
            id: 'nxSupervisorExportReviewV2Modal',
            trigger: trigger,
            title: 'Export Supervisor Directory',
            target: 'Admin · Supervisor Management',
            scope: function () {
                var count = visibleSupervisorRows().rows.length;
                return plural(count, 'visible supervisor') + '. Current search and filters are applied; hidden rows are excluded.';
            },
            fields: ['#', 'Supervisor', 'Email', 'Role / Status', 'Assigned Students'],
            formats: [
                {
                    key: 'csv', label: 'CSV', detail: 'Supervisor-List.csv · visible rows only',
                    run: function () { exportCsv(requireRows(visibleSupervisorRows, 'supervisors'), 'Supervisor-List.csv'); }
                },
                {
                    key: 'xlsx', label: 'Excel', icon: 'sheet', detail: 'Supervisor-List.xlsx · spreadsheet workbook',
                    run: function () { return exportXlsx(requireRows(visibleSupervisorRows, 'supervisors'), 'Supervisor-List.xlsx', 'Supervisors'); }
                },
                {
                    key: 'pdf', label: 'PDF', detail: 'Supervisor-List.pdf · formatted directory',
                    run: function () {
                        return exportPdf(requireRows(visibleSupervisorRows, 'supervisors'), {
                            title: 'Nexora Supervisor List',
                            subtitle: 'Visible supervisors exported from Supervisor Management',
                            filename: 'Supervisor-List.pdf',
                            headColor: [231, 81, 45]
                        });
                    }
                }
            ],
            note: 'All formats use only supervisors currently visible in the filtered directory. No hidden records are added back into the export.'
        });
    }

    function anchorByPath(test) {
        return Array.from(document.querySelectorAll('a[href]')).find(function (anchor) {
            try {
                return test(new URL(anchor.href, window.location.href).pathname, anchor);
            } catch (error) {
                return false;
            }
        }) || null;
    }

    function headingText(selector, fallback) {
        var node = document.querySelector(selector);
        return node ? cleanText(node.textContent) : (fallback || 'Current export');
    }

    function pageTitleValue(prefix) {
        var title = cleanText(document.title);
        var marker = prefix + ' - ';
        if (title.indexOf(marker) === 0 && title.lastIndexOf(' - Nexora') > marker.length) {
            return title.slice(marker.length, title.lastIndexOf(' - Nexora'));
        }
        return '';
    }

    function configureServerExport(options) {
        if (!options || !options.trigger) return;
        var trigger = cloneWithoutListeners(options.trigger);
        if (options.label) trigger.textContent = options.label;
        if (options.fallbackUrl) trigger.setAttribute('href', options.fallbackUrl);
        trigger.title = 'Review export details';
        createReviewModal({
            id: options.id,
            trigger: trigger,
            title: options.title,
            description: 'Review exactly what Nexora will export. Downloading does not change stored records.',
            target: options.target,
            scope: options.scope,
            fields: options.fields,
            formats: options.formats,
            note: options.note
        });
    }

    function setupSupervisorGradebookExport(path) {
        if (!/^\/supervisor\/classes\/\d+\/gradebook\/?$/.test(path)) return false;
        var csv = anchorByPath(function (hrefPath) { return /\/gradebook\/export\.csv$/.test(hrefPath); });
        if (!csv) return false;
        configureServerExport({
            id: 'nxGradebookExportReviewModal',
            trigger: csv,
            label: 'Export Gradebook',
            fallbackUrl: safeHref(csv),
            title: 'Export Classroom Gradebook',
            target: function () { return pageTitleValue('Gradebook') || headingText('.supervisor-gradebook-back', 'Current classroom').replace(/^←\s*Back to\s*/i, ''); },
            scope: function () { return headingText('.supervisor-gradebook-summary', 'Entire classroom'); },
            fields: ['Student Number', 'Student', 'Email', 'One score column per Work item', 'Overall %'],
            formats: [{ key: 'csv', label: 'CSV', detail: 'Student identity, Work item scores, Overall %', url: safeHref(csv) }],
            note: 'Gradebook export is CSV-only because that is the format supported by the existing protected Gradebook export route.'
        });
        return true;
    }

    function setupSupervisorIndividualInsightsExport(path) {
        var match = path.match(/^\/supervisor\/classes\/(\d+)\/insights\/(\d+)\/?$/);
        if (!match) return false;
        var actions = document.querySelector('.nexora-page > .d-flex.flex-wrap.align-items-start.justify-content-between .d-flex.flex-wrap.gap-2');
        if (!actions || actions.querySelector('[data-nx-individual-insights-export]')) return false;
        var csvUrl = '/supervisor/classes/' + match[1] + '/insights/' + match[2] + '/export.csv';
        var pdfUrl = '/supervisor/classes/' + match[1] + '/insights/' + match[2] + '/export.pdf';
        var trigger = document.createElement('a');
        trigger.href = csvUrl;
        trigger.className = 'btn btn-outline-primary';
        trigger.textContent = 'Export Insights';
        trigger.dataset.nxIndividualInsightsExport = '1';
        var primary = Array.from(actions.querySelectorAll('a')).find(function (item) { return item.classList.contains('btn-primary'); });
        if (primary) actions.insertBefore(trigger, primary); else actions.appendChild(trigger);
        configureServerExport({
            id: 'nxIndividualInsightsExportReviewModal',
            trigger: trigger,
            label: 'Export Insights',
            fallbackUrl: csvUrl,
            title: 'Export Individual Insights',
            target: function () { return headingText('.nexora-page h1', 'Selected intern'); },
            scope: function () { return '1 intern · ' + headingText('.nexora-page h1 + p', 'Current Intern Classroom'); },
            fields: ['Identity', 'Attendance & OJT Hours', 'Daily Performance', 'Daily Logbook', 'Work evidence', 'Feedback ML', 'Decision Support', 'Official Evaluation'],
            formats: [
                { key: 'csv', label: 'CSV', detail: 'Includes required hours and pending logbook count', url: csvUrl },
                { key: 'pdf', label: 'PDF', detail: 'Formatted evidence sections + evaluation remarks', url: pdfUrl }
            ],
            note: 'These exports preserve the separate OJT evidence dimensions. They do not calculate a combined OJT grade.'
        });
        return true;
    }

    function setupSupervisorClassroomInsightsExport(path) {
        var match = path.match(/^\/supervisor\/classes\/(\d+)\/insights\/?$/);
        if (!match) return false;
        var current = anchorByPath(function (hrefPath, anchor) {
            return /\/gradebook\/export\.csv$/.test(hrefPath) && /Export CSV/i.test(cleanText(anchor.textContent));
        });
        if (!current) return false;
        var csvUrl = '/supervisor/classes/' + match[1] + '/insights/export.csv';
        var pdfUrl = '/supervisor/classes/' + match[1] + '/insights/export.pdf';
        configureServerExport({
            id: 'nxClassroomInsightsExportReviewModal',
            trigger: current,
            label: 'Export Insights',
            fallbackUrl: csvUrl,
            title: 'Export Classroom Performance Insights',
            target: function () { return pageTitleValue('Performance Insights') || 'Current Intern Classroom'; },
            scope: function () {
                var countNode = document.querySelector('.supervisor-insights-readiness-card strong');
                var section = headingText('.supervisor-classwork-heading p', 'Current classroom');
                return (countNode ? plural(parseInt(cleanText(countNode.textContent), 10) || 0, 'intern') + ' · ' : '') + section;
            },
            fields: ['Intern identity', 'Work average', 'Work completion', 'Work label', 'Sentiment', 'Competency', 'Recommendation', 'Priority'],
            formats: [
                { key: 'csv', label: 'CSV', detail: 'Detailed intern rows including competency and recommendation', url: csvUrl },
                { key: 'pdf', label: 'PDF', detail: 'Classroom summary + Work/ML insights table', url: pdfUrl }
            ],
            note: 'This fixes the old Insights action that pointed at the Gradebook CSV. Both choices now use the existing protected Insights export routes.'
        });
        return true;
    }

    function setupSupervisorIndividualReportExport(path) {
        if (!/^\/supervisor\/classes\/\d+\/reports\/\d+\/?$/.test(path)) return false;
        var csv = anchorByPath(function (hrefPath) { return /\/reports\/\d+\/export\.csv$/.test(hrefPath); });
        var pdf = anchorByPath(function (hrefPath) { return /\/reports\/\d+\/export\.pdf$/.test(hrefPath); });
        if (!csv && !pdf) return false;
        var trigger = pdf || csv;
        if (csv && csv !== trigger) csv.hidden = true;
        configureServerExport({
            id: 'nxIndividualReportExportReviewModal',
            trigger: trigger,
            label: 'Export Report',
            fallbackUrl: safeHref(pdf || csv),
            title: 'Export Individual Performance Report',
            target: function () { return headingText('.supervisor-classwork-heading h1', 'Selected intern'); },
            scope: function () { return '1 intern · ' + headingText('.supervisor-classwork-heading p', 'Current Intern Classroom'); },
            fields: ['Identity', 'Attendance & OJT Hours', 'Daily Performance', 'Daily Logbook', 'Work', 'Feedback ML', 'Decision Support', 'Official Evaluation'],
            formats: [
                csv ? { key: 'csv', label: 'CSV', detail: 'Dimension / Metric / Value rows + manual evaluation score', url: safeHref(csv) } : null,
                pdf ? { key: 'pdf', label: 'PDF', detail: 'Formatted evidence sections + priority and evaluation remarks', url: safeHref(pdf) } : null
            ].filter(Boolean),
            note: 'The report keeps attendance, daily performance, logbook, Work analytics, feedback ML, and Official Evaluation as separate evidence dimensions.'
        });
        return true;
    }

    function setupSupervisorReportsWorkspaceExport(path) {
        if (!(path === '/supervisor/reports' || /^\/supervisor\/classes\/\d+\/reports\/?$/.test(path))) return false;
        var csv = anchorByPath(function (hrefPath) { return /\/reports\/export\.csv$/.test(hrefPath); });
        var pdf = anchorByPath(function (hrefPath) { return /\/reports\/export\.pdf$/.test(hrefPath); });
        if (!csv && !pdf) return false;
        var trigger = pdf || csv;
        if (csv && csv !== trigger) csv.hidden = true;
        configureServerExport({
            id: 'nxClassroomReportExportReviewModal',
            trigger: trigger,
            label: 'Export Report',
            fallbackUrl: safeHref(pdf || csv),
            title: 'Export Classroom Performance Report',
            target: function () { return headingText('.supervisor-reports-toolbar strong', 'Selected Intern Classroom'); },
            scope: function () { return headingText('.supervisor-reports-toolbar .text-muted.small', 'Entire selected classroom'); },
            fields: ['Classroom identity', 'Intern identity', 'Work average', 'Work completion', 'Work classification', 'Feedback signal', 'Priority'],
            formats: [
                csv ? { key: 'csv', label: 'CSV', detail: 'Detailed rows: student #, email, competency, sentiment, recommendation, priority', url: safeHref(csv) } : null,
                pdf ? { key: 'pdf', label: 'PDF', detail: 'Classroom summary + intern Work/feedback table', url: safeHref(pdf) } : null
            ].filter(Boolean),
            note: 'CSV contains the detailed Work/feedback directory. PDF is the formatted classroom summary supported by the existing report route.'
        });
        return true;
    }

    function setupSupervisorServerExports() {
        if (!/^\/supervisor\//.test(window.location.pathname)) return;
        var path = window.location.pathname;
        if (setupSupervisorIndividualInsightsExport(path)) return;
        if (setupSupervisorClassroomInsightsExport(path)) return;
        if (setupSupervisorIndividualReportExport(path)) return;
        if (setupSupervisorReportsWorkspaceExport(path)) return;
        setupSupervisorGradebookExport(path);
    }

    function boot() {
        setupAdminStudentExport();
        setupAdminSupervisorExport();
        setupSupervisorServerExports();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot, { once: true });
    } else {
        boot();
    }
})();
