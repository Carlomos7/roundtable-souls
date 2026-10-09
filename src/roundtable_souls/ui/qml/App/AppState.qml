pragma Singleton
pragma ComponentBehavior: Bound
import QtQuick
import Theme

// The view state the components share: the theme mode, the atmosphere settings (effects, grain), what the scene
// graph can draw (blur, GPU shadows), and the toast channel. What the launcher knows (jobs, profiles, games) comes
// from each page's adapter, never from here.
QtObject {
    id: app

    // ---------------------------------------------------------------- atmosphere: what Acrylic / Grain / SoftShadow read
    readonly property bool blurAvailable: effects === "full" && !softwareRender   // Reduced / Off: no blur; software scene graph: no blur
    property Item blurSource: null                   // the page area the acrylic overlays blur
    property string effects: "full"                  // "full" | "reduced" | "off": glow, grain, blur budget
    property Loader gpuProbe: Loader {
        source: Qt.resolvedUrl("../Components/GpuShadow.qml")
    }
    // RectangularShadow needs Qt 6.9: probed once here, so an older Qt warns once, not once per SoftShadow
    readonly property bool gpuShadowAvailable: !softwareRender && gpuProbe.status === Loader.Ready
    property string grain: "subtle"                  // "off" | "subtle" | "film"
    readonly property real grainOpacity: effects === "off" || grain === "off" ? 0 : (grain === "film" ? (Theme.dark ? Theme.grainFilmDark : Theme.grainFilmLight) : (Theme.dark ? Theme.grainSubtleDark : Theme.grainSubtleLight)) * (effects === "reduced" ? 0.5 : 1)
    property Item overlayLayer: null                 // toasts and drag ghosts live here, outside what a blur samples

    // "System" follows the OS (Qt.styleHints.colorScheme); no answer from the platform keeps dark
    property Connections schemeWatch: Connections {
        function onColorSchemeChanged() {
            if (app.themeMode === "system")
                Theme.dark = app.systemDark();
        }

        target: Qt.styleHints
    }
    property bool softwareRender: false              // the window binds it to GraphicsInfo.api === Software (off-screen renders)
    property string themeMode: "dark"                // "dark" | "tarnished" | "light" | "system"

    // ---------------------------------------------------------------- toasts: one at a time; errors stay until closed
    signal toastRequested(string text, string actionLabel, var action, bool isError)

    function setThemeMode(mode) {  // Tarnished is dark with the olive variant
        themeMode = mode;
        Theme.dark = mode === "system" ? systemDark() : mode !== "light";
        Theme.variant = mode === "tarnished" ? "tarnished" : "";
    }
    function systemDark() {
        return Qt.styleHints.colorScheme !== Qt.ColorScheme.Light; // qmllint disable missing-property
    }
    function toast(text, actionLabel, action) {
        toastRequested(text, actionLabel || "", action || null, false);
    }
    function toastError(text, actionLabel, action) {
        toastRequested(text, actionLabel || "", action || null, true);
    }
}
