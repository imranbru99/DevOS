#!/usr/bin/env python3
"""
DevOS Network Usage — interfaces, last 30 days per-day graph, monthly totals.

Data is sampled from /proc/net/dev and kept for 12 months only.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
COMP = os.path.join(ROOT, "components")
if COMP not in sys.path:
    sys.path.insert(0, COMP)

import collector  # noqa: E402

APP_NAME = "DevOS Network Usage"
APP_ID = "devos-network-usage"
ICON_CANDIDATES = (
    os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps/devos-network-usage.svg"),
    os.path.join(ROOT, "build/includes.chroot/usr/share/icons/hicolor/scalable/apps/devos-network-usage.svg"),
    "/usr/share/icons/hicolor/scalable/apps/devos-network-usage.svg",
    os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps/devos-network-usage.png"),
)


def _load_icon():
    from PyQt5.QtGui import QIcon

    icon = QIcon.fromTheme("devos-network-usage")
    if not icon.isNull():
        return icon
    for path in ICON_CANDIDATES:
        if os.path.isfile(path):
            return QIcon(path)
    return QIcon.fromTheme("network-wired")


def run_gui():
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5.QtCore import Qt

    try:
        from app_identity import prepare as prepare_identity
        prepare_identity(APP_ID)
    except Exception:
        prepare_identity = None  # type: ignore
    try:
        from app_identity import apply as apply_identity
    except Exception:
        apply_identity = None  # type: ignore

    STYLE = """
    QWidget#root {
      background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #070b14, stop:0.45 #0b1220, stop:1 #0a1628);
      color: #e2e8f0;
      font-family: "Segoe UI Variable", "Noto Sans", "Inter";
      font-size: 13px;
    }
    QLabel#brand {
      font-size: 11px; font-weight: 700; letter-spacing: 2.4px;
      color: #38bdf8; text-transform: uppercase;
    }
    QLabel#title {
      font-size: 26px; font-weight: 750; color: #f8fafc;
      letter-spacing: -0.6px;
    }
    QLabel#muted { color: #94a3b8; font-size: 12.5px; }
    QLabel#section {
      font-size: 14px; font-weight: 650; color: #f1f5f9;
      letter-spacing: 0.2px;
    }
    QLabel#statValue {
      font-size: 20px; font-weight: 750; color: #f8fafc;
      letter-spacing: -0.4px;
    }
    QLabel#statLabel {
      font-size: 11px; font-weight: 600; color: #64748b;
      letter-spacing: 0.8px; text-transform: uppercase;
    }
    QFrame#card {
      background: rgba(15, 23, 42, 0.82);
      border: 1px solid rgba(56, 189, 248, 0.12);
      border-radius: 18px;
    }
    QFrame#stat {
      background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(14, 165, 233, 0.12), stop:1 rgba(15, 23, 42, 0.4));
      border: 1px solid rgba(56, 189, 248, 0.16);
      border-radius: 14px;
    }
    QListWidget {
      background: transparent; border: none; outline: none; padding: 2px;
    }
    QListWidget::item {
      padding: 12px 14px; border-radius: 12px; margin: 2px 0;
      color: #cbd5e1;
    }
    QListWidget::item:selected {
      background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(14, 165, 233, 0.35), stop:1 rgba(14, 165, 233, 0.12));
      color: #f0f9ff; border: 1px solid rgba(56, 189, 248, 0.35);
    }
    QListWidget::item:hover:!selected {
      background: rgba(148, 163, 184, 0.08);
    }
    QPushButton {
      background: rgba(30, 41, 59, 0.9);
      border: 1px solid rgba(148, 163, 184, 0.22);
      border-radius: 10px; padding: 8px 16px; color: #e2e8f0;
      font-weight: 600;
    }
    QPushButton:hover { border-color: #38bdf8; color: #f8fafc; }
    QPushButton#primary {
      background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #0ea5e9, stop:1 #0369a1);
      border: 1px solid #38bdf8; color: white; font-weight: 700;
      padding: 9px 18px;
    }
    QPushButton#primary:hover {
      background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #38bdf8, stop:1 #0284c7);
    }
    QPushButton#period {
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(148, 163, 184, 0.18);
      border-radius: 10px; padding: 8px 18px; color: #94a3b8;
      font-weight: 650;
    }
    QPushButton#period:checked {
      background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(14, 165, 233, 0.45), stop:1 rgba(14, 165, 233, 0.18));
      border: 1px solid rgba(56, 189, 248, 0.55);
      color: #f0f9ff;
    }
    QPushButton#period:hover:!checked {
      border-color: rgba(56, 189, 248, 0.35); color: #e2e8f0;
    }
    QPushButton#yearlyToggle {
      background: transparent; border: none; text-align: left;
      color: #94a3b8; font-weight: 650; padding: 4px 2px;
    }
    QPushButton#yearlyToggle:hover { color: #e2e8f0; }
    QFrame#focusRow {
      background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(14, 165, 233, 0.16), stop:1 rgba(15, 23, 42, 0.35));
      border: 1px solid rgba(56, 189, 248, 0.18);
      border-radius: 14px;
    }
    QLabel#focusTitle { font-size: 14px; font-weight: 700; color: #f8fafc; }
    QLabel#focusSub { font-size: 11px; color: #64748b; }
    QLabel#focusTotal { font-size: 18px; font-weight: 750; color: #7dd3fc; }
    QLabel#focusSide { font-size: 11px; color: #94a3b8; }
    QTableWidget {
      background: transparent; border: none; gridline-color: rgba(30, 41, 59, 0.8);
      selection-background-color: rgba(14, 165, 233, 0.22);
      selection-color: #f8fafc;
    }
    QTableWidget::item { padding: 8px 10px; }
    QHeaderView::section {
      background: transparent; color: #64748b; border: none;
      border-bottom: 1px solid rgba(51, 65, 85, 0.8);
      padding: 10px 10px; font-weight: 650; font-size: 11px;
      letter-spacing: 0.6px;
    }
    QScrollArea#mainScroll {
      background: transparent; border: none;
    }
    QScrollArea#mainScroll > QWidget > QWidget { background: transparent; }
    QScrollBar:vertical {
      background: transparent; width: 10px; margin: 2px;
    }
    QScrollBar::handle:vertical {
      background: rgba(100, 116, 139, 0.55); border-radius: 5px; min-height: 28px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar:horizontal { height: 0; }
    """

    class BarChart(QtWidgets.QWidget):
        """Premium stacked download/upload bars for the last N days."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.rows = []
            self.setMinimumHeight(250)
            self.setAttribute(Qt.WA_OpaquePaintEvent, False)

        def set_rows(self, rows):
            self.rows = list(rows or [])
            self.update()

        def paintEvent(self, _event):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setRenderHint(QtGui.QPainter.TextAntialiasing)
            w, h = self.width(), self.height()

            bg = QtGui.QLinearGradient(0, 0, 0, h)
            bg.setColorAt(0.0, QtGui.QColor(15, 23, 42, 40))
            bg.setColorAt(1.0, QtGui.QColor(2, 132, 199, 18))
            p.fillRect(self.rect(), bg)

            if not self.rows:
                p.setPen(QtGui.QColor("#64748b"))
                font = p.font()
                font.setPointSize(11)
                p.setFont(font)
                p.drawText(
                    self.rect(),
                    Qt.AlignCenter,
                    "No usage recorded yet — the sampler will fill this chart.",
                )
                p.end()
                return

            pad_l, pad_r, pad_t, pad_b = 52, 16, 28, 40
            chart_w = max(1, w - pad_l - pad_r)
            chart_h = max(1, h - pad_t - pad_b)
            peak = max((r["total"] for r in self.rows), default=1) or 1
            n = len(self.rows)
            gap = 3.0
            bar_w = max(4.0, (chart_w - gap * (n - 1)) / n)

            # soft grid
            for i in range(5):
                y = pad_t + chart_h * i / 4
                p.setPen(QtGui.QPen(QtGui.QColor(148, 163, 184, 28), 1))
                p.drawLine(pad_l, int(y), w - pad_r, int(y))
            p.setPen(QtGui.QColor("#64748b"))
            font = p.font()
            font.setPointSize(9)
            font.setBold(True)
            p.setFont(font)
            p.drawText(6, pad_t + 10, collector.human_bytes(peak))
            p.drawText(6, pad_t + chart_h, "0")

            for i, row in enumerate(self.rows):
                x = pad_l + i * (bar_w + gap)
                total_h = chart_h * (row["total"] / peak) if peak else 0
                rx_h = chart_h * (row["rx"] / peak) if peak else 0
                tx_h = max(0.0, total_h - rx_h)
                y_base = pad_t + chart_h

                # glow under active bars
                if row["total"] > 0:
                    glow = QtGui.QColor(56, 189, 248, 35)
                    p.setPen(Qt.NoPen)
                    p.setBrush(glow)
                    p.drawRoundedRect(
                        QtCore.QRectF(x - 1, y_base - total_h - 2, bar_w + 2, total_h + 4),
                        4,
                        4,
                    )

                # download (rx)
                rx_grad = QtGui.QLinearGradient(x, y_base, x, y_base - max(rx_h, 1))
                rx_grad.setColorAt(0.0, QtGui.QColor("#0284c7"))
                rx_grad.setColorAt(1.0, QtGui.QColor("#7dd3fc"))
                p.setBrush(rx_grad)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(QtCore.QRectF(x, y_base - rx_h, bar_w, rx_h), 3, 3)

                # upload (tx)
                if tx_h > 0.5:
                    tx_grad = QtGui.QLinearGradient(x, y_base - rx_h, x, y_base - total_h)
                    tx_grad.setColorAt(0.0, QtGui.QColor("#7c3aed"))
                    tx_grad.setColorAt(1.0, QtGui.QColor("#c4b5fd"))
                    p.setBrush(tx_grad)
                    p.drawRoundedRect(
                        QtCore.QRectF(x, y_base - total_h, bar_w, tx_h), 3, 3
                    )

                # Always label when few bars (weekly); sample when many (monthly)
                show_label = n <= 10 or i % max(1, n // 8) == 0 or i == n - 1
                if show_label:
                    p.setPen(QtGui.QColor("#64748b"))
                    label = row.get("label") or row["date"][5:]
                    p.drawText(
                        QtCore.QRectF(x - 14, y_base + 6, bar_w + 28, 20),
                        Qt.AlignHCenter | Qt.AlignTop,
                        label,
                    )

            # legend pills
            def pill(px, color, text):
                p.setPen(Qt.NoPen)
                p.setBrush(QtGui.QColor(color))
                p.drawRoundedRect(QtCore.QRectF(px, 8, 9, 9), 3, 3)
                p.setPen(QtGui.QColor("#94a3b8"))
                p.drawText(px + 14, 17, text)

            pill(w - 168, "#38bdf8", "Download")
            pill(w - 78, "#a78bfa", "Upload")
            p.end()

    class StatCard(QtWidgets.QFrame):
        def __init__(self, label, parent=None):
            super().__init__(parent)
            self.setObjectName("stat")
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(14, 12, 14, 12)
            lay.setSpacing(4)
            self.value = QtWidgets.QLabel("—")
            self.value.setObjectName("statValue")
            lab = QtWidgets.QLabel(label)
            lab.setObjectName("statLabel")
            lay.addWidget(self.value)
            lay.addWidget(lab)

        def set_value(self, text):
            self.value.setText(text)

    class Main(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName("root")
            self.setWindowTitle(APP_NAME)
            self.setWindowIcon(_load_icon())
            self.resize(1040, 700)
            self.setStyleSheet(STYLE)
            self.iface = None
            self.period = "weekly"  # weekly | monthly
            self._iface_by_row = {0: None}
            self._store = {}

            root = QtWidgets.QVBoxLayout(self)
            root.setContentsMargins(22, 18, 22, 14)
            root.setSpacing(12)

            # Header
            head = QtWidgets.QHBoxLayout()
            brand_row = QtWidgets.QHBoxLayout()
            brand_row.setSpacing(12)
            icon_lab = QtWidgets.QLabel()
            icon_lab.setPixmap(_load_icon().pixmap(42, 42))
            icon_lab.setFixedSize(42, 42)
            titles = QtWidgets.QVBoxLayout()
            titles.setSpacing(2)
            brand = QtWidgets.QLabel("DEVOS · DATA METER")
            brand.setObjectName("brand")
            t = QtWidgets.QLabel("Network Usage")
            t.setObjectName("title")
            s = QtWidgets.QLabel(
                "Weekly first · Monthly = this month · Yearly = all 12 months (tap to open)"
            )
            s.setObjectName("muted")
            titles.addWidget(brand)
            titles.addWidget(t)
            titles.addWidget(s)
            brand_row.addWidget(icon_lab)
            brand_row.addLayout(titles, 1)
            head.addLayout(brand_row, 1)
            self.refresh_btn = QtWidgets.QPushButton("Refresh")
            self.refresh_btn.setObjectName("primary")
            self.refresh_btn.setCursor(Qt.PointingHandCursor)
            self.refresh_btn.clicked.connect(self.refresh)
            head.addWidget(self.refresh_btn, 0, Qt.AlignTop)
            root.addLayout(head)

            # Stats
            stats = QtWidgets.QHBoxLayout()
            stats.setSpacing(10)
            self.stat_today = StatCard("Today")
            self.stat_week = StatCard("This week")
            self.stat_month = StatCard("This month")
            self.stat_conn = StatCard("Connection")
            for w in (self.stat_today, self.stat_week, self.stat_month, self.stat_conn):
                stats.addWidget(w, 1)
            root.addLayout(stats)

            body = QtWidgets.QHBoxLayout()
            body.setSpacing(14)

            left = QtWidgets.QFrame()
            left.setObjectName("card")
            left.setFixedWidth(280)
            lv = QtWidgets.QVBoxLayout(left)
            lv.setContentsMargins(14, 14, 14, 14)
            lv.setSpacing(10)
            lv.addWidget(self._section("Your connections"))
            self.list = QtWidgets.QListWidget()
            self.list.currentRowChanged.connect(self._iface_changed)
            lv.addWidget(self.list, 1)
            self.iface_detail = QtWidgets.QLabel("")
            self.iface_detail.setObjectName("muted")
            self.iface_detail.setWordWrap(True)
            lv.addWidget(self.iface_detail)
            note = QtWidgets.QLabel(
                "Names show what people use (Wi‑Fi / Ethernet). "
                "Technical IDs stay in the details only."
            )
            note.setObjectName("muted")
            note.setWordWrap(True)
            lv.addWidget(note)
            body.addWidget(left)

            # Right column: scrollable chart/focus + Yearly pinned at bottom
            right_col = QtWidgets.QWidget()
            right = QtWidgets.QVBoxLayout(right_col)
            right.setContentsMargins(0, 0, 0, 0)
            right.setSpacing(10)

            scroll = QtWidgets.QScrollArea()
            scroll.setObjectName("mainScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

            scroll_inner = QtWidgets.QWidget()
            si = QtWidgets.QVBoxLayout(scroll_inner)
            si.setContentsMargins(0, 0, 6, 0)
            si.setSpacing(10)

            chart_card = QtWidgets.QFrame()
            chart_card.setObjectName("card")
            cv = QtWidgets.QVBoxLayout(chart_card)
            cv.setContentsMargins(16, 14, 16, 14)
            cv.setSpacing(8)

            period_row = QtWidgets.QHBoxLayout()
            period_row.setSpacing(8)
            self.chart_title = QtWidgets.QLabel("This week")
            self.chart_title.setObjectName("section")
            period_row.addWidget(self.chart_title, 1)
            self.btn_weekly = QtWidgets.QPushButton("Weekly")
            self.btn_monthly = QtWidgets.QPushButton("Monthly")
            for btn, key in ((self.btn_weekly, "weekly"), (self.btn_monthly, "monthly")):
                btn.setObjectName("period")
                btn.setCheckable(True)
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _=False, k=key: self._set_period(k))
                period_row.addWidget(btn)
            self.btn_weekly.setChecked(True)
            cv.addLayout(period_row)

            self.summary = QtWidgets.QLabel("")
            self.summary.setObjectName("muted")
            cv.addWidget(self.summary)
            self.chart = BarChart()
            self.chart.setMinimumHeight(220)
            cv.addWidget(self.chart)

            # Monthly focus panel — This week + This month only
            self.focus_panel = QtWidgets.QWidget()
            fl = QtWidgets.QVBoxLayout(self.focus_panel)
            fl.setContentsMargins(0, 4, 0, 0)
            fl.setSpacing(8)
            focus_head = QtWidgets.QLabel("This week & this month")
            focus_head.setObjectName("section")
            fl.addWidget(focus_head)
            self.focus_rows_host = QtWidgets.QVBoxLayout()
            self.focus_rows_host.setSpacing(8)
            fl.addLayout(self.focus_rows_host)
            self.focus_panel.hide()
            cv.addWidget(self.focus_panel)
            si.addWidget(chart_card)
            si.addStretch(1)
            scroll.setWidget(scroll_inner)
            right.addWidget(scroll, 1)

            # Yearly stays pinned under the scroll area so it is never lost off-screen
            year_card = QtWidgets.QFrame()
            year_card.setObjectName("card")
            yv = QtWidgets.QVBoxLayout(year_card)
            yv.setContentsMargins(14, 10, 14, 10)
            yv.setSpacing(8)
            self.yearly_btn = QtWidgets.QPushButton(
                "▸  Yearly · all months  ·  tap to show"
            )
            self.yearly_btn.setObjectName("yearlyToggle")
            self.yearly_btn.setCursor(Qt.PointingHandCursor)
            self.yearly_btn.setCheckable(True)
            self.yearly_btn.toggled.connect(self._toggle_yearly)
            yv.addWidget(self.yearly_btn)
            self.year_body = QtWidgets.QWidget()
            yb = QtWidgets.QVBoxLayout(self.year_body)
            yb.setContentsMargins(0, 0, 0, 0)
            yb.setSpacing(6)
            self.year_hint = QtWidgets.QLabel(
                "Every month in the last 12 months (older data is auto-removed)."
            )
            self.year_hint.setObjectName("muted")
            self.year_hint.setWordWrap(True)
            yb.addWidget(self.year_hint)
            self.year_table = QtWidgets.QTableWidget(0, 4)
            self.year_table.setHorizontalHeaderLabels(
                ["MONTH", "DOWNLOAD", "UPLOAD", "TOTAL"]
            )
            self.year_table.horizontalHeader().setStretchLastSection(True)
            self.year_table.horizontalHeader().setSectionResizeMode(
                QtWidgets.QHeaderView.Stretch
            )
            self.year_table.verticalHeader().setVisible(False)
            self.year_table.setShowGrid(False)
            self.year_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.year_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.year_table.setFocusPolicy(Qt.NoFocus)
            self.year_table.setMinimumHeight(160)
            self.year_table.setMaximumHeight(260)
            yb.addWidget(self.year_table)
            self.year_body.hide()
            yv.addWidget(self.year_body)
            right.addWidget(year_card, 0)

            body.addWidget(right_col, 1)
            root.addLayout(body, 1)

            self.foot = QtWidgets.QLabel("")
            self.foot.setObjectName("muted")
            root.addWidget(self.foot)

            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.refresh)
            self.timer.start(60_000)
            self.refresh()

        def _section(self, text):
            lab = QtWidgets.QLabel(text)
            lab.setObjectName("section")
            return lab

        def _table_item(self, text, align=Qt.AlignLeft | Qt.AlignVCenter, accent=False):
            item = QtWidgets.QTableWidgetItem(text)
            item.setTextAlignment(align)
            if accent:
                item.setForeground(QtGui.QBrush(QtGui.QColor("#7dd3fc")))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            else:
                item.setForeground(QtGui.QBrush(QtGui.QColor("#cbd5e1")))
            return item

        def _fill_table(self, table, rows, label_key="label"):
            table.setRowCount(len(rows))
            for i, m in enumerate(rows):
                table.setItem(i, 0, self._table_item(m.get(label_key) or m.get("date") or ""))
                table.setItem(
                    i,
                    1,
                    self._table_item(
                        collector.human_bytes(m["rx"]), Qt.AlignRight | Qt.AlignVCenter
                    ),
                )
                table.setItem(
                    i,
                    2,
                    self._table_item(
                        collector.human_bytes(m["tx"]), Qt.AlignRight | Qt.AlignVCenter
                    ),
                )
                table.setItem(
                    i,
                    3,
                    self._table_item(
                        collector.human_bytes(m["total"]),
                        Qt.AlignRight | Qt.AlignVCenter,
                        accent=m["total"] > 0,
                    ),
                )
                table.setRowHeight(i, 32)

        def _clear_layout(self, layout):
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        def _fill_focus_panel(self, rows):
            self._clear_layout(self.focus_rows_host)
            for m in rows:
                row = QtWidgets.QFrame()
                row.setObjectName("focusRow")
                hl = QtWidgets.QHBoxLayout(row)
                hl.setContentsMargins(14, 12, 14, 12)
                hl.setSpacing(12)
                left = QtWidgets.QVBoxLayout()
                left.setSpacing(2)
                title = QtWidgets.QLabel(m.get("label") or "")
                title.setObjectName("focusTitle")
                sub = QtWidgets.QLabel(m.get("sub") or "")
                sub.setObjectName("focusSub")
                left.addWidget(title)
                left.addWidget(sub)
                hl.addLayout(left, 1)
                side = QtWidgets.QVBoxLayout()
                side.setSpacing(2)
                total = QtWidgets.QLabel(collector.human_bytes(m["total"]))
                total.setObjectName("focusTotal")
                total.setAlignment(Qt.AlignRight)
                detail = QtWidgets.QLabel(
                    f"↓ {collector.human_bytes(m['rx'])}   ↑ {collector.human_bytes(m['tx'])}"
                )
                detail.setObjectName("focusSide")
                detail.setAlignment(Qt.AlignRight)
                side.addWidget(total)
                side.addWidget(detail)
                hl.addLayout(side)
                self.focus_rows_host.addWidget(row)

        def _set_period(self, key):
            self.period = key
            self.btn_weekly.setChecked(key == "weekly")
            self.btn_monthly.setChecked(key == "monthly")
            self.focus_panel.setVisible(key == "monthly")
            self._reload_charts(self._store or collector.load_store())

        def _toggle_yearly(self, checked):
            self.year_body.setVisible(checked)
            self.yearly_btn.setText(
                "▾  Yearly · all months  ·  tap to hide"
                if checked
                else "▸  Yearly · all months  ·  tap to show"
            )
            if checked:
                self._reload_charts(self._store or collector.load_store())

        def refresh(self):
            collector.sample_once()
            store = collector.load_store()
            self._store = store
            rows = collector.list_tracked_ifaces(store)
            cur = self.list.currentRow()
            self.list.blockSignals(True)
            self.list.clear()
            self._iface_by_row = {0: None}
            self.list.addItem("All connections\n     Every cable + Wi‑Fi together")
            for i, r in enumerate(rows, start=1):
                online = r.get("online") and r.get("state") == "up"
                mark = "●" if online else "○"
                title = collector.friendly_iface_title(r)
                state = r.get("state_label") or r.get("state") or ""
                today = collector.human_bytes(r.get("today_total") or 0)
                self.list.addItem(f"{mark}  {title}\n     {state} · today {today}")
                self._iface_by_row[i] = r.get("name")
            self.list.blockSignals(False)
            for i in range(self.list.count()):
                self.list.item(i).setSizeHint(QtCore.QSize(0, 50 if i else 46))
            if 0 <= cur < self.list.count():
                self.list.setCurrentRow(cur)
            else:
                self.list.setCurrentRow(0)
            self._reload_charts(store)
            sampled = store.get("sampled_at") or "—"
            self.foot.setText(
                f"Last sample {sampled}  ·  Keeps 12 months only  ·  {collector.data_dir()}"
            )

        def _iface_changed(self, row):
            self.iface = self._iface_by_row.get(row)
            if not self.iface:
                self.iface_detail.setText(
                    "Combined use across every connection on this PC."
                )
            else:
                meta = collector.iface_meta(self.iface)
                bits = [
                    collector.friendly_iface_title(meta),
                    meta.get("state_label") or meta.get("state"),
                ]
                if meta.get("speed"):
                    bits.append(meta["speed"])
                bits.append(f"ID: {meta.get('name')}")
                self.iface_detail.setText(" · ".join(b for b in bits if b))
            self._reload_charts(self._store or collector.load_store())

        def _reload_charts(self, store):
            who = (
                collector.friendly_iface_title(collector.iface_meta(self.iface))
                if self.iface
                else "all connections"
            )
            if self.period == "monthly":
                chart_rows = collector.current_month_days(store, self.iface)
                focus = collector.month_focus_summary(store, self.iface)
                self._fill_focus_panel(focus)
                total = sum(d["total"] for d in chart_rows)
                down = sum(d["rx"] for d in chart_rows)
                up = sum(d["tx"] for d in chart_rows)
                month_name = __import__("datetime").date.today().strftime("%B %Y")
                self.chart_title.setText(f"This month — {who}")
                self.summary.setText(
                    f"{month_name}  {collector.human_bytes(total)}   "
                    f"↓ {collector.human_bytes(down)}   ↑ {collector.human_bytes(up)}"
                )
                self.chart.set_rows(chart_rows)
            else:
                chart_rows = collector.weekly_totals(store, self.iface)
                total = sum(d["total"] for d in chart_rows)
                down = sum(d["rx"] for d in chart_rows)
                up = sum(d["tx"] for d in chart_rows)
                self.chart_title.setText(f"This week — {who}")
                self.summary.setText(
                    f"7-day total {collector.human_bytes(total)}   "
                    f"↓ {collector.human_bytes(down)}   ↑ {collector.human_bytes(up)}"
                )
                self.chart.set_rows(chart_rows)

            today_key = __import__("datetime").date.today().isoformat()
            week = collector.weekly_totals(store, self.iface)
            today_total = sum(d["total"] for d in week if d.get("date") == today_key)
            week_total = sum(d["total"] for d in week)
            this_month = collector.sum_rows(
                collector.current_month_days(store, self.iface)
            )["total"]

            self.stat_today.set_value(collector.human_bytes(today_total))
            self.stat_week.set_value(collector.human_bytes(week_total))
            self.stat_month.set_value(collector.human_bytes(this_month))
            self.stat_conn.set_value(
                collector.friendly_iface_title(collector.iface_meta(self.iface))
                if self.iface
                else "All"
            )

            if self.year_body.isVisible():
                # Yearly = month-by-month for the kept 12 months (not calendar-year totals)
                months = collector.monthly_totals(store, self.iface, months=12)
                self._fill_table(self.year_table, list(reversed(months)))

    app = QtWidgets.QApplication(sys.argv)
    if apply_identity:
        apply_identity(app, APP_ID)
    icon = _load_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    win = Main()
    win.show()
    return app.exec_()


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] in ("sample", "collect"):
        store = collector.sample_once()
        print(store.get("sampled_at"), "ifaces=", ",".join(store.get("ifaces") or {}))
        return 0
    if argv and argv[0] in ("--help", "-h", "help"):
        print(
            "Usage: networkusage.py [sample]\n"
            "  (no args) open the usage window\n"
            "  sample     record counters once"
        )
        return 0
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
