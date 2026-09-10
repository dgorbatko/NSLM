import hashlib
import threading
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QRectF, QObject, QRunnable, QThreadPool, QPoint
from collections import OrderedDict
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QPixmap, QPainterPath, QFont, QPen, QIcon, QImageReader, QPolygon
from PySide6.QtWidgets import QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, QSizePolicy, QProgressBar, QComboBox


def label(text, kind='', wrap=False):
    item = QLabel(text)
    item.setTextFormat(Qt.PlainText)
    item.setObjectName(kind)
    item.setWordWrap(wrap)
    return item


def button(text, callback, primary=False):
    item = QPushButton(text)
    if primary:
        item.setObjectName('primary')
    item.setCursor(Qt.PointingHandCursor)
    item.clicked.connect(callback)
    return item


class FilterComboBox(QComboBox):
    """A visible, native-drawn chevron; Qt stylesheets cannot draw CSS triangles."""
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor('#d5d5d5'))
        right = self.width() - 14
        middle = self.height() // 2
        painter.drawPolygon(QPolygon([
            QPoint(right - 6, middle - 3),
            QPoint(right + 6, middle - 3),
            QPoint(right, middle + 4),
        ]))
        painter.end()


def line_icon(kind, color='#bdbdbd'):
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 1.5))
    if kind == 'grid':
        for x in (4, 14):
            for y in (4, 14):
                p.drawRoundedRect(QRectF(x, y, 6, 6), 1, 1)
    elif kind == 'folder':
        path = QPainterPath()
        path.moveTo(3, 7)
        path.lineTo(3, 4)
        path.lineTo(10, 4)
        path.lineTo(12, 7)
        path.lineTo(21, 7)
        path.lineTo(21, 20)
        path.lineTo(3, 20)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == 'clock':
        p.drawEllipse(QRectF(3, 3, 18, 18))
        p.drawLine(12, 6, 12, 12)
        p.drawLine(12, 12, 16, 14)
    else:
        for y, x in [(5, 9), (12, 16), (19, 7)]:
            p.drawLine(3, y, 21, y)
            p.setBrush(QColor('#242424'))
            p.drawEllipse(QRectF(x-2, y-2, 4, 4))
    p.end()
    return QIcon(pixmap)


