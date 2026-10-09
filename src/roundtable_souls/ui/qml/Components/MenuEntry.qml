pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// One menu row: an optional icon, the label, an optional shortcut hint, a check mark when `checked`, hover and
// pressed fills (rows: 4% hover, the ramp's pressed). A submenu shows a chevron.
MenuItem {
    id: root

    property string icon_: ""
    property string shortcut: ""
    property url thumb: ""
    readonly property bool hasThumb: String(thumb).length > 0
    property url thumbFallback: ""         // v2.15: a small picture left of the label (the game pickers); the check moves right

    checkable: checked
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontBody
    hoverEnabled: true
    implicitHeight: Theme.controlH
    opacity: enabled ? 1 : 0.5

    background: Rectangle {
        color: root.down ? Theme.surfacePressed : root.highlighted || root.hovered ? Theme.fillHover : "transparent"
        radius: Theme.radiusControl

        Behavior on color {
            ColorAnimation {
                duration: Theme.mFast
                easing.type: Easing.OutCubic
            }
        }
    }
    contentItem: Item {
        implicitHeight: Theme.controlH
        implicitWidth: lab.implicitWidth + sc.implicitWidth + 70 + (root.hasThumb ? 24 : 0)

        FluentIcon {
            anchors.left: root.hasThumb ? undefined : parent.left
            anchors.leftMargin: Theme.sp12
            anchors.right: root.hasThumb ? parent.right : undefined
            anchors.rightMargin: Theme.sp12
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.accent
            name: "Accept"
            size: 12
            visible: root.checkable && root.checked
        }
        Thumb {
            anchors.left: parent.left
            anchors.leftMargin: Theme.sp8
            anchors.verticalCenter: parent.verticalCenter
            fallback: root.thumbFallback
            source: root.thumb
            visible: root.hasThumb
        }
        FluentIcon {
            anchors.left: parent.left
            anchors.leftMargin: Theme.sp12
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.textIcon
            name: root.icon_
            size: 16
            visible: root.icon_ !== "" && !(root.checkable && root.checked)
        }
        Text {
            id: lab

            anchors.left: parent.left
            anchors.leftMargin: root.hasThumb ? Theme.sp8 + 24 + Theme.sp8 : root.icon_ !== "" || root.checkable ? 34 : 12
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.textPrimary
            font: root.font
            text: root.text

            Behavior on color {
                ColorAnimation {
                    duration: Theme.mToggle
                    easing.type: Easing.OutCubic
                }
            }
        }
        Text {
            id: sc

            anchors.right: parent.right
            anchors.rightMargin: root.subMenu ? 28 : 12
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            text: root.shortcut
        }
        FluentIcon {
            anchors.right: parent.right
            anchors.rightMargin: Theme.sp12
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.textSecondary
            name: "ChevronRight"
            size: 12
            visible: root.subMenu !== null
        }
    }
}
