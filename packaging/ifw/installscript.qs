function Component() {
}

Component.prototype.createOperations = function() {
    component.createOperations();

    if (systemInfo.productType === "windows") {
        component.addOperation(
            "CreateShortcut",
            "@TargetDir@/QGIS+.exe",
            "@StartMenuDir@/QGIS+.lnk"
        );
    }
}
