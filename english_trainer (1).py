
# english_trainer.py
# A gamified English vocabulary trainer with spaced repetition (SM-2 simplified).
# Requires: PySide6
# Run:  pip install PySide6
#       python english_trainer.py

from __future__ import annotations
import sys, json, csv, random
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer, QSize, QPropertyAnimation
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QMessageBox, QProgressBar, QSpinBox, QFileDialog, QComboBox,
    QTableWidget, QTableWidgetItem, QGroupBox, QGridLayout, QLineEdit, QDialog, QFormLayout,
    QGraphicsOpacityEffect
)

APP_NAME = "English Trainer"
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
WORDS_CSV = DATA_DIR / "words.csv"
PROGRESS_JSON = DATA_DIR / "progress.json"

# --- bootstrap: создать стартовый словарь, если его нет ---
STARTER_CSV = """english,russian,ipa,example
time,время,taɪm,I don't have much time.
person,человек,ˈpɜːsən,She's a kind person.
year,год,jɪə,This year is important.
day,день,deɪ,What a beautiful day!
thing,вещь,θɪŋ,That's a simple thing.
man,мужчина,mæn,The man is walking.
woman,женщина,ˈwʊmən,That woman is a doctor.
child,ребёнок,tʃaɪld,Every child needs love.
world,мир,wɜːld,The world is changing.
work,работа, wɜːk,I work hard.
water,вода,ˈwɔːtə,Drink more water.
friend,друг,frend,He's my friend.
house,дом,haʊs,A big house.
money,деньги,ˈmʌni,Save your money.
game,игра,ɡeɪm,Let's play a game.
be,быть,biː,To be or not to be.
have,иметь,hæv,I have a car.
do,делать,duː,Do your best.
go,идти,ɡəʊ,Go home.
say,сказать,seɪ,Say it again.
get,получать,ɡet,Get some rest.
make,делать,meɪk,Make a plan.
see,видеть,siː,I see the point.
know,знать,nəʊ,I know him.
take,брать,teɪk,Take a seat.
"""
DATA_DIR.mkdir(parents=True, exist_ok=True)
if not WORDS_CSV.exists():
    WORDS_CSV.write_text(STARTER_CSV, encoding="utf-8")
# --- end bootstrap ---

def today() -> datetime:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

@dataclass
class Word:
    english: str
    russian: str
    ipa: str = ""
    example: str = ""

@dataclass
class CardState:
    # Simplified SM-2 state per word
    ease: float = 2.5
    interval_days: int = 0
    reps: int = 0
    lapses: int = 0
    due: str = today().strftime("%Y-%m-%d")
    # Stats
    total_seen: int = 0
    correct: int = 0
    streak: int = 0
    last_seen: str = ""
    last_result: str = ""  # "again"/"hard"/"good"/"easy"

