"""Tell one speaker from another by the pitch of their voice.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
This measures fundamental frequency and reports "a higher voice" or "a lower
voice". That is enough to notice that someone else has walked up to the
microphone, and to greet a partner by name in a two-person household.

It is NOT speaker recognition. It does not know who anyone is. Two people in
the same pitch range are indistinguishable to it, and a man with a high voice
or a woman with a low one will be labelled wrongly. Anything built on top of
this must fail gracefully when it is wrong — greeting the wrong person by name
is a small embarrassment, so nothing here should ever gate access or actions.

WHY PITCH AND NOT EMBEDDINGS
Real speaker identification needs a neural embedding model, enrolment samples
and a similarity threshold — a dependency, a download, and a calibration step.
Pitch needs numpy and the audio that is already flowing through the callback.
For "is this the usual person or someone else", it earns its keep.

CALIBRATION
Defaults are population averages and will be wrong for some voices. Call
calibrate() with a few seconds of each person's speech to replace the guess
with a threshold derived from the two people who actually use the machine.
"""

from __future__ import annotations

import time

import numpy as np

# Human speech lives here. Anything outside is noise, a hum, or a harmonic
# mis-detection, and is discarded rather than averaged in.
_MIN_HZ = 70.0
_MAX_HZ = 320.0

# Below this the block is silence or room tone; pitch of silence is meaningless.
_MIN_RMS = 450.0

# Population midpoint between typical male (85-180 Hz) and female (165-255 Hz)
# ranges. Deliberately a shade high: calling the household's usual (lower)
# voice "someone else" is the more annoying error.
DEFAULT_SPLIT_HZ = 172.0

# A speaker label only changes after this much evidence. One block is 64 ms, so
# this is roughly a second of continuous speech — long enough that a cough, a
# laugh or one clipped word cannot flip it.
_MIN_BLOCKS_TO_SWITCH = 14

# Once someone has been announced, stay quiet about them for this long even if
# they leave and come back. Nothing is worse than being greeted every sentence.
_REANNOUNCE_SECONDS = 180.0


def estimate_pitch(samples: np.ndarray, rate: int) -> float | None:
    """Fundamental frequency of one block, or None if it is not voiced.

    Autocorrelation: a periodic signal correlates with itself shifted by its
    own period, so the strongest non-trivial peak is the pitch. Cheap, no
    dependencies beyond numpy, and accurate enough to separate voice ranges."""
    try:
        x = np.asarray(samples, dtype=np.float64).flatten()
        if x.size < rate // 40:            # under ~25 ms is too short to judge
            return None

        rms = float(np.sqrt(np.mean(x * x)))
        if rms < _MIN_RMS:
            return None                    # silence or room tone

        x = x - x.mean()
        corr = np.correlate(x, x, mode="full")[x.size - 1:]
        if corr[0] <= 0:
            return None

        lag_min = int(rate / _MAX_HZ)
        lag_max = int(rate / _MIN_HZ)
        if lag_max >= corr.size:
            lag_max = corr.size - 1
        if lag_min >= lag_max:
            return None

        window = corr[lag_min:lag_max]
        peak   = int(np.argmax(window)) + lag_min

        # A weak peak means the block was not really voiced — a fricative, a
        # keyboard, a door. Averaging those in is how a pitch track drifts.
        if corr[peak] < 0.3 * corr[0]:
            return None

        return rate / float(peak)
    except Exception:
        return None


class VoiceWatcher:
    """Follows who is speaking and says when that changes.

    Feed it microphone blocks; it returns a label exactly once per change,
    and None the rest of the time."""

    def __init__(self, split_hz: float = DEFAULT_SPLIT_HZ):
        self.split_hz     = split_hz
        self._current     = None      # "higher" | "lower" | None
        self._candidate   = None
        self._streak      = 0
        self._recent      = []        # last few pitches, for calibration/debug
        self._announced   = {}        # label -> monotonic time

    def observe(self, samples: np.ndarray, rate: int) -> str | None:
        """Returns "higher" or "lower" when the speaker has demonstrably
        changed and has not been announced recently. Otherwise None.

        Never raises: this runs inside the microphone callback, where an
        exception would cost the user their voice input entirely."""
        try:
            pitch = estimate_pitch(samples, rate)
            if pitch is None:
                return None

            self._recent.append(pitch)
            if len(self._recent) > 200:
                del self._recent[:100]

            label = "higher" if pitch >= self.split_hz else "lower"

            if label == self._current:
                self._candidate, self._streak = None, 0
                return None

            if label == self._candidate:
                self._streak += 1
            else:
                self._candidate, self._streak = label, 1

            if self._streak < _MIN_BLOCKS_TO_SWITCH:
                return None

            # Confirmed change.
            self._current = label
            self._candidate, self._streak = None, 0

            last = self._announced.get(label, 0.0)
            now  = time.monotonic()
            if now - last < _REANNOUNCE_SECONDS:
                return None            # changed, but we already said so recently
            self._announced[label] = now
            return label
        except Exception:
            return None

    def median_pitch(self) -> float | None:
        """Median of recent voiced blocks — what calibration reads."""
        return float(np.median(self._recent)) if self._recent else None

    def reset(self) -> None:
        self._current = self._candidate = None
        self._streak  = 0
        self._announced.clear()


def split_from_samples(low_hz: float, high_hz: float) -> float:
    """Threshold for two known voices: the midpoint between them, in the log
    domain because pitch is perceived — and distributed — multiplicatively."""
    low_hz  = max(_MIN_HZ, min(_MAX_HZ, float(low_hz)))
    high_hz = max(_MIN_HZ, min(_MAX_HZ, float(high_hz)))
    if high_hz <= low_hz:
        return DEFAULT_SPLIT_HZ
    return float(np.sqrt(low_hz * high_hz))
