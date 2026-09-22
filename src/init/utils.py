#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty
#  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
from pathlib import Path

def resource_path(*parts: str) -> Path:
    """Resolve how and where are assets loaded"""
    import sys

    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent

    return base.joinpath(*parts)

def spectrum_levels(audio, sample_rate=44100):
    """Spectrum levels of audio"""
    import numpy as np
    samples = np.asarray(audio)
    if samples.ndim == 1:
        samples = samples[:, None]

    band_count = 15

    if len(samples) < 2 or samples.shape[1] == 0:
        return np.zeros(band_count)

    window = np.hanning(len(samples))
    spectrum = np.abs(
        np.fft.rfft(samples * window[:, None], axis=0))

    power = np.mean(
        (spectrum / max(window.sum(), 1)) ** 2,
        axis=1)

    frequencies = np.fft.rfftfreq(
        len(samples),
        1 / sample_rate)

    edges = np.geomspace(60,
        min(12000, sample_rate / 2),
        band_count + 1)

    rms = np.array([
        np.sqrt(power[
                (frequencies >= low) &
                (frequencies < high)
            ].sum()) for low, high in zip(edges, edges[1:])])

    return np.clip((20 * np.log10(np.maximum(rms, 1e-8)) + 60) / 60, 0, 1)


def get_stylesheet():
    """Returns the global stylesheet"""
    from pathlib import Path
    stylesheet_path = resource_path(
        (Path(__file__).resolve().parent.parent.parent / "assets" / "arlo.qss"))
    stylesheet = stylesheet_path.read_text(encoding="utf-8")
    return stylesheet