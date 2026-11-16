"""
SolomonAir: AirFight v5.1 — «Штаб Второй Мировой».
Пошаговая тактическая игра на Python 3.10+ / Pygame.

Запуск:
    python -m pip install pygame  # или pygame-ce (совместимая замена)
    python solomonair_airfight.py

Что нового в v3.0 (механика боя v2.0 не менялась):
- стиль «карта штаба»: старая бумага, чернила, шрифты с засечками, рисованная от руки сетка;
- глобальная карта (game_state = "MAP"): два сектора, клик — бой 9×9 над сектором,
  исход боя меняет владельца сектора (game_state = "BATTLE");
- система событий «Газетная вырезка»: класс Event, очередь event_queue, окно ставит игру на паузу.

Управление в бою:
- Клик по клетке правого поля — выбрать цель выстрела.
- Клик по своему самолёту — выбрать его (для перевеса и просмотра типа).
- «ПЕРЕВЕСИТЬ» — запомнить выбранный самолёт как новую цель истребителя
  (сработает после «ХОД»; клик по другой клетке своего поля сбрасывает выбор).
- «ПВО» — выбрать ПВО вместо обычного выстрела.
- «ХОД» — выполнить ход: перевес → движение → выстрел → урон → ход ИИ.
В окне газеты: «Продолжить» (или Enter / Пробел).
"""
from __future__ import annotations

import math
import random
import sys
import json
import os
import tempfile
from dataclasses import dataclass
from typing import Iterator, Optional

import pygame
pygame.init()

