pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Effects
import App
import Theme

// "Acrylic" for the things that float (v2.5 F): menus, dialogs, toasts, side panels, the drag ghost. Recipe: a
// live ShaderEffectSource of the page area behind the overlay (AppState.blurSource, mapped to this item's
// geometry every frame while visible), blurred by MultiEffect (24 px; 12 for toasts) and masked to the rounded
// shape, then the tint (Theme.surfaceAcrylic = card at 70 % dark / 80 % light; `ghost` = card at 50 %), the grain
// on top, and a 1 px edge at 10 % white (Theme.borderEdge).
// Blur happens only with Appearance > Effects = Full AND a shader-capable scene graph: with Reduced / Off, or
// off-screen (the software renderer, where MultiEffect draws nothing), nothing GPU-side is created and the slot is
// the opaque card, so nothing is see-through and the text keeps its contrast. Never blur page content or cards.
// Place it in a floating thing's `acrylicSlot`, filling it, and make the body behind it transparent.
Item {
    id: root

    property bool active: true                  // the overlay wants acrylic (false = plain opaque card)
    readonly property bool blurOn: active && visible && AppState.blurAvailable && AppState.blurSource !== null && width > 0 && height > 0
    property int blurPx: Theme.ceilingBlurPx
    property real bottomLeftRadius: radius
    property real bottomRightRadius: radius
    property bool edge: true                    // the 10 % white hairline (drawn only while the glass shows)
    property bool ghost: false                  // the drag ghost: 50 % tint
    property real radius: Theme.radiusCard
    readonly property color tint: ghost ? Qt.rgba(Theme.surfaceCard.r, Theme.surfaceCard.g, Theme.surfaceCard.b, Theme.ceilingTintDragGhost) : Theme.surfaceAcrylic
    property real topLeftRadius: radius
    property real topRightRadius: radius

    Loader {  // the GPU part exists only while the blur shows
        active: root.blurOn
        anchors.fill: parent

        sourceComponent: Item {
            id: glass

            function track() {
                const p = root.mapToItem(AppState.blurSource, 0, 0);
                capture.sourceRect = Qt.rect(p.x, p.y, root.width, root.height);
            }

            Component.onCompleted: track()

            FrameAnimation {  // overlays move (slide in, drag): follow them every frame while the glass shows
                running: true

                onTriggered: glass.track()
            }
            ShaderEffectSource {
                id: capture

                anchors.fill: parent
                live: true
                recursive: false
                smooth: true
                sourceItem: AppState.blurSource
                visible: false
            }
            Rectangle {  // the rounded shape, as a mask texture
                id: mask

                anchors.fill: parent
                bottomLeftRadius: root.bottomLeftRadius
                bottomRightRadius: root.bottomRightRadius
                color: "black"
                layer.enabled: true
                topLeftRadius: root.topLeftRadius
                topRightRadius: root.topRightRadius
                visible: false
            }
            MultiEffect {
                anchors.fill: parent
                autoPaddingEnabled: false
                blur: 1.0
                blurEnabled: true
                blurMax: root.blurPx
                maskEnabled: true
                maskSource: mask
                source: capture
            }
        }
    }
    Rectangle {  // the tint over the blur, or the opaque card when there is no blur
        anchors.fill: parent
        bottomLeftRadius: root.bottomLeftRadius
        bottomRightRadius: root.bottomRightRadius
        color: root.blurOn ? root.tint : Theme.surfaceCard
        topLeftRadius: root.topLeftRadius
        topRightRadius: root.topRightRadius

        Behavior on color {
            ColorAnimation {
                duration: Theme.mToggle
                easing.type: Easing.OutCubic
            }
        }
    }
    Grain {  // only over the blurred capture (a gradient); an opaque card gets none (v2.15)
        strength: root.blurOn ? 0.6 : 0
        anchors.fill: parent
    }
    Rectangle {  // the 10 % white edge of the glass
        anchors.fill: parent
        border.color: Theme.borderEdge
        border.width: 1
        bottomLeftRadius: root.bottomLeftRadius
        bottomRightRadius: root.bottomRightRadius
        color: "transparent"
        topLeftRadius: root.topLeftRadius
        topRightRadius: root.topRightRadius
        visible: root.edge && root.blurOn
    }
}
