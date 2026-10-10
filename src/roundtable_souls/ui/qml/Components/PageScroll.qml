pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// A page's scrolling column: the page margins (40 / 28 / 40 / 36; 20 under 820 px), capped at maxContentWidth and
// centred past it (v2.11), 24 px between sections (v2.5 D:
// between sections use space, never a line). Scrollbar 6 px, round ends, shown while the page is hovered or
// scrolling (v2.5 E).
Flickable {
    id: root

    default property alias content: pageColumn.data
    property int maxContentWidth: Theme.contentMaxW  // Theme.formMaxW for settings-style pages
    property int sideMargin: width < 820 ? 20 : 40

    boundsBehavior: Flickable.StopAtBounds
    clip: true
    contentHeight: pageColumn.implicitHeight + 28 + 36
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

    HoverHandler {
        id: hover
    }
    Column {
        id: pageColumn

        spacing: Theme.sp24
        width: Math.min(root.width - root.sideMargin * 2, root.maxContentWidth)
        x: Math.max(root.sideMargin, Math.round((root.width - width) / 2))
        y: 28
    }
}
