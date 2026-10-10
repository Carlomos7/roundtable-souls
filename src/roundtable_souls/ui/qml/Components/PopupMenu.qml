pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// A drop-down menu. Fill it with MenuEntry / MenuSep / nested PopupMenu (title: ...). Floats (v2.5 D): no border,
// shadow y8 blur24 45%. Acrylic hook for the atmosphere agent: `acrylic` and `acrylicSlot` sit behind the content;
// the Acrylic in the slot blurs the page behind (Effects = Full) and tints it with Theme.surfaceAcrylic (v2.5 F).
Menu {
    id: root

    property bool acrylic: false   // v2.15 (owner): menus are opaque too
    property int minWidth: 200

    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontBody
    margins: 8
    padding: Theme.sp6
    readonly property real widestEntry: {  // Menu's implicitContentWidth ignores the delegates; measure them (v2.15)
        let w = 0;
        for (let i = 0; i < count; i++) {
            const it = itemAt(i);
            if (it)
                w = Math.max(w, it.implicitWidth);
        }
        return w;
    }

    width: Math.max(minWidth, widestEntry + padding * 2)
    height: Math.min(implicitHeight, (Overlay.overlay ? Overlay.overlay.height : 9999) - Theme.sp16)  // v2.15: long menus scroll

    background: Item {
        implicitWidth: root.minWidth

        SoftShadow {
            elevation: "float"
            radius: Theme.radiusOverlay
            target: body
        }
        Item {
            id: acrylicSlot

            anchors.fill: parent

            Acrylic {  // 24 px blur of the page behind + the 70 / 80 % card tint; the opaque card without blur
                active: root.acrylic
                anchors.fill: parent
                radius: Theme.radiusOverlay
            }
        }
        Rectangle {  // the shape the shadow follows; the acrylic paints the fill
            id: body

            anchors.fill: parent
            color: "transparent"
            radius: Theme.radiusOverlay
        }
    }

    // A submenu shown as a row with a chevron
    delegate: MenuEntry {
    }
    enter: Transition {
        NumberAnimation {
            duration: Theme.mPage
            easing.type: Easing.OutCubic
            from: 0
            property: "opacity"
            to: 1
        }
    }
    exit: Transition {
        NumberAnimation {
            duration: Theme.mFast
            easing.type: Easing.OutCubic
            from: 1
            property: "opacity"
            to: 0
        }
    }
}
