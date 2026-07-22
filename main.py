"""
COLT — Command Launch Tool
Домашний command-palette для автоматизаций Windows.

Запуск:  python main.py
Хоткей:  Ctrl+Alt+Space (можно поменять ниже, в main())
"""

import sys
import os
import threading
import importlib.util

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, Signal, QObject

import keyboard
from rapidfuzz import process, fuzz
import pystray
from PIL import Image, ImageDraw

COLT_HOME = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
COMMANDS_DIR = os.path.join(COLT_HOME, "commands")


class CommandRegistry:
    """Сканирует папку commands/ и хранит все загруженные автоматизации."""

    def __init__(self, folder):
        self.folder = folder
        self.commands = {}  # name -> {"aliases": [...], "run": callable}
        self.reload()

    def reload(self):
        self.commands.clear()
        if not os.path.isdir(self.folder):
            os.makedirs(self.folder, exist_ok=True)

        for filename in os.listdir(self.folder):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue  # файлы с "_" — шаблоны/черновики, их пропускаем

            path = os.path.join(self.folder, filename)
            module_name = f"colt_cmd_{filename[:-3]}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as e:
                print(f"[COLT] Ошибка загрузки '{filename}': {e}")
                continue

            name = getattr(module, "NAME", filename)
            aliases = getattr(module, "ALIASES", [])
            run_func = getattr(module, "run", None)
            hotkey = getattr(module, "HOTKEY", None)  # опционально: своя комбинация клавиш

            if run_func is None:
                print(f"[COLT] В '{filename}' нет функции run() — пропускаю")
                continue

            self.commands[name] = {"aliases": aliases, "run": run_func, "hotkey": hotkey}

        print(f"[COLT] Загружено команд: {len(self.commands)}")

    def search(self, query):
        """Fuzzy-поиск по названиям и алиасам. Пустой запрос -> все команды."""
        if not query:
            return list(self.commands.keys())[:10]

        choice_to_name = {}
        choices = []
        for name, data in self.commands.items():
            choices.append(name)
            choice_to_name[name] = name
            for alias in data["aliases"]:
                choices.append(alias)
                choice_to_name[alias] = name

        matches = process.extract(query, choices, scorer=fuzz.WRatio, limit=30)

        ordered_names = []
        seen = set()
        for matched_text, score, _ in matches:
            name = choice_to_name[matched_text]
            if name not in seen:
                seen.add(name)
                ordered_names.append(name)

        return ordered_names[:10]

    def execute(self, name):
        cmd = self.commands.get(name)
        if not cmd:
            return
        try:
            cmd["run"]()
        except Exception as e:
            print(f"[COLT] Ошибка выполнения '{name}': {e}")


class SignalBridge(QObject):
    """Мост между потоком хоткея (keyboard) и главным потоком Qt."""
    toggle_signal = Signal()


class SearchPopup(QWidget):
    def __init__(self, registry: CommandRegistry):
        super().__init__()
        self.registry = registry

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.resize(520, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Введите команду...")
        self.input.textChanged.connect(self.update_results)
        self.input.returnPressed.connect(self.run_selected)

        self.results = QListWidget()
        self.results.itemActivated.connect(lambda item: self.run_and_hide(item.text()))

        layout.addWidget(self.input)
        layout.addWidget(self.results)

        self.setStyleSheet("""
            QWidget { background-color: #1e1e1e; color: #eaeaea; }
            QLineEdit { font-size: 18px; padding: 8px; border: none; background: #2a2a2a; border-radius: 6px; }
            QListWidget { font-size: 15px; border: none; background: #1e1e1e; }
            QListWidget::item { padding: 6px; }
            QListWidget::item:selected { background: #3a6df0; border-radius: 4px; }
        """)

    def update_results(self, text):
        self.results.clear()
        for name in self.registry.search(text):
            self.results.addItem(QListWidgetItem(name))
        if self.results.count() > 0:
            self.results.setCurrentRow(0)

    def run_selected(self):
        item = self.results.currentItem()
        if item:
            self.run_and_hide(item.text())

    def run_and_hide(self, name):
        self.registry.execute(name)
        self.hide_popup()

    def show_popup(self):
        self.input.clear()
        self.update_results("")
        screen = self.screen().geometry()
        x = screen.center().x() - self.width() // 2
        y = screen.center().y() - self.height() // 2 - 100
        self.move(x, y)
        self.show()
        self.activateWindow()
        self.input.setFocus()

    def hide_popup(self):
        self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide_popup()
        else:
            super().keyPressEvent(event)


def make_tray_icon(app: QApplication, reload_all_callback):
    image = Image.new("RGB", (64, 64), "#3a6df0")
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 14, 46, 50), outline="white", width=3)

    def on_reload(icon, item):
        reload_all_callback()

    def on_quit(icon, item):
        icon.stop()
        app.quit()

    menu = pystray.Menu(
        pystray.MenuItem("Перезагрузить команды", on_reload),
        pystray.MenuItem("Выход", on_quit),
    )
    return pystray.Icon("COLT", image, "COLT", menu)


def main():
    registry = CommandRegistry(COMMANDS_DIR)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    popup = SearchPopup(registry)

    bridge = SignalBridge()
    bridge.toggle_signal.connect(
        lambda: popup.hide_popup() if popup.isVisible() else popup.show_popup()
    )

    MAIN_HOTKEY = "ctrl+alt+space"  # хоткей для открытия окна поиска COLT
    keyboard.add_hotkey(MAIN_HOTKEY, lambda: bridge.toggle_signal.emit())
    print(f"[COLT] Хоткей открытия COLT активен: {MAIN_HOTKEY}")

    # Персональные хоткеи команд (например HOTKEY = "ctrl+space" в файле команды)
    # выполняют команду напрямую, минуя попап.
    registered_command_hotkeys = []

    def register_command_hotkeys():
        for hk in registered_command_hotkeys:
            try:
                keyboard.remove_hotkey(hk)
            except KeyError:
                pass
        registered_command_hotkeys.clear()

        for name, data in registry.commands.items():
            hotkey = data.get("hotkey")
            if not hotkey:
                continue
            if hotkey == MAIN_HOTKEY:
                print(f"[COLT] Хоткей '{hotkey}' команды '{name}' совпадает с MAIN_HOTKEY — пропускаю")
                continue
            try:
                keyboard.add_hotkey(hotkey, lambda n=name: registry.execute(n))
                registered_command_hotkeys.append(hotkey)
                print(f"[COLT] Команда '{name}' привязана к хоткею: {hotkey}")
            except Exception as e:
                print(f"[COLT] Не удалось привязать хоткей '{hotkey}' для '{name}': {e}")

    register_command_hotkeys()

    def reload_all():
        registry.reload()
        register_command_hotkeys()

    tray_icon = make_tray_icon(app, reload_all)
    threading.Thread(target=tray_icon.run, daemon=True).start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()