def panel(layout_type=QVBoxLayout, name='panel'):
    frame = QFrame()
    frame.setObjectName(name)
    layout = layout_type(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(8)
    return frame, layout


class ScanningBanner(QFrame):
    def __init__(self, on_cancel=None, parent=None):
        super().__init__(parent)
        self.setObjectName('task')
        self.setStyleSheet('''
            QFrame#task {
                background: #23272a;
                border: 1px solid #3c444c;
                border-radius: 10px;
            }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.title_label = label('Scanning for games...', kind='section')
        top.addWidget(self.title_label, 1)

        if on_cancel:
            self.cancel_btn = button('Cancel', on_cancel)
            self.cancel_btn.setStyleSheet('padding: 4px 12px; font-size: 12px;')
            top.addWidget(self.cancel_btn)
        else:
            self.cancel_btn = None
        layout.addLayout(top)

        self.detail_label = label('Checking folders...', kind='muted', wrap=True)
        layout.addWidget(self.detail_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        layout.addWidget(self.progress_bar)

    def show_scanning(self, title='Scanning for games...', detail='Starting folder scan...'):
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.progress_bar.setRange(0, 0)
        self.show()

    def set_status(self, text: str):
        self.detail_label.setText(text)

    def hide_scanning(self):
        self.hide()


class Worker(QThread):
    result = Signal(object)
    failed = Signal(object)
    progress = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.cancel = threading.Event()

    def run(self):
        try:
            self.result.emit(self.function(self.cancel, self.progress.emit))
        except Exception as error:
            self.failed.emit(error)


class ImageSignals(QObject):
    loaded = Signal(str, object)


class ImageJob(QRunnable):
    def __init__(self, path, signals):
        super().__init__()
        self.path, self.signals = path, signals

    def run(self):
        reader = QImageReader(self.path)
        size = reader.size()
        if size.isValid():
            size.scale(640, 400, Qt.KeepAspectRatio)
            reader.setScaledSize(size)
        self.signals.loaded.emit(self.path, reader.read())


class Thumbnails(QObject):
    ready = Signal(str, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.cache, self.pending = OrderedDict(), set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.signals = ImageSignals(self)
        self.signals.loaded.connect(self.receive)

    def receive(self, path, image):
        self.pending.discard(path)
        self.cache[path] = image
        while len(self.cache) > 150:
            self.cache.popitem(last=False)
        self.ready.emit(path, image)

    def request(self, path):
        if path not in self.pending and path not in self.cache:
            self.pending.add(path)
            self.pool.start(ImageJob(path, self.signals))


def thumbnails():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if not hasattr(app, 'thumbnails'):
        app.thumbnails = Thumbnails(app)
    return app.thumbnails


class Cover(QWidget):
    def __init__(self, name='', path='', portrait=False, parent=None):
        super().__init__(parent)
        self.name, self.path = name, path
        self.portrait = portrait
        self.pixmap = QPixmap()
        if path:
            service = thumbnails()
            if path in service.cache:
                self.pixmap = QPixmap.fromImage(service.cache[path])
            service.ready.connect(self.image_ready)
        # Steam's library cover is 600×900.  Keep that 2:3 frame so a cover
        # is shown whole instead of being zoomed and cropped to a grid slot.
        self.setFixedHeight(243 if portrait else 92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def image_ready(self, path, image):
        if path == self.path:
            self.pixmap = QPixmap.fromImage(image)
            self.update()

    def paintEvent(self, event):
        if self.path and self.pixmap.isNull():
            thumbnails().request(self.path)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, 10, 10)
        painter.setClipPath(clip)
        if not self.pixmap.isNull():
            image = self.pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            painter.drawPixmap((self.width() - image.width()) // 2, (self.height() - image.height()) // 2, image)
        else:
            palettes = [('#323438', '#282a2d'), ('#373532', '#2c2a28'), ('#303538', '#262b2e'), ('#353236', '#2b282c')]
            a, b = palettes[int(hashlib.md5(self.name.encode()).hexdigest()[:2], 16) % len(palettes)]
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0, QColor(a))
            gradient.setColorAt(1, QColor(b))
            painter.fillRect(rect, gradient)
            painter.setPen(QColor('#bdbdbd'))
            painter.setFont(QFont('Segoe UI', 25, QFont.Light))
            initials = ''.join(w[0] for w in self.name.split()[:2]).upper() or 'S'
            painter.drawText(rect.adjusted(24, 0, -24, 0), Qt.AlignLeft | Qt.AlignVCenter, initials)
            painter.setFont(QFont('Segoe UI', 9))
            painter.drawText(rect.adjusted(24, 0, -24, -16), Qt.AlignLeft | Qt.AlignBottom, 'NO ARTWORK')


class GameCard(QFrame):
    def __init__(self, game, edit, changed):
        super().__init__()
        self.setObjectName('card')
        # 180px card minus 18px margins leaves a 162×243 Cover frame (2:3).
        # Fixed shelf tiles also prevent QGridLayout from stretching a row of
        # covers into differently shaped rectangles on wide screens.
        self.setFixedWidth(180)
        self.setFixedHeight(341)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(5)
        # The library is a compact shelf: prefer Steam's vertical cover and
        # only fall back to a horizontal grid when no cover exists.
        cover = Cover(game.name, game.art.get('portrait') or game.art.get('landscape') or game.art.get('hero', ''), portrait=True)
        layout.addWidget(cover)
        row = QHBoxLayout()
        select = QCheckBox()
        select.setChecked(game.selected)
        select.setAccessibleName('Select ' + game.name)
        select.toggled.connect(lambda value: (setattr(game, 'selected', value), changed()))
        row.addWidget(select)
        title = label(game.name if len(game.name) < 32 else game.name[:29] + '…')
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setStyleSheet('font-size: 13px; font-weight: 600;')
        title.setToolTip(game.name)
        row.addWidget(title, 1)
        layout.addLayout(row)
        status = 'In Steam' if game.existing else ('Review needed' if game.confidence < 60 else 'Ready to add')
        if game.existing and game.pending:
            status = 'Pending changes'
        subtitle = ('EDEN  ·  ' if game.kind == 'eden' else '') + status
        state = label(subtitle, 'muted')
        if game.confidence < 60 and not game.existing:
            state.setStyleSheet('color: #ac7b35;')
        layout.addWidget(state)
        info = QHBoxLayout()
        info.addWidget(label(f'{len(game.art)}/5 artworks', 'muted'), 1)
        edit_button = button('Edit', lambda: edit(game))
        edit_button.setStyleSheet('padding: 3px 8px; font-size: 11px;')
        info.addWidget(edit_button)
        layout.addLayout(info)
        if game.note:
            state.setToolTip(game.note)
