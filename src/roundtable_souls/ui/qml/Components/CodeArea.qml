pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// A plain text editor (raw .me3, .ini or .txt; the README editor): monospace, 6% fill, no border at rest, accent
// ring while it has focus, danger when `error`. Scrollbar 6 px, round ends, shown on hover (v2.5 E). Ctrl+F opens
// the find / replace bar (v2.14, `findable`), which takes the editor's top edge while it is open.
Rectangle {
    id: root

    property bool error: false
    property bool findable: !readOnly
    property bool mono: true
    property bool readOnly: false
    property alias text: textArea.text

    signal edited

    color: Theme.fillInput
    implicitHeight: 200
    radius: Theme.radiusControl

    Behavior on color {
        ColorAnimation {
            duration: Theme.mToggle
            easing.type: Easing.OutCubic
        }
    }

    HoverHandler {
        id: hover
    }
    FocusRing {
        active: textArea.activeFocus
        error: root.error
        radiusOf: Theme.radiusControl
    }
    FindBar {
        id: findBar

        anchors.left: parent.left
        anchors.margins: Theme.sp4
        anchors.right: parent.right
        anchors.top: parent.top
        area: textArea
        z: 2
    }
    Shortcut {
        enabled: root.findable && root.visible && (textArea.activeFocus || findBar.open)
        sequences: [StandardKey.Find]

        onActivated: findBar.show()
    }
    Flickable {
        id: flick

        anchors.fill: parent
        anchors.margins: Theme.sp8
        anchors.topMargin: Theme.sp8 + (findBar.open ? findBar.height + Theme.sp4 : 0)
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        contentHeight: textArea.implicitHeight
        contentWidth: width

        ScrollBar.vertical: ScrollBar {
            id: bar

            policy: ScrollBar.AsNeeded

            contentItem: Rectangle {
                color: Theme.textTertiary
                implicitWidth: 6
                opacity: bar.pressed ? 1 : (hover.hovered || bar.active ? 0.8 : 0)
                radius: 3

                Behavior on opacity {
                    NumberAnimation {
                        duration: Theme.mFast
                        easing.type: Easing.OutCubic
                    }
                }
            }
        }
        TextArea.flickable: TextArea {
            id: textArea

            background: null
            color: Theme.textPrimary
            font.family: root.mono ? "Cascadia Mono" : Theme.fontFamily
            font.pixelSize: root.mono ? 13 : Theme.fontBody
            readOnly: root.readOnly
            selectedTextColor: Theme.textOnAccent
            selectionColor: Theme.accent
            wrapMode: TextArea.Wrap

            onTextChanged: if (activeFocus)
                root.edited()
        }
    }
}
