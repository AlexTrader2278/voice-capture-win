# -*- coding: utf-8 -*-
"""
Голосовой ввод по горячей клавише (офлайн, GigaAM v3 E2E RNNT).

Как работает (режим "hold", по умолчанию):
  1. Ставишь курсор в поле ввода.
  2. Зажимаешь и ДЕРЖИШЬ горячую клавишу (по умолчанию — правый Ctrl) — пошла запись,
     короткий высокий сигнал. Говоришь, пока держишь.
  3. Отпускаешь — запись стоп (низкий сигнал), распознавание, текст вставляется
     туда, где курсор (через буфер обмена + Ctrl+V).
     Готово — двойной высокий сигнал. Пусто/ошибка — длинный низкий сигнал.

Режим "toggle" (config.json -> "mode": "toggle"): нажал — запись, нажал ещё раз — стоп.
Удобно для длинной диктовки, когда держать клавишу неудобно.

Выход из программы: Ctrl+Alt+Shift+G  (или просто закрыть окно).
Диагностика (доходят ли нажатия): voice-input.bat с аргументом --diag.

Настройки — в config.json рядом с этим файлом (можно не трогать).
"""

import ctypes
import json
import os
import queue
import sys
import threading
import time
import traceback
import winsound
from datetime import datetime

import numpy as np
import sounddevice as sd
import keyboard
import pyperclip

from cleaner import clean_fillers

# --------------------------------------------------------------------------- #
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "voice-input.log")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULTS = {
    "mode": "hold",                     # "hold" — держать клавишу; "toggle" — нажал/нажал
    "hotkey": "right ctrl",            # клавиша диктовки (одиночная — ничего не печатает)
    "quit_hotkey": "ctrl+alt+shift+g",  # выход
    "model": "gigaam-v3-e2e-rnnt",      # модель onnx-asr (сама ставит пунктуацию и регистр)
    "input_device": None,               # null = микрофон по умолчанию; или номер из --list-devices
    "sample_rate": 16000,
    "max_seconds": 120,                 # авто-стоп, чтобы не писать вечно
    "remove_fillers": True,             # вырезать «э-э», «эээ», «а-а-а», «эм», «ммм»
    "capitalize_first": True,           # первая буква фразы заглавной
    "trailing_space": True,             # пробел в конце (удобно диктовать подряд)
    "restore_clipboard": True,          # вернуть прежнее содержимое буфера после вставки
    "paste_delay": 0.12,                # пауза перед Ctrl+V (сек)
}


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user = json.load(f)
            cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
        except Exception as e:
            log(f"config.json не прочитан ({e}), беру значения по умолчанию")
    else:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULTS, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return cfg


_mutex_handle = None


def already_running():
    """Не даём запуститься второму экземпляру (ярлык автозагрузки + ручной запуск)."""
    global _mutex_handle
    kernel32 = ctypes.windll.kernel32
    _mutex_handle = kernel32.CreateMutexW(None, False, "Global\\voice_input_gigaam")
    ERROR_ALREADY_EXISTS = 183
    return kernel32.GetLastError() == ERROR_ALREADY_EXISTS


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# --- звуковые сигналы ------------------------------------------------------- #
def beep_start():
    winsound.Beep(900, 110)


def beep_stop():
    winsound.Beep(500, 110)


def beep_done():
    winsound.Beep(1150, 70)
    winsound.Beep(1400, 70)


def beep_empty():
    winsound.Beep(300, 260)


