pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import Theme

// A quiet button that opens a PopupMenu under itself (the game and profile drop-downs).
GhostButton {
    id: root

    property alias menu: dropMenu
    default property alias menuContent: dropMenu.contentData
    property url thumb: ""   // v2.15: a small picture of the current choice (the game picker)
    readonly property bool hasThumb: String(thumb).length > 0
    property url thumbFallback: ""
    readonly property var win: Window.window   // the attached property, read once (qmllint cannot see root.Window)

    property int fixedWidth: 0   // v2.16: pickers in forms and the top bar are fixed, so a longer choice never moves the row

    implicitWidth: fixedWidth > 0 ? fixedWidth : Math.max(Theme.buttonMinW, contentItem.implicitWidth + 44)

    contentItem: Row {
        anchors.centerIn: parent
        spacing: Theme.sp8

        Thumb {
            anchors.verticalCenter: parent.verticalCenter
            size: 20
            fallback: root.thumbFallback
            source: root.thumb
            visible: root.hasThumb
        }
        FluentIcon {
            anchors.verticalCenter: parent.verticalCenter
            color: root.fg
            name: root.icon_
            size: 16
            visible: root.icon_ !== "" && !root.hasThumb
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            color: root.fg
            elide: Text.ElideRight
            font: root.font
            text: root.text
            width: root.fixedWidth > 0 ? Math.max(24, root.fixedWidth - 44 - (root.hasThumb ? 28 : root.icon_ !== "" ? 24 : 0)) : implicitWidth

            Behavior on color {
                ColorAnimation {
                    duration: Theme.mToggle
                    easing.type: Easing.OutCubic
                }
            }
        }
        FluentIcon {
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.textSecondary
            name: "ChevronDown"
            size: 12
        }
    }

    onClicked: dropMenu.open()

    PopupMenu {  // v2.15: opens below, flips above when the window has no room below; never wider than the window
        id: dropMenu

        readonly property real roomBelow: root.win ? root.win.height - root.mapToItem(null, 0, root.height).y - Theme.sp8 : 9999

        minWidth: root.width
        width: Math.min(Math.max(minWidth, widestEntry + padding * 2), root.win ? root.win.width - Theme.sp16 : 9999)
        y: implicitHeight <= roomBelow ? root.height + Theme.sp4 : -implicitHeight - Theme.sp4
    }
}
