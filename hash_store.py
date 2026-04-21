"""Robust image hashing and lookup utilities.

This module implements a block-based robust hash tuned for image
deduplication and forensic-style similarity lookup. The workflow is:

1. Convert an image to grayscale and normalize it to a fixed size.
2. Split the normalized image into four quadrants.
3. Normalize mirroring so the darkest quadrant is placed top-left.
4. Threshold each quadrant around its own median to produce a binary hash.
5. Store those hashes for known images and compare query images against them.

The comparison stage follows the two-step decision process described in the
project notes: use Hamming distance as the primary filter, then weighted
distance to review borderline candidates.
"""

import numpy as np
from PIL import Image
import os
import json


class RobustImageHasher:
    """Compute robust hashes and comparison metrics for images.

    The hash is a fixed-length binary fingerprint produced from a normalized
    grayscale image. Each bit also carries a signed offset from the quadrant
    median, which becomes part of the distance vector used in weighted
    comparison.
    """

    def __init__(self, size=16):
        self.size = size

    def _preprocess_image(self, img):
        """Convert an input image to a normalized grayscale pixel matrix."""
        img = img.convert("L")
        img = img.resize((self.size, self.size), Image.Resampling.LANCZOS)
        return np.array(img, dtype=float)

    def _get_quadrants(self, arr):
        """Split a normalized pixel matrix into top/bottom and left/right quadrants."""
        h, w = arr.shape
        mid_h, mid_w = h // 2, w // 2
        return {
            'tl': arr[0:mid_h, 0:mid_w],
            'tr': arr[0:mid_h, mid_w:w],
            'bl': arr[mid_h:h, 0:mid_w],
            'br': arr[mid_h:h, mid_w:w]
        }

    def _optimize_mirroring(self, arr):
        """Flips the image so the darkest quadrant is top-left.
        Returns (flipped_array, ambiguous) where *ambiguous* is True
        when the two darkest quadrant mean-brightness values differ by less
        than 10% of the full quadrant-brightness range.

        The ambiguity flag tells the caller that mirroring normalization may be
        unstable for this image, so all four mirror variants should be tried at
        query time.
        """
        quads = self._get_quadrants(arr)
        quadrant_mean_brightness = np.array([
            np.mean(quads['tl']),
            np.mean(quads['tr']),
            np.mean(quads['bl']),
            np.mean(quads['br']),
        ])
        sorted_mean_brightness = np.sort(quadrant_mean_brightness)
        # Ambiguity: difference between lowest and second-lowest < 10%
        # of the overall quadrant-brightness range.
        brightness_range = max(
            sorted_mean_brightness[-1] - sorted_mean_brightness[0],
            1e-9,
        )
        ambiguous = (
            (sorted_mean_brightness[1] - sorted_mean_brightness[0])
            / brightness_range
        ) < 0.10

        min_idx = np.argmin(quadrant_mean_brightness)
        if min_idx == 1: arr = np.fliplr(arr)
        elif min_idx == 2: arr = np.flipud(arr)
        elif min_idx == 3: arr = np.fliplr(np.flipud(arr))
        return arr, ambiguous

    def _compute_hash_from_array(self, arr):
        """Core hash computation from a preprocessed & mirrored pixel array.
        Returns (hash_string, distance_vector).

        Each quadrant is thresholded against its own median instead of a global
        threshold so large dark/light regions do not collapse into near-uniform
        hashes.
        """
        quads = self._get_quadrants(arr)
        h, w = arr.shape
        mid_h, mid_w = h // 2, w // 2

        hash_matrix = np.zeros_like(arr, dtype=int)
        distance_vector_matrix = np.zeros_like(arr, dtype=float)

        for (key, r_start, r_end, c_start, c_end) in [
            ('tl', 0, mid_h, 0, mid_w),
            ('tr', 0, mid_h, mid_w, w),
            ('bl', mid_h, h, 0, mid_w),
            ('br', mid_h, h, mid_w, w),
        ]:
            med = np.median(quads[key])
            hash_matrix[r_start:r_end, c_start:c_end] = (
                quads[key] >= med
            ).astype(int)
            distance_vector_matrix[r_start:r_end, c_start:c_end] = (
                quads[key].astype(float) - med
            )

        hash_str = "".join(hash_matrix.flatten().astype(str))
        distance_vector = distance_vector_matrix.flatten().tolist()
        return hash_str, distance_vector

    def _get_mirror_variants(self, arr):
        """Return the unflipped, horizontal, vertical, and dual-flip variants."""
        return [
            arr,                          # unflipped
            np.fliplr(arr),               # horizontal flip
            np.flipud(arr),               # vertical flip
            np.fliplr(np.flipud(arr)),    # both
        ]

    def compute_hash(self, img_input):
        """Compute the robust hash and distance vector for one image.
        Returns (hash_string, distance_vector, ambiguous_flag).

        *distance_vector* contains the signed offset of each pixel from its
        quadrant median after mirroring normalization.
        """
        if isinstance(img_input, str):
            img = Image.open(img_input)
        else:
            img = img_input
        arr = self._preprocess_image(img)
        arr, ambiguous = self._optimize_mirroring(arr)
        hash_str, distance_vector = self._compute_hash_from_array(arr)
        return hash_str, distance_vector, ambiguous

    def compute_hash_variants(self, img_input):
        """Computes hashes for all four mirroring variants.
        Returns a list of (hash_string, distance_vector).

        This is only needed for ambiguous images where the darkest quadrant is
        not clearly distinguishable.
        """
        if isinstance(img_input, str):
            img = Image.open(img_input)
        else:
            img = img_input
        arr = self._preprocess_image(img)
        results = []
        for variant in self._get_mirror_variants(arr):
            hash_str, distance_vector = self._compute_hash_from_array(variant)
            results.append((hash_str, distance_vector))
        return results

    def hamming_distance(self, hash1, hash2):
        """Return the number of differing bits between two hashes."""
        if len(hash1) != len(hash2):
            return -1
        return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))

    def weighted_distance(self, hash1, distance_vector1, hash2, distance_vector2):
        """Computes the weighted distance as described in the paper (§2.3).
        Uses the query image's distance vector. The formula:
          weighted = (var_of_unequal_bit_distances / var_of_equal_bit_distances)
                     * hamming_distance * 1000
        Returns float; lower = more likely a true match.

        The second distance vector is accepted for API symmetry, but
        the current formula intentionally uses only the query image's vector.
        """
        d1 = np.array(distance_vector1)
        equal_dists = []
        unequal_dists = []
        for i, (c1, c2) in enumerate(zip(hash1, hash2)):
            if c1 == c2:
                equal_dists.append(abs(d1[i]))
            else:
                unequal_dists.append(abs(d1[i]))

        if not unequal_dists:
            return 0.0
        if not equal_dists:
            return float('inf')

        var_unequal = np.var(unequal_dists)
        var_equal = np.var(equal_dists)

        if var_equal < 1e-9:
            return float('inf')

        ham = len(unequal_dists)
        return (var_unequal / var_equal) * ham * 1000

    def distance_vector_similarity(self, distance_vector1, distance_vector2):
        """L2 (Euclidean) distance between two distance vectors.
        Lower = more similar. Used as a tie-breaker between equal Hamming scores."""
        d1 = np.array(distance_vector1)
        d2 = np.array(distance_vector2)
        return float(np.sqrt(np.sum((d1 - d2) ** 2)))

    def check_similarity(self, hamming_dist, weighted_dist=None):
        """Two-stage decision per §2.4 of the paper:
        1. hamming ≤ 8  → MATCH
        2. 8 < hamming ≤ 32 and weighted ≤ 16  → MATCH
        3. otherwise → NO MATCH"""
        if hamming_dist <= 8:
            return "MATCH (High Confidence)"
        elif hamming_dist <= 32:
            if weighted_dist is not None and weighted_dist <= 16:
                return "MATCH (Weighted Confidence)"
            return "POSSIBLE MATCH (Review Needed)"
        else:
            return "NO MATCH"


