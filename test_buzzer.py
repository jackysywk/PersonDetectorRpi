"""Buzzer test - TMB12A05 passive buzzer on GPIO17, direct lgpio tx_pwm."""
import time

import lgpio

PIN = 17
RESONANT = 2300  # TMB12A05 resonant frequency

h = lgpio.gpiochip_open(0)
lgpio.gpio_claim_output(h, PIN)

print("Test 1: 2.3kHz resonant beep (expected: loud)")
lgpio.tx_pwm(h, PIN, RESONANT, 50)
time.sleep(0.6)
lgpio.tx_pwm(h, PIN, 0, 0)
time.sleep(0.4)

print("Test 2: frequency sweep")
for f in (800, 1200, 1600, 2000, 2300, 2700):
    print(f"  {f} Hz")
    lgpio.tx_pwm(h, PIN, f, 50)
    time.sleep(0.3)
lgpio.tx_pwm(h, PIN, 0, 0)
time.sleep(0.4)

print("Test 3: DC on (expected: faint click only)")
lgpio.gpio_write(h, PIN, 1)
time.sleep(0.5)
lgpio.gpio_write(h, PIN, 0)

lgpio.gpiochip_close(h)
print("done")
