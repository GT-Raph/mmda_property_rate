(function () {
    "use strict";

    function resetSubmissionState(form) {
        const overlay = document.getElementById(form.dataset.submissionOverlay || "");
        const button = document.getElementById(form.dataset.submissionButton || "");

        form.dataset.submitting = "false";
        form.removeAttribute("aria-busy");

        if (button) {
            button.disabled = false;
            button.removeAttribute("aria-busy");
        }

        if (overlay) {
            overlay.hidden = true;
            overlay.setAttribute("aria-hidden", "true");
        }
    }

    function activateSubmissionState(form) {
        const overlay = document.getElementById(form.dataset.submissionOverlay || "");
        const button = document.getElementById(form.dataset.submissionButton || "");
        const label = button?.querySelector(".submit-label");

        form.dataset.submitting = "true";
        form.setAttribute("aria-busy", "true");

        if (button) {
            button.disabled = true;
            button.setAttribute("aria-busy", "true");
        }

        if (label && form.dataset.submissionLabel) {
            label.textContent = form.dataset.submissionLabel;
        }

        if (overlay) {
            overlay.hidden = false;
            overlay.setAttribute("aria-hidden", "false");
        }
    }

    function bindSubmissionFeedback(form) {
        resetSubmissionState(form);

        form.addEventListener("submit", function (event) {
            if (form.dataset.submitting === "true") {
                event.preventDefault();
                return;
            }

            activateSubmissionState(form);
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("form[data-submission-overlay]").forEach(bindSubmissionFeedback);
    });

    window.addEventListener("pageshow", function () {
        document.querySelectorAll("form[data-submission-overlay]").forEach(resetSubmissionState);
    });
})();
