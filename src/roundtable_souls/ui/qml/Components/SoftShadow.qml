pragma ComponentBehavior: Bound
import QtQuick
import Theme
import App

// The drop shadow (v2.5 D; rebuilt in v2.13). ONE elevation scale, picked by `elevation`:
//   "rest"   y1  blur 3   shadowRest   cards sitting on the page
//   "raise"  y4  blur 12  shadowMove   things that lift: drag ghosts, tooltips, teaching tips
//   "float"  y8  blur 24  shadowColor  menus, dialogs, toasts, side panels
// Shadows are never neutral (warm black in dark, blue-black in light: the tokens carry that).
// On a real window this is Qt's RectangularShadow (QtQuick.Effects, Qt 6.9+): a true gaussian, no texture, no layer,
// so it costs nothing to stack. The software scene graph (off-screen renders, the mock-up checks) draws no effects,
// so there the fallback is rings of 1 px with a gaussian-ish falloff, which read as a blur at these sizes.
// Place it as a sibling declared BEFORE the body and point `target` at the body; set `radius` to the body's.
Item {
    id: root

    property string elevation: "rest"
    property int blur: elevation === "float" ? 24 : elevation === "raise" ? 12 : 3
    property color color: elevation === "float" ? Theme.shadowColor : elevation === "raise" ? Theme.shadowMove : Theme.shadowRest
    property int offsetY: elevation === "float" ? 8 : elevation === "raise" ? 4 : 1
    property real radius: Theme.radiusCard
    property Item target: parent

    height: target ? target.height : 0
    width: target ? target.width : 0
    x: target ? target.x : 0
    y: target ? target.y + offsetY : 0

    Loader {  // the GPU shadow lives in GpuShadow.qml: on a Qt without RectangularShadow (< 6.9) AppState's one probe
        // fails and the rings below take over, instead of this whole component (and everything using it) failing to load
        id: gpuLoader

        anchors.fill: parent
        source: AppState.gpuShadowAvailable ? Qt.resolvedUrl("GpuShadow.qml") : ""

        onLoaded: {
            item.blurPx = Qt.binding(() => root.blur);
            item.shadowColor = Qt.binding(() => root.color);
            item.cornerRadius = Qt.binding(() => root.radius);
        }
    }
    Loader {
        anchors.fill: parent
        sourceComponent: AppState.gpuShadowAvailable ? null : rings
    }
    Component {
        id: rings

        Item {
            Repeater {  // 1 px rings; alpha ~ gaussian in the distance, scaled so the sum at the edge is color.a
                model: root.blur

                Rectangle {
                    id: ring

                    required property int index
                    readonly property real t: (index + 0.5) / root.blur
                    readonly property real weight: Math.exp(-t * t * 4.5)

                    anchors.fill: parent
                    anchors.margins: -(index + 1)
                    border.color: root.color
                    border.width: 1
                    color: "transparent"
                    opacity: Math.min(1, ring.weight * 2.6 / Math.max(1, root.blur / 4))
                    radius: root.radius + index + 1
                }
            }
            Rectangle {  // the body footprint, so the offset shows under the body's bottom edge
                anchors.fill: parent
                color: root.color
                radius: root.radius
            }
        }
    }
}
