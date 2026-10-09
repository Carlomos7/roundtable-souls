pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme

// Find / replace for a text editor (v2.14; the launcher's FindBar): Ctrl+F opens it over the editor's top edge,
// Enter = next, Shift+Enter = previous, Esc closes. Match case toggle, "3 of 12", Replace (the selected match, then
// move on) and Replace all (one undo step). Works on any TextArea passed as `area`.
Rectangle {
    id: root

    property TextArea area
    property bool matchCase: false
    property int current: -1
    property var matches: []
    property bool open: false

    function close() {
        root.open = false;
        root.matches = [];
        root.current = -1;
        if (root.area)
            root.area.forceActiveFocus();
    }
    function next(backwards) {
        if (!root.matches.length)
            return;
        root.current = (root.current + (backwards ? -1 : 1) + root.matches.length) % root.matches.length;
        root.area.select(root.matches[root.current], root.matches[root.current] + findField.text.length);
    }
    function refresh() {
        const out = [];
        const needle = findField.text;
        if (root.area && needle.length) {
            const hay = root.matchCase ? root.area.text : root.area.text.toLowerCase();
            const n = root.matchCase ? needle : needle.toLowerCase();
            let i = hay.indexOf(n);
            while (i >= 0) {
                out.push(i);
                i = hay.indexOf(n, i + n.length);
            }
        }
        root.matches = out;
        root.current = out.length ? 0 : -1;
        if (out.length)
            root.area.select(out[0], out[0] + needle.length);
    }
    function replaceAll() {
        if (!root.matches.length)
            return;
        const needle = findField.text;
        const re = new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), root.matchCase ? "g" : "gi");
        root.area.text = root.area.text.replace(re, replaceField.text);
        root.refresh();
    }
    function replaceOne() {
        if (root.current < 0)
            return;
        const at = root.matches[root.current];
        root.area.remove(at, at + findField.text.length);
        root.area.insert(at, replaceField.text);
        root.refresh();
    }
    function show() {
        root.open = true;
        findField.forceActiveFocus();
        findField.selectAll();
    }

    color: Theme.surfaceCard
    height: open ? Theme.controlH + Theme.sp8 * 2 : 0
    radius: Theme.radiusControl
    visible: open

    Keys.onEscapePressed: root.close()

    Row {
        anchors.left: parent.left
        anchors.margins: Theme.sp8
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.gapInline

        TextBox {
            id: findField

            implicitHeight: Theme.controlH
            placeholderText: qsTr("Find")
            width: Math.max(100, Math.min(220, (parent.width - 470) / 2))  // 470 = the buttons, count and gaps

            Keys.onReturnPressed: event => root.next(event.modifiers & Qt.ShiftModifier)
            onTextChanged: root.refresh()
        }
        TextBox {
            id: replaceField

            implicitHeight: Theme.controlH
            placeholderText: qsTr("Replace")
            width: findField.width
        }
        IconButton {
            ToolTip.text: qsTr("Match case")
            icon_: "Font"
            selected: root.matchCase

            onClicked: {
                root.matchCase = !root.matchCase;
                root.refresh();
            }
        }
        Txt {
            anchors.verticalCenter: parent.verticalCenter
            color: findField.text.length && !root.matches.length ? Theme.statusDanger : Theme.textSecondary
            kind: "caption"
            text: !findField.text.length ? "" : root.matches.length ? qsTr("%1 of %2").arg(root.current + 1).arg(root.matches.length) : qsTr("No matches")
            width: 72
        }
        IconButton {
            ToolTip.text: qsTr("Previous match (Shift+Enter)")
            enabled: root.matches.length > 0
            icon_: "Up"

            onClicked: root.next(true)
        }
        IconButton {
            ToolTip.text: qsTr("Next match (Enter)")
            enabled: root.matches.length > 0
            icon_: "Down"

            onClicked: root.next(false)
        }
        GhostButton {
            enabled: root.current >= 0
            implicitHeight: Theme.controlH
            text: qsTr("Replace")

            onClicked: root.replaceOne()
        }
        GhostButton {
            ToolTip.text: qsTr("Replace every match (one undo step)")
            enabled: root.matches.length > 0
            implicitHeight: Theme.controlH
            text: qsTr("Replace all")

            onClicked: root.replaceAll()
        }
        IconButton {
            ToolTip.text: qsTr("Close (Esc)")
            icon_: "Close"

            onClicked: root.close()
        }
    }
}
