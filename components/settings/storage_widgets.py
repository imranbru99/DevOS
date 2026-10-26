"""Storage layout preview and size editor. No writes occur inside this dialog."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPainter, QFont
from PyQt5.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QHeaderView, QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox,
    QDialogButtonBox, QFormLayout)
from storage_layout import plan_layout, GIB

PALETTE = ['#38bdf8', '#818cf8', '#2dd4bf', '#fbbf24', '#fb7185', '#a78bfa', '#60a5fa', '#34d399']


class VolumeMap(QWidget):
    def __init__(self, disk_bytes, partitions, parent=None):
        super().__init__(parent)
        self.disk_bytes = max(1, disk_bytes)
        self.partitions = partitions
        self.setMinimumHeight(72)
        self.setAccessibleName('Disk partition capacity map')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#0a1120'))
        x = 0.0
        painter.setFont(QFont('Sans Serif', 9))
        for index, part in enumerate(self.partitions):
            width = self.width() * part['size_bytes'] / self.disk_bytes
            painter.fillRect(int(x), 8, max(1, int(width) - 2), 22, QColor(PALETTE[index % len(PALETTE)]))
            if width > 65:
                painter.setPen(QColor('#dbeafe'))
                label = part.get('label') or part.get('device', '').split('/')[-1]
                painter.drawText(int(x) + 4, 48, label[:20])
                painter.setPen(QColor('#94a3b8'))
                painter.drawText(int(x) + 4, 64, f"{part['size_bytes'] / GIB:.1f} GiB")
            x += width
        if x < self.width() - 2:
            painter.fillRect(int(x), 8, self.width() - int(x), 22, QColor('#243047'))
            if self.width() - x > 85:
                painter.setPen(QColor('#94a3b8'))
                painter.drawText(int(x) + 4, 48, 'Unallocated')
        painter.end()


class PartitionLayoutDialog(QDialog):
    def __init__(self, disk, parent=None):
        super().__init__(parent)
        self.disk = disk
        self.setWindowTitle('Create data volumes · ' + disk['device'])
        self.resize(680, 550)
        self.setStyleSheet('''QDialog { background:#0b1120; color:#f8fafc; }
            QLabel { color:#cbd5e1; } QTableWidget { background:#111c30; color:#f8fafc; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background:#17243a; color:#f8fafc; padding:7px; border:1px solid #334155; border-radius:5px; }
            QPushButton { background:#1e3a5f; color:#f8fafc; padding:10px 18px; border-radius:7px; }
            QPushButton:disabled { color:#64748b; background:#172033; }''')
        layout = QVBoxLayout(self)
        title = QLabel('Design your storage')
        title.setStyleSheet('font-size:25px; font-weight:700; color:#f8fafc;')
        layout.addWidget(title)
        summary = QLabel(f"{disk['model']} · {disk['size_human']} · {disk['device']}")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        note = QLabel('This replaces every partition on this disk. Other disks are unchanged. For resizing existing partitions, use the advanced partition editor.')
        note.setWordWrap(True)
        note.setStyleSheet('color:#fbbf24; padding:8px 0;')
        layout.addWidget(note)
        form = QFormLayout()
        self.count = QSpinBox(); self.count.setRange(1, 8); self.count.setValue(3)
        form.addRow('Number of volumes', self.count)
        self.filesystem = QComboBox()
        for text, value in [('ext4 · DevOS data', 'ext4'), ('exFAT · Share with Windows/macOS', 'exfat'), ('NTFS · Share with Windows', 'ntfs'), ('Btrfs · Advanced', 'btrfs')]:
            self.filesystem.addItem(text, value)
        form.addRow('Filesystem', self.filesystem)
        layout.addLayout(form)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['Volume label', 'Capacity (GiB)'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table)
        self.preview = VolumeMap(disk['size_bytes'], [])
        layout.addWidget(self.preview)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.confirm = QLineEdit(); self.confirm.setPlaceholderText('Type ' + disk['device'] + ' to confirm erasing this disk')
        layout.addWidget(self.confirm)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        self.apply_button = self.buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText('Erase disk & create volumes')
        self.buttons.rejected.connect(self.reject)
        self.apply_button.clicked.connect(self.accept)
        layout.addWidget(self.buttons)
        self.count.valueChanged.connect(self.rebuild)
        self.filesystem.currentIndexChanged.connect(self.update_preview)
        self.confirm.textChanged.connect(self.update_preview)
        self.rebuild()

    def rebuild(self):
        count = self.count.value()
        self.table.setRowCount(count)
        for i in range(count):
            label = QLineEdit(chr(65 + i)); label.setMaxLength(32)
            label.textChanged.connect(self.update_preview)
            self.table.setCellWidget(i, 0, label)
            if i == count - 1:
                remainder = QLabel('Remaining space'); remainder.setAlignment(Qt.AlignCenter)
                self.table.setCellWidget(i, 1, remainder)
            else:
                size = QDoubleSpinBox(); size.setDecimals(2); size.setRange(0.07, self.disk['size_bytes'] / GIB)
                size.setValue(max(0.07, int(self.disk['size_bytes'] / GIB / count)))
                size.valueChanged.connect(self.update_preview)
                self.table.setCellWidget(i, 1, size)
        self.update_preview()

    def get_volumes(self):
        return [{'label': self.table.cellWidget(i, 0).text(),
                 'size_gib': self.table.cellWidget(i, 1).value() if i < self.table.rowCount() - 1 else 0,
                 'filesystem': self.filesystem.currentData()} for i in range(self.table.rowCount())]

    def update_preview(self):
        try:
            planned = plan_layout(self.disk['size_bytes'], self.get_volumes())
            self.preview.partitions = planned
            self.status.setText(' + '.join(f"{p['label']}: {p['size_bytes']/GIB:.1f} GiB" for p in planned))
            self.status.setStyleSheet('color:#7dd3fc;')
            self.apply_button.setEnabled(self.confirm.text() == self.disk['device'])
        except (ValueError, AttributeError):
            self.preview.partitions = []
            self.status.setText('Choose valid labels and sizes that fit on this drive.')
            self.status.setStyleSheet('color:#fbbf24;')
            self.apply_button.setEnabled(False)
        self.preview.update()