class HashStore:
    """
    Persist and query a library of known-image hashes.

    The store keeps one canonical robust hash per known image plus its
    distance vector. Query images are compared against every stored entry, and
    the best candidate match per known image is returned.
    """

    IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tiff')

    def __init__(self, hasher: RobustImageHasher | None = None):
        self.hasher = hasher or RobustImageHasher()
        # {known_image_name: {"hash": str, "distance_vector": list[float]}}
        self._store: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Building / updating the store
    # ------------------------------------------------------------------

    def index_directory(self, directory: str, verbose: bool = True) -> int:
        """
        Compute and store hashes for every supported image in *directory*.

        Returns the number of images successfully indexed.
        """
        files = [
            f for f in os.listdir(directory)
            if f.lower().endswith(self.IMAGE_EXTENSIONS)
        ]
        indexed = 0
        for fname in files:
            path = os.path.join(directory, fname)
            try:
                hash_str, distance_vector, _ = self.hasher.compute_hash(path)
                self._store[fname] = {
                    "hash": hash_str,
                    "distance_vector": distance_vector,
                }
                indexed += 1
                if verbose:
                    print(f"  Indexed: {fname}")
            except Exception as e:
                print(f"  Error indexing {fname}: {e}")
        return indexed

    def add_image(self, image_path: str, name: str | None = None) -> dict:
        """
        Add one image to the store.

        *name* defaults to the file's basename.
        Returns the stored entry dict.
        """
        name = name or os.path.basename(image_path)
        hash_str, distance_vector, _ = self.hasher.compute_hash(image_path)
        self._store[name] = {
            "hash": hash_str,
            "distance_vector": distance_vector,
        }
        return self._store[name]

    def remove(self, name: str) -> bool:
        """Removes an entry from the store. Returns True if it existed."""
        return self._store.pop(name, None) is not None

    def __len__(self) -> int:
        return len(self._store)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def _compare_one_hash(self, query_hash, query_distance_vector, known_image_name, entry):
        """Compare one query hash against one known-image entry.

        Returns a candidate-match dict with explicit metric names so the
        result payload cannot confuse Hamming distance, weighted distance, and
        distance-vector similarity.
        """
        known_image_hash = entry["hash"]
        known_image_distance_vector = entry["distance_vector"]
        hamming_distance = self.hasher.hamming_distance(query_hash, known_image_hash)

        weighted_distance = None
        if 8 < hamming_distance <= 32:
            weighted_distance = self.hasher.weighted_distance(
                query_hash,
                query_distance_vector,
                known_image_hash,
                known_image_distance_vector,
            )

        distance_vector_similarity = self.hasher.distance_vector_similarity(
            query_distance_vector,
            known_image_distance_vector,
        )

        verdict = self.hasher.check_similarity(hamming_distance, weighted_distance)
        return {
            "known_image_name": known_image_name,
            "hamming_distance": hamming_distance,
            "weighted_distance": weighted_distance,
            "distance_vector_similarity": distance_vector_similarity,
            "verdict": verdict,
        }

    def query(
        self,
        image_input,
        top_k: int | None = None,
        include_no_match: bool = False,
    ) -> list[dict]:
        """
        Compare a query image against the stored image library.

        The query image can be a filesystem path or an already-open PIL image.
        Each stored entry receives a candidate-match dict containing the known
        image name, Hamming distance, optional weighted distance,
        distance-vector similarity, and verdict.

        When the mirroring decision is ambiguous, all four mirroring
        variants are tried and the best result per stored image is kept.

        Returns a list of candidate-match dicts sorted by ascending Hamming
        distance, then ascending distance-vector similarity.
        """
        if not self._store:
            raise RuntimeError("The hash store is empty. Index some images first.")

        query_hash, query_distance_vector, ambiguous = self.hasher.compute_hash(image_input)

        if ambiguous:
            variants = self.hasher.compute_hash_variants(image_input)
        else:
            variants = [(query_hash, query_distance_vector)]

        best_candidate_by_known_image: dict[str, dict] = {}

        for variant_hash, variant_distance_vector in variants:
            for known_image_name, entry in self._store.items():
                candidate_match = self._compare_one_hash(
                    variant_hash,
                    variant_distance_vector,
                    known_image_name,
                    entry,
                )
                previous_best = best_candidate_by_known_image.get(known_image_name)
                if previous_best is None or (
                    candidate_match["hamming_distance"]
                    < previous_best["hamming_distance"]
                ):
                    best_candidate_by_known_image[known_image_name] = candidate_match

        results = list(best_candidate_by_known_image.values())

        if not include_no_match:
            results = [r for r in results if r["verdict"] != "NO MATCH"]

        results.sort(
            key=lambda result: (
                result["hamming_distance"],
                result["distance_vector_similarity"],
            )
        )

        if top_k is not None:
            results = results[:top_k]

        return results

    def best_match(self, image_input) -> dict | None:
        """
        Return the single closest stored candidate for a query image.

        The returned dict always includes a verdict, even when the best
        candidate is still classified as "NO MATCH".
        """
        all_results = self.query(image_input, include_no_match=True)
        return all_results[0] if all_results else None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Serialize the current store to JSON."""
        with open(path, 'w') as f:
            json.dump(self._store, f, indent=2)
        print(f"Store saved to {path}  ({len(self._store)} entries)")

    def load(self, path: str) -> int:
        """
        Load hashes from JSON and merge them into the current store.

        Supports both the current format
        ({name: {"hash": ..., "distance_vector": ...}}) and the legacy format
        ({name: hash_string}).

        Returns the number of entries loaded.
        """
        with open(path, 'r') as f:
            data = json.load(f)
        for name, value in data.items():
            if isinstance(value, str):
                # Legacy format: hash string only, no distance vector.
                self._store[name] = {
                    "hash": value,
                    "distance_vector": [0.0] * len(value),
                }
            else:
                normalized_value = dict(value)
                if "distance_vector" not in normalized_value and "distances" in normalized_value:
                    normalized_value["distance_vector"] = normalized_value.pop("distances")
                self._store[name] = normalized_value
        print(f"Loaded {len(data)} entries from {path}")
        return len(data)

    @classmethod
    def from_file(cls, path: str, hasher: RobustImageHasher | None = None) -> "HashStore":
        """Create a store instance pre-populated from a saved JSON file."""
        store = cls(hasher=hasher)
        store.load(path)
        return store


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    KNOWN_IMAGE_DIR = "./data/original_images/"
    QUERY_IMAGE_DIR = "./data/modified_images/"
    HASH_LIBRARY_FILE = "./data/hash_library/original_hashes.json"

    store = HashStore()

    # --- Build (or reload) the hash library of known images ---
    if os.path.exists(HASH_LIBRARY_FILE):
        store.load(HASH_LIBRARY_FILE)
        print(f"Loaded existing hash library with {len(store)} known images.\n")
    else:
        print("Indexing known images …")
        n = store.index_directory(KNOWN_IMAGE_DIR)
        print(f"Indexed {n} known images.\n")
        store.save(HASH_LIBRARY_FILE)

    # --- Query every query image against the hash library ---
    RESULTS_FILE = "./data/results/match_results.txt"

    query_image_names = [
        f for f in os.listdir(QUERY_IMAGE_DIR)
        if f.lower().endswith(HashStore.IMAGE_EXTENSIONS)
    ]

    header = (
        f"{'Query image':<35} {'Known image':<25} "
        f"{'Hamming distance':<18} {'Weighted distance':<18} {'Verdict'}\n"
    )
    separator = "-" * 125 + "\n"

    with open(RESULTS_FILE, "w") as out:
        out.write(header)
        out.write(separator)

        for query_image_name in sorted(query_image_names):
            query_image_path = os.path.join(QUERY_IMAGE_DIR, query_image_name)
            try:
                candidate_match = store.best_match(query_image_path)
                if candidate_match:
                    weighted_distance = candidate_match.get('weighted_distance')
                    weighted_distance_str = (
                        f"{weighted_distance:.1f}"
                        if weighted_distance is not None
                        else "-"
                    )
                    line = (
                        f"{query_image_name:<35} "
                        f"{candidate_match['known_image_name']:<25} "
                        f"{candidate_match['hamming_distance']:<18} "
                        f"{weighted_distance_str:<18} "
                        f"{candidate_match['verdict']}\n"
                    )
                    out.write(line)
            except Exception as e:
                out.write(f"ERROR querying {query_image_name}: {e}\n")

    print(f"Results written to {RESULTS_FILE}")