def resource_path(relative_path):
    """Путь к ресурсу рядом с игрой или внутри сборки PyInstaller."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

SETTINGS = {"fullscreen": False, "rotor": True, "newspapers": True, "music": True}
MUSIC_PATH = None

pygame.display.set_caption("SolomonAir: AirFight")

# ============================ ОКНО И СЕТКА ============================
W, H = 1400, 850
FPS = 60
MAX_DT_MS = 50                      # ограничение шага времени (после лагов анимация не «прыгает»)
SCREEN = pygame.display.set_mode((W, H))
CLOCK = pygame.time.Clock()


def set_fullscreen(enabled):
    """Переключает режим окна, сохраняя логический размер игры и пропорции."""
    global SCREEN
    if enabled:
        SCREEN = pygame.display.set_mode((W, H), pygame.FULLSCREEN | pygame.SCALED)
    else:
        SCREEN = pygame.display.set_mode((W, H))
    return SCREEN


# Музыка необязательна. Для MP3/OGG задаём явный формат микшера;
# если один файл не читается, пробуем следующий из списка.
try:
    pygame.mixer.quit()  # pygame.init() мог включить микшер с параметрами по умолчанию
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    for _music_name in ("bgm.mp3", "bgm.ogg", "music.mp3"):
        _candidate = resource_path(_music_name)
        if os.path.isfile(_candidate):
            try:
                pygame.mixer.music.load(_candidate)
                pygame.mixer.music.set_volume(0.30)
                pygame.mixer.music.play(-1)
                MUSIC_PATH = _candidate
                break
            except Exception:
                continue
except Exception:
    MUSIC_PATH = None

GRID_SIZE = 9                       # поле 9x9
CELL = 40                           # размер клетки в пикселях
BOARD = CELL * GRID_SIZE
LEFT_X, RIGHT_X, BOARD_Y = 55, 535, 185
BOARD_RECT_L = pygame.Rect(LEFT_X, BOARD_Y, BOARD, BOARD)
BOARD_RECT_R = pygame.Rect(RIGHT_X, BOARD_Y, BOARD, BOARD)

# Панель управления и кнопки (одни и те же Rect — и для рисования, и для кликов)
PANEL_RECT = pygame.Rect(1015, 135, 340, 570)
PANEL_TEXT_X = 1040
BTN_PVO = pygame.Rect(1040, 255, 140, 43)
BTN_NORMAL = pygame.Rect(1190, 255, 140, 43)
BTN_RADAR = pygame.Rect(1040, 300, 290, 40)
BTN_MENU = pygame.Rect(1270, 2, 115, 32)
BTN_PLAY = pygame.Rect(560, 325, 280, 44)
BTN_LOAD = pygame.Rect(560, 378, 280, 44)
BTN_SETTINGS = pygame.Rect(560, 431, 280, 44)
BTN_DEVS = pygame.Rect(560, 484, 280, 44)
BTN_EXIT = pygame.Rect(560, 537, 280, 44)
PAUSE_BOX = pygame.Rect(480, 245, 440, 360)
PAUSE_CONTINUE = pygame.Rect(560, 330, 280, 48)
PAUSE_SAVE = pygame.Rect(560, 395, 280, 48)
PAUSE_HOME = pygame.Rect(560, 460, 280, 48)
DEV_CLOSE = pygame.Rect(650, 510, 180, 42)
SETTINGS_BACK = pygame.Rect(560, 690, 280, 46)
def _user_data_dir():
    """Папка пользовательских данных; не зависит от прав на каталог игры."""
    candidates = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(appdata)
    # Резервные варианты для систем без APPDATA или с недоступным APPDATA.
    candidates.append(os.path.join(os.path.expanduser("~"), ".config"))
    candidates.append(tempfile.gettempdir())
    last_error = None
    for base in candidates:
        path = os.path.join(base, "SolomonAir")
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError as exc:
            last_error = exc
    # Возвращаем последний путь: дальнейшие save/load функции перехватят ошибку.
    print(f"Не удалось создать папку данных SolomonAir: {last_error}")
    return os.path.join(tempfile.gettempdir(), "SolomonAir")


def _user_data_file(filename):
    return os.path.join(_user_data_dir(), filename)


SAVE_FILE = _user_data_file("savegame.json")
BTN_REBALANCE = pygame.Rect(1040, 515, 290, 40)
BTN_TURN = pygame.Rect(1040, 565, 290, 48)
BTN_BACK = pygame.Rect(560, 448, 280, 46)           # «Вернуться на карту»

# Окно «газетной вырезки»
EVENT_RECT = pygame.Rect(310, 105, 780, 640)
BTN_CONTINUE = pygame.Rect(EVENT_RECT.centerx - 110, EVENT_RECT.bottom - 62, 220, 44)

# Состояния игры
STATE_MAP = "MAP"
STATE_BATTLE = "BATTLE"
STATE_SETTINGS = "SETTINGS"

# ============================ ПАЛИТРА («Штаб Второй Мировой») ============================
PAPER = (232, 220, 196)             # #E8DCC4 — старая бумага
PANEL = (224, 210, 180)
PANEL2 = (210, 194, 160)
PANEL_OFF = (206, 194, 168)
FIELD = (238, 228, 206)
INK = (58, 42, 26)                  # #3A2A1A — тёмно-коричневые чернила
RED_INK = (139, 58, 58)             # #8B3A3A — выцветший красный
BLUE_INK = (42, 58, 74)             # #2A3A4A — тёмно-синий
GREEN_INK = (62, 98, 70)
OCHRE = (166, 122, 48)
MUTED = (122, 104, 84)
GRID_COLOR = (92, 66, 42)
GRID_SKETCH = (150, 124, 96)
NEWS_PAPER = (238, 236, 228)        # бумага газетной вырезки
HULL_EDGE = INK
ENGINE_COLOR = (46, 38, 30)
COCKPIT_COLOR = (226, 222, 200)
STAR_DARK = (60, 42, 18)
SPLASH = (84, 110, 130)             # цвет брызг/промахов — «синие чернила»

# Сепия для иллюстраций в газете
SEPIA_DARK = (48, 35, 24)
SEPIA_MID = (122, 98, 72)
SEPIA_LIGHT = (206, 188, 154)
SEPIA_PALE = (228, 214, 184)
SEPIA_FIRE = (214, 160, 80)

# ============================ ШРИФТЫ ============================
# Перечень через запятую: pygame берёт первый найденный в системе шрифт с засечками
# (все они поддерживают кириллицу). Звезда рисуется полигоном — «квадратиков» нет.
SERIF_NAMES = "timesnewroman,times,georgia,dejavuserif,liberationserif,notoserif,freeserif"


def make_font(size: int, bold: bool = False, italic: bool = False) -> pygame.font.Font:
    return pygame.font.SysFont(SERIF_NAMES, size, bold=bold, italic=italic)


FONT = make_font(19)
SMALL = make_font(15)
BOLD = make_font(21, bold=True)
TITLE = make_font(32, bold=True)
NEWS_HEAD = make_font(42, bold=True)
NEWS_HEAD_SMALL = make_font(32, bold=True)
NEWS_BODY = make_font(19)
NEWS_MAST = make_font(15, bold=True)
MAP_TITLE = make_font(40, bold=True)
MAP_ITALIC = make_font(17, italic=True)
CITY_FONT = make_font(15, italic=True)
ZONE_FONT = make_font(25, bold=True)

# ============================ ПРАВИЛА (УТВЕРЖДЕНЫ, НЕ МЕНЯТЬ) ============================
MAX_HP = 100
PVO_MIN_HP = 10                     # ПВО доступно, только если HP > 10
PVO_SHOTS = 3                       # ПВО = 3 случайных выстрела
FLEET_SPECS = [("helicopter", 1, 1), ("bomber", 3, 3), ("strategic", 4, 2)]  # (тип, длина, кол-во)
BOMBER_DAMAGE = (1, 2)
STRATEGIC_DAMAGE = (2, 4)
REPAIR_WITH_HELI = (1, 3)
REPAIR_NO_HELI = 1
AI_PVO_CHANCE = 0.22
AI_REBALANCE_CHANCE = 0.12

# Позывные лётчиков (по порядку появления самолётов каждого типа)
PILOT_NAMES = {
    "bomber": ["Yandex", "GPT", "Grok"],    # в ТЗ названы два бомбардировщика; у третьего — «Grok»
    "strategic": ["Claude", "DeepSeek"],
    "helicopter": ["Mistral"],
}
FIGHTER_CALLSIGN = "Gemini"                 # истребитель-«метка»

# ============================ ПОВЕДЕНИЕ ИИ ============================
AI_MEMORY_TURNS = 4                 # сколько ходов ИИ «помнит», что стрелял в клетку
AI_HUNT_TTL_TURNS = 3               # сколько ходов ИИ «добивает» вокруг подбитой клетки
AI_HUNT_RADIUS = 1                  # самолёты двигаются на 1 клетку → ищем в радиусе 1

# ============================ АНИМАЦИЯ (мс) ============================
MOVE_MS = 450                       # плавное смещение самолётов
MISSILE_MS = 300                    # полёт ракеты
PVO_STAGGER_MS = 160                # задержка между 3 ракетами ПВО
EXPLOSION_MS = 450                  # длительность взрыва
AI_THINK_MS = 500                   # пауза «ИИ маневрирует»
HP_ANIM_MS = 500                    # ожидание, пока полоски HP доедут
HP_IDLE_MS = 150                    # короткая пауза, если HP не менялся
HP_ANIM_SPEED = 60.0                # скорость полоски HP, ед./сек
MISSILE_ARC = 70                    # высота дуги полёта ракеты, px
MISSILE_TRAIL_STEPS = 6
MISSILE_TRAIL_GAP = 0.04            # шаг следа в долях пути
EXPLOSION_MAX_R = 40
EXPLOSION_SPARKS = 8
ROTOR_SPEED = 0.03                  # рад/мс — вращение винта вертолёта

# ============================ СПРАЙТЫ ============================
SPRITE_SS = 4                       # суперсэмплинг для сглаживания
SPRITE_MARGIN = 3                   # отступ силуэта от границы клетки, px
SELECT_INSET = 2                    # рамка выделения облегает модель плотно

# Контур самолёта: точки (s, v). s: 0 — хвост, 1 — нос (вдоль длины);
# v: 0 — ось фюзеляжа, 1 — край клетки поперёк. Задана одна сторона от носа к хвосту,
# вторая строится зеркально.
HULLS = {
    "bomber": [(1.00, 0.00), (0.97, 0.12), (0.90, 0.22), (0.72, 0.28), (0.64, 0.28),
               (0.52, 0.98), (0.40, 0.98), (0.38, 0.30), (0.22, 0.26), (0.17, 0.26),
               (0.11, 0.62), (0.03, 0.62), (0.06, 0.22), (0.00, 0.15), (0.00, 0.00)],
    "strategic": [(1.00, 0.00), (0.97, 0.10), (0.91, 0.20), (0.74, 0.24), (0.60, 0.24),
                  (0.47, 0.98), (0.40, 0.98), (0.36, 0.26), (0.22, 0.22), (0.16, 0.22),
                  (0.11, 0.52), (0.04, 0.52), (0.06, 0.20), (0.00, 0.12), (0.00, 0.00)],
}
# Двигатели на крыльях: (s, v) — рисуются симметрично с обеих сторон.
ENGINES = {"bomber": [(0.54, 0.52)], "strategic": [(0.52, 0.40), (0.47, 0.70)]}
ENGINE_SIZE = (8, 5)                # длина × ширина гондолы, px
COCKPIT_POS = 0.88                  # положение кабины вдоль фюзеляжа
COCKPIT_SIZE = (7, 4)

# Слегка приглушённые цвета самолётов под стилистику карты
KIND_COLOR = {"helicopter": (96, 128, 92), "bomber": (78, 108, 130), "strategic": (160, 100, 56)}
KIND_LABEL = {"helicopter": "Вертолёт", "bomber": "Бомбардировщик", "strategic": "Стратегический"}

ACTION_SHOT = "shot"
ACTION_PVO = "pvo"
ACTION_RADAR = "radar"

# Результаты попадания
RESULT_MISS = "miss"
RESULT_SAVED = "saved"              # истребитель принял удар на себя
RESULT_KILL = "kill"                # самолёт сбит


# ============================ МОДЕЛЬ ============================
@dataclass
class Plane:
    uid: int
    kind: str
    length: int
    x: int
    y: int
    vertical: bool
    alive: bool = True
    pilot_name: str = ""            # позывной лётчика

    def cells(self):
        return [(self.x, self.y + i) if self.vertical else (self.x + i, self.y)
                for i in range(self.length)]

    def label(self):
        return KIND_LABEL[self.kind]


class Fleet:
    def __init__(self):
        self.planes: list[Plane] = []
        self.marker: Optional[int] = None          # самолёт, который прикрывает истребитель
        self.marker_transit = False                # метка «в пути» (защиты нет ни у кого)
        self.marker_pending: Optional[int] = None  # куда летит метка
        self.pvo_used = False
        self.hp = MAX_HP
        self.hp_shown = float(MAX_HP)              # плавно догоняет hp (для анимации полоски)
        self._next_id = 0
        self._place_fleet()

    def _place_fleet(self):
        occupied = set()
        for kind, length, count in FLEET_SPECS:
            names = PILOT_NAMES.get(kind, [])
            for index in range(count):
                for _attempt in range(3000):
                    vertical = bool(random.getrandbits(1))
                    x = random.randrange(GRID_SIZE - (0 if vertical else length - 1))
                    y = random.randrange(GRID_SIZE - (length - 1 if vertical else 0))
                    cells = [(x, y + i) if vertical else (x + i, y) for i in range(length)]
                    if not occupied.intersection(cells):
                        pilot = names[index] if index < len(names) else ""
                        p = Plane(self._next_id, kind, length, x, y, vertical, pilot_name=pilot)
                        self._next_id += 1
                        self.planes.append(p)
                        occupied.update(cells)
                        break
        fighters = [p for p in self.planes if p.kind != "helicopter"]
        self.marker = random.choice(fighters).uid

    def get(self, uid):
        return next((p for p in self.planes if p.uid == uid and p.alive), None)

    def alive(self):
        return [p for p in self.planes if p.alive]

    def count(self, kind):
        """(живых, всего) самолётов данного типа."""
        total = [p for p in self.planes if p.kind == kind]
        return sum(1 for p in total if p.alive), len(total)

    def occupied(self, exclude=None):
        result = set()
        for p in self.alive():
            if p.uid != exclude:
                result.update(p.cells())
        return result

    def move_all(self):
        """Двигает все самолёты на 1 клетку. Возвращает {uid: ((старый x,y), (новый x,y))}
        — по ним рисуется плавная анимация."""
        moves = {}
        planes = self.alive()[:]
        random.shuffle(planes)  # случайный порядок убирает преимущество первых юнитов
        for p in planes:
            old = (p.x, p.y)
            occupied = self.occupied(exclude=p.uid)
            offsets = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                       if (dx, dy) != (0, 0)]
            random.shuffle(offsets)
            for dx, dy in offsets:
                nx, ny = p.x + dx, p.y + dy
                cells = [(nx, ny + i) if p.vertical else (nx + i, ny)
                         for i in range(p.length)]
                if (all(0 <= cx < GRID_SIZE and 0 <= cy < GRID_SIZE for cx, cy in cells)
                        and not occupied.intersection(cells)):
                    p.x, p.y = nx, ny
                    break
            moves[p.uid] = (old, (p.x, p.y))
        return moves

    def incoming_hit(self, x, y):
        """Попадание в клетку. Возвращает (результат, текст для журнала, самолёт или None).
        Попадание = мгновенное уничтожение. Истребитель жертвуется ОДИН раз:
        сразу после этого метка пропадает, и повторное попадание (в том числе
        в этом же залпе) самолёт уже собьёт."""
        for p in self.alive():
            if (x, y) in p.cells():
                if p.uid == self.marker and not self.marker_transit:
                    self.marker = None
                    return RESULT_SAVED, (f"Попадание в {coord(x, y)}: истребитель принял удар — "
                                          f"{p.label()} выжил."), p
                p.alive = False
                if self.marker == p.uid:
                    self.marker = None
                if self.marker_pending == p.uid:
                    self.marker_pending = None
                return RESULT_KILL, f"Попадание в {coord(x, y)}: сбит {p.label().lower()}!", p
        return RESULT_MISS, f"Промах по {coord(x, y)}.", None

    def bombardment(self):
        damage = 0
        for p in self.alive():
            if p.kind == "bomber":
                damage += random.randint(*BOMBER_DAMAGE)
            elif p.kind == "strategic":
                damage += random.randint(*STRATEGIC_DAMAGE)
        return damage

    def repair(self):
        if self.hp >= MAX_HP:
            return 0
        has_heli = any(p.alive and p.kind == "helicopter" for p in self.planes)
        amount = random.randint(*REPAIR_WITH_HELI) if has_heli else REPAIR_NO_HELI
        before = self.hp
        self.hp = min(MAX_HP, self.hp + amount)
        return self.hp - before

    def can_pvo(self):
        return (self.hp > PVO_MIN_HP and self.marker is not None and not self.marker_transit
                and self.get(self.marker) is not None and not self.pvo_used)


def coord(x, y):
    return f"{chr(65 + x)}{y + 1}"


# ============================ СОБЫТИЯ («Газетная вырезка») ============================
@dataclass
class Event:
    kind: str       # ключ события
    title: str      # заголовок вырезки
    text: str       # текст
    art: str        # ключ иллюстрации (см. ART)


# kind -> (заголовок, текст-шаблон, иллюстрация)
EVENT_DEFS = {
    "bomber_lost": (
        "Потеря в небе",
        "Во время налёта на позиции противника наш бомбардировщик был перехвачен вражескими "
        "истребителями. Экипаж до последнего держал строй, но машина получила критические "
        "повреждения и рухнула за линией фронта. Среди погибших — пилот с позывным "
        "«{pilot_name}», опытный лётчик, успевший совершить немало вылетов. Его гибель — "
        "горькая весть для эскадрильи, но война требует новых имён на замену старым.",
        "falling"),
    "strategic_lost": (
        "Дорогая потеря",
        "Стратегический бомбардировщик, выполнявший рейд по промышленным центрам врага, был "
        "сбит над территорией противника. Такие машины строятся месяцами и стоят целое "
        "состояние, а подготовка экипажа занимает не меньше времени. Потеря (пилот "
        "«{pilot_name}») — серьёзный удар по нашим стратегическим силам, и командование "
        "требует пересмотреть маршруты и прикрытие дальних вылетов.",
        "falling_big"),
    "fighter_saved": (
        "Ценой собственной жизни",
        "В разгар воздушного боя вражеский перехватчик зашёл в хвост нашему бомбардировщику. "
        "Когда исход казался предрешённым, молодой пилот истребителя сопровождения (позывной "
        "«{pilot_name}») бросил свою машину наперерез огню, приняв удар на себя. "
        "Бомбардировщик вернулся на базу. Истребитель — нет. Этот поступок не останется "
        "незамеченным: о нём будут говорить в казармах и на аэродромах.",
        "saved"),
    "pvo": (
        "Стена огня",
        "Когда вражеская авиация приблизилась к нашим позициям, расчёты ПВО открыли шквальный "
        "огонь. В небо одновременно взмыли несколько снарядов, создав плотную завесу, сквозь "
        "которую противнику так и не удалось прорваться организованно. Строй врага рассыпался, "
        "бомбы легли мимо целей, а уцелевшие самолёты повернули назад. Зенитчики доказали: "
        "небо — тоже линия фронта.",
        "flak"),
    "defeat": (
        "Небо потеряно",
        "Воздушное сражение закончилось поражением. Наши эскадрильи понесли тяжёлые потери: "
        "большинство машин сбито, уцелевшие отступили на запасные аэродромы. Противник "
        "завоевал господство в воздухе над регионом, и теперь наши наземные части будут "
        "действовать под постоянной угрозой с неба. Командование требует срочно восстановить "
        "авиагруппировку — иначе потери станут необратимыми.",
        "ruins"),
    "victory": (
        "Небо наше",
        "Воздушное сражение выиграно. Вражеская авиация разбита или отступила, и небо над "
        "сектором снова принадлежит нам. Эскадрильи возвращаются на аэродромы под приветственные "
        "сигналы наземных служб. Командование благодарит экипажи, но предупреждает: враг ещё "
        "соберёт силы, и расслабляться рано.",
        "victory"),
    # --- v5.1: спецоперации и сбитый вертолёт ---
    # {plane_type} — тип самолёта, на котором держится истребитель; {zone_name} — название сектора
    "ops_search": (
        "Тень над целью",
        "В ходе специальной операции наш вертолёт вёл разведку у линии фронта, как вдруг экипаж "
        "заметил вражеский истребитель. Машина шла не одна: в кильватере держался {plane_type}, "
        "и истребитель явно выполнял роль прикрытия — выжидал, маневрировал, держался выше и чуть "
        "в стороне, готовый в любой момент броситься на перехват. Наш вертолёт остался "
        "незамеченным, но теперь командование знает: у противника есть связка "
        "\"истребитель + {plane_type}\", и её нужно ломать, пока она не добралась до наших позиций.",
        "shadow"),
    "ops_trade": (
        "Размен",
        "В ходе специальной операции наш вертолёт обнаружил вражескую машину, выполнявшую "
        "разведывательный полёт над {zone_name}. Оба вертолёта были без вооружения — ни ракет, "
        "ни пушек, только экипажи и винты. Поняв, что иначе противник уйдёт и наведёт артиллерию "
        "на наши позиции, наш пилот принял решение, которое не обсуждают в штабах: он направил "
        "машину прямо на врага. Два винта встретились в воздухе, и оба вертолёта рухнули на землю. "
        "Экипаж погиб, но вражеский вертолет больше не представляет угрозы. Это был размен — один "
        "к одному, и в этой войне он стоил того.",
        "trade"),
    "heli_down": (
        "Гравитация работает",
        "Вражеский вертолёт, попавший под наш огонь, лишился несущего винта и пошёл к земле по "
        "кратчайшей траектории. Наблюдатели успели заметить над местом падения маленький парашют: "
        "экипаж, похоже, отделался испугом. Командование отмечает, что законы физики по-прежнему "
        "действуют, причём в нашу пользу.",
        "gravity"),
}


def zone_instrumental(name: str) -> str:
    """Название сектора в творительном падеже («Северный сектор» -> «Северным сектором») для фразы «над ...»."""
    words = []
    for w in name.split():
        if w.lower() == "сектор":
            w += "ом"
        elif w.endswith("ый"):
            w = w[:-2] + "ым"
        elif w.lower() in ("твой", "мой", "свой"):
            w = w[:-1] + "им"
        elif w.endswith("ий") or w.endswith("ой"):
            w = w[:-2] + "им"
        words.append(w)
    return " ".join(words)


def make_event(kind: str, pilot_name: str = "", **fmt) -> Event:
    """Собирает событие по шаблону. Доп. поля шаблона (plane_type, zone_name) — через **fmt."""
    title, text, art = EVENT_DEFS[kind]
    return Event(kind, title, text.format(pilot_name=pilot_name, **fmt), art)


# ============================ ДАННЫЕ АНИМАЦИИ ============================
@dataclass
class MoveAnim:
    paths: dict          # uid -> ((x0, y0), (x1, y1))
    start: int
    duration: int


@dataclass
class Missile:
    cell: tuple          # клетка-цель
    start: tuple         # откуда летит (px)
    end: tuple           # куда летит (px)
    launch_at: int
    land_at: int
    defender: Fleet
    ai_side: bool        # True — стреляет ИИ
    via_pvo: bool
    resolved: bool = False


@dataclass
class Explosion:
    pos: tuple
    start: int
    kind: str


# ============================ ВСПОМОГАТЕЛЬНАЯ ГРАФИКА ============================
def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def cell_center(rect, cell):
    return rect.x + cell[0] * CELL + CELL / 2, rect.y + cell[1] * CELL + CELL / 2


def draw_text(surface, text, x, y, font=FONT, color=INK):
    surface.blit(font.render(str(text), True, color), (x, y))


def draw_text_center(surface, text, cx, y, font=FONT, color=INK):
    img = font.render(str(text), True, color)
    surface.blit(img, (cx - img.get_width() // 2, y))


def wrap_text(font, text, max_width):
    """Переносит текст по словам так, чтобы строка влезала в max_width."""
    lines, line = [], ""
    for word in text.split():
        trial = word if not line else line + " " + word
        if font.size(trial)[0] <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def rounded(surface, rect, color, radius=10, border=None, width=1):
    pygame.draw.rect(surface, color, rect, border_radius=radius)
    if border:
        pygame.draw.rect(surface, border, rect, width, border_radius=radius)


def draw_star(surface, center, r_out, r_in, color, outline=None):
    """Пятиконечная звезда полигоном — не зависит от шрифтов."""
    pts = []
    for i in range(10):
        r = r_out if i % 2 == 0 else r_in
        a = -math.pi / 2 + i * math.pi / 5
        pts.append((center[0] + math.cos(a) * r, center[1] + math.sin(a) * r))
    pygame.draw.polygon(surface, color, pts)
    if outline:
        pygame.draw.polygon(surface, outline, pts, 1)


def lighter(color, amount=60):
    return tuple(min(255, c + amount) for c in color)


# ---------- Бумага ----------
def build_paper(seed=7):
    """Фон «старая бумага»: крапинки, волокна, пятна, сгибы и тёмные края."""
    rng = random.Random(seed)
    surf = pygame.Surface((W, H)).convert()
    surf.fill(PAPER)
    for _ in range(9000):                                   # крапинки
        d = rng.randint(-16, 8)
        color = tuple(max(0, min(255, v + d)) for v in PAPER)
        surf.set_at((rng.randrange(W), rng.randrange(H)), color)
    for _ in range(450):                                    # короткие волокна
        x, y = rng.randrange(W), rng.randrange(H)
        a = rng.uniform(0, math.pi)
        ln = rng.randint(4, 14)
        d = rng.randint(-12, -4)
        color = tuple(max(0, v + d) for v in PAPER)
        pygame.draw.line(surf, color, (x, y), (x + math.cos(a) * ln, y + math.sin(a) * ln), 1)
    layer = pygame.Surface((W, H), pygame.SRCALPHA)
    for _ in range(16):                                     # пятна от времени
        pygame.draw.circle(layer, (150, 108, 56, rng.randint(8, 18)),
                           (rng.randrange(W), rng.randrange(H)), rng.randint(40, 170))
    pygame.draw.line(layer, (120, 90, 50, 40), (W // 2, 0), (W // 2, H), 2)     # сгиб
    pygame.draw.line(layer, (255, 245, 220, 40), (W // 2 + 2, 0), (W // 2 + 2, H), 1)
    pygame.draw.line(layer, (120, 90, 50, 34), (0, H // 2), (W, H // 2), 2)
    for i in range(50):                                     # виньетка по краям
        alpha = int(75 * (1 - i / 50) ** 2)
        pygame.draw.rect(layer, (90, 58, 26, alpha), (i, i, W - 2 * i, H - 2 * i), 1)
    surf.blit(layer, (0, 0))
    return surf


PAPER_SURF = build_paper()


# ---------- Рисованная от руки сетка ----------
_GRID_CACHE: dict = {}


def hand_drawn_grid(rect):
    """Линии сетки с небольшой неровностью (считаются один раз, чтобы не «дрожали»)."""
    key = rect.topleft
    if key not in _GRID_CACHE:
        rng = random.Random(key[0] * 31 + key[1])
        lines = []
        steps = GRID_SIZE * 2
        for i in range(GRID_SIZE + 1):
            outer = i in (0, GRID_SIZE)
            for pass_no in range(2):                         # второй проход — «карандашный» повтор
                color = GRID_COLOR if pass_no == 0 else GRID_SKETCH
                width = (2 if outer else 1) if pass_no == 0 else 1
                vert = [(rect.x + i * CELL + rng.uniform(-1.4, 1.4), rect.y + j * CELL / 2)
                        for j in range(steps + 1)]
                horiz = [(rect.x + j * CELL / 2, rect.y + i * CELL + rng.uniform(-1.4, 1.4))
                         for j in range(steps + 1)]
                lines.append((vert, color, width))
                lines.append((horiz, color, width))
        _GRID_CACHE[key] = lines
    return _GRID_CACHE[key]


# ---------- Спрайты самолётов ----------
def _paint_airplane(surf, ss, kind, color):
    """Рисует силуэт, растянутый РОВНО на все клетки самолёта (нос вправо)."""
    w, h = surf.get_size()
    margin = SPRITE_MARGIN * ss
    span = w - 2 * margin
    half = h / 2 - margin

    def pt(s, v):
        return margin + s * span, h / 2 - v * half

    hull = HULLS[kind]
    poly = [pt(s, v) for s, v in hull] + [pt(s, -v) for s, v in reversed(hull)]
    pygame.draw.polygon(surf, color, poly)
    pygame.draw.polygon(surf, HULL_EDGE, poly, 2 * ss)
    pygame.draw.line(surf, lighter(color), pt(0.08, 0), pt(0.93, 0), max(1, ss))   # блик по оси
    for s, v in ENGINES[kind]:                                                     # двигатели
        for sign in (1, -1):
            cx, cy = pt(s, sign * v)
            rect = pygame.Rect(0, 0, ENGINE_SIZE[0] * ss, ENGINE_SIZE[1] * ss)
            rect.center = (int(cx), int(cy))
            pygame.draw.ellipse(surf, ENGINE_COLOR, rect)
    cx, cy = pt(COCKPIT_POS, 0)                                                    # кабина
    rect = pygame.Rect(0, 0, COCKPIT_SIZE[0] * ss, COCKPIT_SIZE[1] * ss)
    rect.center = (int(cx), int(cy))
    pygame.draw.ellipse(surf, COCKPIT_COLOR, rect)


def _paint_helicopter(surf, ss, color):
    """Вертолёт в одной клетке (нос вправо). Винт рисуется отдельно, чтобы вращаться."""
    u = CELL * ss

    def p(fx, fy):
        return fx * u, fy * u

    sk = max(1, ss)
    pygame.draw.line(surf, HULL_EDGE, p(0.38, 0.22), p(0.90, 0.22), 2 * sk)   # лыжи
    pygame.draw.line(surf, HULL_EDGE, p(0.38, 0.78), p(0.90, 0.78), 2 * sk)
    boom = [p(0.06, 0.47), p(0.50, 0.44), p(0.50, 0.56), p(0.06, 0.53)]       # хвостовая балка
    pygame.draw.polygon(surf, color, boom)
    pygame.draw.polygon(surf, HULL_EDGE, boom, sk)
    fin = [p(0.04, 0.28), p(0.12, 0.28), p(0.18, 0.50), p(0.12, 0.72), p(0.04, 0.72), p(0.07, 0.50)]
    pygame.draw.polygon(surf, color, fin)                                      # стабилизатор
    pygame.draw.polygon(surf, HULL_EDGE, fin, sk)
    body = pygame.Rect(int(0.28 * u), int(0.30 * u), int(0.60 * u), int(0.40 * u))
    pygame.draw.ellipse(surf, color, body)                                     # фюзеляж
    pygame.draw.ellipse(surf, HULL_EDGE, body, 2 * sk)
    cockpit = pygame.Rect(int(0.62 * u), int(0.36 * u), int(0.20 * u), int(0.28 * u))
    pygame.draw.ellipse(surf, COCKPIT_COLOR, cockpit)


_SPRITE_CACHE: dict = {}


def get_sprite(kind, length, vertical):
    """Спрайт размером ровно length×1 клеток (или 1×length для вертикальных)."""
    key = (kind, length, vertical)
    if key not in _SPRITE_CACHE:
        w_px, h_px = length * CELL, CELL
        big = pygame.Surface((w_px * SPRITE_SS, h_px * SPRITE_SS), pygame.SRCALPHA)
        if kind == "helicopter":
            _paint_helicopter(big, SPRITE_SS, KIND_COLOR[kind])
        else:
            _paint_airplane(big, SPRITE_SS, kind, KIND_COLOR[kind])
        sprite = pygame.transform.smoothscale(big, (w_px, h_px))
        if vertical:
            sprite = pygame.transform.rotate(sprite, 90)    # нос смотрит вверх
        _SPRITE_CACHE[key] = sprite
    return _SPRITE_CACHE[key]


def legend_sprite(kind, length):
    """Уменьшенный спрайт для легенды."""
    key = ("legend", kind, length)
    if key not in _SPRITE_CACHE:
        src = get_sprite(kind, length, False)
        _SPRITE_CACHE[key] = pygame.transform.smoothscale(
            src, (src.get_width() // 2, src.get_height() // 2))
    return _SPRITE_CACHE[key]


def draw_plane(surface, plane, board_rect, pos, now, selected=False, queued=False,
               marker=False, marker_pending=False):
    """Рисует самолёт в дробной позиции pos (клетки) — это даёт плавное движение."""
    sprite = get_sprite(plane.kind, plane.length, plane.vertical)
    rect = sprite.get_rect(topleft=(round(board_rect.x + pos[0] * CELL),
                                    round(board_rect.y + pos[1] * CELL)))
    surface.blit(sprite, rect)
    if plane.kind == "helicopter":
        _draw_rotor(surface, rect.center, now)
    if selected:                                             # рамки облегают модель
        pygame.draw.rect(surface, OCHRE, rect.inflate(-SELECT_INSET, -SELECT_INSET), 2, border_radius=6)
    if queued:
        pygame.draw.rect(surface, BLUE_INK, rect.inflate(-SELECT_INSET, -SELECT_INSET), 3, border_radius=6)
    if marker:
        pygame.draw.circle(surface, OCHRE, rect.center, 10)
        pygame.draw.circle(surface, STAR_DARK, rect.center, 10, 2)
        draw_star(surface, rect.center, 7, 3, STAR_DARK)
    elif marker_pending:
        # Метка в пути: показываем, куда она летит (контур, защиты ещё нет)
        pygame.draw.circle(surface, MUTED, rect.center, 10, 1)
        draw_star(surface, rect.center, 7, 3, MUTED)


def _draw_rotor(surface, center, now):
    if not SETTINGS["rotor"]:
        return
    radius = CELL * 0.44
    angle = now * ROTOR_SPEED
    pygame.draw.circle(surface, (70, 110, 90), center, int(radius), 1)
    for k in (0, math.pi / 2):
        dx, dy = math.cos(angle + k) * radius, math.sin(angle + k) * radius
        pygame.draw.line(surface, (236, 240, 232),
                         (center[0] - dx, center[1] - dy), (center[0] + dx, center[1] + dy), 2)
    pygame.draw.circle(surface, HULL_EDGE, center, 3)


# ---------- Поля, метки, эффекты ----------
def draw_board_frame(surface, rect, title):
    rounded(surface, pygame.Rect(rect.x - 10, rect.y - 48, rect.width + 20, rect.height + 62),
            PANEL, 13, INK, 2)
    draw_text(surface, title, rect.x, rect.y - 40, BOLD, INK)
    for i in range(GRID_SIZE):
        draw_text(surface, chr(65 + i), rect.x + i * CELL + 14, rect.y - 21, SMALL, MUTED)
        draw_text(surface, str(i + 1), rect.x - 20, rect.y + i * CELL + 11, SMALL, MUTED)
    pygame.draw.rect(surface, FIELD, rect)
    for points, color, width in hand_drawn_grid(rect):
        pygame.draw.lines(surface, color, False, points, width)


def draw_flak_marker(surface, center):
    """Постоянный след взрыва ПВО: кольцо с расходящимися лучами."""
    pygame.draw.circle(surface, OCHRE, center, 13, 2)
    for k in range(8):
        a = k * math.pi / 4
        pygame.draw.line(surface, OCHRE,
                         (center[0] + math.cos(a) * 7, center[1] + math.sin(a) * 7),
                         (center[0] + math.cos(a) * 17, center[1] + math.sin(a) * 17), 2)


def draw_marks(surface, rect, hits, misses, flak):
    """Промахи — точки синими чернилами, попадания — красные крестики, ПВО — «вспышки»."""
    for cell in flak:
        draw_flak_marker(surface, cell_center(rect, cell))
    for cell in misses:
        cx, cy = cell_center(rect, cell)
        pygame.draw.circle(surface, BLUE_INK, (int(cx), int(cy)), 4)
    for cell in hits:
        cx, cy = cell_center(rect, cell)
        cx, cy = int(cx), int(cy)
        pygame.draw.line(surface, RED_INK, (cx - 9, cy - 9), (cx + 9, cy + 9), 3)
        pygame.draw.line(surface, RED_INK, (cx + 9, cy - 9), (cx - 9, cy + 9), 3)
        pygame.draw.circle(surface, (176, 104, 60), (cx, cy), 12, 2)


def missile_position(m, u):
    """Позиция ракеты на дуге; u — доля пути 0..1."""
    x = lerp(m.start[0], m.end[0], u)
    y = lerp(m.start[1], m.end[1], u) - MISSILE_ARC * 4 * u * (1 - u)
    return x, y


def draw_missile(surface, m, now):
    u = (now - m.launch_at) / MISSILE_MS
    if not 0 <= u < 1:
        return
    head_color, trail_color = (RED_INK, (176, 104, 60)) if m.ai_side else (BLUE_INK, SPLASH)
    for k in range(MISSILE_TRAIL_STEPS, 0, -1):          # след — от хвоста к голове
        uk = u - k * MISSILE_TRAIL_GAP
        if uk < 0:
            continue
        x, y = missile_position(m, uk)
        pygame.draw.circle(surface, trail_color, (int(x), int(y)), max(1, 4 - k // 2))
    x, y = missile_position(m, u)
    pygame.draw.circle(surface, head_color, (int(x), int(y)), 5)
    pygame.draw.circle(surface, INK, (int(x), int(y)), 5, 1)


def draw_explosion(surface, ex, now):
    t = (now - ex.start) / EXPLOSION_MS
    if not 0 <= t < 1:
        return
    size = EXPLOSION_MAX_R * 2 + 4
    layer = pygame.Surface((size, size), pygame.SRCALPHA)
    c = (size // 2, size // 2)
    fade = 1 - t
    if ex.kind == RESULT_MISS:                           # всплеск: кольцо синих чернил
        pygame.draw.circle(layer, (*SPLASH, int(230 * fade)), c, int(6 + 16 * t), 2)
    elif ex.kind == RESULT_SAVED:                        # щит истребителя: кольца охры и синевы
        r = int(8 + 26 * t)
        pygame.draw.circle(layer, (*OCHRE, int(230 * fade)), c, r, 3)
        pygame.draw.circle(layer, (*BLUE_INK, int(170 * fade)), c, int(r * 0.6), 2)
    else:                                                # попадание: огонь, вспышка, искры
        r = int(6 + 26 * math.sqrt(t))
        pygame.draw.circle(layer, (210, 130, 60, int(210 * fade)), c, r)
        pygame.draw.circle(layer, (*RED_INK, int(240 * fade)), c, r, 3)
        core = int(14 * fade)
        if core > 0:
            pygame.draw.circle(layer, (252, 244, 214, 255), c, core)
        for k in range(EXPLOSION_SPARKS):
            a = 2 * math.pi * k / EXPLOSION_SPARKS + 0.4
            p0 = (c[0] + math.cos(a) * r * 0.7, c[1] + math.sin(a) * r * 0.7)
            p1 = (c[0] + math.cos(a) * r * 1.25, c[1] + math.sin(a) * r * 1.25)
            pygame.draw.line(layer, (*INK, int(255 * fade)), p0, p1, 2)
    surface.blit(layer, (int(ex.pos[0]) - size // 2, int(ex.pos[1]) - size // 2))


def draw_bar(surface, x, y, label, hp, color):
    draw_text(surface, label, x, y - 24, SMALL, MUTED)
    pygame.draw.rect(surface, (196, 180, 150), (x, y, 310, 15), border_radius=7)
    width = int(306 * max(0, hp) / MAX_HP)
    if width:
        pygame.draw.rect(surface, color, (x + 2, y + 2, width, 11), border_radius=5)
    pygame.draw.rect(surface, INK, (x, y, 310, 15), 1, border_radius=7)
    draw_text(surface, f"{int(round(max(0, hp)))}/{MAX_HP}", x + 320, y - 6, BOLD, INK)


def button(surface, rect, label, active=True, accent=BLUE_INK):
    color = PANEL2 if active else PANEL_OFF
    rounded(surface, rect, color, 9, accent if active else MUTED, 2)
    txt = BOLD.render(label, True, INK if active else MUTED)
    surface.blit(txt, txt.get_rect(center=rect.center))


# ============================ ИЛЛЮСТРАЦИИ ДЛЯ ГАЗЕТЫ (рисуются кодом) ============================
def _rot(points, angle_deg, scale, cx, cy):
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    return [(cx + (x * ca - y * sa) * scale, cy + (x * sa + y * ca) * scale) for x, y in points]


# Силуэт самолёта сбоку (нос вправо): части корпуса
SIDE_PLANE = [
    [(-34, -3), (-10, -6), (22, -5), (36, 0), (22, 5), (-10, 5), (-34, 2)],      # фюзеляж
    [(-34, -2), (-44, -18), (-34, -18), (-18, -4)],                              # киль
    [(-6, 0), (-20, 14), (-6, 14), (12, 1)],                                     # крыло
]
SIDE_CANOPY = [(6, -5), (16, -9), (25, -3), (14, -3)]


def draw_side_plane(surface, cx, cy, scale, angle, color=SEPIA_DARK, flip=False):
    for part in SIDE_PLANE:
        pts = [(-x, y) for x, y in part] if flip else part
        pygame.draw.polygon(surface, color, _rot(pts, angle, scale, cx, cy))
    canopy = [(-x, y) for x, y in SIDE_CANOPY] if flip else SIDE_CANOPY
    pygame.draw.polygon(surface, SEPIA_PALE, _rot(canopy, angle, scale, cx, cy))


def _sky(surface, rect, top, bottom):
    for i in range(rect.height):
        k = i / max(1, rect.height - 1)
        color = tuple(int(lerp(top[j], bottom[j], k)) for j in range(3))
        pygame.draw.line(surface, color, (rect.x, rect.y + i), (rect.right - 1, rect.y + i))


def _hills(surface, rect, base, amp, color, phase=0.0):
    pts = [(rect.x + i * 10, rect.bottom - base - amp * math.sin(i * 0.23 + phase))
           for i in range(rect.width // 10 + 2)]
    pts += [(rect.right, rect.bottom), (rect.x, rect.bottom)]
    pygame.draw.polygon(surface, color, pts)


def _smoke(surface, start, direction, count, step, t, size=6):
    """Шлейф дыма: от далёких (светлых, больших) клубов к близким (тёмным)."""
    dx, dy = direction
    for k in range(count - 1, -1, -1):
        wob = math.sin(t / 400 + k * 0.7) * 3
        x = start[0] + dx * k * step + wob
        y = start[1] + dy * k * step
        shade = int(lerp(60, 175, k / max(1, count - 1)))
        r = int(size + k * 1.6)
        pygame.draw.circle(surface, (shade, int(shade * 0.88), int(shade * 0.72)), (int(x), int(y)), r)
        pygame.draw.circle(surface, SEPIA_DARK, (int(x), int(y)), r, 1)


def _burst(surface, center, r_out, r_in, color):
    """Зубчатая вспышка взрыва."""
    pts = []
    for i in range(18):
        r = r_out if i % 2 == 0 else r_in
        a = i * math.pi / 9
        pts.append((center[0] + math.cos(a) * r, center[1] + math.sin(a) * r))
    pygame.draw.polygon(surface, color, pts)
    pygame.draw.polygon(surface, SEPIA_DARK, pts, 2)


def _flame(surface, cx, cy, scale, angle, ox=0, oy=0):
    local = [(-14 + ox, -3 + oy), (-34 + ox, -12 + oy), (-24 + ox, 0 + oy),
             (-42 + ox, 8 + oy), (-14 + ox, 5 + oy)]
    pts = _rot(local, angle, scale, cx, cy)
    pygame.draw.polygon(surface, SEPIA_FIRE, pts)
    pygame.draw.polygon(surface, SEPIA_DARK, pts, 2)


def _art_falling(surface, rect, t, big=False):
    """Падающий самолёт с дымом (big — тяжёлый стратегический, с двумя очагами огня и обломками)."""
    _sky(surface, rect, SEPIA_PALE, SEPIA_LIGHT)
    _hills(surface, rect, 26, 10, SEPIA_MID, 0.5)
    _hills(surface, rect, 10, 8, SEPIA_DARK, 2.0)
    scale = 2.0 if big else 1.4
    angle = 28
    cx, cy = rect.centerx + 70, rect.y + 90
    back = (-math.cos(math.radians(angle)), -math.sin(math.radians(angle)))
    _smoke(surface, (cx, cy), back, 13, 20 if big else 17, t, 8 if big else 6)
    draw_side_plane(surface, cx, cy, scale, angle)
    _flame(surface, cx, cy, scale, angle)
    if big:
        _flame(surface, cx, cy, scale, angle, 6, 12)
        rng = random.Random(11)
        for _ in range(9):                                   # обломки
            px = cx + rng.randint(-90, 60)
            py = cy + rng.randint(-30, 60)
            piece = [(0, 0), (rng.randint(5, 11), rng.randint(-3, 3)), (rng.randint(2, 8), rng.randint(4, 9))]
            pygame.draw.polygon(surface, SEPIA_DARK, _rot(piece, rng.randint(0, 359), 1, px, py))


def _art_falling_big(surface, rect, t):
    _art_falling(surface, rect, t, big=True)


def _art_saved(surface, rect, t):
    """Истребитель бросается наперерез очереди, защищая бомбардировщик."""
    _sky(surface, rect, SEPIA_PALE, SEPIA_LIGHT)
    for ox, oy, w in ((120, 42, 120), (430, 30, 160), (640, 92, 100)):      # облака
        pygame.draw.ellipse(surface, (238, 228, 204), (rect.x + ox, rect.y + oy, w, 26))
        pygame.draw.ellipse(surface, (238, 228, 204), (rect.x + ox + 22, rect.y + oy - 12, w - 50, 26))
    _hills(surface, rect, 12, 8, SEPIA_MID, 1.0)
    bomber = (rect.centerx + 150, rect.y + 120)
    enemy = (rect.x + 110, rect.y + 96)
    draw_side_plane(surface, bomber[0], bomber[1], 2.0, 0)
    draw_side_plane(surface, enemy[0], enemy[1], 1.3, 0)
    sx, sy = enemy[0] + 50, enemy[1]
    ex, ey = bomber[0] - 70, bomber[1] - 4
    for k in range(14):                                                      # трассы
        if k % 2 == 0:
            a, b = k / 14, (k + 0.55) / 14
            pygame.draw.line(surface, SEPIA_DARK, (lerp(sx, ex, a), lerp(sy, ey, a)),
                             (lerp(sx, ex, b), lerp(sy, ey, b)), 2)
    fx, fy = lerp(sx, ex, 0.55), lerp(sy, ey, 0.55)
    _smoke(surface, (fx, fy), (-0.9, -0.4), 6, 16, t, 5)
    _burst(surface, (fx, fy), 38, 18, SEPIA_FIRE)
    draw_side_plane(surface, fx, fy, 1.0, -20)


def _art_flak(surface, rect, t):
    """Зенитки, прожекторы, чёрные разрывы и отступающие самолёты."""
    _sky(surface, rect, SEPIA_LIGHT, SEPIA_MID)
    gy = rect.bottom - 28
    layer = pygame.Surface(rect.size, pygame.SRCALPHA)                       # лучи прожекторов
    for gx in (rect.x + 120, rect.right - 130):
        lx, ly = gx - rect.x, gy - rect.y
        pygame.draw.polygon(layer, (255, 248, 220, 70),
                            [(lx - 8, ly), (lx + 8, ly), (lx + 70, 0), (lx + 20, 0)])
    surface.blit(layer, rect.topleft)
    rng = random.Random(5)
    for _ in range(26):                                                      # разрывы зениток
        px, py = rect.x + rng.randint(60, rect.width - 60), rect.y + rng.randint(15, 140)
        for _k in range(3):
            r = rng.randint(7, 14)
            pygame.draw.circle(surface, (70, 60, 52), (px + rng.randint(-10, 10), py + rng.randint(-8, 8)), r)
    draw_side_plane(surface, rect.x + 600, rect.y + 62, 1.0, -8)             # враг отступает
    draw_side_plane(surface, rect.x + 650, rect.y + 112, 0.8, -4)
    _hills(surface, rect, 22, 8, SEPIA_DARK, 0.2)
    for gx, ang in ((rect.x + 250, -70), (rect.x + 360, -90), (rect.x + 470, -110)):   # орудия
        pygame.draw.rect(surface, SEPIA_DARK, (gx - 16, gy - 10, 32, 14))
        a = math.radians(ang)
        tip = (gx + math.cos(a) * 44, gy - 8 + math.sin(a) * 44)
        pygame.draw.line(surface, SEPIA_DARK, (gx, gy - 8), tip, 6)
        for k in range(1, 9):                                                # трассы вверх
            pygame.draw.circle(surface, SEPIA_FIRE, (int(tip[0] + math.cos(a) * k * 13),
                                                     int(tip[1] + math.sin(a) * k * 13)), 2)


def _art_ruins(surface, rect, t):
    """Разрушенный город, дым над крышами и обломки самолёта."""
    _sky(surface, rect, SEPIA_LIGHT, SEPIA_MID)
    ground = rect.bottom - 30
    rng = random.Random(9)
    x = rect.x + 20
    tops = []
    while x < rect.right - 100:
        w, h = rng.randint(40, 70), rng.randint(60, 120)
        top = ground - h
        zig = [(x, ground), (x, top), (x + w * 0.25, top - rng.randint(0, 14)), (x + w * 0.5, top + rng.randint(6, 20)),
               (x + w * 0.75, top - rng.randint(0, 10)), (x + w, top + 8), (x + w, ground)]
        pygame.draw.polygon(surface, SEPIA_DARK, zig)
        for wx in range(int(x + 8), int(x + w - 8), 14):                      # окна
            for wy in range(int(top + 22), ground - 12, 20):
                if rng.random() < 0.6:
                    pygame.draw.rect(surface, SEPIA_MID, (wx, wy, 6, 9))
        tops.append((x + w / 2, top))
        x += w + rng.randint(4, 18)
    for tx, ty in tops[::2]:                                                 # дым
        _smoke(surface, (tx, ty - 6), (0.12, -1.0), 7, 16, t + tx * 3, 6)
    pygame.draw.rect(surface, SEPIA_DARK, (rect.x, ground, rect.width, 30))
    draw_side_plane(surface, rect.right - 90, ground - 8, 1.4, 14)           # обломки самолёта
    _flame(surface, rect.right - 90, ground - 8, 1.4, 14)


def _art_victory(surface, rect, t):
    """Закат, лучи солнца и строй самолётов, возвращающихся на базу."""
    _sky(surface, rect, SEPIA_PALE, SEPIA_LIGHT)
    sun = (rect.centerx, rect.bottom - 50)
    for k in range(18):
        a = math.pi + k * math.pi / 17
        pygame.draw.line(surface, (240, 226, 190), sun, (sun[0] + math.cos(a) * 420, sun[1] + math.sin(a) * 420), 3)
    pygame.draw.circle(surface, (246, 236, 206), sun, 48)
    pygame.draw.circle(surface, SEPIA_FIRE, sun, 48, 3)
    _hills(surface, rect, 24, 9, SEPIA_MID, 0.8)
    _hills(surface, rect, 8, 6, SEPIA_DARK, 2.4)
    lead = (rect.centerx + 120, rect.y + 90)
    for dx, dy in ((0, 0), (-70, -28), (-70, 28), (-140, -56), (-140, 56)):  # строй «клином»
        px, py = lead[0] + dx, lead[1] + dy
        pygame.draw.line(surface, (244, 236, 214), (px - 40, py), (px - 150, py), 3)   # инверсионный след
        draw_side_plane(surface, px, py, 1.1, 0)


# Силуэт вертолёта сбоку (нос вправо): части корпуса
HELI_BODY = [(-12, -7), (6, -9), (18, -4), (22, 3), (12, 8), (-10, 8)]            # кабина
HELI_TAIL = [(-10, -4), (-40, -3), (-40, 0), (-10, 3)]                           # хвостовая балка
HELI_FIN = [(-40, -3), (-46, -12), (-41, -12), (-34, -3)]                        # хвостовое оперение
HELI_CANOPY = [(8, -6), (16, -3), (18, 2), (8, 2)]                               # остекление
HELI_MAST_TOP = (0, -14)                                                         # верх мачты винта
HELI_ROTOR_HALF = 36                                                             # половина размаха винта


def draw_side_heli(surface, cx, cy, scale, angle=0.0, color=SEPIA_DARK, flip=False, rotor=True):
    """Вертолёт сбоку. rotor=False — винт оторван (остаётся обломок мачты)."""
    def tf(pts):
        pts = [(-x, y) for x, y in pts] if flip else pts
        return _rot(pts, angle, scale, cx, cy)

    width = max(1, int(2 * scale))
    for part in (HELI_BODY, HELI_TAIL, HELI_FIN):
        pygame.draw.polygon(surface, color, tf(part))
    pygame.draw.polygon(surface, SEPIA_PALE, tf(HELI_CANOPY))
    for a, b in (((-4, 8), (-5, 13)), ((10, 8), (11, 13)), ((-12, 13), (18, 13))):     # шасси
        pygame.draw.line(surface, color, tf([a])[0], tf([b])[0], width)
    mast_top = (0, -14) if rotor else (0, -11)                                         # мачта
    pygame.draw.line(surface, color, tf([(0, -9)])[0], tf([mast_top])[0], width)
    if rotor:
        left, right = tf([(-HELI_ROTOR_HALF, -14)])[0], tf([(HELI_ROTOR_HALF, -14)])[0]
        pygame.draw.line(surface, color, left, right, width + 1)


def _clouds(surface, rect, items):
    for ox, oy, w in items:
        pygame.draw.ellipse(surface, (238, 228, 204), (rect.x + ox, rect.y + oy, w, 26))
        pygame.draw.ellipse(surface, (238, 228, 204), (rect.x + ox + 22, rect.y + oy - 12, w - 50, 26))


def _art_trade(surface, rect, t):
    """Лобовое столкновение двух вертолётов: вспышка между ними, обломки, дым."""
    _sky(surface, rect, SEPIA_PALE, SEPIA_LIGHT)
    _clouds(surface, rect, ((90, 36, 120), (600, 28, 140)))
    _hills(surface, rect, 22, 9, SEPIA_MID, 0.9)
    _hills(surface, rect, 8, 6, SEPIA_DARK, 2.2)
    mid = (rect.centerx, rect.y + 92)
    for sign in (-1, 1):                                                       # дымные хвосты вверх и в стороны
        _smoke(surface, (mid[0] + sign * 40, mid[1] - 8), (sign * 0.35, -1.0), 7, 15, t + sign * 300, 6)
    draw_side_heli(surface, mid[0] - 78, mid[1] + 10, 1.5, -14, SEPIA_DARK, False, False)
    draw_side_heli(surface, mid[0] + 78, mid[1] + 10, 1.5, 14, SEPIA_DARK, True, False)
    pulse = 3 * math.sin(t / 180)
    _burst(surface, mid, 46 + pulse, 23, SEPIA_FIRE)                           # вспышка между машинами
    _burst(surface, mid, 22 + pulse / 2, 10, (246, 236, 206))
    rng = random.Random(21)
    for _ in range(8):                                                         # лопасти и обломки
        px = mid[0] + rng.randint(-120, 120)
        py = mid[1] + rng.randint(-60, 70)
        a = rng.randint(0, 359)
        dx, dy = math.cos(math.radians(a)) * rng.randint(14, 26), math.sin(math.radians(a)) * rng.randint(14, 26)
        pygame.draw.line(surface, SEPIA_DARK, (px, py), (px + dx, py + dy), 3)
        piece = [(0, 0), (rng.randint(5, 10), rng.randint(-3, 3)), (rng.randint(2, 7), rng.randint(4, 8))]
        pygame.draw.polygon(surface, SEPIA_DARK, _rot(piece, rng.randint(0, 359), 1, px + 8, py - 10))


def _art_shadow(surface, rect, t):
    """Сумерки: впереди малый вертолёт-разведчик, вдали силуэты бомбардировщика и истребителя."""
    _sky(surface, rect, (110, 88, 64), SEPIA_LIGHT)
    moon = (rect.x + 110, rect.y + 44)
    pygame.draw.circle(surface, (236, 224, 192), moon, 20)
    pygame.draw.circle(surface, (110, 88, 64), (moon[0] + 8, moon[1] - 4), 17)         # серп луны
    sway = math.sin(t / 900) * 26
    layer = pygame.Surface(rect.size, pygame.SRCALPHA)                                 # луч прожектора
    gx, gy = 560, rect.height - 18
    pygame.draw.polygon(layer, (255, 248, 220, 80),
                        [(gx - 9, gy), (gx + 9, gy), (gx - 170 + sway + 40, 0), (gx - 170 + sway - 40, 0)])
    surface.blit(layer, rect.topleft)
    far = (88, 70, 52)                                                                  # дальние силуэты
    bomber = (rect.centerx + 120, rect.y + 70)
    fighter = (rect.centerx - 10, rect.y + 36)
    pygame.draw.line(surface, (190, 172, 140), (bomber[0] - 60, bomber[1]), (bomber[0] - 230, bomber[1]), 2)
    draw_side_plane(surface, bomber[0], bomber[1], 2.6, 0, far)
    draw_side_plane(surface, fighter[0], fighter[1], 1.0, 4, far)
    _hills(surface, rect, 22, 9, SEPIA_MID, 0.4)
    scout = (rect.x + 190, rect.bottom - 62 + math.sin(t / 500) * 3)
    draw_side_heli(surface, scout[0], scout[1], 1.3, 3, SEPIA_DARK)
    _hills(surface, rect, 8, 6, SEPIA_DARK, 2.0)


def _parachute(surface, px, py, r, t):
    """Маленький парашют с пилотом: купол, стропы, фигурка."""
    px += math.sin(t / 500) * 3
    dome = [(px + math.cos(math.pi * k / 12) * r, py - math.sin(math.pi * k / 12) * r * 0.8) for k in range(13)]
    pygame.draw.polygon(surface, SEPIA_PALE, dome)
    pygame.draw.polygon(surface, SEPIA_DARK, dome, 2)
    body = (px, py + 30)
    for sx in (-r, 0, r):
        pygame.draw.line(surface, SEPIA_DARK, (px + sx, py), body, 1)
    pygame.draw.circle(surface, SEPIA_DARK, (int(body[0]), int(body[1])), 4)
    pygame.draw.line(surface, SEPIA_DARK, body, (px, py + 44), 3)


def _art_gravity(surface, rect, t):
    """Вертолёт без винта падает со шлейфом дыма; рядом — оторванный винт и крошечный парашют."""
    _sky(surface, rect, SEPIA_PALE, SEPIA_LIGHT)
    _clouds(surface, rect, ((70, 40, 110), (560, 30, 150)))
    _hills(surface, rect, 26, 10, SEPIA_MID, 0.5)
    _hills(surface, rect, 10, 8, SEPIA_DARK, 2.0)
    angle = 32
    cx, cy = rect.centerx + 90, rect.y + 92
    back = (-math.cos(math.radians(angle)), -math.sin(math.radians(angle)))
    _smoke(surface, (cx - 6, cy - 12), back, 12, 18, t, 6)
    draw_side_heli(surface, cx, cy, 1.7, angle, SEPIA_DARK, False, False)
    _burst(surface, (cx - 4, cy - 20), 16, 8, SEPIA_FIRE)                               # огонь у мачты
    rot_c = (cx - 130, cy - 40)                                                         # оторванный винт
    a = math.radians(t / 6)
    for k in (0, 1):
        ang = a + k * math.pi
        pygame.draw.line(surface, SEPIA_DARK, rot_c,
                         (rot_c[0] + math.cos(ang) * 42, rot_c[1] + math.sin(ang) * 42), 4)
    for k in range(1, 5):                                                               # пунктир траектории винта
        pygame.draw.circle(surface, SEPIA_MID, (int(lerp(rot_c[0], cx - 10, k / 5.5)),
                                                int(lerp(rot_c[1], cy - 14, k / 5.5))), 2)
    _parachute(surface, rect.x + 190, rect.y + 112, 20, t)


ART = {
    "falling": _art_falling,
    "falling_big": _art_falling_big,
    "saved": _art_saved,
    "flak": _art_flak,
    "ruins": _art_ruins,
    "victory": _art_victory,
    "trade": _art_trade,
    "shadow": _art_shadow,
    "gravity": _art_gravity,
}


def draw_illustration(surface, rect, art, ticks):
    """Иллюстрация в рамке; всё рисуется pygame.draw, клипуется по рамке."""
    old_clip = surface.get_clip()
    surface.set_clip(rect)
    ART[art](surface, rect, ticks)
    surface.set_clip(old_clip)
    pygame.draw.rect(surface, INK, rect, 3)


def draw_event_popup(surface, event, remaining, ticks):
    """Окно «газетной вырезки» поверх всего. remaining — сколько событий осталось в очереди."""
    veil = pygame.Surface((W, H), pygame.SRCALPHA)
    veil.fill((24, 14, 4, 170))
    surface.blit(veil, (0, 0))
    r = EVENT_RECT
    pygame.draw.rect(surface, (30, 20, 10), r.move(9, 9))                   # тень
    pygame.draw.rect(surface, NEWS_PAPER, r)
    pygame.draw.rect(surface, INK, r, 5)
    pygame.draw.rect(surface, INK, r.inflate(-16, -16), 1)
    # Шапка газеты
    draw_text_center(surface, "ВОЕННЫЙ ВЕСТНИК   •   ЭКСТРЕННЫЙ ВЫПУСК", r.centerx, r.y + 22, NEWS_MAST, INK)
    pygame.draw.line(surface, INK, (r.x + 30, r.y + 46), (r.right - 30, r.y + 46), 3)
    pygame.draw.line(surface, INK, (r.x + 30, r.y + 51), (r.right - 30, r.y + 51), 1)
    # Заголовок
    head_font = NEWS_HEAD if NEWS_HEAD.size(event.title)[0] <= r.width - 60 else NEWS_HEAD_SMALL
    draw_text_center(surface, event.title, r.centerx, r.y + 58, head_font, INK)
    pygame.draw.line(surface, INK, (r.x + 30, r.y + 110), (r.right - 30, r.y + 110), 2)
    # Иллюстрация
    ill = pygame.Rect(r.x + 30, r.y + 120, r.width - 60, 200)
    draw_illustration(surface, ill, event.art, ticks)
    # Текст
    y = ill.bottom + 16
    for line in wrap_text(NEWS_BODY, event.text, r.width - 60):
        if y > BTN_CONTINUE.y - 24:
            break
        draw_text(surface, line, r.x + 30, y, NEWS_BODY, INK)
        y += 25
    # Кнопка и счётчик
    hover = BTN_CONTINUE.collidepoint(pygame.mouse.get_pos())
    rounded(surface, BTN_CONTINUE, PANEL2 if hover else PANEL, 6, INK, 3)
    img = BOLD.render("Продолжить", True, INK)
    surface.blit(img, img.get_rect(center=BTN_CONTINUE.center))
    if remaining > 1:
        draw_text(surface, f"Ещё сообщений: {remaining - 1}", r.x + 30, r.bottom - 46, SMALL, MUTED)


# ============================ ГЛОБАЛЬНАЯ КАРТА ============================
ZONE_POINTS = 72
ZONE_SQUASH = 0.92                  # овал чуть приплюснут по вертикали
OWNER_PLAYER = "player"
OWNER_ENEMY = "enemy"
OWNER_COLOR = {OWNER_PLAYER: BLUE_INK, OWNER_ENEMY: RED_INK}
OWNER_TEXT = {OWNER_PLAYER: "Под нашим контролем", OWNER_ENEMY: "Удерживается врагом"}
LAND_COLOR = (218, 203, 168)


@dataclass
class Zone:
    name: str
    center: tuple
    radius: int
    owner: str
    outline: list        # неровный контур (основной)
    outline2: list       # «повторный» контур карандашом
    battled: bool = False

    def contains(self, pos):
        dx = (pos[0] - self.center[0]) / self.radius
        dy = (pos[1] - self.center[1]) / (self.radius * ZONE_SQUASH)
        return dx * dx + dy * dy <= 1.0


def make_zone(name, center, radius, owner, seed):
    rng = random.Random(seed)

    def ring(scale):
        phase = rng.uniform(0, 2 * math.pi)
        pts = []
        for k in range(ZONE_POINTS):
            a = 2 * math.pi * k / ZONE_POINTS
            rr = radius * scale * (1 + 0.03 * math.sin(5 * a + phase) + rng.uniform(-0.012, 0.012))
            pts.append((center[0] + math.cos(a) * rr, center[1] + math.sin(a) * rr * ZONE_SQUASH))
        return pts

    return Zone(name, center, radius, owner, ring(1.0), ring(1.04), False)


def blob_points(cx, cy, rx, ry, phase, scale=1.0, n=64):
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n
        m = 1 + 0.09 * math.sin(3 * a + phase) + 0.06 * math.sin(5 * a + phase * 1.7) + 0.035 * math.sin(9 * a + phase * 2.3)
        pts.append((cx + rx * m * scale * math.cos(a), cy + ry * m * scale * math.sin(a)))
    return pts


def wavy_line(p0, p1, amp, freq, n=40):
    pts = []
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    for k in range(n + 1):
        t = k / n
        off = math.sin(t * freq * math.pi) * amp
        pts.append((p0[0] + dx * t + nx * off, p0[1] + dy * t + ny * off))
    return pts


MAP_BLOBS = [((370, 470), 260, 240, 1.3), ((1030, 440), 260, 235, 4.1)]
MAP_CITIES = [((190, 330), "Нордвик"), ((500, 640), "Эрстад"), ((210, 640), "Хальбург"),
              ((1170, 300), "Ронсфельд"), ((880, 620), "Вельмар"), ((1190, 590), "Дюнберг")]


def build_map_background():
    """Статичная часть карты: бумага, суша, море, реки, города, компас, рамка, линия фронта."""
    surf = PAPER_SURF.copy()
    rng = random.Random(21)
    # Волны в море
    for _ in range(260):
        x, y = rng.randint(50, W - 60), rng.randint(130, H - 60)
        inside = False
        for (cx, cy), rx, ry, _ph in MAP_BLOBS:
            if ((x - cx) / (rx * 1.2)) ** 2 + ((y - cy) / (ry * 1.2)) ** 2 < 1:
                inside = True
        if not inside:
            pygame.draw.lines(surf, SPLASH, False, [(x, y), (x + 4, y - 3), (x + 8, y), (x + 12, y - 3)], 1)
    # Суша
    for (cx, cy), rx, ry, ph in MAP_BLOBS:
        for scale, color in ((1.09, (196, 184, 156)), (1.045, (186, 170, 140))):    # «эхо» береговой линии
            pygame.draw.polygon(surf, color, blob_points(cx, cy, rx, ry, ph, scale), 1)
        pygame.draw.polygon(surf, LAND_COLOR, blob_points(cx, cy, rx, ry, ph))
        pygame.draw.polygon(surf, INK, blob_points(cx, cy, rx, ry, ph), 2)
    # Реки
    pygame.draw.lines(surf, SPLASH, False, wavy_line((120, 300), (330, 740), 14, 4), 2)
    pygame.draw.lines(surf, SPLASH, False, wavy_line((1280, 260), (1010, 720), 14, 4), 2)
    # Города
    for (x, y), name in MAP_CITIES:
        pygame.draw.rect(surf, INK, (x - 4, y - 4, 8, 8))
        pygame.draw.rect(surf, LAND_COLOR, (x - 2, y - 2, 4, 4))
        draw_text(surf, name, x + 9, y - 9, CITY_FONT, INK)
    # Линия фронта — красная пунктирная волнистая
    front = wavy_line((700, 140), (700, 780), 7, 9, 90)
    for i in range(0, len(front) - 1, 2):
        pygame.draw.line(surf, RED_INK, front[i], front[i + 1], 3)
    label = pygame.transform.rotate(CITY_FONT.render("ЛИНИЯ ФРОНТА", True, RED_INK), 90)
    surf.blit(label, (712, 400))
    # Компас
    cx, cy = 1322, 118
    pygame.draw.circle(surf, INK, (cx, cy), 32, 2)
    for k in range(8):
        a = k * math.pi / 4 - math.pi / 2
        r_out = 30 if k % 2 == 0 else 20
        pygame.draw.polygon(surf, INK, [(cx + math.cos(a) * r_out, cy + math.sin(a) * r_out),
                                        (cx + math.cos(a + 0.35) * 7, cy + math.sin(a + 0.35) * 7),
                                        (cx + math.cos(a - 0.35) * 7, cy + math.sin(a - 0.35) * 7)])
    draw_text_center(surf, "С", cx, cy - 56, BOLD, INK)
    # Рамка со штрихами по краю
    pygame.draw.rect(surf, INK, (24, 24, W - 48, H - 48), 3)
    pygame.draw.rect(surf, INK, (32, 32, W - 64, H - 64), 1)
    for x in range(52, W - 40, 40):
        pygame.draw.line(surf, INK, (x, 32), (x, 40), 1)
        pygame.draw.line(surf, INK, (x, H - 32), (x, H - 40), 1)
    for y in range(52, H - 40, 40):
        pygame.draw.line(surf, INK, (32, y), (40, y), 1)
        pygame.draw.line(surf, INK, (W - 32, y), (W - 40, y), 1)
    # Заголовок
    draw_text_center(surf, "ТЕАТР ВОЗДУШНЫХ ДЕЙСТВИЙ", W // 2, 46, MAP_TITLE, INK)
    draw_text_center(surf, "Выбери сектор — кликни по кругу, и над ним начнётся бой", W // 2, 96, MAP_ITALIC, MUTED)
    return surf


MAP_BG = build_map_background()


def draw_zone(surface, zone, hover):
    color = OWNER_COLOR[zone.owner]
    cx, cy = zone.center
    pad = 40
    side = zone.radius * 2 + pad * 2
    ox, oy = cx - zone.radius - pad, cy - zone.radius - pad
    layer = pygame.Surface((side, side), pygame.SRCALPHA)
    pygame.draw.polygon(layer, (*color, 60 if not hover else 90), [(x - ox, y - oy) for x, y in zone.outline])
    surface.blit(layer, (ox, oy))
    pygame.draw.lines(surface, color, True, zone.outline, 5 if hover else 3)
    pygame.draw.lines(surface, color, True, zone.outline2, 1)
    # Флажок в центре
    pygame.draw.line(surface, INK, (cx, cy - 26), (cx, cy + 30), 3)
    pygame.draw.polygon(surface, color, [(cx, cy - 26), (cx + 34, cy - 14), (cx, cy - 2)])
    pygame.draw.polygon(surface, INK, [(cx, cy - 26), (cx + 34, cy - 14), (cx, cy - 2)], 1)
    draw_text_center(surface, zone.name, cx, int(cy - zone.radius * 0.55), ZONE_FONT, INK)
    draw_text_center(surface, OWNER_TEXT[zone.owner], cx, int(cy + zone.radius * 0.5), SMALL, color)
    if hover:
        draw_text_center(surface, "Клик — начать бой", cx, int(cy + zone.radius * 0.5) + 20, SMALL, INK)


def draw_stamp(surface, text, center, color, angle=-7):
    """Штамп с рамкой (для итога кампании)."""
    img = TITLE.render(text, True, color)
    pad = 14
    stamp = pygame.Surface((img.get_width() + pad * 2, img.get_height() + pad * 2), pygame.SRCALPHA)
    stamp.blit(img, (pad, pad))
    pygame.draw.rect(stamp, color, stamp.get_rect(), 4)
    pygame.draw.rect(stamp, color, stamp.get_rect().inflate(-10, -10), 1)
    stamp = pygame.transform.rotate(stamp, angle)
    surface.blit(stamp, stamp.get_rect(center=center))


# ============================ БОЙ ============================
class Game:
    """Один бой 9×9 над сектором. Время игры — виртуальное (clock_ms): оно не идёт,
    пока на экране окно газеты, поэтому анимации замирают на паузе."""

    def __init__(self, event_queue, zone_name="Твой сектор"):
        self.event_queue = event_queue
        self.zone_name = zone_name
        self.clock_ms = 0.0
        self.player = Fleet()
        self.ai = Fleet()
        self.selected_target = None
        self.selected_plane = None
        self.marker_target_id: Optional[int] = None   # выбранный (но ещё не применённый) перевес
        self.action = ACTION_SHOT
        # Инициализация Радара
        self.radar_used = False
        self.radar_scan = None
        self.radar_revealed = set()
        self.radar_checked = set()
        self.radar_hover = None
        # Метки на полях
        self.hits = set()          # наши попадания по врагу (правое поле)
        self.misses = set()
        self.ai_hits = set()       # попадания ИИ по нам (левое поле)
        self.ai_misses = set()
        self.pvo_marks_enemy = set()   # следы ПВО на небе врага
        self.pvo_marks_own = set()     # следы ПВО ИИ на нашем небе
        # Память ИИ
        self.ai_memory: dict = {}      # клетка -> номер хода, когда ИИ туда стрелял
        self.ai_followups: dict = {}   # клетка -> ход, где самолёт выжил (его нужно добить)
        self.log = []
        self.game_over = False
        self.result = ""
        self.turn = 1
        self.status = ""
        # Анимация и сценарий хода
        self.script: Optional[Iterator[int]] = None
        self.wake_at = 0
        self.move_anim: Optional[MoveAnim] = None
        self.missiles: list[Missile] = []
        self.explosions: list[Explosion] = []
        self.add_log("Матч начался. Уничтожь промышленность врага или все его бомбардировщики.")
        self.add_log("Твоя метка истребителя отмечена звездой.")

    # ---------------- служебное ----------------
    def now(self):
        return int(self.clock_ms)

    @property
    def busy(self):
        """Пока идёт анимация хода, ввод заблокирован."""
        return self.script is not None

    def add_log(self, message):
        self.log.append(message)
        self.log = self.log[-9:]

    def emit(self, event: Event):
        """Добавляет событие в очередь, если газетные вырезки включены."""
        if SETTINGS["newspapers"]:
            self.event_queue.append(event)

    # ---------------- перевес ----------------
    def choose_rebalance(self):
        """Клик по «ПЕРЕВЕСИТЬ»: только ЗАПОМИНАЕМ цель. Применится после «ХОД»."""
        p = self.player.get(self.selected_plane)
        if not p or p.kind == "helicopter" or self.player.marker is None or self.player.marker_transit:
            return
        if p.uid == self.player.marker:
            self.add_log("Метка уже находится на выбранном самолёте.")
            return
        if self.marker_target_id == p.uid:                 # повторный клик — отмена
            self.marker_target_id = None
            self.add_log("Перевес отменён.")
            return
        self.marker_target_id = p.uid
        self.add_log(f"Перевес на {p.label().lower()} выбран — он сработает после «ХОД».")

    def _apply_marker_choice(self):
        """Применяет запомненный перевес — вызывается в начале хода."""
        uid, self.marker_target_id = self.marker_target_id, None
        if uid is None:
            return
        f = self.player
        target = f.get(uid)
        if target is None or f.marker is None or f.marker_transit or uid == f.marker:
            self.add_log("Перевес отменён: условия изменились.")
            return
        f.marker = None
        f.marker_transit = True
        f.marker_pending = uid
        self.add_log(f"Истребитель отправлен к {target.label().lower()}: защита отсутствует один ход.")

    def _finish_marker_transit(self, fleet, ai_side):
        if fleet.marker_transit:
            fleet.marker = fleet.marker_pending if fleet.get(fleet.marker_pending) else None
            fleet.marker_pending = None
            fleet.marker_transit = False
            if fleet.marker is not None:
                self.add_log("Истребитель ИИ занял новую позицию." if ai_side
                             else "Истребитель прибыл к новому самолёту.")

    def _ai_maybe_rebalance(self):
        """ИИ иногда переводит метку на другой бомбардировщик (защита исчезает на ход)."""
        ai = self.ai
        if ai.marker is not None and not ai.marker_transit and random.random() < AI_REBALANCE_CHANCE:
            choices = [p for p in ai.alive() if p.kind != "helicopter" and p.uid != ai.marker]
            if choices:
                ai.marker = None
                ai.marker_transit = True
                ai.marker_pending = random.choice(choices).uid
                self.add_log("ИИ перевёл истребитель на другой самолёт.")

    # ---------------- ИИ ----------------
    def _ai_recent_cells(self):
        """Клетки, в которые ИИ стрелял совсем недавно (самолёты движутся — старое устаревает)."""
        return {c for c, t in self.ai_memory.items() if self.turn - t < AI_MEMORY_TURNS}

    def _ai_hunt_cells(self, recent):
        """Клетки рядом с подбитыми самолётами, которые выжили благодаря метке: их надо добить."""
        for cell in [c for c, t in self.ai_followups.items() if self.turn - t > AI_HUNT_TTL_TURNS]:
            del self.ai_followups[cell]
        cells = set()
        for hx, hy in self.ai_followups:
            for dx in range(-AI_HUNT_RADIUS, AI_HUNT_RADIUS + 1):
                for dy in range(-AI_HUNT_RADIUS, AI_HUNT_RADIUS + 1):
                    c = (hx + dx, hy + dy)
                    if 0 <= c[0] < GRID_SIZE and 0 <= c[1] < GRID_SIZE and c not in recent:
                        cells.add(c)
        return sorted(cells)

    def ai_choose(self):
        if self.ai.can_pvo() and random.random() < AI_PVO_CHANCE:
            return ACTION_PVO, None
        recent = self._ai_recent_cells()
        pool = self._ai_hunt_cells(recent)                       # 1) добиваем подбитых
        if not pool:                                             # 2) иначе — «свежая» клетка
            pool = [(x, y) for y in range(GRID_SIZE) for x in range(GRID_SIZE) if (x, y) not in recent]
        if not pool:
            pool = [(x, y) for y in range(GRID_SIZE) for x in range(GRID_SIZE)]
        return ACTION_SHOT, random.choice(pool)

    # ---------------- ход ----------------
    def start_player_turn(self):
        if self.busy or self.game_over:
            return
        if self.action == ACTION_PVO:
            if not self.player.can_pvo():
                self.add_log("ПВО сейчас недоступно.")
                return
            action, target = ACTION_PVO, None
        elif self.action == ACTION_RADAR:
            if self.radar_used:
                self.add_log("Радар уже использован в этом матче.")
                return
            if self.selected_target is None:
                self.add_log("Выбери клетку для сканирования радаром.")
                return
            action, target = ACTION_RADAR, self.selected_target
        else:
            if self.selected_target is None:
                self.add_log("Сначала выбери клетку на небе врага.")
                return
            action, target = ACTION_SHOT, self.selected_target
        self.selected_target = None
        if action == ACTION_RADAR:
            self.radar_used = True
            self.action = ACTION_SHOT
            x, y = target
            area = {(xx, yy) for xx in range(max(0, x-1), min(GRID_SIZE, x+2))
                    for yy in range(max(0, y-1), min(GRID_SIZE, y+2))}
            self.radar_scan = area
            found = set()
            for plane in self.ai.alive():
                if area.intersection(plane.cells()):
                    found.add(plane.uid)
            self.radar_revealed.update(found)
            if not found:
                self.radar_checked.update(area)
                self.add_log("Радар: сектор пуст. Клетки отмечены как проверенные.")
            else:
                self.add_log("Радар обнаружил самолёт противника в зоне 3×3.")
        self.script = self._turn_script(action, target)
        self.wake_at = 0

    def _turn_script(self, action, target):
        """Сценарий хода. Каждый yield — «подождать столько мс», пока играет анимация.
        Порядок: перевес → движение → ракета → взрыв → HP → ход ИИ (те же шаги)."""
        # 1. Перевес (применяется только сейчас) и плавное движение наших самолётов
        self.status = "Самолёты маневрируют…"
        self._apply_marker_choice()
        yield self._start_player_move()
        self.move_anim = None
        # 2. Наш выстрел: ракета → взрыв
        self.status = "Ракета в полёте…"
        yield self._launch_volley(self.player, self.ai, action, target, ai_side=False)
        # 3. Урон бомбардировщиков и починка, полоски HP плавно меняются
        yield self._economy_step(self.player, self.ai, ai_side=False)
        self._finish_marker_transit(self.ai, ai_side=True)   # метка ИИ прибывает после нашего залпа
        self.check_end()
        if self.game_over:
            self.status = ""
            return
        # 4. Ответный ход ИИ
        self.status = "Ход ИИ: самолёты маневрируют…"
        self._ai_maybe_rebalance()
        ai_action, ai_target = self.ai_choose()
        self.ai.move_all()                                   # поле врага скрыто — просто пауза
        if self.radar_scan is not None:
            for plane in self.ai.alive():
                if not self.radar_scan.intersection(plane.cells()):
                    self.radar_revealed.discard(plane.uid)
        yield AI_THINK_MS
        self.status = "ИИ стреляет…"
        yield self._launch_volley(self.ai, self.player, ai_action, ai_target, ai_side=True)
        self._finish_marker_transit(self.player, ai_side=False)  # наша метка прибывает после залпа ИИ
        yield self._economy_step(self.ai, self.player, ai_side=True)
        self.turn += 1
        self.check_end()
        self.action = ACTION_SHOT
        self.status = ""

    def _start_player_move(self):
        moves = self.player.move_all()
        self.move_anim = MoveAnim(moves, self.now(), MOVE_MS)
        if self.radar_scan is not None:
            for plane in self.ai.alive():
                if not self.radar_scan.intersection(plane.cells()):
                    self.radar_revealed.discard(plane.uid)
        return MOVE_MS

    def _launch_point(self, ai_side, index, total):
        """Откуда стартует ракета: с края «своего» поля стрелявшего."""
        offset = (index - (total - 1) / 2) * CELL
        x = RIGHT_X if ai_side else LEFT_X + BOARD
        return x, BOARD_Y + BOARD / 2 + offset

    def _launch_volley(self, attacker, defender, action, target, ai_side):
        """Создаёт ракеты (по одной на выстрел, 3 для ПВО). Попадания считаются
        в момент приземления каждой ракеты. Возвращает, сколько мс ждать."""
        now = self.now()
        if action == ACTION_RADAR:
            return 0
        if action == ACTION_PVO:
            attacker.pvo_used = True
            cells = [(random.randrange(GRID_SIZE), random.randrange(GRID_SIZE)) for _ in range(PVO_SHOTS)]
            self.add_log(("ИИ" if ai_side else "Ты") + " активировал ПВО: " +
                         ", ".join(coord(x, y) for x, y in cells) + ".")
            if not ai_side:
                self.emit(make_event("pvo"))                 # «Стена огня»
        else:
            cells = [target]
        target_rect = BOARD_RECT_L if ai_side else BOARD_RECT_R
        for i, cell in enumerate(cells):
            launch = now + i * PVO_STAGGER_MS
            self.missiles.append(Missile(
                cell=cell,
                start=self._launch_point(ai_side, i, len(cells)),
                end=cell_center(target_rect, cell),
                launch_at=launch, land_at=launch + MISSILE_MS,
                defender=defender, ai_side=ai_side, via_pvo=(action == ACTION_PVO)))
        return (len(cells) - 1) * PVO_STAGGER_MS + MISSILE_MS + EXPLOSION_MS

    def _emit_for_ai_hit(self, result, plane):
        """События «газеты» по результату попадания ИИ в наш самолёт."""
        if result == RESULT_SAVED:
            self.emit(make_event("fighter_saved", FIGHTER_CALLSIGN))
        elif result == RESULT_KILL and plane is not None:
            if plane.kind == "bomber":
                self.emit(make_event("bomber_lost", plane.pilot_name))
            elif plane.kind == "strategic":
                self.emit(make_event("strategic_lost", plane.pilot_name))

    def _resolve_missile(self, m):
        """Ракета приземлилась: считаем попадание, пишем в журнал, запускаем взрыв."""
        m.resolved = True
        x, y = m.cell
        result, text, plane = m.defender.incoming_hit(x, y)
        if m.ai_side:
            self.add_log("ИИ: " + text)
            hits, misses, flak = self.ai_hits, self.ai_misses, self.pvo_marks_own
            self.ai_memory[m.cell] = self.turn                 # в память — и обычные, и ПВО-клетки
            if result == RESULT_SAVED:
                self.ai_followups[m.cell] = self.turn          # самолёт выжил — надо добить
            elif result == RESULT_KILL:                        # самолёт сбит — добивать нечего
                for c in [c for c in self.ai_followups
                          if abs(c[0] - x) <= AI_HUNT_RADIUS and abs(c[1] - y) <= AI_HUNT_RADIUS]:
                    del self.ai_followups[c]
            self._emit_for_ai_hit(result, plane)
        else:
            self.add_log(("Ты: " if m.via_pvo else "") + text)
            hits, misses, flak = self.hits, self.misses, self.pvo_marks_enemy
        if result == RESULT_MISS:
            misses.add(m.cell)
            hits.discard(m.cell)
        else:
            hits.add(m.cell)
            misses.discard(m.cell)
        if m.via_pvo:
            flak.add(m.cell)
        self.explosions.append(Explosion(m.end, self.now(), result))

    def _economy_step(self, attacker, defender, ai_side):
        """Урон по промышленности и починка. Полоска HP доедет анимацией."""
        damage = attacker.bombardment()
        defender.hp = max(0, defender.hp - damage)
        if damage:
            self.add_log(f"Бомбардировщики ИИ нанесли твоей промышленности {damage} урона." if ai_side
                         else f"Твои бомбардировщики нанесли промышленности ИИ {damage} урона.")
        repaired = attacker.repair()
        if repaired:
            self.add_log(f"Промышленность ИИ восстановила {repaired} HP." if ai_side
                         else f"Твоя промышленность восстановила {repaired} HP.")
        return HP_ANIM_MS if (damage or repaired) else HP_IDLE_MS

    def check_end(self):
        if self.game_over:
            return
        player_bombers = any(p.alive and p.kind in ("bomber", "strategic") for p in self.player.planes)
        ai_bombers = any(p.alive and p.kind in ("bomber", "strategic") for p in self.ai.planes)
        if self.ai.hp <= 0 or not ai_bombers:
            self.game_over, self.result = True, "ПОБЕДА!"
            self.emit(make_event("victory"))
        elif self.player.hp <= 0 or not player_bombers:
            self.game_over, self.result = True, "ПОРАЖЕНИЕ"
            self.emit(make_event("defeat"))                    # «Небо потеряно»

    # ---------------- обновление кадра ----------------
    def update(self, dt_ms):
        """Вызывается только когда нет окна газеты — иначе игра на паузе."""
        self.clock_ms += dt_ms
        now = self.now()
        for m in self.missiles:
            if not m.resolved and now >= m.land_at:
                self._resolve_missile(m)
        self.missiles = [m for m in self.missiles if not m.resolved]
        self.explosions = [e for e in self.explosions if now - e.start < EXPLOSION_MS]
        if self.script is not None and now >= self.wake_at:
            try:
                delay = next(self.script)
                self.wake_at = self.now() + delay
            except StopIteration:
                self.script = None
                self.status = ""
        # Плавное движение полосок HP к реальному значению
        step = HP_ANIM_SPEED * dt_ms / 1000
        for fleet in (self.player, self.ai):
            diff = fleet.hp - fleet.hp_shown
            fleet.hp_shown = fleet.hp if abs(diff) <= step else fleet.hp_shown + math.copysign(step, diff)

    # ---------------- отрисовка ----------------
    def _plane_draw_pos(self, plane, now):
        anim = self.move_anim
        if anim and plane.uid in anim.paths:
            (ox, oy), (nx, ny) = anim.paths[plane.uid]
            t = smoothstep((now - anim.start) / anim.duration)
            return lerp(ox, nx, t), lerp(oy, ny, t)
        return plane.x, plane.y

    def _draw_enemy_status(self, surface):
        """Сколько самолётов осталось у врага: «Флот ИИ: Бомбардировщики 2/3, Стратеги 1/2»."""
        x, y = RIGHT_X, 38
        draw_text(surface, "Флот ИИ:", x, y, FONT, MUTED)
        x += FONT.size("Флот ИИ: ")[0]
        parts = [("helicopter", "Вертолёт"), ("bomber", "Бомбардировщики"), ("strategic", "Стратеги")]
        for i, (kind, name) in enumerate(parts):
            alive, total = self.ai.count(kind)
            text = f"{name} {alive}/{total}" + ("," if i < len(parts) - 1 else "")
            draw_text(surface, text, x, y, FONT, INK if alive else MUTED)
            x += FONT.size(text + " ")[0]

    def draw(self, surface):
        now = self.now()
        surface.blit(PAPER_SURF, (0, 0))
        draw_text(surface, "SolomonAir: AirFight", 55, 25, TITLE, INK)
        draw_text(surface, f"Ход {self.turn}  •  {self.zone_name}", 58, 68, SMALL, MUTED)
        self._draw_enemy_status(surface)
        draw_bar(surface, 55, 125, "ТВОЯ ПРОМЫШЛЕННОСТЬ", self.player.hp_shown, GREEN_INK)
        draw_bar(surface, 535, 125, "ПРОМЫШЛЕННОСТЬ ИИ", self.ai.hp_shown, RED_INK)

        # Левое поле: наши самолёты и выстрелы ИИ
        draw_board_frame(surface, BOARD_RECT_L, "ТВОЁ НЕБО")
        fleet = self.player
        for p in fleet.alive():
            draw_plane(surface, p, BOARD_RECT_L, self._plane_draw_pos(p, now), now,
                       selected=p.uid == self.selected_plane,
                       queued=p.uid == self.marker_target_id,
                       marker=p.uid == fleet.marker and not fleet.marker_transit,
                       marker_pending=fleet.marker_transit and p.uid == fleet.marker_pending)
        draw_marks(surface, BOARD_RECT_L, self.ai_hits, self.ai_misses, self.pvo_marks_own)

        # Правое поле: наши выстрелы
        draw_board_frame(surface, BOARD_RECT_R, "НЕБО ВРАГА")
        if self.action == ACTION_RADAR and not self.radar_used:
            preview_cell = self.selected_target if self.selected_target is not None else self.radar_hover
            if preview_cell is not None:
                rx, ry = preview_cell
                area = {(xx, yy) for xx in range(max(0, rx - 1), min(GRID_SIZE, rx + 2))
                        for yy in range(max(0, ry - 1), min(GRID_SIZE, ry + 2))}
                overlay = pygame.Surface((BOARD, BOARD), pygame.SRCALPHA)
                for xx, yy in area:
                    pygame.draw.rect(overlay, (45, 150, 75, 55),
                                     (xx * CELL, yy * CELL, CELL, CELL))
                surface.blit(overlay, BOARD_RECT_R.topleft)
                frame = pygame.Rect(RIGHT_X + max(0, rx - 1) * CELL,
                                    BOARD_Y + max(0, ry - 1) * CELL,
                                    min(GRID_SIZE, rx + 2) * CELL - max(0, rx - 1) * CELL,
                                    min(GRID_SIZE, ry + 2) * CELL - max(0, ry - 1) * CELL)
                pygame.draw.rect(surface, GREEN_INK, frame, 3, border_radius=4)
        elif self.selected_target is not None:
            cx, cy = cell_center(BOARD_RECT_R, self.selected_target)
            pygame.draw.rect(surface, BLUE_INK, (cx - CELL / 2 + 2, cy - CELL / 2 + 2, CELL - 4, CELL - 4), 2,
                             border_radius=4)
        draw_marks(surface, BOARD_RECT_R, self.hits, self.misses, self.pvo_marks_enemy)
        for cell in self.radar_checked:
            cx, cy = cell_center(BOARD_RECT_R, cell)
            pygame.draw.rect(surface, GREEN_INK, (cx-15, cy-15, 30, 30), 1)
            draw_text_center(surface, "✓", int(cx), int(cy-9), SMALL, GREEN_INK)
        if self.radar_scan:
            for plane in self.ai.alive():
                if plane.uid in self.radar_revealed and self.radar_scan.intersection(plane.cells()):
                    pos = (plane.x, plane.y)
                    spr = get_sprite(plane.kind, plane.length, plane.vertical)
                    ghost = spr.copy()
                    ghost.set_alpha(150)
                    surface.blit(ghost, (RIGHT_X + pos[0]*CELL, BOARD_Y + pos[1]*CELL))
                    pygame.draw.rect(surface, OCHRE, (RIGHT_X+pos[0]*CELL, BOARD_Y+pos[1]*CELL,
                                      spr.get_width(), spr.get_height()), 2)

        # Ракеты и взрывы — поверх всего
        for m in self.missiles:
            draw_missile(surface, m, now)
        for e in self.explosions:
            draw_explosion(surface, e, now)

        self._draw_panel(surface)
        self._draw_legend(surface)
        self._draw_log(surface)
        button(surface, BTN_MENU, "МЕНЮ", True, OCHRE)

        if self.game_over and not self.busy and not self.event_queue:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((30, 20, 8, 150))
            surface.blit(veil, (0, 0))
            box = pygame.Rect(420, 325, 560, 190)
            rounded(surface, box, PANEL, 14, INK, 3)
            won = self.result == "ПОБЕДА!"
            draw_text_center(surface, self.result, 700, 345, TITLE, GREEN_INK if won else RED_INK)
            draw_text_center(surface,
                             "Сектор останется под нашим контролем." if won else "Сектор перейдёт под контроль врага.",
                             700, 398, FONT, INK)
            button(surface, BTN_BACK, "Вернуться на карту", True, OCHRE)

    def _draw_panel(self, surface):
        x = PANEL_TEXT_X
        rounded(surface, PANEL_RECT, PANEL, 14, INK, 2)
        draw_text(surface, "УПРАВЛЕНИЕ", x, 155, BOLD)
        draw_text(surface, "Выбери клетку на правом поле", x, 190, SMALL, MUTED)
        target_label = coord(*self.selected_target) if self.selected_target else "не выбрана"
        draw_text(surface, f"Цель: {target_label}", x, 215, FONT, BLUE_INK)
        free = not self.busy and not self.game_over
        pvo_ok = free and self.player.can_pvo()
        button(surface, BTN_PVO, "ПВО" if not self.player.pvo_used else "ПВО: ИСП.",
               pvo_ok or (free and self.action == ACTION_PVO), OCHRE)
        button(surface, BTN_NORMAL, "ОБЫЧНЫЙ", free, BLUE_INK)
        button(surface, BTN_RADAR, "РАДАР: ИСП." if self.radar_used else "РАДАР", free and not self.radar_used or
               (free and self.action == ACTION_RADAR), GREEN_INK)
        draw_text(surface, "Свой самолёт:", x, 350, SMALL, MUTED)
        selected = self.player.get(self.selected_plane)
        draw_text(surface, selected.label() if selected else "не выбран", x, 374, FONT, INK)

        queued = self.player.get(self.marker_target_id)
        if queued:
            marker_text = f"перевес: {queued.label().lower()} — на «ХОД»"
        elif self.player.marker_transit:
            marker_text = "в пути — защиты нет"
        elif self.player.marker is None:
            marker_text = "истребитель потерян"
        else:
            marker_text = "истребитель на посту"
        draw_star(surface, (x + 8, 420), 8, 3.5, OCHRE, STAR_DARK)          # звезда рисуется полигоном
        draw_text(surface, marker_text, x + 24, 411, SMALL, BLUE_INK if queued else OCHRE)

        can_rebalance = bool(free and selected and selected.kind != "helicopter" and
                             self.player.marker is not None and not self.player.marker_transit and
                             selected.uid != self.player.marker)
        cancel = bool(free and selected and selected.uid == self.marker_target_id)
        button(surface, BTN_REBALANCE, "ОТМЕНИТЬ ПЕРЕВЕС" if cancel else "ПЕРЕВЕСИТЬ",
               can_rebalance or cancel, OCHRE)
        button(surface, BTN_TURN, "ХОД", free, GREEN_INK)
        draw_text(surface, "ПВО: 3 случайные клетки, 1 раз за матч", x, 630, SMALL, MUTED)
        draw_text(surface, "Попадание без метки сбивает самолёт целиком.", x, 650, SMALL, MUTED)
        draw_text(surface, "Второе попадание в тот же самолёт сбивает его.", x, 670, SMALL, MUTED)
        draw_text(surface, "Живой вертолёт усиливает починку.", x, 690, SMALL, MUTED)
        if self.status:
            draw_text(surface, self.status, x, 675, FONT, BLUE_INK)

    def _draw_legend(self, surface):
        rounded(surface, pygame.Rect(55, 610, 900, 95), PANEL, 12, INK, 2)
        draw_text(surface, "ФЛОТ", 75, 625, SMALL, MUTED)
        x, y_center = 75, 672
        for kind, length in (("helicopter", 1), ("bomber", 3), ("strategic", 4)):
            spr = legend_sprite(kind, length)
            surface.blit(spr, (x, y_center - spr.get_height() // 2))
            name = KIND_LABEL[kind]
            draw_text(surface, name, x + spr.get_width() + 8, y_center - 8, SMALL)
            x += spr.get_width() + 8 + SMALL.size(name)[0] + 30
        draw_star(surface, (x + 8, y_center), 9, 4, OCHRE, STAR_DARK)
        draw_text(surface, "Истребитель-защитник", x + 24, y_center - 8, SMALL, OCHRE)

    def _draw_log(self, surface):
        rounded(surface, pygame.Rect(55, 725, 1300, 105), PANEL, 12, INK, 2)
        draw_text(surface, "ЖУРНАЛ БОЯ", 75, 738, SMALL, MUTED)
        lines = self.log[-4:]
        for i, line in enumerate(lines):
            draw_text(surface, "› " + line[:145], 75, 758 + i * 17, SMALL,
                      INK if i == len(lines) - 1 else MUTED)

    # ---------------- ввод ----------------
    def handle_motion(self, pos):
        if self.action == ACTION_RADAR and BOARD_RECT_R.collidepoint(pos):
            self.radar_hover = (int((pos[0] - RIGHT_X) // CELL),
                                int((pos[1] - BOARD_Y) // CELL))
        else:
            self.radar_hover = None

    def handle_click(self, pos):
        if self.game_over or self.busy:
            return
        if BTN_MENU.collidepoint(pos):
            return "MENU"
        if BOARD_RECT_R.collidepoint(pos):
            x = (pos[0] - RIGHT_X) // CELL
            y = (pos[1] - BOARD_Y) // CELL
            self.selected_target = (int(x), int(y))
            if self.action not in (ACTION_RADAR,):
                self.action = ACTION_SHOT
            return
        if BOARD_RECT_L.collidepoint(pos):
            x = (pos[0] - LEFT_X) // CELL
            y = (pos[1] - BOARD_Y) // CELL
            clicked = next((p.uid for p in self.player.alive() if (x, y) in p.cells()), None)
            # Клик по другой клетке своего поля сбрасывает выбор перевеса
            if self.marker_target_id is not None and clicked != self.marker_target_id:
                self.marker_target_id = None
                self.add_log("Выбор перевеса сброшен.")
            self.selected_plane = clicked
            return
        if BTN_PVO.collidepoint(pos):
            if self.player.can_pvo():
                self.action = ACTION_PVO
                self.selected_target = None
            return
        if BTN_NORMAL.collidepoint(pos):
            self.action = ACTION_SHOT
            return
        if BTN_RADAR.collidepoint(pos):
            if not self.radar_used:
                self.action = ACTION_RADAR
                self.selected_target = None
                mouse_pos = pygame.mouse.get_pos()
                self.handle_motion(mouse_pos)
                self.status = "Наведи курсор, выбери центр сектора 3×3 и нажми «ХОД»."
            return
        if BTN_REBALANCE.collidepoint(pos):
            self.choose_rebalance()
            return
        if BTN_TURN.collidepoint(pos):
            self.start_player_turn()


# ============================ СОХРАНЕНИЯ И ПРИЛОЖЕНИЕ v4.0 ============================
def _pack(value):
    """Безопасное JSON-представление игровых объектов (без pickle)."""
    if isinstance(value, set):
        return {"__type__": "set", "items": [_pack(v) for v in value]}
    if isinstance(value, tuple):
        return {"__type__": "tuple", "items": [_pack(v) for v in value]}
    if isinstance(value, list):
        return [_pack(v) for v in value]
    if isinstance(value, dict):
        return {"__type__": "dict", "items": [[_pack(k), _pack(v)] for k, v in value.items()]}
    if hasattr(value, "__dict__"):
        return {"__type__": value.__class__.__name__,
                "attrs": {k: _pack(v) for k, v in value.__dict__.items()
                          if k not in ("script", "event_queue")}}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _unpack(value):
    if isinstance(value, list):
        return [_unpack(v) for v in value]
    if not isinstance(value, dict) or "__type__" not in value:
        return value
    typ = value["__type__"]
    items = value.get("items", [])
    if typ == "set":
        return set(_unpack(v) for v in items)
    if typ == "tuple":
        return tuple(_unpack(v) for v in items)
    if typ == "dict":
        return {_unpack(k): _unpack(v) for k, v in items}
    classes = {"Plane": Plane, "Fleet": Fleet, "Game": Game, "Zone": Zone,
               "Event": Event, "Missile": Missile, "Explosion": Explosion,
               "MoveAnim": MoveAnim}
    cls = classes.get(typ)
    if cls is None:
        return None
    obj = cls.__new__(cls)
    for key, val in value.get("attrs", {}).items():
        setattr(obj, key, _unpack(val))
    return obj


class App:
    def __init__(self):
        self.game_state = "MENU"
        self.event_queue: list[Event] = []
        self.zones = []
        self.battle: Optional[Game] = None
        self.active_zone: Optional[Zone] = None
        self.battles = 0
        self.wins = 0
        self.pause_open = False
        self.devs_open = False
        self.message = ""
        self.campaign_result = ""
        self.decisive = False
        self.decisive_zone = None
        self.settings_return_state = "MENU"
        self.new_campaign()
        self.game_state = "MENU"
        self.splash_active = True          # заставка при запуске
        self.splash_time = 0               # сколько мс уже идёт заставка

    def new_campaign(self):
        self.zones = [
            make_zone("Северный сектор", (370, 470), 140, OWNER_ENEMY, 3),
            make_zone("Южный сектор", (1030, 440), 140, OWNER_ENEMY, 8),
        ]
        self.battle = None
        self.active_zone = None
        self.battles = self.wins = 0
        self.campaign_result = ""
        self.decisive = False
        self.decisive_zone = None
        self.event_queue = []
        self.pause_open = False
        self.game_state = STATE_MAP
        self.message = ""

    @property
    def paused(self):
        return bool(self.event_queue) or self.pause_open

    def start_battle(self, zone):
        if zone.battled and not self.decisive:
            self.message = "Этот сектор уже захвачен."
            return
        self.active_zone = zone
        self.battle = Game(self.event_queue, zone.name)
        self.game_state = STATE_BATTLE
        self.pause_open = False

    def finish_battle(self):
        if self.battle is None or self.active_zone is None:
            return
        won = self.battle.result == "ПОБЕДА!"
        zone = self.active_zone
        zone.owner = OWNER_PLAYER if won else OWNER_ENEMY
        zone.battled = True
        self.battles += 1
        self.wins += int(won)
        self.battle = None
        self.active_zone = None
        self.game_state = STATE_MAP

        if self.decisive:
            self.campaign_result = "WIN" if won else "LOSS"
            self.decisive = False
            return

        if all(z.battled for z in self.zones):
            player_zones = [z for z in self.zones if z.owner == OWNER_PLAYER]
            enemy_zones = [z for z in self.zones if z.owner == OWNER_ENEMY]
            if len(player_zones) == 2:
                self.campaign_result = "WIN"
            elif len(enemy_zones) == 2:
                self.campaign_result = "LOSS"
            else:
                # Смешанный исход: решающий повторный бой за потерянный сектор.
                self.decisive_zone = enemy_zones[0]
                self.decisive_zone.battled = False
                self.decisive = True
                self.message = "Решающий бой: необходимо отбить оставшийся сектор."

    def save_game(self):
        try:
            if self.battle is not None and self.battle.busy:
                self.message = "Дождитесь завершения анимации хода перед сохранением."
                return False
            data = {
                "version": 4,
                "game_state": self.game_state,
                "zones": [_pack(z) for z in self.zones],
                "battle": _pack(self.battle) if self.battle else None,
                "active_zone": self.zones.index(self.active_zone) if self.active_zone in self.zones else None,
                "battles": self.battles, "wins": self.wins,
                "events": [_pack(e) for e in self.event_queue],
                "campaign_result": self.campaign_result,
                "decisive": self.decisive,
                "decisive_zone": self.zones.index(self.decisive_zone) if self.decisive_zone in self.zones else None,
            }
            os.makedirs(os.path.dirname(SAVE_FILE), exist_ok=True)
            with open(SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.message = "Игра сохранена."
            return True
        except Exception as exc:
            self.message = f"Ошибка сохранения: {exc}"
            return False

    def load_game(self):
        try:
            os.makedirs(os.path.dirname(SAVE_FILE), exist_ok=True)
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") != 4:
                raise ValueError("несовместимая версия сохранения")
            self.zones = [_unpack(z) for z in data["zones"]]
            self.event_queue = [_unpack(e) for e in data.get("events", [])]
            self.game_state = data.get("game_state", STATE_MAP)
            self.battle = _unpack(data["battle"]) if data.get("battle") else None
            if self.battle:
                self.battle.event_queue = self.event_queue
                self.battle.script = None
                self.battle.move_anim = None
            idx = data.get("active_zone")
            self.active_zone = self.zones[idx] if idx is not None else None
            self.battles = int(data.get("battles", 0))
            self.wins = int(data.get("wins", 0))
            self.campaign_result = data.get("campaign_result", "")
            self.decisive = bool(data.get("decisive", False))
            dz = data.get("decisive_zone")
            self.decisive_zone = self.zones[dz] if dz is not None else None
            self.pause_open = False
            self.message = "Сохранение загружено."
            return True
        except Exception as exc:
            self.message = f"Не удалось загрузить: {exc}"
            return False

    # ---------------- ввод ----------------
    def close_event(self):
        if self.event_queue:
            self.event_queue.pop(0)

    def handle_click(self, pos):
        if self.event_queue:
            if BTN_CONTINUE.collidepoint(pos):
                self.close_event()
            return

        if self.devs_open:
            if DEV_CLOSE.collidepoint(pos):
                self.devs_open = False
            return

        if self.game_state == STATE_SETTINGS:
            if SETTINGS_BACK.collidepoint(pos):
                self.game_state = "MENU"
                return
            setting_rows = [
                (pygame.Rect(500, 350, 400, 48), "fullscreen"),
                (pygame.Rect(500, 415, 400, 48), "rotor"),
                (pygame.Rect(500, 480, 400, 48), "newspapers"),
                (pygame.Rect(500, 545, 400, 48), "music"),
            ]
            for rect, key in setting_rows:
                if rect.collidepoint(pos):
                    SETTINGS[key] = not SETTINGS[key]
                    if key == "fullscreen":
                        try:
                            set_fullscreen(SETTINGS["fullscreen"])
                        except Exception:
                            SETTINGS[key] = not SETTINGS[key]
                    elif key == "music":
                        try:
                            if SETTINGS["music"] and MUSIC_PATH:
                                if not pygame.mixer.music.get_busy():
                                    pygame.mixer.music.play(-1)
                                else:
                                    pygame.mixer.music.unpause()
                            else:
                                pygame.mixer.music.pause()
                        except Exception:
                            pass
                    return
            return

        if self.pause_open:
            if PAUSE_CONTINUE.collidepoint(pos):
                self.pause_open = False
            elif PAUSE_SAVE.collidepoint(pos):
                self.save_game()
            elif PAUSE_HOME.collidepoint(pos):
                self.pause_open = False
                self.battle = None
                self.active_zone = None
                self.game_state = "MENU"
            return

        if self.game_state == "MENU":
            if BTN_PLAY.collidepoint(pos):
                try:
                    if os.path.exists(SAVE_FILE):
                        os.remove(SAVE_FILE)
                except OSError:
                    pass
                self.new_campaign()
            elif BTN_LOAD.collidepoint(pos) and os.path.exists(SAVE_FILE):
                self.load_game()
            elif BTN_SETTINGS.collidepoint(pos):
                self.game_state = STATE_SETTINGS
            elif BTN_DEVS.collidepoint(pos):
                self.devs_open = True
            elif BTN_EXIT.collidepoint(pos):
                pygame.event.post(pygame.event.Event(pygame.QUIT))
            return

        if self.game_state == STATE_MAP:
            if BTN_MENU.collidepoint(pos):
                self.pause_open = True
                return
            for zone in self.zones:
                if zone.contains(pos):
                    if zone.battled:
                        self.message = "Этот сектор уже захвачен."
                    elif self.campaign_result:
                        self.message = "Кампания завершена."
                    else:
                        self.start_battle(zone)
                    return
        elif self.battle is not None:
            if BTN_MENU.collidepoint(pos):
                self.pause_open = True
                return
            g = self.battle
            if g.game_over and not g.busy:
                if BTN_BACK.collidepoint(pos):
                    self.finish_battle()
                return
            g.handle_click(pos)

    def handle_key(self, key):
        if self.event_queue and key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.close_event()
        elif self.pause_open and key == pygame.K_ESCAPE:
            self.pause_open = False
        elif self.devs_open and key == pygame.K_ESCAPE:
            self.devs_open = False
        elif self.game_state == STATE_SETTINGS and key == pygame.K_ESCAPE:
            self.game_state = "MENU"

    def update(self, dt_ms):
        if self.paused or self.devs_open:
            return
        if self.game_state == STATE_BATTLE and self.battle is not None:
            self.battle.update(dt_ms)

    def draw(self, surface):
        if self.game_state == "MENU":
            self._draw_main_menu(surface)
        elif self.game_state == STATE_SETTINGS:
            self._draw_settings(surface)
        elif self.game_state == STATE_MAP:
            self._draw_map(surface)
            button(surface, BTN_MENU, "МЕНЮ", True, OCHRE)
        elif self.battle is not None:
            self.battle.draw(surface)

        if self.event_queue:
            draw_event_popup(surface, self.event_queue[0], len(self.event_queue), pygame.time.get_ticks())
        if self.devs_open:
            self._draw_developers(surface)
        if self.pause_open:
            self._draw_pause(surface)

    def _draw_main_menu(self, surface):
        surface.blit(MAP_BG, (0, 0))
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((30, 22, 12, 100))
        surface.blit(veil, (0, 0))
        box = pygame.Rect(450, 195, 500, 500)
        rounded(surface, box, PANEL, 18, INK, 4)
        draw_text_center(surface, "SolomonAir: AirFight", W//2, 250, TITLE, INK)
        draw_text_center(surface, "Воздушная кампания • v5.1", W//2, 292, FONT, MUTED)
        button(surface, BTN_PLAY, "ИГРАТЬ", True, GREEN_INK)
        has_save = os.path.exists(SAVE_FILE)
        button(surface, BTN_LOAD, "ПРОДОЛЖИТЬ", has_save, BLUE_INK)
        button(surface, BTN_SETTINGS, "НАСТРОЙКИ", True, OCHRE)
        button(surface, BTN_DEVS, "РАЗРАБОТЧИКИ", True, OCHRE)
        button(surface, BTN_EXIT, "ВЫХОД", True, RED_INK)
        if self.message:
            draw_text_center(surface, self.message, W//2, 680, SMALL, BLUE_INK)

    def _draw_settings(self, surface):
        surface.blit(MAP_BG, (0, 0))
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((25, 18, 10, 115))
        surface.blit(veil, (0, 0))
        box = pygame.Rect(430, 235, 540, 525)
        rounded(surface, box, PANEL, 18, INK, 4)
        draw_text_center(surface, "НАСТРОЙКИ", W // 2, 270, TITLE, INK)
        rows = [
            ("Полноэкранный режим", "fullscreen"),
            ("Анимация вертолёта (винт)", "rotor"),
            ("Показывать газеты", "newspapers"),
            ("Музыка", "music"),
        ]
        for i, (label, key) in enumerate(rows):
            rect = pygame.Rect(500, 350 + i * 65, 400, 48)
            active = SETTINGS[key]
            rounded(surface, rect, GREEN_INK if active else PANEL_OFF, 9, INK, 2)
            draw_text(surface, label, rect.x + 18, rect.y + 12, FONT,
                      (250, 246, 230) if active else INK)
            draw_text(surface, "ВКЛ" if active else "ВЫКЛ", rect.right - 75, rect.y + 12,
                      BOLD, (250, 246, 230) if active else MUTED)
        button(surface, SETTINGS_BACK, "НАЗАД", True, OCHRE)

    def _draw_pause(self, surface):
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((20, 14, 8, 175))
        surface.blit(veil, (0, 0))
        rounded(surface, PAUSE_BOX, PANEL, 16, INK, 4)
        draw_text_center(surface, "ШТАБ / ПАУЗА", W//2, 275, TITLE, INK)
        button(surface, PAUSE_CONTINUE, "ПРОДОЛЖИТЬ", True, GREEN_INK)
        button(surface, PAUSE_SAVE, "СОХРАНИТЬ", True, BLUE_INK)
        button(surface, PAUSE_HOME, "ВЫЙТИ В ГЛАВНОЕ МЕНЮ", True, RED_INK)
        if self.message:
            draw_text_center(surface, self.message, W//2, 555, SMALL, BLUE_INK)

    def _draw_developers(self, surface):
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((20, 14, 8, 150))
        surface.blit(veil, (0, 0))
        box = pygame.Rect(480, 300, 440, 270)
        rounded(surface, box, PANEL, 14, INK, 3)
        draw_text_center(surface, "РАЗРАБОТЧИКИ", W//2, 335, TITLE, INK)
        draw_text_center(surface, "Студия SolomonAir", W//2, 405, BOLD, BLUE_INK)
        draw_text_center(surface, "t.me/solomon_air", W//2, 445, FONT, OCHRE)
        button(surface, DEV_CLOSE, "ЗАКРЫТЬ", True, INK)

    def _draw_map(self, surface):
        surface.blit(MAP_BG, (0, 0))
        mouse = pygame.mouse.get_pos()
        for zone in self.zones:
            hover = (not self.paused) and zone.contains(mouse) and not zone.battled
            draw_zone(surface, zone, hover)
            if zone.battled:
                draw_text_center(surface, "ЗАХВАЧЕН", zone.center[0], zone.center[1] + 58, SMALL, GREEN_INK)
        if self.campaign_result == "WIN":
            draw_stamp(surface, "КАМПАНИЯ ВЫИГРАНА", (700, 170), GREEN_INK)
        elif self.campaign_result == "LOSS":
            draw_stamp(surface, "КАМПАНИЯ ПРОИГРАНА", (700, 170), RED_INK)
        elif self.decisive:
            draw_stamp(surface, "РЕШАЮЩИЙ БОЙ", (700, 170), OCHRE)
        draw_text_center(surface, f"Сражений: {self.battles}    Побед: {self.wins}    "
                                  f"Поражений: {self.battles - self.wins}", W // 2, 792, FONT, INK)
        pygame.draw.circle(surface, BLUE_INK, (70, 802), 7)
        draw_text(surface, "под нашим контролем", 84, 793, SMALL, INK)
        pygame.draw.circle(surface, RED_INK, (270, 802), 7)
        draw_text(surface, "под контролем врага", 284, 793, SMALL, INK)
        if self.message:
            draw_text_center(surface, self.message, W//2, 745, SMALL, RED_INK)


def main():
    app = App()
    dt = 0
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEMOTION:
                if app.battle is not None and app.game_state == STATE_BATTLE:
                    app.battle.handle_motion(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                app.handle_click(event.pos)
            elif event.type == pygame.KEYDOWN:
                app.handle_key(event.key)
        app.update(min(dt, MAX_DT_MS))
        app.draw(SCREEN)
        pygame.display.flip()
        dt = CLOCK.tick(FPS)
    try:
        pygame.mixer.quit()
    except Exception:
        pass
    pygame.quit()
    sys.exit()



# ============================ v5.0: ВЕРФЬ, ОПЕРАЦИИ, АЧИВКИ, КОНСОЛЬ ============================
ACHIEVEMENTS_FILE = _user_data_file("achievements.json")
SHIP_COSTS = {"bomber": 15, "strategic": 20, "fighter": 25, "helicopter": 30}
SHIP_LENGTHS = {"bomber": 3, "strategic": 4, "fighter": 1, "helicopter": 1}
SHIP_LIMITS = {"bomber": 3, "strategic": 2, "fighter": 1, "helicopter": 1}
SHIP_LABELS = {"bomber": "Бомбардировщик", "strategic": "Стратег", "fighter": "Истребитель", "helicopter": "Вертолёт"}
KIND_LABEL.update({"fighter": "Истребитель"})
KIND_COLOR["fighter"] = (112, 92, 142)
HULLS["fighter"] = HULLS["bomber"]
ENGINES["fighter"] = [(0.54, 0.52)]
ACHIEVEMENT_INFO = {
    "surgeon": "Хирург", "one_plane": "Приказ выполнен, но какой ценой?",
    "gravity": "Гравитация работает!", "gravity_2": "Гравитация все таки работает",
    "clean": "Чисто", "gpt_killer": "Слава роботам"}
BTN_SHIPYARD = pygame.Rect(1040, 455, 140, 40)
BTN_OPS = pygame.Rect(1190, 455, 140, 40)
OVERLAY_BOX = pygame.Rect(390, 190, 620, 470)
OVERLAY_CLOSE = pygame.Rect(610, 595, 180, 42)
CONSOLE_BOX = pygame.Rect(300, 285, 800, 270)
CONSOLE_INPUT = pygame.Rect(350, 405, 700, 42)
ACH_BTN = pygame.Rect(560, 600, 280, 42)


def _load_achievements():
    try:
        os.makedirs(os.path.dirname(ACHIEVEMENTS_FILE), exist_ok=True)
        with open(ACHIEVEMENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: bool(data.get(k, False)) for k in ACHIEVEMENT_INFO}
    except FileNotFoundError:
        return {k: False for k in ACHIEVEMENT_INFO}
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        return {k: False for k in ACHIEVEMENT_INFO}


def _save_achievements(data):
    try:
        os.makedirs(os.path.dirname(ACHIEVEMENTS_FILE), exist_ok=True)
        with open(ACHIEVEMENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError as exc:
        # Не прерываем игру, если каталог пользователя недоступен.
        print(f"Не удалось сохранить достижения: {exc}")
        return False

if not os.path.exists(ACHIEVEMENTS_FILE):
    _save_achievements({k: False for k in ACHIEVEMENT_INFO})

_old_game_init = Game.__init__
def _v5_game_init(self, *a, **kw):
    _old_game_init(self, *a, **kw)
    self.ship_queue = None
    self.ai_ship_queue = None
    # Достижения, для которых уже показывали всплывающее окно в этом бою.
    self._v5_shown_achievements = set()
    self.shipyard_open = False
    self.operations_open = False
    self.operation_pending = None
    self.operation_due = None
    self.operation_hide = 0
    self.operation_hidden_uid = None
    self.ai_known_zones = []
    self.god_mode = False
    self.ai_debug = []
    self._v5_turn_seen = self.turn
    self._v5_first_shot = True
    self._v5_initial_ai_planes = len(self.ai.alive())
    self._v5_initial_player_planes = len(self.player.alive())
    self._v5_surgeon = False
Game.__init__ = _v5_game_init

# Movement remembers recently attacked/scanned cells; AI prefers to move away.
_old_move_all = Fleet.move_all
def _v5_move_all(self):
    zones = getattr(self, "_avoid_zones", [])
    if not zones:
        return _old_move_all(self)
    moves = {}
    planes = self.alive()[:]
    random.shuffle(planes)
    for p in planes:
        old = (p.x, p.y); occupied = self.occupied(exclude=p.uid)
        offsets = [(dx,dy) for dx in (-1,0,1) for dy in (-1,0,1) if (dx,dy)!=(0,0)]
        random.shuffle(offsets)
        candidates=[]
        for dx,dy in offsets:
            nx,ny=p.x+dx,p.y+dy
            cells=[(nx,ny+i) if p.vertical else (nx+i,ny) for i in range(p.length)]
            if all(0<=cx<GRID_SIZE and 0<=cy<GRID_SIZE for cx,cy in cells) and not occupied.intersection(cells):
                risk=sum(1 for zone in zones for c in cells if c in zone)
                candidates.append((risk,random.random(),nx,ny))
        if candidates:
            _,_,p.x,p.y=min(candidates)
        moves[p.uid]=(old,(p.x,p.y))
    return moves
Fleet.move_all = _v5_move_all

_old_turn_script = Game._turn_script
def _v5_turn_script(self, action, target):
    # Radar and shots become danger zones for the enemy on the next movement phase.
    self.ai._avoid_zones = [z for z,t in self.ai_known_zones if t >= self.turn]
    if action == ACTION_RADAR and self.radar_scan:
        self.ai_known_zones.append((set(self.radar_scan), self.turn + 2))
    elif action in (ACTION_SHOT, ACTION_PVO) and target is not None:
        x, y = target
        self.ai_known_zones.append(({(xx, yy) for xx in range(max(0,x-1), min(9,x+2)) for yy in range(max(0,y-1), min(9,y+2))}, self.turn + 2))
    yield from _old_turn_script(self, action, target)
Game._turn_script = _v5_turn_script

# Queue countdown and AI construction after completed rounds.
_old_update = Game.update
def _v5_update(self, dt_ms):
    old_turn = self.turn
    _old_update(self, dt_ms)
    if self.turn != old_turn:
        self._v5_tick_shipyards()
        self._v5_tick_operations()
        self._v5_ai_build()
    self.ai_known_zones = [(z,t) for z,t in self.ai_known_zones if t >= self.turn]
    if self.god_mode:
        self.ai_debug = self.ai_debug[-5:]
Game.update = _v5_update

def _v5_spawn_plane(self, fleet, kind):
    """Создаёт самолёт на свободных клетках; возвращает True при успехе."""
    if kind not in SHIP_LENGTHS:
        return False
    length = SHIP_LENGTHS[kind]
    occupied = fleet.occupied()
    for _ in range(500):
        vertical = bool(random.getrandbits(1)) if length > 1 else False
        x = random.randrange(GRID_SIZE - (0 if vertical else length - 1))
        y = random.randrange(GRID_SIZE - (length - 1 if vertical else 0))
        cells = [(x, y+i) if vertical else (x+i, y) for i in range(length)]
        if not occupied.intersection(cells):
            names = PILOT_NAMES.get(kind, [])
            used = sum(1 for q in fleet.planes if q.kind == kind)
            pilot = names[used] if used < len(names) else (FIGHTER_CALLSIGN if kind == 'fighter' else f"Экипаж-{used+1}")
            plane = Plane(fleet._next_id, kind, length, x, y, vertical, pilot_name=pilot)
            fleet._next_id += 1
            fleet.planes.append(plane)
            if kind == 'fighter' and fleet.marker is None and not fleet.marker_transit:
                fleet.marker = plane.uid
            return True
    return False

def _free_spawn(fleet, kind):
    # Совместимость с существующим кодом верфи.
    return _v5_spawn_plane(None, fleet, kind)

def _v5_start_build(self, fleet, kind, ai=False):
    if (self.ship_queue if not ai else self.ai_ship_queue) is not None:
        return False
    alive_total = sum(1 for p in fleet.planes if p.kind == kind and p.alive)
    if alive_total >= SHIP_LIMITS[kind] or fleet.hp < SHIP_COSTS[kind]:
        return False
    fleet.hp -= SHIP_COSTS[kind]
    queue = {"kind": kind, "turns": 3}
    if ai:
        self.ai_ship_queue = queue
        self.add_log("Разведка: активность на заводе врага.")
    else:
        self.ship_queue = queue
        self.add_log(f"Верфь: заказан {SHIP_LABELS[kind].lower()} — прибытие через 3 хода.")
    return True

def _v5_tick_shipyards(self):
    for attr, fleet, side in (("ship_queue", self.player, "player"), ("ai_ship_queue", self.ai, "ai")):
        q = getattr(self, attr)
        if not q: continue
        q["turns"] -= 1
        if q["turns"] <= 0:
            kind = q["kind"]
            if _free_spawn(fleet, kind):
                self.add_log(("Наш" if side == "player" else "Вражеский") + f" {SHIP_LABELS[kind].lower()} сошёл с верфи.")
            else:
                fleet.hp = min(MAX_HP, fleet.hp + SHIP_COSTS[kind])
                self.add_log("Верфь: нет свободной клетки, заказ отменён.")
            setattr(self, attr, None)

Game._v5_tick_shipyards = _v5_tick_shipyards
Game._v5_spawn_plane = _v5_spawn_plane

def _v5_ai_build(self):
    if self.ai_ship_queue is not None: return
    candidates = [k for k in SHIP_COSTS if self.ai.hp >= SHIP_COSTS[k] and
                  sum(1 for p in self.ai.alive() if p.kind == k) < SHIP_LIMITS[k]]
    if candidates and random.random() < 0.22:
        _v5_start_build(self, self.ai, random.choice(candidates), True)

# Как называется самолёт-«носитель» в тексте ивента «Тень над целью»
SEARCH_CARRIER_NAMES = {"bomber": "бомбардировщик", "strategic": "стратегический бомбардировщик"}


def _v5_tick_operations(self):
    if self.operation_pending and self.turn >= self.operation_due:
        op = self.operation_pending
        self.operation_pending = None
        if op == "trade":
            for fleet in (self.player, self.ai):
                for p in fleet.alive():
                    if p.kind == "helicopter": p.alive = False
            self._v5_award("gravity_2")
            self.emit(make_event("ops_trade", zone_name=zone_instrumental(self.zone_name)))
            self.add_log("Спецоперация «Размен»: оба вертолёта уничтожены.")
        elif op == "search":
            if self.operation_hidden_uid is not None:
                hp = self.player.get(self.operation_hidden_uid)
                # get() excludes dead units; restore the hidden helicopter by uid.
                hp = next((p for p in self.player.planes if p.uid == self.operation_hidden_uid), None)
                if hp: hp.alive = True
                self.operation_hidden_uid = None
            enemy_heli = any(p.alive and p.kind == "helicopter" for p in self.ai.planes)
            # Истребитель «сидит» на бомбардировщике или стратеге; если таких нет — берём бомбардировщик
            carriers = [p for p in self.ai.alive() if p.kind in SEARCH_CARRIER_NAMES]
            carrier_kind = random.choice(carriers).kind if carriers else "bomber"
            self.emit(make_event("ops_search", plane_type=SEARCH_CARRIER_NAMES[carrier_kind]))
            self.add_log("Спецоперация «Поиск истребителя» завершена.")

Game._v5_tick_operations = _v5_tick_operations
Game._v5_ai_build = _v5_ai_build

def _v5_can_operation(self, op):
    heli = any(p.alive and p.kind == 'helicopter' for p in self.player.planes)
    in_transit = self.player.marker_transit or (self.ship_queue and self.ship_queue['kind'] == 'helicopter')
    if not heli or in_transit or self.operation_pending: return False
    if op == 'trade': return any(p.alive and p.kind == 'helicopter' for p in self.ai.planes)
    return True

def _v5_award(self, key):
    if key not in ACHIEVEMENT_INFO:
        return
    shown = getattr(self, "_v5_shown_achievements", None)
    if shown is None:
        shown = set()
        self._v5_shown_achievements = shown
    # Отмечаем сразу, чтобы повторные проверки в том же ходе не дублировали popup.
    if key in shown:
        return
    app_data = _load_achievements()
    if app_data.get(key, False):
        shown.add(key)
        return
    shown.add(key)
    app_data[key] = True
    if _save_achievements(app_data):
        self.achievement_popup = (ACHIEVEMENT_INFO[key], pygame.time.get_ticks() + 3000)
    else:
        # Даже если диск недоступен, не спамим окном в текущем бою.
        self.achievement_popup = (ACHIEVEMENT_INFO[key], pygame.time.get_ticks() + 3000)

Game._v5_award = _v5_award

def _v5_resolve(self, m):
    before = {p.uid:p.kind for p in m.defender.alive()}
    _old_resolve = _resolve_missile_original
    _old_resolve(self, m)
    if not m.ai_side:
        x,y=m.cell
        killed = [p for p in self.ai.planes if p.uid in before and not p.alive]
        for p in killed:
            if p.kind == 'strategic' and self._v5_first_shot: self._v5_award('surgeon')
            if p.kind == 'helicopter':
                self._v5_award('gravity')
                self.emit(make_event("heli_down"))      # газета с иллюстрацией «gravity»
            if p.pilot_name == 'GPT': self._v5_award('gpt_killer')
        if m.cell and self._v5_first_shot: self._v5_first_shot = False
    else:
        if any(p.kind == 'helicopter' and not p.alive for p in self.player.planes): self._v5_award('gravity_2')
    if not any(p.alive for p in self.ai.planes): self._v5_award('clean')

_resolve_missile_original = Game._resolve_missile
Game._resolve_missile = _v5_resolve

_old_check_end = Game.check_end
def _v5_check_end(self):
    _old_check_end(self)
    if self.game_over and self.result == 'ПОБЕДА!' and len(self.player.alive()) == 1:
        self._v5_award('one_plane')
Game.check_end = _v5_check_end

_old_panel = Game._draw_panel
def _v5_panel(self, surface):
    _old_panel(self, surface)
    button(surface, BTN_SHIPYARD, "ВЕРФЬ", not self.busy and not self.game_over and self.ship_queue is None, OCHRE)
    button(surface, BTN_OPS, "ОПЕРАЦИИ", not self.busy and not self.game_over, GREEN_INK)
    if self.ship_queue:
        draw_text(surface, f"СТРОИТСЯ: {SHIP_LABELS[self.ship_queue['kind']]}", 1040, 500, SMALL, RED_INK)
    if self.god_mode:
        draw_text(surface, "SOLOMON: GOD MODE", 1040, 495, SMALL, RED_INK)
Game._draw_panel = _v5_panel

_old_game_draw = Game.draw
def _v5_draw(self, surface):
    _old_game_draw(self, surface)
    draw_text(surface, f"Верфь: {SHIP_LABELS[self.ship_queue['kind']]} — {self.ship_queue['turns']}" if self.ship_queue else "Верфь: свободна", LEFT_X, 128, SMALL, BLUE_INK)
    if self.god_mode:
        for plane in self.ai.alive():
            spr=get_sprite(plane.kind,plane.length,plane.vertical)
            surface.blit(spr,(RIGHT_X+plane.x*CELL,BOARD_Y+plane.y*CELL))
    if self.shipyard_open or self.operations_open:
        veil=pygame.Surface((W,H),pygame.SRCALPHA); veil.fill((20,14,8,170)); surface.blit(veil,(0,0))
        rounded(surface,OVERLAY_BOX,PANEL,16,INK,3)
        title="ВЕРФЬ" if self.shipyard_open else "СПЕЦОПЕРАЦИИ"
        draw_text_center(surface,title,W//2,215,TITLE,INK)
        if self.shipyard_open:
            for i,k in enumerate(SHIP_COSTS):
                r=pygame.Rect(450,280+i*62,500,48)
                can=self.ship_queue is None and self.player.hp>=SHIP_COSTS[k] and sum(p.alive and p.kind==k for p in self.player.planes)<SHIP_LIMITS[k] and not self.busy
                button(surface,r,f"{SHIP_LABELS[k]} — {SHIP_COSTS[k]} HP",can,BLUE_INK)
        else:
            for i,(op,label) in enumerate((("search","ПОИСК ИСТРЕБИТЕЛЯ"),("trade","РАЗМЕН"))):
                r=pygame.Rect(450,310+i*85,500,55)
                button(surface,r,label,_v5_can_operation(self,op) and not self.busy,GREEN_INK)
        button(surface,OVERLAY_CLOSE,"ЗАКРЫТЬ",True,RED_INK)
    if getattr(self,'achievement_popup',None):
        label,until=self.achievement_popup
        if pygame.time.get_ticks()<until:
            rounded(surface,pygame.Rect(430,65,540,55),PANEL,10,OCHRE,3)
            draw_text_center(surface,"ДОСТИЖЕНИЕ: "+label,W//2,80,BOLD,GREEN_INK)
        else: self.achievement_popup=None
Game.draw = _v5_draw

_old_game_click = Game.handle_click
def _v5_game_click(self,pos):
    if self.shipyard_open:
        if OVERLAY_CLOSE.collidepoint(pos): self.shipyard_open=False; return
        for i,k in enumerate(SHIP_COSTS):
            r=pygame.Rect(450,280+i*62,500,48)
            if r.collidepoint(pos):
                if self.ship_queue is None and self.player.hp>=SHIP_COSTS[k] and sum(p.alive and p.kind==k for p in self.player.planes)<SHIP_LIMITS[k]: _v5_start_build(self,self.player,k)
                self.shipyard_open=False; return
        return
    if self.operations_open:
        if OVERLAY_CLOSE.collidepoint(pos): self.operations_open=False; return
        for i,op in enumerate(('search','trade')):
            if pygame.Rect(450,310+i*85,500,55).collidepoint(pos) and _v5_can_operation(self,op):
                self.operation_pending=op; self.operation_due=self.turn+1
                if op=='search':
                    heli=next((p for p in self.player.alive() if p.kind=='helicopter'),None)
                    if heli:
                        heli.alive=False; self.operation_hidden_uid=heli.uid
                self.operations_open=False
                self.add_log('Спецоперация назначена на следующий ход.')
                return
        return
    if BTN_SHIPYARD.collidepoint(pos) and not self.busy and not self.game_over:
        self.shipyard_open=True; return
    if BTN_OPS.collidepoint(pos) and not self.busy and not self.game_over:
        self.operations_open=True; return
    _old_game_click(self,pos)
Game.handle_click = _v5_game_click

# App overlays and developer console.
_old_app_init=App.__init__
def _v5_app_init(self,*a,**kw):
    _old_app_init(self,*a,**kw)
    self.achievements_open=False; self.console_open=False; self.console_text=''; self.console_log=[]
App.__init__=_v5_app_init

_old_app_click=App.handle_click
def _v5_app_click(self,pos):
    if self.achievements_open:
        if OVERLAY_CLOSE.collidepoint(pos): self.achievements_open=False
        return
    if self.console_open: return
    if self.game_state=='MENU' and ACH_BTN.collidepoint(pos): self.achievements_open=True; return
    _old_app_click(self,pos)
App.handle_click=_v5_app_click

_old_app_key=App.handle_key
def _v5_app_key(self,key):
    if self.console_open:
        if key==pygame.K_ESCAPE: self.console_open=False; return
        if key in (pygame.K_RETURN,pygame.K_KP_ENTER): self._run_console(); return
        if key==pygame.K_BACKSPACE: self.console_text=self.console_text[:-1]; return
        return
    if key in (pygame.K_BACKQUOTE, getattr(pygame,'K_WORLD_1',-999)):
        if self.game_state==STATE_BATTLE: self.console_open=True; self.console_text=''
        return
    _old_app_key(self,key)
App.handle_key=_v5_app_key

CONSOLE_EVENT_COMMANDS = {
    1: ("bomber_lost", "Потеря бомбардировщика"),
    2: ("strategic_lost", "Потеря стратегического бомбардировщика"),
    3: ("fighter_saved", "Истребитель прикрыл самолёт"),
    4: ("pvo", "Работа ПВО"),
    5: ("defeat", "Поражение"),
    6: ("victory", "Победа"),
    7: ("ops_search", "Спецоперация «Тень над целью»"),
    8: ("ops_trade", "Спецоперация «Размен»"),
    9: ("heli_down", "Сбит вражеский вертолёт"),
}

def _console_event(self, g, number):
    if number in (1, 2, 3, 4, 5, 6):
        key, _label = CONSOLE_EVENT_COMMANDS[number]
        g.emit(make_event(key, "GPT"))
    elif number == 7:
        g.emit(make_event("ops_search", plane_type=random.choice(list(SEARCH_CARRIER_NAMES.values()))))
    elif number == 8:
        g.emit(make_event("ops_trade", zone_name=zone_instrumental(g.zone_name)))
    elif number == 9:
        g.emit(make_event("heli_down"))

def _run_console(self):
    cmd = self.console_text.strip()
    self.console_text = ""
    g = self.battle
    if not g:
        return
    lower = cmd.lower()
    if lower == "help":
        self.console_log.extend([
            "solomon — God Mode; win — победа; hp — восстановить HP",
            "event_1..event_9 — газетные события по списку ниже",
        ])
    elif lower == "solomon":
        g.god_mode = not g.god_mode
        self.console_log.append("God Mode: " + str(g.god_mode))
    elif lower == "win":
        g.ai.hp = 0; g.game_over = True; g.result = "ПОБЕДА!"; g.emit(make_event("victory"))
    elif lower == "hp":
        g.player.hp = MAX_HP; g.player.hp_shown = MAX_HP
        self.console_log.append("HP восстановлены.")
    elif lower.startswith("event_"):
        try:
            n = int(lower.split("_", 1)[1])
            if n in CONSOLE_EVENT_COMMANDS:
                _console_event(self, g, n)
                self.console_log.append(f"Вызвано событие event_{n}: {CONSOLE_EVENT_COMMANDS[n][1]}")
            else:
                self.console_log.append("Номер события должен быть от 1 до 9. Введите help.")
        except ValueError:
            self.console_log.append("Формат: event_1 ... event_9. Введите help.")
    else:
        self.console_log.append("Неизвестная команда. Подсказка: help (solomon, win, hp, event_1..event_9).")
    self.console_log = self.console_log[-8:]
App._run_console = _run_console

_old_menu=App._draw_main_menu
def _v5_menu(self,surface):
    _old_menu(self,surface)
    button(surface,ACH_BTN,'ДОСТИЖЕНИЯ',True,OCHRE)
App._draw_main_menu=_v5_menu

_old_app_draw=App.draw
def _v5_app_draw(self,surface):
    _old_app_draw(self,surface)
    if self.achievements_open:
        veil=pygame.Surface((W,H),pygame.SRCALPHA); veil.fill((20,14,8,175)); surface.blit(veil,(0,0))
        rounded(surface,OVERLAY_BOX,PANEL,16,INK,3)
        draw_text_center(surface,'ДОСТИЖЕНИЯ',W//2,215,TITLE,INK)
        data=_load_achievements()
        for i,(k,label) in enumerate(ACHIEVEMENT_INFO.items()):
            draw_text(surface,('★ ' if data[k] else '☆ ')+label,455,275+i*43,FONT,GREEN_INK if data[k] else MUTED)
        button(surface,OVERLAY_CLOSE,'ЗАКРЫТЬ',True,RED_INK)
    if self.console_open:
        veil=pygame.Surface((W,H),pygame.SRCALPHA); veil.fill((0,0,0,150)); surface.blit(veil,(0,0))
        rounded(surface,CONSOLE_BOX,PANEL,14,INK,3)
        draw_text_center(surface,'КОНСОЛЬ РАЗРАБОТЧИКА',W//2,300,TITLE,INK)
        rounded(surface,CONSOLE_INPUT,FIELD,6,BLUE_INK,2)
        draw_text(surface,self.console_text+'▌',CONSOLE_INPUT.x+12,CONSOLE_INPUT.y+10,FONT,INK)
        draw_text(surface,'Команды: help, solomon, win, hp',350,475,SMALL,MUTED)
        draw_text(surface,'event_1 бомбер • 2 стратег • 3 прикрытие • 4 ПВО',350,492,SMALL,MUTED)
        draw_text(surface,'event_5 поражение • 6 победа • 7 Тень • 8 Размен • 9 Вертолёт',350,509,SMALL,MUTED)
        draw_text(surface,'Enter — выполнить • Esc — закрыть',350,526,SMALL,MUTED)
        for i,line in enumerate(self.console_log[-2:]): draw_text(surface,line,350,355+i*20,SMALL,RED_INK)
App.draw=_v5_app_draw


# ============================ ЗАСТАВКА (SPLASH SCREEN) ============================
SPLASH_HOLD_MS = 3000               # сколько логотип держится на чёрном экране
SPLASH_FADE_IN_MS = 600             # плавное появление логотипа
SPLASH_FADE_OUT_MS = 800            # плавное исчезновение (за ним проступает меню)
SPLASH_LOGO_FILE = "logo.png"       # необязательный файл логотипа рядом с игрой
SPLASH_LOGO_MAX = (640, 320)        # максимальный размер логотипа из файла
SPLASH_BG = (0, 0, 0)
SPLASH_TEXT_COLOR = (232, 220, 196)
SPLASH_LINE_COLOR = (160, 130, 84)
SPLASH_TITLE = "SolomonAir"
SPLASH_SUBTITLE = "В О З Д У Ш Н А Я   К А М П А Н И Я"
SPLASH_FONT_SIZE = 120
SPLASH_PLAQUE_TEXT = "SolomonAir • Open Source (MIT License)"


def _build_splash_logo() -> pygame.Surface:
    """logo.png, если он лежит рядом с игрой; иначе — текстовый логотип «SolomonAir» с засечками."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), SPLASH_LOGO_FILE)
    try:
        img = pygame.image.load(path).convert_alpha()
        k = min(SPLASH_LOGO_MAX[0] / img.get_width(), SPLASH_LOGO_MAX[1] / img.get_height(), 1.0)
        if k < 1.0:
            img = pygame.transform.smoothscale(img, (max(1, int(img.get_width() * k)),
                                                     max(1, int(img.get_height() * k))))
        return img
    except (pygame.error, FileNotFoundError, OSError):
        pass
    title = make_font(SPLASH_FONT_SIZE, bold=True).render(SPLASH_TITLE, True, SPLASH_TEXT_COLOR)
    sub = make_font(22).render(SPLASH_SUBTITLE, True, SPLASH_LINE_COLOR)
    width = max(title.get_width(), sub.get_width()) + 80
    logo = pygame.Surface((width, title.get_height() + sub.get_height() + 50), pygame.SRCALPHA)
    logo.blit(title, title.get_rect(midtop=(width // 2, 0)))
    line_y = title.get_height() + 10
    pygame.draw.line(logo, SPLASH_LINE_COLOR, (40, line_y), (width - 40, line_y), 2)
    logo.blit(sub, sub.get_rect(midtop=(width // 2, line_y + 14)))
    return logo


SPLASH_LOGO = _build_splash_logo()
SPLASH_VEIL = pygame.Surface((W, H))
SPLASH_VEIL.fill(SPLASH_BG)


def _splash_skip(self):
    """Клик/клавиша: не ждём конец паузы, сразу начинаем плавное исчезновение."""
    if self.splash_active and self.splash_time < SPLASH_HOLD_MS:
        self.splash_time = SPLASH_HOLD_MS


def _splash_update(self, dt_ms):
    self.splash_time += dt_ms
    if self.splash_time >= SPLASH_HOLD_MS + SPLASH_FADE_OUT_MS:
        self.splash_active = False


def _splash_draw(self, surface):
    """Фаза 1: чёрный экран с логотипом. Фаза 2: логотип и чёрный фон тают, под ними — меню."""
    t = self.splash_time
    if t < SPLASH_HOLD_MS:
        surface.fill(SPLASH_BG)
        alpha = min(1.0, t / SPLASH_FADE_IN_MS)
    else:
        _prev_app_draw(self, surface)                      # меню проступает из-под чёрного
        alpha = max(0.0, 1.0 - (t - SPLASH_HOLD_MS) / SPLASH_FADE_OUT_MS)
        SPLASH_VEIL.set_alpha(int(255 * alpha))
        surface.blit(SPLASH_VEIL, (0, 0))
    SPLASH_LOGO.set_alpha(int(255 * alpha))
    surface.blit(SPLASH_LOGO, SPLASH_LOGO.get_rect(center=(W // 2, H // 2)))


_prev_app_draw = App.draw
_prev_app_update = App.update
_prev_app_click = App.handle_click
_prev_app_key = App.handle_key


def _app_draw_with_splash(self, surface):
    if self.splash_active:
        _splash_draw(self, surface)
    else:
        _prev_app_draw(self, surface)


def _app_update_with_splash(self, dt_ms):
    if self.splash_active:
        _splash_update(self, dt_ms)
        return
    _prev_app_update(self, dt_ms)


def _app_click_with_splash(self, pos):
    if self.splash_active:                                  # во время заставки меню не кликается
        _splash_skip(self)
        return
    _prev_app_click(self, pos)


def _app_key_with_splash(self, key):
    if self.splash_active:
        _splash_skip(self)
        return
    _prev_app_key(self, key)


App.draw = _app_draw_with_splash
App.update = _app_update_with_splash
App.handle_click = _app_click_with_splash
App.handle_key = _app_key_with_splash

# Плашка в главном меню
_prev_menu = App._draw_main_menu


def _menu_with_plaque(self, surface):
    _prev_menu(self, surface)
    label = SMALL.render(SPLASH_PLAQUE_TEXT, True, MUTED)
    plaque = label.get_rect(center=(W // 2, H - 70)).inflate(36, 16)
    rounded(surface, plaque, PANEL, 10, OCHRE, 2)
    surface.blit(label, label.get_rect(center=plaque.center))


App._draw_main_menu = _menu_with_plaque


_old_main=main
def main():
    app=App(); dt=0; running=True
    while running:
        for event in pygame.event.get():
            if event.type==pygame.QUIT: running=False
            elif event.type==pygame.MOUSEMOTION:
                if app.battle is not None and app.game_state==STATE_BATTLE: app.battle.handle_motion(event.pos)
            elif event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
                if app.splash_active: _splash_skip(app)       # заставка: клик лишь пропускает ожидание
                else: app.handle_click(event.pos)
            elif event.type==pygame.KEYDOWN:
                if app.splash_active: _splash_skip(app)
                elif app.console_open and event.unicode and event.unicode.isprintable() and event.key not in (pygame.K_RETURN,pygame.K_BACKSPACE):
                    app.console_text += event.unicode
                else: app.handle_key(event.key)
        app.update(min(dt,MAX_DT_MS)); app.draw(SCREEN); pygame.display.flip(); dt=CLOCK.tick(FPS)
    try: pygame.mixer.quit()
    except Exception: pass
    pygame.quit(); sys.exit()

if __name__ == "__main__":
    main()