# --------------------------------------------------------------------------- #
class VoiceInput:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sr = int(cfg["sample_rate"])
        self.recording = False
        self.busy = False               # идёт распознавание/вставка
        self._frames = []
        self._stream = None
        self._lock = threading.Lock()
        self._auto_stop_timer = None

        log("Загружаю модель " + cfg["model"] + " ...")
        t0 = time.time()
        import onnx_asr
        self.model = onnx_asr.load_model(cfg["model"])
        log(f"Модель готова за {time.time() - t0:.1f} c")

    # -- запись ------------------------------------------------------------- #
    def _audio_cb(self, indata, frames, time_info, status):
        if status:
            log(f"audio status: {status}")
        self._frames.append(indata.copy())

    def start_recording(self):
        with self._lock:
            if self.recording or self.busy:
                return
            self._frames = []
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sr,
                    channels=1,
                    dtype="float32",
                    device=self.cfg["input_device"],
                    callback=self._audio_cb,
                )
                self._stream.start()
            except Exception as e:
                log(f"Не удалось открыть микрофон: {e}")
                beep_empty()
                return
            self.recording = True
            log("● запись...")
            beep_start()
            self._auto_stop_timer = threading.Timer(
                float(self.cfg["max_seconds"]), self._auto_stop
            )
            self._auto_stop_timer.daemon = True
            self._auto_stop_timer.start()

    def _auto_stop(self):
        log(f"авто-стоп по лимиту {self.cfg['max_seconds']} c")
        self.stop_recording()

    def stop_recording(self):
        with self._lock:
            if not self.recording:
                return
            self.recording = False
            if self._auto_stop_timer:
                self._auto_stop_timer.cancel()
                self._auto_stop_timer = None
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                log(f"ошибка закрытия потока: {e}")
            self._stream = None
            frames = self._frames
            self._frames = []
        beep_stop()
        self.busy = True
        threading.Thread(target=self._process, args=(frames,), daemon=True).start()

    # -- распознавание + вставка ----------------------------------------- #
    def _process(self, frames):
        try:
            if not frames:
                log("пусто (нет кадров)")
                beep_empty()
                return
            audio = np.concatenate(frames, axis=0).reshape(-1).astype(np.float32)
            dur = len(audio) / self.sr
            if dur < 0.3:
                log(f"слишком коротко ({dur:.2f} c)")
                beep_empty()
                return
            t0 = time.time()
            text = self.model.recognize(audio)
            log(f"распознано за {time.time() - t0:.2f} c ({dur:.1f} c аудио): {text!r}")
            text = self._postprocess(text)
            if not text.strip():
                beep_empty()
                return
            self._paste(text)
            beep_done()
        except Exception:
            log("ОШИБКА в обработке:\n" + traceback.format_exc())
            beep_empty()
        finally:
            self.busy = False

    def _postprocess(self, text):
        text = (text or "").strip()
        if self.cfg["remove_fillers"]:
            text = clean_fillers(text)
        if not text:
            return text
        if self.cfg["capitalize_first"]:
            text = text[0].upper() + text[1:]
        if self.cfg["trailing_space"]:
            text = text + " "
        return text

    def _paste(self, text):
        old = None
        if self.cfg["restore_clipboard"]:
            try:
                old = pyperclip.paste()
            except Exception:
                old = None
        pyperclip.copy(text)
        time.sleep(float(self.cfg["paste_delay"]))
        keyboard.send("ctrl+v")
        time.sleep(0.15)
        if self.cfg["restore_clipboard"] and old is not None:
            time.sleep(0.25)
            try:
                pyperclip.copy(old)
            except Exception:
                pass

    # -- по горячей клавише --------------------------------------------- #
    def toggle(self):
        if self.busy:
            log("занят распознаванием, подожди")
            return
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()


