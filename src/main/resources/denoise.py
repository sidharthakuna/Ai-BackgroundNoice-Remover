import sys
import numpy as np
import soundfile as sf
import noisereduce as nr

input_path = sys.argv[1]
output_path = sys.argv[2]

data, rate = sf.read(input_path)

if data.ndim > 1:
    left = nr.reduce_noise(y=data[:, 0], sr=rate)
    right = nr.reduce_noise(y=data[:, 1], sr=rate)
    min_len = min(len(left), len(right))
    left = left[:min_len]
    right = right[:min_len]
    clean = np.stack([left, right], axis=1)
else:
    clean = nr.reduce_noise(y=data, sr=rate)



sf.write(output_path, clean, rate)