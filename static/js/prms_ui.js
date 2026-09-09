(function () {
    "use strict";

    function setExpanded(control, expanded) {
        if (control) {
            control.setAttribute("aria-expanded", String(expanded));
        }
    }

    function closeSidebar() {
        var sidebar = document.getElementById("sidebar");
        var overlay = document.getElementById("mobileOverlay");
        var toggle = document.querySelector(".menu-toggle");

        if (!sidebar || !sidebar.classList.contains("open")) return false;

        if (typeof window.closeSidebar === "function") {
            window.closeSidebar();
        } else {
            sidebar.classList.remove("open");
            if (overlay) overlay.classList.remove("show");
        }

        setExpanded(toggle, false);
        if (toggle) toggle.focus();
        return true;
    }

    function closeDrawer() {
        var backdrop = document.getElementById("drawerBackdrop");
        var trigger = document.querySelector(".menu-btn");

        if (!backdrop || !backdrop.classList.contains("show")) return false;

        if (typeof window.closeDrawer === "function") {
            window.closeDrawer();
        } else {
            backdrop.classList.remove("show");
        }

        setExpanded(trigger, false);
        if (trigger) trigger.focus();
        return true;
    }

    function closeDropdowns() {
        var openDropdowns = document.querySelectorAll(".user-dropdown:not([hidden])");
        if (!openDropdowns.length) return false;

        openDropdowns.forEach(function (dropdown) {
            dropdown.hidden = true;
        });
        document.querySelectorAll(".user-trigger[aria-expanded='true']").forEach(function (trigger) {
            setExpanded(trigger, false);
            trigger.focus();
        });
        return true;
    }

    function prepareNavigation() {
        document.querySelectorAll("nav a.active").forEach(function (link) {
            link.setAttribute("aria-current", "page");
        });

        var primaryNav = document.querySelector("nav.nav");
        if (primaryNav && !primaryNav.hasAttribute("aria-label")) {
            primaryNav.setAttribute("aria-label", "Primary navigation");
        }

        var bottomNav = document.querySelector("nav.bottom-nav");
        if (bottomNav && !bottomNav.hasAttribute("aria-label")) {
            bottomNav.setAttribute("aria-label", "Owner portal navigation");
        }
    }

    function prepareSidebar() {
        var sidebar = document.getElementById("sidebar");
        var toggle = document.querySelector(".menu-toggle");
        if (!sidebar || !toggle) return;

        toggle.setAttribute("aria-controls", "sidebar");
        setExpanded(toggle, sidebar.classList.contains("open"));

        toggle.addEventListener("click", function () {
            window.requestAnimationFrame(function () {
                setExpanded(toggle, sidebar.classList.contains("open"));
            });
        });
    }

    function prepareDrawer() {
        var drawer = document.querySelector(".drawer");
        var backdrop = document.getElementById("drawerBackdrop");
        var trigger = document.querySelector(".menu-btn");
        if (!drawer || !backdrop || !trigger) return;

        if (!drawer.id) drawer.id = "ownerMenu";
        trigger.setAttribute("aria-controls", drawer.id);
        trigger.setAttribute("aria-haspopup", "dialog");
        setExpanded(trigger, backdrop.classList.contains("show"));

        trigger.addEventListener("click", function () {
            window.requestAnimationFrame(function () {
                setExpanded(trigger, backdrop.classList.contains("show"));
            });
        });
    }

    function prepareTables() {
        document.querySelectorAll(".table-wrap, .table-responsive").forEach(function (wrapper) {
            if (!wrapper.hasAttribute("tabindex")) wrapper.tabIndex = 0;
            if (!wrapper.hasAttribute("role")) wrapper.setAttribute("role", "region");
            if (!wrapper.hasAttribute("aria-label")) {
                wrapper.setAttribute("aria-label", "Scrollable data table");
            }
        });
    }

    function prepareIconButtons() {
        document.querySelectorAll(".icon-btn, .notification-btn, .menu-toggle, .menu-btn").forEach(function (control) {
            control.querySelectorAll("svg, img").forEach(function (icon) {
                icon.setAttribute("aria-hidden", "true");
                if (icon.tagName === "IMG") icon.alt = "";
            });

            if (!control.hasAttribute("aria-label") && control.hasAttribute("title")) {
                control.setAttribute("aria-label", control.getAttribute("title"));
            }
        });
    }

    function prepareBuildingTypeFilters() {
        var choicesByUse = {
            residential: [
                ["apartment", "Apartment"],
                ["detached", "Detached"],
                ["semi_detached", "Semi-Detached"],
                ["self_contained", "Self-Contained"],
                ["compound", "Compound House"]
            ],
            commercial: [
                ["office", "Office"],
                ["shop", "Shop"]
            ],
            industrial: [["warehouse", "Warehouse"]],
            mixed_use: [["other", "Other"]],
            institutional: [
                ["school", "School"],
                ["other", "Other"]
            ]
        };

        document.querySelectorAll("select[name$='property_use']").forEach(function (propertyUse) {
            var form = propertyUse.closest("form") || document;
            var buildingType = form.querySelector("select[name$='building_type']");

            if (!buildingType) return;

            function updateBuildingTypes() {
                var previousValue = buildingType.value;
                var allowedChoices = choicesByUse[propertyUse.value] || [];

                buildingType.replaceChildren();

                var placeholder = document.createElement("option");
                placeholder.value = "";
                placeholder.textContent = propertyUse.value
                    ? "Select building type"
                    : "Select property use first";
                buildingType.appendChild(placeholder);

                allowedChoices.forEach(function (choice) {
                    var option = document.createElement("option");
                    option.value = choice[0];
                    option.textContent = choice[1];
                    buildingType.appendChild(option);
                });

                var previousStillAllowed = allowedChoices.some(function (choice) {
                    return choice[0] === previousValue;
                });

                buildingType.value = previousStillAllowed ? previousValue : "";
                buildingType.disabled = !propertyUse.value;
            }

            propertyUse.addEventListener("change", updateBuildingTypes);
            updateBuildingTypes();
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        prepareNavigation();
        prepareSidebar();
        prepareDrawer();
        prepareTables();
        prepareIconButtons();
        prepareBuildingTypeFilters();

        document.addEventListener("keydown", function (event) {
            if (event.key !== "Escape") return;
            if (closeSidebar()) return;
            if (closeDrawer()) return;
            closeDropdowns();
        });
    });
})();
