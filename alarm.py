import threading
import time

import lgpio


class AlarmController:
    """Sounds a siren while active=True; goes silent the moment active=False."""

    def __init__(self, pin=17, chip=0, low=2000, high=2700, step=0.15):
        self.pin = pin
        self.low = low
        self.high = high
        self.step = step
        self.enabled = True
        self.busy = False
        self.active = False
        self.err = None
        self.h = None
        try:
            self.h = lgpio.gpiochip_open(chip)
            lgpio.gpio_claim_output(self.h, pin)
            lgpio.gpio_write(self.h, pin, 0)
        except Exception as e:
            self.err = str(e)

    @property
    def ok(self):
        return self.h is not None

    def _pwm(self, freq, duty=50):
        lgpio.tx_pwm(self.h, self.pin, freq, duty)

    def _off(self):
        try:
            lgpio.tx_pwm(self.h, self.pin, 0, 0)
            lgpio.gpio_write(self.h, self.pin, 0)
        except Exception:
            pass

    def _alarm_loop(self):
        self.busy = True
        freq = self.low
        while self.active and self.enabled:
            self._pwm(freq)
            freq = self.high if freq == self.low else self.low
            time.sleep(self.step)
        self._off()
        self.busy = False

    def set_active(self, on):
        """True -> siren while person present; False -> immediate silence.
        Returns True if this call newly activated the alarm."""
        if not (self.ok and self.enabled):
            on = False
        if on == self.active:
            return False
        self.active = on
        if on:
            threading.Thread(target=self._alarm_loop, daemon=True).start()
            return True
        self._off()
        return False

    def beep(self, freq=2300, dur=0.4):
        if not self.ok:
            return

        def task():
            self.busy = True
            self._pwm(freq)
            time.sleep(dur)
            self._off()
            self.busy = False

        threading.Thread(target=task, daemon=True).start()

    def rhythm(self, notes):
        """notes: list of (freq, dur_sec) played in sequence."""
        if not self.ok:
            return

        def task():
            self.busy = True
            for freq, dur in notes:
                self._pwm(freq)
                time.sleep(dur)
                self._off()
                time.sleep(0.1)
            self.busy = False

        threading.Thread(target=task, daemon=True).start()

    def startup_ok(self):
        self.rhythm([(2000, 0.12), (2300, 0.12), (2700, 0.2)])

    def startup_fail(self):
        self.rhythm([(800, 0.3), (800, 0.3)])

    def status(self):
        return {"ok": self.ok, "enabled": self.enabled, "error": self.err,
                "pin": self.pin, "active": self.active, "busy": self.busy}

    def silence(self):
        self.active = False
        self._off()

    def close(self):
        self.active = False
        if self.ok:
            self._off()
            try:
                lgpio.gpiochip_close(self.h)
            except Exception:
                pass
