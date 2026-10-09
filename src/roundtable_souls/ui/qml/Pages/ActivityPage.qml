pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import Theme
import Components

// Activity (technical specification §8.10): a summary row (last Play, last install, last failure), filters, the jobs
// grouped by day (one card per day, the jobs as rows), each opening to its log, with Undo where the job can still be
// taken back. Everything shown and every word comes from the adapter (ui/pages/activity/adapter.py).
PageScroll {
    id: page

    required property var adapter
    readonly property var words: adapter.words

    objectName: "activityPage"

    Component.onCompleted: {
        page.adapter.refresh();
        page.adapter.seen();
    }

    Row {  // the summary row
        id: summaryRow

        spacing: Theme.sp12
        width: parent ? parent.width : 0

        Repeater {
            model: page.adapter.summary

            Card {
                id: summaryCard

                required property string label
                required property string level
                required property string value

                padding: Theme.sp12
                width: Math.floor((summaryRow.width - summaryRow.spacing * 2) / 3)

                Column {
                    spacing: Theme.sp4
                    width: parent ? parent.width : 0

                    Txt {
                        kind: "caption"
                        text: summaryCard.label
                    }
                    Txt {
                        color: summaryCard.level === "danger" ? Theme.statusDanger : summaryCard.level === "muted" ? Theme.textSecondary : Theme.textPrimary
                        kind: "strong"
                        text: summaryCard.value
                        width: parent ? parent.width : 0
                    }
                }
            }
        }
    }
    Row {  // the filters
        spacing: Theme.sp8

        DropButton {
            fixedWidth: Theme.pickerW
            implicitHeight: Theme.controlH
            text: page.adapter.gameLabel

            Repeater {
                model: page.adapter.games

                MenuEntry {
                    required property string key
                    required property string label

                    checked: key === page.adapter.game
                    text: label

                    onTriggered: page.adapter.setGame(key)
                }
            }
        }
        DropButton {
            fixedWidth: Theme.pickerW
            implicitHeight: Theme.controlH
            text: page.adapter.kindLabel

            Repeater {
                model: page.adapter.kinds

                MenuEntry {
                    required property string key
                    required property string label

                    checked: key === page.adapter.kind
                    text: label

                    onTriggered: page.adapter.setKind(key)
                }
            }
        }
        CheckRow {
            anchors.verticalCenter: parent.verticalCenter
            checked: page.adapter.failedOnly
            text: page.adapter.failedOnlyText

            onToggled: page.adapter.setFailedOnly(checked)
        }
    }
    Txt {  // nothing yet, or nothing matches the filters
        kind: "hint"
        text: page.adapter.empty
        visible: page.adapter.empty !== ""
        width: parent ? parent.width : 0
        wrapMode: Text.WordWrap
    }
    Repeater {
        model: page.adapter.days

        Column {
            id: dayColumn

            required property var jobs
            required property string label

            spacing: Theme.sp8
            width: parent ? parent.width : 0

            Txt {
                kind: "section"
                text: dayColumn.label
            }
            Card {  // one day = one card: the jobs are rows with hairline dividers; the log opens inside its row
                padding: 0
                width: parent ? parent.width : 0

                Column {
                    spacing: 0
                    width: parent ? parent.width : 0

                    Repeater {
                        id: jobRows

                        model: dayColumn.jobs

                        HoverRow {
                            id: job

                            required property int index
                            required property var modelData
                            readonly property bool open: page.adapter.openJob === modelData.id

                            clip: true
                            divider: index < jobRows.count - 1
                            objectName: "job_" + modelData.id
                            first: index === 0
                            implicitHeight: open ? 60 + logBox.implicitHeight + Theme.sp12 : 60
                            last: index === jobRows.count - 1
                            padding: Theme.padCard
                            pressable: !open
                            width: parent ? parent.width : 0

                            Behavior on implicitHeight {
                                NumberAnimation {
                                    duration: Theme.mPage
                                    easing.type: Easing.OutCubic
                                }
                            }

                            onClicked: page.adapter.toggleLog(job.modelData.id)

                            Item {
                                height: 60
                                width: parent ? parent.width : 0

                                IconButton {
                                    id: chevron

                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    icon_: job.open ? "ChevronDown" : "ChevronRight"
                                    ToolTip.text: job.open ? page.words.hideLog : page.words.showLog
                                    ToolTip.visible: hovered

                                    onClicked: page.adapter.toggleLog(job.modelData.id)
                                }
                                Txt {
                                    id: when

                                    anchors.left: chevron.right
                                    anchors.leftMargin: Theme.sp8
                                    anchors.verticalCenter: parent.verticalCenter
                                    kind: "caption"
                                    tabular: true
                                    text: job.modelData.when
                                    width: 44
                                }
                                Column {
                                    anchors.left: when.right
                                    anchors.leftMargin: Theme.sp8
                                    anchors.right: acts.left
                                    anchors.rightMargin: Theme.sp8
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 2

                                    Txt {
                                        kind: "strong"
                                        text: job.modelData.title
                                        width: parent ? parent.width : 0
                                    }
                                    Txt {
                                        color: job.modelData.failed ? Theme.statusDanger : Theme.textSecondary
                                        kind: "caption"
                                        text: job.modelData.line || job.modelData.meta
                                        visible: text !== ""
                                        width: parent ? parent.width : 0
                                    }
                                }
                                Row {
                                    id: acts

                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: Theme.gapInline

                                    Txt {
                                        anchors.verticalCenter: parent.verticalCenter
                                        kind: "caption"
                                        text: job.modelData.line ? job.modelData.meta : ""
                                        visible: text !== "" && page.width >= 900
                                    }
                                    Pill {
                                        anchors.verticalCenter: parent.verticalCenter
                                        level: job.modelData.level
                                        text: job.modelData.outcome
                                    }
                                    GhostButton {
                                        ToolTip.text: job.modelData.undo_tip
                                        ToolTip.visible: hovered && job.modelData.undo_tip !== ""
                                        icon_: "Return"
                                        implicitHeight: Theme.controlSmallH
                                        objectName: "undo_" + job.modelData.id
                                        text: job.modelData.undo_label
                                        visible: job.modelData.undo_label !== ""

                                        onClicked: page.adapter.undo(job.modelData.id)
                                    }
                                }
                            }
                            Column {  // the opened log
                                id: logBox

                                spacing: Theme.sp8
                                visible: job.open
                                width: parent ? parent.width : 0
                                y: 60

                                Row {
                                    spacing: Theme.gapInline

                                    CheckRow {
                                        ToolTip.text: page.words.showDetailsTip
                                        ToolTip.visible: hovered
                                        anchors.verticalCenter: parent.verticalCenter
                                        checked: page.adapter.logDetail
                                        text: page.words.showDetails
                                        visible: page.adapter.logSource === "" || page.adapter.logSource === job.modelData.sources[0].key

                                        onToggled: page.adapter.setLogDetail(checked)
                                    }
                                    DropButton {
                                        implicitHeight: Theme.controlSmallH
                                        text: {
                                            const s = job.modelData.sources;
                                            for (let i = 0; i < s.length; i++)
                                                if (s[i].key === page.adapter.logSource)
                                                    return s[i].label;
                                            return s.length ? s[0].label : "";
                                        }
                                        visible: job.modelData.sources.length > 1

                                        Repeater {
                                            model: job.modelData.sources

                                            MenuEntry {
                                                required property var modelData

                                                text: modelData.label

                                                onTriggered: page.adapter.setLogSource(modelData.key)
                                            }
                                        }
                                    }
                                    GhostButton {
                                        ToolTip.text: page.words.copyTip
                                        ToolTip.visible: hovered
                                        icon_: "Copy"
                                        implicitHeight: Theme.controlSmallH
                                        text: page.words.copy

                                        onClicked: page.adapter.copyLog(false)
                                    }
                                    GhostButton {
                                        ToolTip.text: page.words.copySupportTip
                                        ToolTip.visible: hovered
                                        icon_: "Share"
                                        implicitHeight: Theme.controlSmallH
                                        text: page.words.copySupport

                                        onClicked: page.adapter.copyLog(true)
                                    }
                                    GhostButton {
                                        icon_: "Document"
                                        implicitHeight: Theme.controlSmallH
                                        text: page.words.openFile

                                        onClicked: page.adapter.openLogFile()
                                    }
                                }
                                Txt {
                                    kind: "hint"
                                    text: page.adapter.logNote
                                    visible: text !== ""
                                    width: parent ? parent.width : 0
                                    wrapMode: Text.WordWrap
                                }
                                CodeArea {
                                    height: Math.min(420, Math.max(180, implicitHeight))
                                    readOnly: true
                                    text: job.open ? page.adapter.logText : ""
                                    width: parent ? parent.width : 0
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
