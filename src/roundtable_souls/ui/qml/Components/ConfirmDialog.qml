pragma ComponentBehavior: Bound
import QtQuick

// Confirm an action: a body line, a primary button named after the action (red when destructive), Cancel.
ModalDialog {
    id: root

    property bool destructive: false
    property string message: ""
    property var onConfirm: null
    property string primaryText: qsTr("OK")

    preferredWidth: 480

    footerRow: [
        PrimaryButton {
            danger: root.destructive
            text: root.primaryText

            onClicked: {
                if (root.onConfirm)
                    root.onConfirm();
                root.close();
            }
        },
        GhostButton {
            text: qsTr("Cancel")

            onClicked: root.close()
        }
    ]

    Txt {
        elide: Text.ElideNone
        text: root.message
        width: parent.width
        wrapMode: Text.WordWrap
    }
}
