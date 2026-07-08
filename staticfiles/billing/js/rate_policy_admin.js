(function () {
    function onReady(callback) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", callback);
        } else {
            callback();
        }
    }

    function getField(id) {
        return document.getElementById(id);
    }

    function getValue(id) {
        const field = getField(id);
        return field ? field.value : "";
    }

    function clearSelect(select) {
        if (!select) {
            return;
        }

        while (select.options.length) {
            select.remove(0);
        }
    }

    function addOption(select, value, text, selected) {
        if (!select) {
            return;
        }

        const option = new Option(
            text,
            value,
            selected || false,
            selected || false
        );

        select.add(option);
    }

    function getAreaResults(data) {
        if (!data) {
            return [];
        }

        if (Array.isArray(data.results)) {
            return data.results;
        }

        if (Array.isArray(data.areas)) {
            return data.areas;
        }

        return [];
    }

    function clearCoveredAreas() {
        const originalSelect = getField("id_covered_areas");
        const availableSelect = getField("id_covered_areas_from");
        const chosenSelect = getField("id_covered_areas_to");

        clearSelect(originalSelect);
        clearSelect(availableSelect);
        clearSelect(chosenSelect);
    }

    function setCoveredAreas(areas) {
        const originalSelect = getField("id_covered_areas");
        const availableSelect = getField("id_covered_areas_from");
        const chosenSelect = getField("id_covered_areas_to");

        clearSelect(originalSelect);
        clearSelect(availableSelect);
        clearSelect(chosenSelect);

        areas.forEach(function (area) {
            const value = String(area.id);
            const text = area.text || area.name || value;

            addOption(
                originalSelect,
                value,
                text,
                true
            );

            addOption(
                chosenSelect,
                value,
                text,
                false
            );
        });

        const helpText = document.querySelector(
            ".field-covered_areas .help, .form-row.field-covered_areas .help"
        );

        if (helpText) {
            if (areas.length) {
                helpText.textContent = (
                    areas.length +
                    " covered area" +
                    (areas.length === 1 ? "" : "s") +
                    " loaded automatically from the selected Property class."
                );
            } else {
                helpText.textContent = (
                    "No covered areas are assigned to the selected Property class."
                );
            }
        }
    }

    async function loadCoveredAreas() {
        const propertyClassField = getField("id_property_class");

        if (!propertyClassField) {
            return;
        }

        const propertyClassId = propertyClassField.value;
        const url = propertyClassField.dataset.propertyClassAreasUrl;

        clearCoveredAreas();

        if (!propertyClassId || !url) {
            return;
        }

        const requestUrl = (
            url +
            "?property_class=" +
            encodeURIComponent(propertyClassId)
        );

        try {
            const response = await fetch(
                requestUrl,
                {
                    headers: {
                        "Accept": "application/json",
                    },
                }
            );

            if (!response.ok) {
                console.error(
                    "Could not load covered areas:",
                    response.status
                );
                return;
            }

            const data = await response.json();
            const areas = getAreaResults(data);

            setCoveredAreas(areas);

        } catch (error) {
            console.error(
                "Covered areas AJAX failed:",
                error
            );
        }
    }

    async function loadPropertyClasses() {
        const assemblyField = getField("id_assembly");
        const propertyUseField = getField("id_property_use");
        const propertyClassField = getField("id_property_class");

        if (!assemblyField || !propertyClassField) {
            return;
        }

        const url = (
            assemblyField.dataset.propertyClassesUrl ||
            propertyUseField?.dataset.propertyClassesUrl ||
            ""
        );

        if (!url) {
            return;
        }

        const assemblyId = getValue("id_assembly");
        const propertyUse = getValue("id_property_use");

        clearSelect(propertyClassField);
        addOption(
            propertyClassField,
            "",
            "---------",
            false
        );

        clearCoveredAreas();

        if (!assemblyId) {
            return;
        }

        const requestUrl = (
            url +
            "?assembly=" +
            encodeURIComponent(assemblyId) +
            "&property_use=" +
            encodeURIComponent(propertyUse || "")
        );

        try {
            const response = await fetch(
                requestUrl,
                {
                    headers: {
                        "Accept": "application/json",
                    },
                }
            );

            if (!response.ok) {
                console.error(
                    "Could not load property classes:",
                    response.status
                );
                return;
            }

            const data = await response.json();
            const results = Array.isArray(data.results)
                ? data.results
                : [];

            results.forEach(function (item) {
                addOption(
                    propertyClassField,
                    String(item.id),
                    item.text || item.name || String(item.id),
                    false
                );
            });

            if (results.length === 1) {
                propertyClassField.value = String(
                    results[0].id
                );

                await loadCoveredAreas();
            }

        } catch (error) {
            console.error(
                "Property class AJAX failed:",
                error
            );
        }
    }

    function prepareCoveredAreasForSubmit() {
        const originalSelect = getField("id_covered_areas");
        const chosenSelect = getField("id_covered_areas_to");

        if (originalSelect) {
            Array.from(originalSelect.options).forEach(function (option) {
                option.selected = true;
            });
        }

        if (chosenSelect) {
            Array.from(chosenSelect.options).forEach(function (option) {
                option.selected = true;
            });
        }
    }

    onReady(function () {
        const assemblyField = getField("id_assembly");
        const propertyUseField = getField("id_property_use");
        const propertyClassField = getField("id_property_class");
        const form = document.querySelector("form");

        if (assemblyField) {
            assemblyField.addEventListener(
                "change",
                loadPropertyClasses
            );
        }

        if (propertyUseField) {
            propertyUseField.addEventListener(
                "change",
                loadPropertyClasses
            );
        }

        if (propertyClassField) {
            propertyClassField.addEventListener(
                "change",
                loadCoveredAreas
            );

            if (propertyClassField.value) {
                loadCoveredAreas();
            }
        }

        if (form) {
            form.addEventListener(
                "submit",
                prepareCoveredAreasForSubmit
            );
        }
    });
})();