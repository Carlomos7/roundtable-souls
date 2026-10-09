pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// The primary button (v2.9 "gilded"): a faint accent wash, a 1 px accent outline, a top sheen and accent text; hover
// brightens the wash and outline and lights a thin halo at the edge (v2.12). Never a solid fill. `danger` is the red outline variant.
// One primary per view (v2.10). Press: scale 0.98 for 60 ms.
Button {
    id: root

    property bool danger: false
    property bool dropDown: false       // shows a chevron; the caller opens its menu on click
    readonly property color fg: !enabled ? Theme.textDisabled : danger ? Theme.statusDanger : Theme.goldText
    property string icon_: ""

    focusPolicy: Qt.TabFocus
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontBody
    font.weight: Font.DemiBold
    hoverEnabled: true
    implicitHeight: Theme.controlH
    implicitWidth: Math.max(Theme.buttonMinW, row.implicitWidth + Theme.sp16 * 2)
    opacity: enabled ? 1 : 0.5
    scale: down ? 0.98 : 1

    background: Item {
        GildedFrame {
            anchors.fill: parent
            dim: !root.enabled
            hot: root.hovered && root.enabled
            pressed: root.down
            radius: Theme.radiusControl
            visible: !root.danger
        }
        Rectangle {  // danger: red outline, red tint on hover
            anchors.fill: parent
            border.color: root.hovered ? Theme.statusDanger : Qt.rgba(Theme.statusDanger.r, Theme.statusDanger.g, Theme.statusDanger.b, 0.55)
            border.width: 1
            color: root.hovered ? Theme.statusDangerBg : "transparent"
            radius: Theme.radiusControl
            visible: root.danger
        }
        FocusRing {
            active: root.visualFocus
            radiusOf: Theme.radiusControl
        }
    }
    contentItem: Row {
        id: row

        anchors.centerIn: parent
        spacing: Theme.sp8

        FluentIcon {
            anchors.verticalCenter: parent.verticalCenter
            color: root.fg
            name: root.icon_
            size: 16
            visible: root.icon_ !== ""
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            color: root.fg
            font: root.font
            text: root.text
        }
        FluentIcon {
            anchors.verticalCenter: parent.verticalCenter
            color: root.fg
            name: "ChevronDown"
            size: 12
            visible: root.dropDown
        }
    }
    Behavior on scale {
        NumberAnimation {
            duration: Theme.mPress
            easing.type: Easing.OutCubic
        }
    }
}
