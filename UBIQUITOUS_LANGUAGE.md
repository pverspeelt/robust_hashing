# Ubiquitous Language

## Image matching domain

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Known image** | An image whose robust hash is already stored in the hash library. | Original image, database image |
| **Query image** | An image being tested against the hash library. | Modified image, test image |
| **Robust hash** | A binary fingerprint that remains stable across common image processing changes. | Perceptual hash, fingerprint |
| **Distance vector** | The per-bit signed offsets from each quadrant median used to weight comparisons. | Distances, weights |
| **Quadrant** | One of the four equal subregions of the normalized grayscale image. | Subarea, block group |
| **Quadrant mean brightness** | The average pixel value of one quadrant used only during mirror normalization. | Quadrant mean, mean value |
| **Quadrant median** | The median pixel value of one quadrant used to threshold bits and build the distance vector. | Median threshold, mean threshold |
| **Mirror normalization** | The step that flips an image so its darkest quadrant becomes top-left. | Auto mirroring, flipping step |
| **Ambiguous mirroring** | A condition where the darkest quadrant is not distinct enough to trust a single mirror normalization. | Unclear flip, uncertain orientation |

## Match evaluation

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Hash library** | The persisted collection of known-image hashes and distance vectors. | Store, database, index |
| **Candidate match** | A known image currently being compared to a query image. | Result, hit |
| **Hamming distance** | The count of differing bits between two robust hashes. | Distance |
| **Weighted distance** | A secondary score for borderline candidates derived from unequal-bit and equal-bit variance. | Confidence score, review score |
| **Distance-vector similarity** | The Euclidean distance between two distance vectors, used as a tie-breaker. | Vector distance, L2 score |
| **High-confidence match** | A candidate whose Hamming distance is 8 or less. | Direct match |
| **Weighted-confidence match** | A candidate whose Hamming distance is between 9 and 32 and whose weighted distance is 16 or less. | Secondary match |
| **Possible match** | A borderline candidate that merits review but does not satisfy the weighted-distance threshold. | Maybe match, soft match |
| **No match** | A candidate that fails the decision thresholds. | Rejection |

## Relationships

- A **Query image** is normalized into four **Quadrants** before hashing.
- Each **Quadrant** has one **Quadrant mean brightness** and one **Quadrant median**.
- A **Robust hash** is paired with exactly one **Distance vector**.
- A **Known image** contributes one **Robust hash** and one **Distance vector** to the **Hash library**.
- Every **Candidate match** compares a **Query image** against one **Known image**.
- **Mirror normalization** compares **Quadrant mean brightness** values and may produce **Ambiguous mirroring**, which requires evaluating all mirror variants of the **Query image**.
- A **Distance vector** is derived from per-pixel offsets relative to each **Quadrant median**.
- **Hamming distance** is the primary decision metric; **Weighted distance** is only evaluated for borderline candidates.
- **Distance-vector similarity** breaks ties between candidates with the same **Hamming distance**.

## Example dialogue

> **Dev:** "When a **Query image** has **Ambiguous mirroring**, do we store four hashes in the **Hash library**?"
>
> **Domain expert:** "No. The **Hash library** still keeps one canonical hash per **Known image**. We evaluate four mirror variants only for the **Query image**."
>
> **Dev:** "So the first filter is always **Hamming distance**, and **Weighted distance** only applies to borderline cases?"
>
> **Domain expert:** "Exactly. A **High-confidence match** is decided from **Hamming distance** alone, while a **Weighted-confidence match** needs the second score."
>
> **Dev:** "If two candidates have the same **Hamming distance**, what resolves the tie?"
>
> **Domain expert:** "Use **Distance-vector similarity**. The smaller value is the closer **Candidate match**."

## Flagged ambiguities

- The bare word "distance" previously referred to three different metrics. In repo code and docs, use **Hamming distance**, **Weighted distance**, or **Distance-vector similarity** explicitly.
- "Original image," "test image," and "modified image" previously described two distinct roles. In repo code and docs, use **Known image** for hash-library entries and **Query image** for the image under test.
- "Subarea," "block," and "quadrant" previously overlapped. In repo code and docs, use **Quadrant** for the four-way image split used by this implementation.
- "Mean" and "median" previously blurred two separate operations. In repo code and docs, use **Quadrant mean brightness** for mirror normalization and **Quadrant median** for hash thresholding and distance-vector generation.