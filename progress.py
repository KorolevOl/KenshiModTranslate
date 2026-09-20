"""Два консольных прогрессбара на tqdm + совместимое логирование.

Внешний (ALL)  — сколько модов сделано.
Внутренний (NOW) — строки внутри текущего мода (пересоздаётся на каждый мод).
log() пишет текст в тот же поток, что и бары (stderr), поэтому строки и бары
никогда не перемешиваются (старый баг «смесь stdout/stderr + хвостовой \r»).

Почему tqdm, а не самописное: tqdm сам ведёт ETA, корректно работает с
Ctrl+C на Windows, а tqdm.write гарантирует порядок текста и баров.
"""
import sys
try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - дружелюбная подсказка
    print("[env] tqdm is required (pip install tqdm).")
    raise

OUTER_POSITION = 0
INNER_POSITION = 1

class Progress:
    """Stacked two-bar progress: ALL mods (outer) + current mod strings (inner)."""

    def __init__(self, total_mods: int):
        self.total_mods = total_mods
        self.outer = tqdm(
            total=total_mods, position=OUTER_POSITION,
            desc="ALL", unit=" мод", mininterval=0.25, leave=True,
            # {unit} — единица измерения (моды) сразу после N/Total
            bar_format='{desc} {bar}| {n_fmt}/{total_fmt} {unit} [{elapsed}<{remaining}]',
        )
        self.inner = None

    # --- text that coexists with the bar (never corrupts them) ---
    def log(self, msg):
        # Write into the outer bar's stream (stderr) so ordering is preserved.
        tqdm.write("" if msg is None else str(msg), file=self.outer.fp)

    # --- inner bar = current mod (NOW / FIX), tokens ---
    def begin_mod(self, name: str, total: int, done: int = 0, unit: str = "tok"):
        """Main pass bar. total/done = estimated INPUT tokens of the mod."""
        self._open_inner("NOW ", name, total, done, unit)

    def begin_repair(self, name: str, total: int, done: int = 0, unit: str = "tok"):
        """'FIX' bar — replaces NOW in the same slot (position 1).

        Used by the do-period (допериод): re-translation of failed rows.
        total = tokens of the failed rows.
        """
        self._open_inner("FIX ", name, total, done, unit)

    def _open_inner(self, prefix: str, name: str, total: int, done: int, unit: str = "ток"):
        if self.inner is not None:
            try: self.inner.close()
            except Exception: pass
        n = min(max(0, done), total) if total else 0
        label = (name[:18] if name else "")
        self.inner = tqdm(
            total=total, initial=n, position=INNER_POSITION,
            desc=prefix + label,
            unit=unit or "ток", mininterval=0.25, leave=False,
            file=sys.stderr,
            # {unit} сразу после N/Total — единица измерения видна на каждом баре
            bar_format='{desc} {bar}| {n_fmt}/{total_fmt} {unit} [{elapsed}<{remaining}]',
        )

    def step_strings(self, n: int = 1):
        if n and self.inner is not None:
            self.inner.update(n)

    # --- busy indicator (dotnet apply/extract, LLM single call — no real progress) ---
    def busy(self, msg=""):
        """Non-progress indicator (spinner) for steps where progress is
        unknown (dotnet CLI, single LLM request). Replaces NOW slot."""
        if self.inner is not None:
            try: self.inner.close()
            except Exception: pass
        self.inner = tqdm(
            total=None, position=INNER_POSITION,
            desc=("BUSY " + msg[:28] if msg else "BUSY …"),
            mininterval=0.25, leave=False, file=sys.stderr,
        )

    def idle(self):
        """Close busy/spinner bar."""
        if self.inner is not None:
            try: self.inner.close()
            except Exception: pass
            self.inner = None

    def finish_mod(self):
        # Finish inner at 100%, then advance outer by one mod.
        if self.inner is not None:
            try:
                self.inner.update(max(0, self.inner.total - self.inner.n))
                self.inner.close()
            except Exception:
                pass
            self.inner = None
        self.outer.update(1)

    def finish(self):
        if self.inner is not None:
            try:
                self.inner.close()
            except Exception:
                pass
            self.inner = None
        self.outer.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is KeyboardInterrupt:
                self.outer.write("")  # newline so the message starts clean
        except Exception:
            pass
        finally:
            self.finish()
            return False
