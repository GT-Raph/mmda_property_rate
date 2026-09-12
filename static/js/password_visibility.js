(function () {
    "use strict";

    var showIcon = [
        '<svg class="password-icon-show" viewBox="0 0 24 24" fill="none" aria-hidden="true">',
        '<path d="M2 12c1.8-3.5 5.2-6 10-6s8.2 2.5 10 6c-1.8 3.5-5.2 6-10 6S3.8 15.5 2 12Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"></path>',
        '<circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.8"></circle>',
        '</svg>'
    ].join("");

    var hideIcon = [
        '<svg class="password-icon-hide" viewBox="0 0 24 24" fill="none" aria-hidden="true">',
        '<path d="M2 12c1.8-3.5 5.2-6 10-6s8.2 2.5 10 6c-1.8 3.5-5.2 6-10 6S3.8 15.5 2 12Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"></path>',
        '<circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.8"></circle>',
        '<path d="M3 3l18 18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>',
        '</svg>'
    ].join("");

    function restoreSelection(input, start, end) {
        if (start === null || end === null || typeof input.setSelectionRange !== "function") return;

        try {
            input.setSelectionRange(start, end);
        } catch (error) {
            // Some browsers do not expose a selection range for every input state.
        }
    }

    function addPasswordToggle(input) {
        if (input.dataset.passwordVisibilityReady === "true") return;
        if (input.closest(".password-field")) return;

        var parent = input.parentNode;
        if (!parent) return;

        var wrapper = document.createElement("div");
        wrapper.className = "password-visibility-field";
        parent.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        var toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "password-visibility-toggle";
        toggle.setAttribute("aria-label", "Show password");
        toggle.setAttribute("aria-pressed", "false");
        toggle.setAttribute("title", "Show password");
        toggle.innerHTML = showIcon + hideIcon;

        toggle.addEventListener("click", function () {
            var selectionStart = input.selectionStart;
            var selectionEnd = input.selectionEnd;
            var willShow = input.type === "password";
            var label = willShow ? "Hide password" : "Show password";

            input.type = willShow ? "text" : "password";
            input.dataset.passwordVisible = String(willShow);
            toggle.setAttribute("aria-label", label);
            toggle.setAttribute("aria-pressed", String(willShow));
            toggle.setAttribute("title", label);
            try {
                input.focus({ preventScroll: true });
            } catch (error) {
                input.focus();
            }
            restoreSelection(input, selectionStart, selectionEnd);
        });

        wrapper.appendChild(toggle);
        input.dataset.passwordVisibilityReady = "true";
    }

    function preparePasswordVisibility() {
        document.querySelectorAll('input[type="password"]').forEach(addPasswordToggle);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", preparePasswordVisibility);
    } else {
        preparePasswordVisibility();
    }
})();