def main():
    cfg = load_config()

    if "--list-devices" in sys.argv:
        print(sd.query_devices())
        return
    if "--selftest" in sys.argv:
        vi = VoiceInput(cfg)
        sil = np.zeros(vi.sr, dtype=np.float32)
        print("recognize(silence) ->", repr(vi.model.recognize(sil)))
        print("OK")
        return

    if "--diag" in sys.argv:
        # логируем нажатия — проверить, доходят ли события и как шлётся правый Ctrl
        secs = 60
        try:
            i = sys.argv.index("--diag")
            secs = int(sys.argv[i + 1])
        except (ValueError, IndexError):
            pass
        print(f"Диагностика {secs} c. Жми не торопясь: правый Ctrl x5, левый Ctrl x2, "
              f"правый Alt x2, затем напечатай любое слово. Лог: {LOG_PATH}")
        log(f"=== DIAG START ({secs} c) ===")
        t0 = time.time()
        seen = {"n": 0, "mods": 0}

        def chk(name):
            try:
                return "1" if keyboard.is_pressed(name) else "0"
            except Exception:
                return "?"

        def on_ev(e):
            seen["n"] += 1
            nm = (e.name or "").lower()
            is_mod = any(w in nm for w in ("ctrl", "alt", "shift", "win", "cmd")) \
                or e.scan_code in (29, 3613, 56, 3640, 42, 54, 91, 92)
            if is_mod:
                seen["mods"] += 1
            tag = "  <<< МОДИФИКАТОР" if is_mod else ""
            log(f"DIAG t+{time.time()-t0:5.1f}s {e.event_type:4} name={e.name!r} "
                f"scan={e.scan_code} | ctrl={chk('ctrl')} Rctrl={chk('right ctrl')} "
                f"Lctrl={chk('left ctrl')} alt={chk('alt')} Ralt={chk('right alt')}{tag}")

        keyboard.hook(on_ev)
        time.sleep(secs)
        keyboard.unhook_all()
        log(f"=== DIAG END, всего событий: {seen['n']}, модификаторов: {seen['mods']} ===")
        print(f"Готово. Всего {seen['n']}, модификаторов {seen['mods']}. Смотри {LOG_PATH}")
        return

    if already_running():
        log("Уже запущен другой экземпляр — выхожу.")
        return

    # чтобы окно не засыпало систему и было видно в трее задач
    try:
        ctypes.windll.kernel32.SetConsoleTitleW("voice-input — GigaAM")
    except Exception:
        pass

    vi = VoiceInput(cfg)
    stop_evt = threading.Event()
    mode = str(cfg.get("mode", "hold")).lower()
    hotkey = str(cfg["hotkey"]).strip().lower()
    quit_hotkey = cfg["quit_hotkey"]

    # Клавиши, которые keyboard различает по СТОРОНЕ через e.name (is_pressed —
    # не различает). Для них ловим события по имени, иначе — опрос is_pressed.
    SIDED = {
        "right ctrl", "left ctrl", "right alt", "left alt",
        "right shift", "left shift", "right windows", "left windows",
    }
    name_match = hotkey in SIDED

    st = {"held": False, "last_down": 0.0}

    def on_key(e):
        if (e.name or "").strip().lower() != hotkey:
            return
        now = time.time()
        if e.event_type == keyboard.KEY_DOWN:
            st["last_down"] = now
            if not st["held"]:
                st["held"] = True
                if mode == "toggle":
                    vi.toggle()
                elif not vi.busy:
                    vi.start_recording()
        elif e.event_type == keyboard.KEY_UP:
            if st["held"]:
                st["held"] = False
                if mode != "toggle" and vi.recording:
                    vi.stop_recording()

    def poll_watch():
        # запасной путь для клавиш без стороны (f9, pause, ...) + сторож за
        # потерянным "up" (потеря фокуса, Win+L): держат — автоповтор освежает
        # last_down; если тишина > 1.2 c при активной записи — считаем отпущенным.
        prev_main = False
        prev_quit = False
        while not stop_evt.is_set():
            try:
                quit_down = keyboard.is_pressed(quit_hotkey)
            except Exception:
                quit_down = False
            if quit_down and not prev_quit:
                log("Выход по горячей клавише.")
                stop_evt.set()
                break
            prev_quit = quit_down

            if not name_match:
                try:
                    main_down = keyboard.is_pressed(hotkey)
                except Exception:
                    main_down = False
                if mode == "toggle":
                    if main_down and not prev_main:
                        vi.toggle()
                else:
                    if main_down and not vi.recording and not vi.busy:
                        vi.start_recording()
                    elif not main_down and vi.recording:
                        vi.stop_recording()
                prev_main = main_down
            elif mode != "toggle" and st["held"] and vi.recording:
                if time.time() - st["last_down"] > 1.2:
                    st["held"] = False
                    log("Сторож: потерян 'up', останавливаю запись.")
                    vi.stop_recording()

            time.sleep(0.03)

    if name_match:
        keyboard.hook(on_key)
    threading.Thread(target=poll_watch, daemon=True).start()

    hint = "держи для записи" if mode != "toggle" else "нажал/нажал"
    how = "по имени события" if name_match else "опросом is_pressed"
    log(f"Готов [{mode}]. {hotkey} — {hint} ({how}), {quit_hotkey} — выход.")
    winsound.Beep(1000, 60)
    winsound.Beep(1300, 60)
    try:
        stop_evt.wait()
    except KeyboardInterrupt:
        pass
    log("Выход.")


if __name__ == "__main__":
    main()
