"""JalRekha vision: OpenCV 5 water-level measurement in metres.

The pipeline turns a fixed-camera frame (or a short burst) plus a staff-gauge
calibration into a stage reading with an uncertainty, a quality report and a
debug overlay. It is pure OpenCV + NumPy and is safe to run out of process
from the LiteRT edge runtime (see ANALYSIS.md section 10).
"""

from jalrekha.vision.gauge import GaugeCalibration
from jalrekha.vision.pipeline import Measurement, measure

__all__ = ["GaugeCalibration", "Measurement", "measure"]
