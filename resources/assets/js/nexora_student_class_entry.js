(function () {
    function resolveStudentClassEntry() {
        var path = window.location.pathname;
        if (path !== '/student/classes' && path !== '/student/classes/') return;

        var classroomLinks = Array.from(
            document.querySelectorAll('a.student-intern-open-btn[href]')
        );

        if (classroomLinks.length === 1) {
            window.location.replace(classroomLinks[0].href);
            return;
        }

        if (classroomLinks.length === 0) {
            var joinLink = document.querySelector(
                'a.empty-join[href], a.join-btn[href*="/student/classes/join"]'
            );
            if (joinLink) window.location.replace(joinLink.href);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', resolveStudentClassEntry, { once: true });
    } else {
        resolveStudentClassEntry();
    }
})();
