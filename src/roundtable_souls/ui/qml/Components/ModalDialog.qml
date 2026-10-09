pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// A modal dialog (v2.3 C.4): the title states the question, the body the consequence and the safety net; buttons
// are verbs, the destructive one red, Cancel always present and rightmost; Esc cancels; nothing has keyboard
// focus, so Enter never triggers the destructive button. Pass the buttons in order, Cancel last.
// Floats (v2.5 D): no border, the "float" shadow; the footer is a 6% tint, no line. Acrylic hook: `acrylic` and
// `acrylicSlot` behind the body holds the Acrylic (blur + Theme.surfaceAcrylic; v2.5 F).
// Responsive (v2.13): width clamps to the window minus 2 x padDialog, height to the window minus 2 x padDialog, and
// the body scrolls when it does not fit (header and footer stay put). Inset is padDialog on every side.
Dialog {
    id: root

    property bool acrylic: false   // v2.15 (owner): overlays are opaque; the blur is opt-in per instance
    default property alias body: bodyItem.data
    property alias footerRow: footerRowItem.data
    property int preferredWidth: 520
    property string subtitle: ""

    readonly property int windowH: parent ? parent.height : 600
    readonly property int windowW: parent ? parent.width : 800

    anchors.centerIn: parent
    closePolicy: Popup.CloseOnEscape
    focus: true
    height: Math.min(implicitHeight, windowH - Theme.padDialog * 2)
    modal: true
    padding: 0
    parent: Overlay.overlay
    width: Math.min(preferredWidth, windowW - Theme.padDialog * 2)

    Overlay.modal: Rectangle {
        color: Theme.fillScrim
    }
    background: Item {
        SoftShadow {
            elevation: "float"
            radius: Theme.radiusOverlay
            target: panel
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
            id: panel

            anchors.fill: parent
            color: "transparent"
            radius: Theme.radiusOverlay
        }
    }
    contentItem: Flickable {  // the body: scrolls only when the dialog had to shrink to the window
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        contentHeight: bodyItem.implicitHeight
        contentWidth: width
        implicitHeight: bodyItem.implicitHeight
        implicitWidth: root.width - Theme.padDialog * 2

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        Item {
            id: bodyItem

            implicitHeight: childrenRect.height + Theme.sp4
            width: root.width - Theme.padDialog * 2
            x: Theme.padDialog
        }
    }
    enter: Transition {
        ParallelAnimation {
            NumberAnimation {
                duration: Theme.mPage
                easing.type: Easing.OutCubic
                from: 0
                property: "opacity"
                to: 1
            }
            NumberAnimation {
                duration: Theme.mPage
                easing.type: Easing.OutCubic
                from: 0.98
                property: "scale"
                to: 1
            }
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
    footer: Rectangle {
        bottomLeftRadius: Theme.radiusOverlay
        bottomRightRadius: Theme.radiusOverlay
        color: Theme.fillInput
        implicitHeight: Theme.controlH + Theme.sp12 * 2
        radius: 0

        Row {
            id: footerRowItem

            anchors.right: parent.right
            anchors.rightMargin: Theme.padDialog
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.sp8
        }
    }
    header: Item {
        implicitHeight: titleCol.implicitHeight + Theme.padDialog + Theme.sp16

        Column {
            id: titleCol

            anchors.left: parent.left
            anchors.margins: Theme.padDialog
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.topMargin: Theme.padDialog
            spacing: Theme.sp4

            Txt {
                kind: "section"
                text: root.title
                width: parent.width
            }
            Txt {
                elide: Text.ElideNone
                kind: "hint"
                text: root.subtitle
                visible: root.subtitle !== ""
                width: parent.width
                wrapMode: Text.WordWrap
            }
        }
    }
}
