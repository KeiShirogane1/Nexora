(function () {
    "use strict";

    function clampPercentage(value) {
        var parsed = Number.parseFloat(value);
        if (!Number.isFinite(parsed)) {
            return 0;
        }
        return Math.min(100, Math.max(0, parsed));
    }

    function applyDynamicProgress(root) {
        var scope = root || document;

        scope.querySelectorAll("[data-nx-progress]").forEach(function (element) {
            var value = clampPercentage(element.getAttribute("data-nx-progress"));
            element.style.width = value + "%";
        });

        scope.querySelectorAll("[data-nx-completion]").forEach(function (element) {
            var value = clampPercentage(element.getAttribute("data-nx-completion"));
            element.style.setProperty("--completion", value + "%");
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            applyDynamicProgress(document);
        });
    } else {
        applyDynamicProgress(document);
    }

    document.addEventListener("nexora:content-updated", function (event) {
        applyDynamicProgress(event.target || document);
    });

    window.NexoraDynamicProgress = {
        apply: applyDynamicProgress
    };
})();
