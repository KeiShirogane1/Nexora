if (window.__nexoraSidebarInit) { /* prevent double-binding from duplicate includes */ } else { window.__nexoraSidebarInit = true;
document.addEventListener("DOMContentLoaded", function () {
    const sidebar = document.getElementById("mainSidebar");
    if (!sidebar) return;
    const toggles = document.querySelectorAll(".sidebar-toggle");
    function isMobile() { return window.innerWidth <= 768; }
    toggles.forEach(function(btn){
        btn.addEventListener("click", function(e){
            e.stopPropagation();
            if (isMobile()) {
                sidebar.classList.toggle("mobile-open");
                document.body.style.overflow = sidebar.classList.contains("mobile-open") ? "hidden" : "";
            } else {
                sidebar.classList.toggle("closed");
                document.body.classList.toggle("sidebar-collapsed");
                try { localStorage.setItem("sidebarClosed", sidebar.classList.contains("closed")); } catch(err){}
            }
        });
    });
    document.addEventListener("click", function(e){
        if (isMobile() && sidebar.classList.contains("mobile-open") && !sidebar.contains(e.target) && !e.target.closest(".sidebar-toggle")) {
            sidebar.classList.remove("mobile-open");
            document.body.style.overflow = "";
        }
    });
    document.addEventListener("keydown", function(e){
        if (e.key === "Escape" && sidebar.classList.contains("mobile-open")) {
            sidebar.classList.remove("mobile-open");
            document.body.style.overflow = "";
        }
    });
    try {
        if (!isMobile() && localStorage.getItem("sidebarClosed") === "true") {
            sidebar.classList.add("closed");
            document.body.classList.add("sidebar-collapsed");
        }
    } catch(err){}
    window.addEventListener("resize", function(){
        if (!isMobile()) {
            sidebar.classList.remove("mobile-open");
            document.body.style.overflow = "";
        }
    });
});
}
