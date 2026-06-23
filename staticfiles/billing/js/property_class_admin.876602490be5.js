(function () {
    "use strict";

    function byId(id) {
        return document.getElementById(id);
    }

    function buildUrl(baseUrl, params) {
        const url = new URL(baseUrl, window.location.origin);

        Object.keys(params).forEach(function (key) {
            const value = params[key];

            if (
                value !== null
                && value !== undefined
                && value !== ""
            ) {
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
            throw new Error(
                "Unable to load community areas."
            );
        }

        return response.json();
    }

    function clearSelect(selectElement) {
        if (!selectElement) {
            return;
        }

        while (selectElement.options.length) {
            selectElement.remove(0);
        }
    }

    function clearSelectBoxCache(selectId) {
        if (
            window.SelectBox
            && window.SelectBox.cache
            && Object.prototype.hasOwnProperty.call(
                window.SelectBox.cache,
                selectId
            )
        ) {
            window.SelectBox.cache[selectId] = [];
        }
    }

    function refreshSelectBox(selectId) {
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

    function clearSearchInputs() {
        [
            "id_covered_areas_input",
            "id_covered_areas_selected_input"
        ].forEach(function (id) {
            const input = byId(id);

            if (!input) {
                return;
            }

            input.value = "";

            input.dispatchEvent(
                new Event(
                    "input",
                    {
                        bubbles: true
                    }
                )
            );
        });
    }

    function addOptions(
        selectElement,
        areas,
        selected
    ) {
        if (!selectElement) {
            return;
        }

        areas.forEach(function (area) {
            selectElement.add(
                new Option(
                    area.text,
                    String(area.id),
                    selected,
                    selected
                )
            );
        });
    }

    function populateCoveredAreas(areas) {
        const availableSelect = byId(
            "id_covered_areas_from"
        );

        const chosenSelect = byId(
            "id_covered_areas_to"
        );

        const originalSelect = byId(
            "id_covered_areas"
        );

        clearSearchInputs();

        if (availableSelect && chosenSelect) {
            clearSelect(availableSelect);
            clearSelect(chosenSelect);

            clearSelectBoxCache(
                availableSelect.id
            );

            clearSelectBoxCache(
                chosenSelect.id
            );

            addOptions(
                availableSelect,
                areas,
                false
            );

            refreshSelectBox(
                availableSelect.id
            );

            refreshSelectBox(
                chosenSelect.id
            );

            availableSelect.dispatchEvent(
                new Event(
                    "change",
                    {
                        bubbles: true
                    }
                )
            );

            chosenSelect.dispatchEvent(
                new Event(
                    "change",
                    {
                        bubbles: true
                    }
                )
            );

            return;
        }

        if (originalSelect) {
            clearSelect(originalSelect);

            addOptions(
                originalSelect,
                areas,
                false
            );

            originalSelect.dispatchEvent(
                new Event(
                    "change",
                    {
                        bubbles: true
                    }
                )
            );
        }
    }

    function setLoadingState() {
        const availableSelect = byId(
            "id_covered_areas_from"
        );

        const chosenSelect = byId(
            "id_covered_areas_to"
        );

        const originalSelect = byId(
            "id_covered_areas"
        );

        if (availableSelect && chosenSelect) {
            clearSelect(availableSelect);
            clearSelect(chosenSelect);

            availableSelect.add(
                new Option(
                    "Loading areas...",
                    ""
                )
            );

            clearSelectBoxCache(
                availableSelect.id
            );

            clearSelectBoxCache(
                chosenSelect.id
            );

            refreshSelectBox(
                availableSelect.id
            );

            refreshSelectBox(
                chosenSelect.id
            );

            return;
        }

        if (originalSelect) {
            clearSelect(originalSelect);

            originalSelect.add(
                new Option(
                    "Loading areas...",
                    ""
                )
            );
        }
    }

    function selectAllChosenAreasBeforeSubmit() {
        const form = document.querySelector(
            "form#propertyclass_form, form[method='post']"
        );

        if (!form) {
            return;
        }

        form.addEventListener(
            "submit",
            function () {
                const chosenSelect = byId(
                    "id_covered_areas_to"
                );

                const originalSelect = byId(
                    "id_covered_areas"
                );

                const targetSelect = (
                    chosenSelect
                    || originalSelect
                );

                if (!targetSelect) {
                    return;
                }

                Array.from(
                    targetSelect.options
                ).forEach(function (option) {
                    option.selected = true;
                });
            }
        );
    }

    function initialiseAssemblyAreaFilter() {
        const assemblySelect = byId(
            "id_assembly"
        );

        if (!assemblySelect) {
            return;
        }

        const areasUrl = (
            assemblySelect.dataset
                .communityAreasUrl
            || ""
        );

        if (!areasUrl) {
            return;
        }

        let requestSequence = 0;

        async function loadAreas() {
            const assemblyId = (
                assemblySelect.value
                || ""
            );

            const currentSequence = (
                ++requestSequence
            );

            if (!assemblyId) {
                populateCoveredAreas([]);
                return;
            }

            setLoadingState();

            try {
                const data = await getJson(
                    buildUrl(
                        areasUrl,
                        {
                            assembly: assemblyId
                        }
                    )
                );

                if (
                    currentSequence
                    !== requestSequence
                ) {
                    return;
                }

                populateCoveredAreas(
                    data.results || []
                );
            } catch (error) {
                if (
                    currentSequence
                    !== requestSequence
                ) {
                    return;
                }

                populateCoveredAreas([]);
                window.console.error(error);
            }
        }

        assemblySelect.addEventListener(
            "change",
            loadAreas
        );
    }

    function start() {
        selectAllChosenAreasBeforeSubmit();

        window.setTimeout(
            initialiseAssemblyAreaFilter,
            80
        );
    }

    if (
        document.readyState
        === "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            start
        );
    } else {
        start();
    }
})();
