(function () {
    "use strict";

    function byId(id) {
        return document.getElementById(id);
    }

    function getSelectedAreaIds() {
        const selectedIds = new Set();

        const chosenSelect = byId(
            "id_covered_areas_to"
        );

        const originalSelect = byId(
            "id_covered_areas"
        );

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

    function clearSelect(selectElement) {
        if (!selectElement) {
            return;
        }

        while (
            selectElement.options.length
        ) {
            selectElement.remove(0);
        }
    }

    function resetSelectBox(
        selectElement
    ) {
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

    function dispatchSelectChange(
        selectElement
    ) {
        if (!selectElement) {
            return;
        }

        selectElement.dispatchEvent(
            new Event(
                "change",
                {
                    bubbles: true
                }
            )
        );
    }

    function createAreaOption(
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

        const originalSelect = byId(
            "id_covered_areas"
        );

        const preservedIds = (
            selectedIds
            || new Set()
        );

        if (
            availableSelect
            && chosenSelect
        ) {
            clearSelect(
                availableSelect
            );

            clearSelect(
                chosenSelect
            );

            areas.forEach(
                function (area) {
                    const areaId = String(
                        area.id
                    );

                    if (
                        preservedIds.has(
                            areaId
                        )
                    ) {
                        chosenSelect.add(
                            createAreaOption(
                                area,
                                true
                            )
                        );
                    } else {
                        availableSelect.add(
                            createAreaOption(
                                area,
                                false
                            )
                        );
                    }
                }
            );

            resetSelectBox(
                availableSelect
            );

            resetSelectBox(
                chosenSelect
            );

            dispatchSelectChange(
                availableSelect
            );

            dispatchSelectChange(
                chosenSelect
            );

            return;
        }

        if (originalSelect) {
            clearSelect(
                originalSelect
            );

            areas.forEach(
                function (area) {
                    const areaId = String(
                        area.id
                    );

                    const isSelected = (
                        preservedIds.has(
                            areaId
                        )
                    );

                    originalSelect.add(
                        createAreaOption(
                            area,
                            isSelected
                        )
                    );
                }
            );

            dispatchSelectChange(
                originalSelect
            );
        }
    }

    function renderMessage(message) {
        const availableSelect = byId(
            "id_covered_areas_from"
        );

        const chosenSelect = byId(
            "id_covered_areas_to"
        );

        const originalSelect = byId(
            "id_covered_areas"
        );

        const messageOption = new Option(
            message,
            ""
        );

        messageOption.disabled = true;

        if (
            availableSelect
            && chosenSelect
        ) {
            clearSelect(
                availableSelect
            );

            clearSelect(
                chosenSelect
            );

            availableSelect.add(
                messageOption
            );

            resetSelectBox(
                availableSelect
            );

            resetSelectBox(
                chosenSelect
            );

            return;
        }

        if (originalSelect) {
            clearSelect(
                originalSelect
            );

            originalSelect.add(
                messageOption
            );
        }
    }

    function buildAreasUrl(
        baseUrl,
        assemblyId
    ) {
        const url = new URL(
            baseUrl,
            window.location.origin
        );

        url.searchParams.set(
            "assembly",
            assemblyId
        );

        return url.toString();
    }

    async function fetchAreas(
        baseUrl,
        assemblyId
    ) {
        const response = await fetch(
            buildAreasUrl(
                baseUrl,
                assemblyId
            ),
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
                "Unable to load covered areas."
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
                ).forEach(
                    function (option) {
                        if (option.value) {
                            option.selected = true;
                        }
                    }
                );
            }
        );
    }

    function initialiseAreaFiltering() {
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
                "The community areas URL "
                + "is missing from the "
                + "Assembly field."
            );

            renderMessage(
                "Areas could not be loaded"
            );

            return;
        }

        let isInitialLoad = true;
        let requestSequence = 0;

        async function loadAreas() {
            const assemblyId = (
                assemblySelect.value
                || ""
            );

            const currentRequest = (
                ++requestSequence
            );

            const selectedIds = (
                isInitialLoad
                ? getSelectedAreaIds()
                : new Set()
            );

            isInitialLoad = false;

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
                    areasUrl,
                    assemblyId
                );

                if (
                    currentRequest
                    !== requestSequence
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
                    !== requestSequence
                ) {
                    return;
                }

                renderMessage(
                    "Areas could not be loaded"
                );

                window.console.error(
                    error
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

    function waitForDjangoAdminWidget() {
        let attempts = 0;

        const timer = window.setInterval(
            function () {
                attempts += 1;

                const filteredWidgetReady = Boolean(
                    byId(
                        "id_covered_areas_from"
                    )
                );

                const plainSelectReady = Boolean(
                    byId(
                        "id_covered_areas"
                    )
                ) && attempts >= 5;

                if (
                    filteredWidgetReady
                    || plainSelectReady
                    || attempts >= 40
                ) {
                    window.clearInterval(
                        timer
                    );

                    initialiseAreaFiltering();
                }
            },
            100
        );
    }

    if (
        document.readyState
        === "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            waitForDjangoAdminWidget
        );
    } else {
        waitForDjangoAdminWidget();
    }
})();
