(function () {
    "use strict";

    const LEGACY_PREFIX = "__legacy_property_class__:";

    function byId(id) {
        return document.getElementById(id);
    }

    function buildUrl(baseUrl, params) {
        const url = new URL(baseUrl, window.location.origin);

        Object.keys(params).forEach(function (key) {
            const value = params[key];

            if (value !== null && value !== undefined && value !== "") {
                url.searchParams.set(key, value);
            }
        });

        return url.toString();
    }

    async function getJson(url) {
        const response = await fetch(url, {
            method: "GET",
            credentials: "same-origin",
            headers: {
                "X-Requested-With": "XMLHttpRequest"
            }
        });

        if (!response.ok) {
            throw new Error("Unable to load the requested admin data.");
        }

        return response.json();
    }

    function setClassLoading(classSelect) {
        classSelect.innerHTML = "";

        const option = new Option(
            "Loading property classes...",
            "",
            true,
            true
        );

        classSelect.add(option);
        classSelect.disabled = true;
    }

    function setClassPlaceholder(classSelect, text) {
        classSelect.innerHTML = "";
        classSelect.add(new Option(text, "", true, true));
        classSelect.disabled = false;
    }

    function populateClassSelect(classSelect, classes, selectedValue) {
        classSelect.innerHTML = "";
        classSelect.add(new Option("---------", ""));

        classes.forEach(function (item) {
            const option = new Option(
                item.text,
                String(item.id)
            );

            if (String(item.id) === String(selectedValue || "")) {
                option.selected = true;
            }

            classSelect.add(option);
        });

        classSelect.disabled = false;

        if (!classes.length) {
            setClassPlaceholder(
                classSelect,
                "No property classes configured"
            );
        }
    }

    function clearSelectBoxCache(selectId) {
        if (
            window.SelectBox &&
            Object.prototype.hasOwnProperty.call(
                window.SelectBox.cache,
                selectId
            )
        ) {
            window.SelectBox.cache[selectId] = [];
        }
    }

    function clearSelectElement(selectElement) {
        if (!selectElement) {
            return;
        }

        while (selectElement.options.length) {
            selectElement.remove(0);
        }
    }

    function addAreaOptions(selectElement, areas, selected) {
        if (!selectElement) {
            return;
        }

        areas.forEach(function (area) {
            const option = new Option(
                area.text,
                String(area.id),
                selected,
                selected
            );

            selectElement.add(option);
        });
    }

    function refreshDjangoSelectBox(selectId) {
        if (!window.SelectBox) {
            return;
        }

        const selectElement = byId(selectId);

        if (!selectElement) {
            return;
        }

        window.SelectBox.init(selectId);
        window.SelectBox.redisplay(selectId);
    }

    function clearAreaSearchInputs() {
        const possibleIds = [
            "id_covered_areas_input",
            "id_covered_areas_selected_input"
        ];

        possibleIds.forEach(function (id) {
            const input = byId(id);

            if (input) {
                input.value = "";
                input.dispatchEvent(
                    new Event("input", { bubbles: true })
                );
            }
        });
    }

    function populateCoveredAreas(areas) {
        const availableSelect = byId("id_covered_areas_from");
        const chosenSelect = byId("id_covered_areas_to");
        const originalSelect = byId("id_covered_areas");

        clearAreaSearchInputs();

        if (availableSelect && chosenSelect) {
            clearSelectElement(availableSelect);
            clearSelectElement(chosenSelect);

            clearSelectBoxCache(availableSelect.id);
            clearSelectBoxCache(chosenSelect.id);

            addAreaOptions(chosenSelect, areas, true);

            refreshDjangoSelectBox(availableSelect.id);
            refreshDjangoSelectBox(chosenSelect.id);

            chosenSelect.dispatchEvent(
                new Event("change", { bubbles: true })
            );

            return;
        }

        if (originalSelect) {
            clearSelectElement(originalSelect);
            addAreaOptions(originalSelect, areas, true);

            originalSelect.dispatchEvent(
                new Event("change", { bubbles: true })
            );
        }
    }

    function selectAllChosenAreasBeforeSubmit() {
        const form = document.querySelector(
            "form#ratepolicy_form, form[method='post']"
        );

        if (!form) {
            return;
        }

        form.addEventListener("submit", function () {
            const chosenSelect = byId("id_covered_areas_to");
            const originalSelect = byId("id_covered_areas");
            const targetSelect = chosenSelect || originalSelect;

            if (!targetSelect) {
                return;
            }

            Array.from(targetSelect.options).forEach(function (option) {
                option.selected = true;
            });
        });
    }

    function initialiseRatePolicyDependencies() {
        const assemblySelect = byId("id_assembly");
        const propertyUseSelect = byId("id_property_use");
        const propertyClassSelect = byId("id_property_class");

        if (
            !assemblySelect ||
            !propertyUseSelect ||
            !propertyClassSelect
        ) {
            return;
        }

        const classesUrl =
            propertyUseSelect.dataset.propertyClassesUrl || "";

        const areasUrl =
            propertyClassSelect.dataset.propertyClassAreasUrl || "";

        if (!classesUrl || !areasUrl) {
            return;
        }

        let requestSequence = 0;

        async function loadAreas(propertyClassId) {
            if (
                !propertyClassId ||
                String(propertyClassId).startsWith(LEGACY_PREFIX)
            ) {
                return;
            }

            const currentSequence = ++requestSequence;

            try {
                const data = await getJson(
                    buildUrl(areasUrl, {
                        property_class: propertyClassId
                    })
                );

                if (currentSequence !== requestSequence) {
                    return;
                }

                populateCoveredAreas(data.results || []);
            } catch (error) {
                if (currentSequence !== requestSequence) {
                    return;
                }

                populateCoveredAreas([]);
                window.console.error(error);
            }
        }

        async function loadClasses(selectedValue, loadSelectedAreas) {
            const assemblyId = assemblySelect.value;
            const propertyUse = propertyUseSelect.value;

            if (!assemblyId || !propertyUse) {
                setClassPlaceholder(
                    propertyClassSelect,
                    "Select assembly and property use first"
                );
                populateCoveredAreas([]);
                return;
            }

            const currentSequence = ++requestSequence;
            setClassLoading(propertyClassSelect);

            try {
                const data = await getJson(
                    buildUrl(classesUrl, {
                        assembly: assemblyId,
                        property_use: propertyUse
                    })
                );

                if (currentSequence !== requestSequence) {
                    return;
                }

                populateClassSelect(
                    propertyClassSelect,
                    data.results || [],
                    selectedValue
                );

                const activeValue = propertyClassSelect.value;

                if (loadSelectedAreas && activeValue) {
                    await loadAreas(activeValue);
                } else if (!activeValue) {
                    populateCoveredAreas([]);
                }
            } catch (error) {
                if (currentSequence !== requestSequence) {
                    return;
                }

                setClassPlaceholder(
                    propertyClassSelect,
                    "Unable to load property classes"
                );
                populateCoveredAreas([]);
                window.console.error(error);
            }
        }

        assemblySelect.addEventListener("change", function () {
            loadClasses("", false);
        });

        propertyUseSelect.addEventListener("change", function () {
            loadClasses("", false);
        });

        propertyClassSelect.addEventListener("change", function () {
            const selectedValue = propertyClassSelect.value;

            if (!selectedValue) {
                populateCoveredAreas([]);
                return;
            }

            loadAreas(selectedValue);
        });

        const initialClassValue = propertyClassSelect.value;

        if (
            initialClassValue &&
            String(initialClassValue).startsWith(LEGACY_PREFIX)
        ) {
            return;
        }

        loadClasses(initialClassValue, true);
    }

    function start() {
        selectAllChosenAreasBeforeSubmit();

        window.setTimeout(function () {
            initialiseRatePolicyDependencies();
        }, 80);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
