import sys
import numpy as np
import soundfile as sf
import noisereduce as nr
import librosa

input_path = sys.argv[1]
output_path = sys.argv[2]

# librosa handles mp3, wav, flac, etc.
data, rate = librosa.load(input_path, sr=None, mono=False)

# librosa loads as (channels, samples) for stereo, or (samples,) for mono
if data.ndim > 1:
    left = nr.reduce_noise(y=data[0], sr=rate)
    right = nr.reduce_noise(y=data[1], sr=rate)
    min_len = min(len(left), len(right))
    clean = np.stack([left[:min_len], right[:min_len]], axis=1)
else:
    clean = nr.reduce_noise(y=data, sr=rate)

sf.write(output_path, clean, rate)