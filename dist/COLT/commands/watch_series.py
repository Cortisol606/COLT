"""
Пример команды COLT: открыть сериал в браузере.

Как использовать:
1. Замени SERIES_URL на прямую ссылку на твой сериал/сервис.
2. При желании — скопируй этот файл под новым именем и сделай
   отдельную команду для каждого сериала (см. commands/_template.py).
"""

NAME = "Смотреть сериал"
ALIASES = ["сериал", "watch", "series", "смотреть"]

SERIES_URL = "https://www.supernatural-spn.com/seasons/6-sezon/"  # <-- замени на нужную ссылку


def run():
    import webbrowser
    webbrowser.open(SERIES_URL)