from __future__ import annotations

import curses

from scripts.select_wallet_for_analysis.rows import SORT_CHOICES, format_row, sort_rows


def pick_row_curses(stdscr, rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        raise ValueError("no wallets found")
    curses.curs_set(0)
    stdscr.keypad(True)
    sort_key, reverse, selected, top = "net", True, 0, 0
    sorted_rows = sort_rows(rows, sort_key, reverse)
    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        usable_height = max(1, height - 2)
        top = min(top, max(0, len(sorted_rows) - usable_height))
        selected = max(0, min(selected, len(sorted_rows) - 1))
        if selected < top:
            top = selected
        elif selected >= top + usable_height:
            top = selected - usable_height + 1
        stdscr.addstr(0, 0, "Up/Down move | Enter select | sort: n/h/m/d/v/t/w | q quit", curses.A_BOLD)
        for screen_row, index in enumerate(
            range(top, min(top + usable_height, len(sorted_rows))), start=1
        ):
            style = curses.A_REVERSE if index == selected else curses.A_NORMAL
            stdscr.addnstr(screen_row, 0, format_row(sorted_rows[index], width), width - 1, style)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = min(len(sorted_rows) - 1, selected + 1)
        elif key in (10, 13, curses.KEY_ENTER):
            return sorted_rows[selected]
        elif key in (27, ord("q")):
            raise KeyboardInterrupt
        else:
            choice = next((item for item in SORT_CHOICES if key == ord(item[0])), None)
            if choice is not None:
                new_key = choice[1]
                reverse = not reverse if new_key == sort_key else True
                sort_key = new_key
                sorted_rows = sort_rows(rows, sort_key, reverse)
                selected = top = 0
