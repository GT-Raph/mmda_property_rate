(function () {
    "use strict";

    function byId(id) {
        return document.getElementById(id);
    }

    function clearSelect(selectElement) {
        if (!selectElement) {
            return;
        }

        while (selectElement.options.length) {
            selectElement.remove(0);
        }
    }

    function getChosenAreaIds() {
        const selectedIds = new Set();

        const chosenSelect = byId(
            "id_covered_areas_to"
        );

        if (!chosenSelect) {
            return selectedIds;
        }

        Array.from(
            chosenSelect.options
        ).forEach(function (option) {
            if (option.value) {
                selectedIds.add(
                    String(option.value)
                );
            }
        });

        return selectedIds;
    }

    function resetSelectBox(selectElement) {
        if (
            !selectElement
            || !window.SelectBox
        ) {
            return;
        }

        if (!window.SelectBox.cache) {
            window.SelectBox.cache = {};
        }

        window.SelectBox.cache[
            selectElement.id
        ] = [];

        window.SelectBox.init(
            selectElement.id
        );

        window.SelectBox.redisplay(
            selectElement.id
        );
    }

    function createOption(
        area,
        selected
    ) {
        return new Option(
            area.text,
            String(area.id),
            selected,
            selected
        );
    }

    function renderAreas(
        areas,
        selectedIds
    ) {
        const availableSelect = byId(
            "id_covered_areas_from"
        );

        const chosenSelect = byId(
            "id_covered_areas_to"
        );

        if (
            !availableSelect
            || !chosenSelect
        ) {
            return;
        }

        clearSelect(availableSelect);
        clearSelect(chosenSelect);

        const preservedIds = (
            selectedIds
            || new Set()
        );

        areas.forEach(function (area) {
            const areaId = String(
                area.id
            );

            if (preservedIds.has(areaId)) {
                chosenSelect.add(
                    createOption(
                        area,
                        true
                    )
                );
            } else {
                availableSelect.add(
                    createOption(
                        area,
                        false
                    )
                );
            }
        });

        resetSelectBox(
            availableSelect
        );

        resetSelectBox(
            chosenSelect
        );
    }

    function renderMessage(message) {
        const availableSelect = byId(
            "id_covered_areas_from"
        );

        const chosenSelect = byId(
            "id_covered_areas_to"
        );

        if (
            !availableSelect
            || !chosenSelect
        ) {
            return;
        }

        clearSelect(availableSelect);
        clearSelect(chosenSelect);

        const option = new Option(
            message,
            ""
        );

        option.disabled = true;

        availableSelect.add(option);

        resetSelectBox(
            availableSelect
        );

        resetSelectBox(
            chosenSelect
        );
    }

    function getEndpoint(
        assemblySelect
    ) {
        const configuredEndpoint = (
            assemblySelect.dataset
                .communityAreasUrl
            || ""
        );

        if (configuredEndpoint) {
            return configuredEndpoint;
        }

        let basePath = (
            window.location.pathname
        );

        basePath = basePath.replace(
            /add\/$/,
            ""
        );

        basePath = basePath.replace(
            /[^/]+\/change\/$/,
            ""
        );

        return (
            basePath
            + "ajax/community-areas/"
        );
    }

    async function fetchAreas(
        endpoint,
        assemblyId
    ) {
        const url = new URL(
            endpoint,
            window.location.origin
        );

        url.searchParams.set(
            "assembly",
            assemblyId
        );

        const response = await fetch(
            url.toString(),
            {
                method: "GET",
                credentials: "same-origin",
                headers: {
                    "X-Requested-With":
                        "XMLHttpRequest",
                },
            }
        );

        if (!response.ok) {
            throw new Error(
                "Unable to load community areas."
            );
        }

        return response.json();
    }

    function selectChosenAreasBeforeSubmit() {
        const form = byId(
            "propertyclass_form"
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

                if (!chosenSelect) {
                    return;
                }

                Array.from(
                    chosenSelect.options
                ).forEach(function (option) {
                    if (option.value) {
                        option.selected = true;
                    }
                });
            }
        );
    }

    function initialiseFiltering() {
        const assemblySelect = byId(
            "id_assembly"
        );

        const availableSelect = byId(
            "id_covered_areas_from"
        );

        const chosenSelect = byId(
            "id_covered_areas_to"
        );

        if (
            !assemblySelect
            || !availableSelect
            || !chosenSelect
        ) {
            return;
        }

        const endpoint = getEndpoint(
            assemblySelect
        );

        const initialAssemblyId = (
            assemblySelect.value
            || ""
        );

        const initialChosenIds = (
            getChosenAreaIds()
        );

        let requestNumber = 0;
        let firstLoad = true;

        async function loadAreas() {
            const assemblyId = (
                assemblySelect.value
                || ""
            );

            const currentRequest = (
                ++requestNumber
            );

            let selectedIds = new Set();

            if (
                firstLoad
                && assemblyId
                === initialAssemblyId
            ) {
                selectedIds = (
                    initialChosenIds
                );
            }

            firstLoad = false;

            if (!assemblyId) {
                renderAreas(
                    [],
                    new Set()
                );

                return;
            }

            renderMessage(
                "Loading areas..."
            );

            try {
                const data = await fetchAreas(
                    endpoint,
                    assemblyId
                );

                if (
                    currentRequest
                    !== requestNumber
                ) {
                    return;
                }

                renderAreas(
                    data.results || [],
                    selectedIds
                );
            } catch (error) {
                if (
                    currentRequest
                    !== requestNumber
                ) {
                    return;
                }

                window.console.error(
                    error
                );

                renderMessage(
                    "Areas could not be loaded"
                );
            }
        }

        assemblySelect.addEventListener(
            "change",
            loadAreas
        );

        selectChosenAreasBeforeSubmit();

        loadAreas();
    }

    function waitForFilteredSelectWidget() {
        let attempts = 0;

        const timer = window.setInterval(
            function () {
                attempts += 1;

                const availableSelect = byId(
                    "id_covered_areas_from"
                );

                const chosenSelect = byId(
                    "id_covered_areas_to"
                );

                const widgetIsReady = Boolean(
                    availableSelect
                    && chosenSelect
                    && window.SelectBox
                );

                if (widgetIsReady) {
                    window.clearInterval(
                        timer
                    );

                    initialiseFiltering();

                    return;
                }

                if (attempts >= 100) {
                    window.clearInterval(
                        timer
                    );

                    window.console.error(
                        "The Django covered areas "
                        + "widget did not initialise."
                    );
                }
            },
            50
        );
    }

    if (
        document.readyState
        === "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            waitForFilteredSelectWidget
        );
    } else {
        waitForFilteredSelectWidget();
    }
})();