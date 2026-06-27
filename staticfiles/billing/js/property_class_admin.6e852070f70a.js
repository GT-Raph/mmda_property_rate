(function () {
    "use strict";

    function byId(id) {
        return document.getElementById(id);
    }

    function buildUrl(baseUrl, params) {
        const url = new URL(
            baseUrl,
            window.location.origin
        );

        Object.keys(params).forEach(function (key) {
            const value = params[key];

            if (
                value !== null
                && value !== undefined
                && value !== ""
            ) {
                url.searchParams.set(
                    key,
                    value
                );
            }
        });

        return url.toString();
    }

    async function getJson(url) {
        const response = await fetch(
            url,
            {
                method: "GET",
                credentials: "same-origin",
                headers: {
                    "X-Requested-With":
                        "XMLHttpRequest"
                }
            }
        );

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
        ) {
            window.SelectBox.cache[selectId] = [];
        }
    }

    function initialiseSelectBox(selectId) {
        if (!window.SelectBox) {
            return;
        }

        const selectElement = byId(selectId);

        if (!selectElement) {
            return;
        }

        clearSelectBoxCache(selectId);
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
        });
    }

    function getChosenAreaIds() {
        const chosenSelect = byId(
            "id_covered_areas_to"
        );

        const originalSelect = byId(
            "id_covered_areas"
        );

        const selectedIds = new Set();

        if (chosenSelect) {
            Array.from(
                chosenSelect.options
            ).forEach(function (option) {
                if (option.value) {
                    selectedIds.add(
                        String(option.value)
                    );
                }
            });
        }

        if (originalSelect) {
            Array.from(
                originalSelect.options
            ).forEach(function (option) {
                if (
                    option.selected
                    && option.value
                ) {
                    selectedIds.add(
                        String(option.value)
                    );
                }
            });
        }

        return selectedIds;
    }

    function addOption(
        selectElement,
        area,
        selected
    ) {
        if (!selectElement) {
            return;
        }

        selectElement.add(
            new Option(
                area.text,
                String(area.id),
                selected,
                selected
            )
        );
    }

    function populateCoveredAreas(
        areas,
        chosenIds
    ) {
        const availableSelect = byId(
            "id_covered_areas_from"
        );

        const chosenSelect = byId(
            "id_covered_areas_to"
        );

        const originalSelect = byId(
            "id_covered_areas"
        );

        const selectedIds = (
            chosenIds
            || new Set()
        );

        clearSearchInputs();

        if (availableSelect && chosenSelect) {
            clearSelect(availableSelect);
            clearSelect(chosenSelect);

            areas.forEach(function (area) {
                const areaId = String(area.id);

                if (selectedIds.has(areaId)) {
                    addOption(
                        chosenSelect,
                        area,
                        true
                    );
                } else {
                    addOption(
                        availableSelect,
                        area,
                        false
                    );
                }
            });

            initialiseSelectBox(
                availableSelect.id
            );

            initialiseSelectBox(
                chosenSelect.id
            );

            return;
        }

        if (originalSelect) {
            clearSelect(originalSelect);

            areas.forEach(function (area) {
                const isSelected = (
                    selectedIds.has(
                        String(area.id)
                    )
                );

                addOption(
                    originalSelect,
                    area,
                    isSelected
                );
            });
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

            initialiseSelectBox(
                availableSelect.id
            );

            initialiseSelectBox(
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

    function showLoadFailure() {
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
                    "Areas could not be loaded",
                    ""
                )
            );

            initialiseSelectBox(
                availableSelect.id
            );

            initialiseSelectBox(
                chosenSelect.id
            );

            return;
        }

        if (originalSelect) {
            clearSelect(originalSelect);

            originalSelect.add(
                new Option(
                    "Areas could not be loaded",
                    ""
                )
            );
        }
    }

    function selectAllChosenAreasBeforeSubmit() {
        const form = document.querySelector(
            "form#propertyclass_form"
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
            window.console.error(
                "Community area URL is missing from the Assembly field."
            );

            return;
        }

        let requestSequence = 0;
        let firstLoad = true;

        async function loadAreas() {
            const assemblyId = (
                assemblySelect.value
                || ""
            );

            const currentSequence = (
                ++requestSequence
            );

            /*
             * Preserve already-selected areas only on the initial page load.
             * If the user changes the assembly, old selections must be cleared
             * because they belong to a different assembly.
             */
            const chosenIds = firstLoad
                ? getChosenAreaIds()
                : new Set();

            firstLoad = false;

            if (!assemblyId) {
                populateCoveredAreas(
                    [],
                    new Set()
                );

                return;
            }

            setLoadingState();

            try {
                const data = await getJson(
                    buildUrl(
                        areasUrl,
                        {
                            assembly:
                                assemblyId
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
                    data.results || [],
                    chosenIds
                );
            } catch (error) {
                if (
                    currentSequence
                    !== requestSequence
                ) {
                    return;
                }

                showLoadFailure();
                window.console.error(error);
            }
        }

        assemblySelect.addEventListener(
            "change",
            loadAreas
        );

        /*
         * Important: Django can display the first Assembly as selected when
         * the add form opens. A change event has not happened yet, so the
         * areas must also be loaded immediately on page load.
         */
        loadAreas();
    }

    function start() {
        selectAllChosenAreasBeforeSubmit();

        window.setTimeout(
            initialiseAssemblyAreaFilter,
            100
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