class DataManager:
    def __init__(self, csv_path: Path, progress_path: Path):
        self.csv_path = csv_path
        self.progress_path = progress_path
        self.words: list[Word] = []
        self.progress: dict[str, dict] = {}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Dataset not found: {self.csv_path}")
        self.load_words()
        self.load_progress()

    def load_words(self):
        self.words.clear()
        with self.csv_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.words.append(Word(row["english"].strip(), row["russian"].strip(), row.get("ipa","").strip(), row.get("example","").strip()))

    def load_progress(self):
        if self.progress_path.exists():
            try:
                self.progress = json.loads(self.progress_path.read_text(encoding="utf-8"))
            except Exception:
                self.progress = {}
        else:
            self.progress = {}

    def save_progress(self):
        self.progress_path.write_text(json.dumps(self.progress, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_card_state(self, w: Word) -> CardState:
        state = self.progress.get(w.english)
        if state is None:
            cs = CardState()
            self.progress[w.english] = asdict(cs)
            return cs
        # backward compatibility / robustness
        cs = CardState(**{**CardState().__dict__, **state})
        return cs

    def update_card_state(self, w: Word, cs: CardState):
        self.progress[w.english] = asdict(cs)

    def due_words(self, limit: int | None = None) -> list[Word]:
        d = today().strftime("%Y-%m-%d")
        due_list = []
        for w in self.words:
            cs = self.get_card_state(w)
            if cs.due <= d and cs.interval_days > 0:
                due_list.append(w)
        random.shuffle(due_list)
        return due_list[:limit] if limit else due_list

    def new_words(self, limit: int) -> list[Word]:
        new_list = [w for w in self.words if self.get_card_state(w).reps == 0 and self.get_card_state(w).interval_days == 0]
        random.shuffle(new_list)
        return new_list[:limit]

    def last_week_words(self) -> list[Word]:
        week_ago = today() - timedelta(days=7)
        picked = []
        for w in self.words:
            cs = self.get_card_state(w)
            if cs.last_seen:
                try:
                    last = datetime.strptime(cs.last_seen, "%Y-%m-%d")
                    if last >= week_ago:
                        picked.append(w)
                except Exception:
                    pass
        random.shuffle(picked)
        return picked

class SRS:
    @staticmethod
    def rate(cs: CardState, quality: int) -> CardState:
        # quality: 0=again, 3=hard, 4=good, 5=easy
        # Simplified SM-2
        cs.total_seen += 1
        cs.last_seen = today().strftime("%Y-%m-%d")
        if quality < 3:
            cs.reps = 0
            cs.lapses += 1
            cs.interval_days = 1
            cs.due = (today() + timedelta(days=cs.interval_days)).strftime("%Y-%m-%d")
            cs.streak = 0
            cs.last_result = "again"
            return cs

        if cs.reps == 0:
            cs.interval_days = 1 if quality == 3 else 1
        elif cs.reps == 1:
            cs.interval_days = 6 if quality >= 4 else 3
        else:
            # Update ease
            cs.ease = cs.ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
            if cs.ease < 1.3:
                cs.ease = 1.3
            # Interval grows
            cs.interval_days = int(round(cs.interval_days * cs.ease))
            if quality == 3:
                cs.interval_days = max(2, int(cs.interval_days * 0.8))
            elif quality == 5:
                cs.interval_days = int(cs.interval_days * 1.2)

        cs.reps += 1
        cs.correct += 1
        cs.streak += 1
        cs.due = (today() + timedelta(days=cs.interval_days)).strftime("%Y-%m-%d")
        cs.last_result = {3:"hard",4:"good",5:"easy"}.get(quality,"good")
        return cs

class LearnWidget(QWidget):
    def __init__(self, dm: DataManager):
        super().__init__()
        self.dm = dm
        self.daily_target = 20
        self.direction = "EN→RU"  # or "RU→EN"
        self.queue: list[Word] = []
        self.current: Word | None = None
        self.showing_answer = False

        # UI
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.info_label = QLabel("Готов?")
        self.info_label.setWordWrap(True)
        top.addWidget(self.info_label, 1)

        self.dir_box = QComboBox()
        self.dir_box.addItems(["EN→RU", "RU→EN"])
        self.dir_box.currentTextChanged.connect(self._change_direction)
        top.addWidget(self.dir_box)

        v.addLayout(top)

        self.word_label = QLabel("Нажми «Старт»")
        self.word_label.setAlignment(Qt.AlignCenter)
        self.word_label.setStyleSheet("font-size: 28px; font-weight: 600;")
        self.word_label.setWordWrap(True)
        v.addWidget(self.word_label, 3)
        self.word_effect = QGraphicsOpacityEffect(self.word_label)
        self.word_label.setGraphicsEffect(self.word_effect)
        self.word_anim = QPropertyAnimation(self.word_effect, b"opacity")
        self.word_anim.setDuration(500)

        self.ipa_label = QLabel("")
        self.ipa_label.setAlignment(Qt.AlignCenter)
        self.ipa_label.setStyleSheet("font-size: 16px; color: #666;")
        v.addWidget(self.ipa_label)

        self.example_label = QLabel("")
        self.example_label.setAlignment(Qt.AlignCenter)
        self.example_label.setStyleSheet("font-size: 14px; color: #888;")
        self.example_label.setWordWrap(True)
        v.addWidget(self.example_label)
        self.example_effect = QGraphicsOpacityEffect(self.example_label)
        self.example_label.setGraphicsEffect(self.example_effect)
        self.example_anim = QPropertyAnimation(self.example_effect, b"opacity")
        self.example_anim.setDuration(500)

        self.hint_label = QLabel("")
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setStyleSheet("font-size: 16px; color: #ffaa00;")
        self.hint_label.setWordWrap(True)
        v.addWidget(self.hint_label)

        btns = QHBoxLayout()
        self.start_btn = QPushButton("Старт")
        self.start_btn.clicked.connect(self.prepare_queue)
        btns.addWidget(self.start_btn)

        self.show_btn = QPushButton("Показать (Space)")
        self.show_btn.clicked.connect(self.show_answer)
        btns.addWidget(self.show_btn)

        self.hint_btn = QPushButton("Подсказка")
        self.hint_btn.clicked.connect(self.show_hint)
        btns.addWidget(self.hint_btn)

        v.addLayout(btns)

        rate_box = QHBoxLayout()
        self.btn_again = QPushButton("Again [1]")
        self.btn_again.clicked.connect(lambda: self.rate(0))
        self.btn_hard = QPushButton("Hard [2]")
        self.btn_hard.clicked.connect(lambda: self.rate(3))
        self.btn_good = QPushButton("Good [3]")
        self.btn_good.clicked.connect(lambda: self.rate(4))
        self.btn_easy = QPushButton("Easy [4]")
        self.btn_easy.clicked.connect(lambda: self.rate(5))

        for b in (self.btn_again, self.btn_hard, self.btn_good, self.btn_easy):
            b.setEnabled(False)
            b.setMinimumHeight(36)
            rate_box.addWidget(b)

        v.addLayout(rate_box)

        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        bottom.addWidget(self.progress, 2)
        self.stats_label = QLabel("0 due • 0 new • цель: 20")
        bottom.addWidget(self.stats_label, 1)
        v.addLayout(bottom)

        self.setFocusPolicy(Qt.StrongFocus)
        self.hint_btn.setEnabled(False)

    def _change_direction(self, text):
        self.direction = text
        # Reset card state
        self.showing_answer = False
        if self.current:
            self._render_card(self.current)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self.show_answer()
            return
        if not any(b.isEnabled() for b in (self.btn_again, self.btn_hard, self.btn_good, self.btn_easy)):
            return
        mapping = {
            Qt.Key_1: 0,
            Qt.Key_2: 3,
            Qt.Key_3: 4,
            Qt.Key_4: 5
        }
        if event.key() in mapping:
            self.rate(mapping[event.key()])

    def prepare_queue(self):
        due = self.dm.due_words()
        new_quota = max(0, self.daily_target - len(due))
        neww = self.dm.new_words(new_quota)
        self.queue = due + neww
        random.shuffle(self.queue)
        self.progress.setValue(0)
        self.progress.setRange(0, max(1, len(self.queue)))
        self.stats_label.setText(f"{len(due)} due • {len(neww)} new • цель: {self.daily_target}")
        if not self.queue:
            self.word_label.setText("Готово!")
            self.ipa_label.setText("")
            self.example_label.setText("")
            self.hint_label.setText("")
            self.hint_btn.setEnabled(False)
            QMessageBox.information(self, "Ура!", "На сегодня нет карточек. Можно поиграть в мини-игры на вкладке «Игры».")
            return
        self.next_card()

    def next_card(self):
        self.showing_answer = False
        if not self.queue:
            self.word_label.setText("Готово!")
            self.ipa_label.setText("")
            self.example_label.setText("")
            self.hint_label.setText("")
            for b in (self.btn_again, self.btn_hard, self.btn_good, self.btn_easy):
                b.setEnabled(False)
            self.hint_btn.setEnabled(False)
            self.dm.save_progress()
            return
        self.current = self.queue.pop(0)
        self._render_card(self.current)
        for b in (self.btn_again, self.btn_hard, self.btn_good, self.btn_easy):
            b.setEnabled(False)
        self.show_btn.setEnabled(True)
        self.hint_btn.setEnabled(True)

    def _render_card(self, w: Word):
        self.hint_label.setText("")
        if self.direction == "EN→RU":
            self.word_label.setText(w.english)
            self.ipa_label.setText(f"/{w.ipa}/" if w.ipa else "")
            self.example_label.setText(w.example)
        else:
            self.word_label.setText(w.russian)
            self.ipa_label.setText("")
            self.example_label.setText("")
        self.word_effect.setOpacity(0)
        self.example_effect.setOpacity(0)
        self.word_anim.setStartValue(0)
        self.word_anim.setEndValue(1)
        self.word_anim.start()
        self.example_anim.setStartValue(0)
        self.example_anim.setEndValue(1)
        self.example_anim.start()

    def show_answer(self):
        if not self.current:
            return
        if not self.showing_answer:
            # flip
            w = self.current
            if self.direction == "EN→RU":
                self.word_label.setText(f"{w.english} — {w.russian}")
            else:
                self.word_label.setText(f"{w.russian} — {w.english}")
                self.ipa_label.setText(f"/{w.ipa}/" if w.ipa else "")
                self.example_label.setText(w.example)
            self.showing_answer = True
            for b in (self.btn_again, self.btn_hard, self.btn_good, self.btn_easy):
                b.setEnabled(True)
            self.show_btn.setEnabled(False)
            self.hint_btn.setEnabled(False)

    def show_hint(self):
        if not self.current or self.showing_answer:
            return
        word = self.current.russian if self.direction == "EN→RU" else self.current.english
        if word:
            self.hint_label.setText(f"Подсказка: {word[0]}...")
            self.hint_btn.setEnabled(False)

    def rate(self, q: int):
        if not self.current:
            return
        cs = self.dm.get_card_state(self.current)
        cs = SRS.rate(cs, q)
        self.dm.update_card_state(self.current, cs)
        self.progress.setValue(self.progress.value() + 1)
        self.next_card()

class GamesWidget(QWidget):
    def __init__(self, dm: DataManager):
        super().__init__()
        self.dm = dm
        v = QVBoxLayout(self)

        # Multiple choice EN->RU
        v.addWidget(self._quiz_box("Выбор (EN→RU)", lambda: self.multiple_choice("EN→RU")))
        v.addWidget(self._quiz_box("Выбор (RU→EN)", lambda: self.multiple_choice("RU→EN")))
        v.addWidget(self._quiz_box("Печать слова (RU→EN)", self.typing_quiz))
        v.addWidget(self._quiz_box("Спринт 60 секунд", self.sprint_60))
        v.addWidget(self._quiz_box("Weekly Quiz (последние 7 дней)", self.weekly_quiz))

        self.status = QLabel("Выбирай режим и атакуй!")
        v.addWidget(self.status)

    def _quiz_box(self, title: str, on_start):
        box = QGroupBox(title)
        lay = QHBoxLayout(box)
        btn = QPushButton("Старт")
        btn.clicked.connect(on_start)
        lay.addWidget(btn)
        return box

    def _pick_pool(self) -> list[Word]:
        pool = self.dm.due_words() + self.dm.new_words(50) + self.dm.last_week_words()
        if not pool:
            pool = self.dm.words[:]
        random.shuffle(pool)
        return pool[:200]

    def multiple_choice(self, direction="EN→RU", rounds=10):
        pool = self._pick_pool()
        if len(pool) < 4:
            QMessageBox.information(self, "Мало слов", "Добавь больше слов или учись во вкладке «Учить».")
            return
        score = 0
        for _ in range(rounds):
            q = random.choice(pool)
            options = {q}
            while len(options) < 4:
                options.add(random.choice(pool))
            options = list(options)
            random.shuffle(options)
            if direction == "EN→RU":
                question = q.english
                opts_text = [w.russian for w in options]
                correct = q.russian
            else:
                question = q.russian
                opts_text = [w.english for w in options]
                correct = q.english
            answer, ok = self._ask_mc(f"{direction}: {question}", opts_text)
            if not ok:
                break
            if answer == correct:
                score += 1
        QMessageBox.information(self, "Итог", f"Очки: {score}/{rounds}")

    def _ask_mc(self, title, options):
        # simple dialog replacement using QMessageBox buttons
        msg = QMessageBox()
        msg.setWindowTitle(title)
        msg.setText("Выбери ответ:")
        buttons = []
        for opt in options:
            b = msg.addButton(opt, QMessageBox.ActionRole)
            buttons.append(b)
        msg.addButton("Отмена", QMessageBox.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked.text() == "Отмена":
            return None, False
        return clicked.text(), True

    def typing_quiz(self, rounds=10):
        pool = self._pick_pool()
        score = 0
        for _ in range(rounds):
            w = random.choice(pool)
            text, ok = self._ask_input(f"RU→EN: {w.russian}", "Введи слово на английском:")
            if not ok:
                break
            if text.strip().lower() == w.english.lower():
                score += 1
        QMessageBox.information(self, "Итог", f"Очки: {score}/{rounds}")

    def _ask_input(self, title, prompt):
        dlg = QMessageBox()
        dlg.setWindowTitle(title)
        dlg.setText(prompt)
        # Using a simple workaround: separate input dialog
        text, ok = QInputDialogWithText.getText(self, title, prompt)
        return text, ok

    def sprint_60(self):
        pool = self._pick_pool()
        end_time = datetime.now() + timedelta(seconds=60)
        score = 0
        while datetime.now() < end_time:
            w = random.choice(pool)
            options = [w]
            while len(options) < 4:
                c = random.choice(pool)
                if c not in options:
                    options.append(c)
            random.shuffle(options)
            question = w.english
            opts_text = [x.russian for x in options]
            correct = w.russian
            ans, ok = self._ask_mc(f"Спринт — осталось {(end_time - datetime.now()).seconds}s\n{question}", opts_text)
            if not ok:
                break
            if ans == correct:
                score += 1
        QMessageBox.information(self, "Финиш!", f"Очки за 60 секунд: {score}")

    def weekly_quiz(self, rounds=12):
        pool = self.dm.last_week_words()
        if len(pool) < 4:
            QMessageBox.information(self, "Пока рано", "За последнюю неделю мало слов. Учись во вкладке «Учить».")
            return
        score = 0
        for _ in range(rounds):
            w = random.choice(pool)
            direction = random.choice(["EN→RU","RU→EN"])
            if direction == "EN→RU":
                question = w.english
                correct = w.russian
                options = [w]
                while len(options) < 4:
                    c = random.choice(pool)
                    if c not in options:
                        options.append(c)
                random.shuffle(options)
                opts_text = [x.russian for x in options]
            else:
                question = w.russian
                correct = w.english
                options = [w]
                while len(options) < 4:
                    c = random.choice(pool)
                    if c not in options:
                        options.append(c)
                random.shuffle(options)
                opts_text = [x.english for x in options]
            ans, ok = self._ask_mc(f"Weekly Quiz {direction}: {question}", opts_text)
            if not ok:
                break
            if ans == correct:
                score += 1
        QMessageBox.information(self, "Итог недели", f"Очки: {score}/{rounds}")

class QInputDialogWithText(QWidget):
    # Tiny helper to get text input without extra deps
    @staticmethod
    def getText(parent, title, prompt):
        w = QWidget(parent)
        w.setWindowTitle(title)
        layout = QVBoxLayout(w)
        lab = QLabel(prompt)
        layout.addWidget(lab)
        edit = QLineEdit()
        layout.addWidget(edit)
        btns = QHBoxLayout()
        okb = QPushButton("OK")
        cancelb = QPushButton("Отмена")
        btns.addWidget(okb)
        btns.addWidget(cancelb)
        layout.addLayout(btns)
        result = {"ok": False, "text": ""}
        def ok():
            result["ok"] = True
            result["text"] = edit.text()
            w.close()
        def cancel():
            result["ok"] = False
            w.close()
        okb.clicked.connect(ok)
        cancelb.clicked.connect(cancel)
        w.setWindowModality(Qt.ApplicationModal)
        w.resize(400,120)
        w.show()
        app = QApplication.instance()
        while w.isVisible():
            app.processEvents()
        return result["text"], result["ok"]

class ProgressWidget(QWidget):
    def __init__(self, dm: DataManager):
        super().__init__()
        self.dm = dm
        v = QVBoxLayout(self)
        self.labels = QLabel("Статистика появится после первой сессии.")
        v.addWidget(self.labels)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["EN","RU","Ease","Interval","Reps","Due"])
        v.addWidget(self.table, 1)
        self.refresh()

    def refresh(self):
        total = len(self.dm.words)
        learned = sum(1 for w in self.dm.words if self.dm.get_card_state(w).reps > 0)
        due_today = len(self.dm.due_words())
        text = f"Всего слов: {total} • Выучено: {learned} • Долги на сегодня: {due_today}"
        self.labels.setText(text)

        rows = min(200, total)
        self.table.setRowCount(0)
        for i, w in enumerate(self.dm.words[:rows]):
            cs = self.dm.get_card_state(w)
            self.table.insertRow(i)
            self.table.setItem(i,0,QTableWidgetItem(w.english))
            self.table.setItem(i,1,QTableWidgetItem(w.russian))
            self.table.setItem(i,2,QTableWidgetItem(f"{cs.ease:.2f}"))
            self.table.setItem(i,3,QTableWidgetItem(str(cs.interval_days)))
            self.table.setItem(i,4,QTableWidgetItem(str(cs.reps)))
            self.table.setItem(i,5,QTableWidgetItem(cs.due))

class SettingsWidget(QWidget):
    def __init__(self, learn_widget: LearnWidget, dm: DataManager):
        super().__init__()
        self.learn_widget = learn_widget
        self.dm = dm
        v = QVBoxLayout(self)

        # Daily target
        box = QGroupBox("Дневной план")
        lay = QHBoxLayout(box)
        lay.addWidget(QLabel("Сколько слов в день:"))
        self.spin = QSpinBox()
        self.spin.setRange(5, 200)
        self.spin.setValue(self.learn_widget.daily_target)
        lay.addWidget(self.spin)
        btn = QPushButton("Сохранить")
        btn.clicked.connect(self.save_target)
        lay.addWidget(btn)
        v.addWidget(box)

        # Dataset actions
        box2 = QGroupBox("Словари")
        lay2 = QHBoxLayout(box2)
        add_btn = QPushButton("Добавить слово")
        add_btn.clicked.connect(self.add_word)
        lay2.addWidget(add_btn)
        import_btn = QPushButton("Импорт CSV (+добавить слова)")
        import_btn.clicked.connect(self.import_csv)
        lay2.addWidget(import_btn)
        export_btn = QPushButton("Экспорт прогресса")
        export_btn.clicked.connect(self.export_progress)
        lay2.addWidget(export_btn)
        reset_btn = QPushButton("Сбросить прогресс (осторожно)")
        reset_btn.clicked.connect(self.reset_progress)
        lay2.addWidget(reset_btn)
        v.addWidget(box2)
        v.addStretch(1)

    def save_target(self):
        self.learn_widget.daily_target = self.spin.value()
        QMessageBox.information(self, "Готово", f"Дневная цель: {self.learn_widget.daily_target}")

    def add_word(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Добавить слово")
        form = QFormLayout(dlg)
        en_edit = QLineEdit()
        ru_edit = QLineEdit()
        ipa_edit = QLineEdit()
        ex_edit = QLineEdit()
        form.addRow("English:", en_edit)
        form.addRow("Russian:", ru_edit)
        form.addRow("IPA:", ipa_edit)
        form.addRow("Example:", ex_edit)
        btn = QPushButton("Сохранить")
        btn.clicked.connect(dlg.accept)
        form.addWidget(btn)
        if dlg.exec() == QDialog.Accepted:
            en = en_edit.text().strip()
            ru = ru_edit.text().strip()
            ipa = ipa_edit.text().strip()
            ex = ex_edit.text().strip()
            if en and ru:
                with WORDS_CSV.open("a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([en, ru, ipa, ex])
                self.dm.load_words()
                QMessageBox.information(self, "OK", "Слово добавлено")

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбери CSV со словами", "", "CSV Files (*.csv)")
        if not path:
            return
        added = 0
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = {"english","russian"}
            if not required.issubset(set(reader.fieldnames or [])):
                QMessageBox.warning(self, "Ошибка", "CSV должен содержать как минимум столбцы: english,russian")
                return
            rows = list(reader)
        # Append
        with WORDS_CSV.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for r in rows:
                en = r.get("english","").strip()
                ru = r.get("russian","").strip()
                ipa = (r.get("ipa","") or "").strip()
                ex = (r.get("example","") or "").strip()
                if en and ru:
                    writer.writerow([en,ru,ipa,ex])
                    added += 1
        self.dm.load_words()
        QMessageBox.information(self, "Импортированo", f"Добавлено слов: {added}")

    def export_progress(self):
        save_path, _ = QFileDialog.getSaveFileName(self, "Сохранить прогресс как JSON", "progress.json", "JSON Files (*.json)")
        if not save_path:
            return
        Path(save_path).write_text(json.dumps(self.dm.progress, ensure_ascii=False, indent=2), encoding="utf-8")
        QMessageBox.information(self, "OK", "Прогресс сохранён.")

    def reset_progress(self):
        yes = QMessageBox.question(self, "Подтверди", "Точно сбросить весь прогресс?")
        if yes == QMessageBox.Yes:
            self.dm.progress = {}
            self.dm.save_progress()
            QMessageBox.information(self, "Сброшено", "Начинаем заново!")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(880, 640)

        self.dm = DataManager(WORDS_CSV, PROGRESS_JSON)
        self.learn = LearnWidget(self.dm)
        self.games = GamesWidget(self.dm)
        self.progress = ProgressWidget(self.dm)
        self.settings = SettingsWidget(self.learn, self.dm)

        tabs = QTabWidget()
        tabs.addTab(self.learn, "Учить")
        tabs.addTab(self.games, "Игры")
        tabs.addTab(self.progress, "Прогресс")
        tabs.addTab(self.settings, "Настройки")
        self.setCentralWidget(tabs)

        # Game-like dark theme
        self.setStyleSheet(
            """
            QWidget { background-color: #1e1e2f; color: #e8e8ff; }
            QPushButton {
                background-color: #3c3c54;
                border: 2px solid #5a5a7a;
                border-radius: 8px;
                padding: 6px 12px;
            }
            QPushButton:hover { background-color: #505070; }
            QPushButton:disabled { background-color: #2a2a3f; color: #555; }
            QProgressBar { background-color: #2a2a3f; border-radius: 5px; }
            QProgressBar::chunk { background-color: #29a329; border-radius: 5px; }
            """
        )

        # Menu
        bar = self.menuBar()
        file_menu = bar.addMenu("Файл")
        act_save = QAction("Сохранить прогресс", self)
        act_save.triggered.connect(self.dm.save_progress)
        file_menu.addAction(act_save)
        act_exit = QAction("Выход", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        help_menu = bar.addMenu("Помощь")
        act_about = QAction("О программе", self)
        act_about.triggered.connect(self.about)
        help_menu.addAction(act_about)

    def about(self):
        QMessageBox.information(self, "О программе",
            "English Trainer — лёгкое приложение для запоминания слов (SRS + мини‑игры).\n"
            "Формат словаря: CSV с колонками english,russian,ipa,example.\n"
            "Горячие клавиши в учебнике: Space, 1=Again, 2=Hard, 3=Good, 4=Easy.\n"
        )

def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
