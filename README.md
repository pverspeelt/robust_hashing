# Robust Image Hashing

This project implements a robust block-based image hashing system for image deduplication and forensic-style similarity lookup. It converts images to grayscale, normalizes them, splits into quadrants, normalizes mirroring, and thresholds each quadrant to produce binary hashes. Comparisons use Hamming distance as primary filter, followed by weighted distance for borderline candidates.

This is based on the work of Martin Steinebach, Huajian Liu and York Yannikos. The concept of the algorithm is publicly available from the article published in 2012 at the Media watermarking, security and forensics conference. See http://publica.fraunhofer.de/dokumente/N-206786.html for more information. You can also read the pdf that is available in this repo.

## Installation

Ensure you have Python 3.x and install required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

Run the script directly with Python:

```bash
python3 hash_store.py
```

This will index images from `./data/original_images/`, save the hash library to `./data/hash_library/original_hashes.json`, query images from `./data/modified_images/`, and output results to `./data/results/match_results.txt`.

For library usage:

```python
from hash_store import RobustImageHasher, HashStore

# Create hasher and store
hasher = RobustImageHasher()
store = HashStore(hasher)

# Index images
store.index_directory('./images/')

# Query for similar images
results = store.query('query_image.jpg')
for result in results:
    print(f"Match: {result['known_image_name']} - Verdict: {result['verdict']}")
```

## Related Work

- [forbild-hashing](https://github.com/pazifical/forbild-hashing)