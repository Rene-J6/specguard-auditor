# RAG Generation-Quality Evaluation

Results are descriptive. Structural, retrieval, and semantic measures are separate.

## Structural reliability

| Measure | Value |
| --- | ---: |
| Schema validation | 0.979 |
| Safe failure | 0.021 |
| Retry | 0.104 |
| Controlled repair | 0.896 |

## Retrieval quality

| Measure | Value |
| --- | ---: |
| Diagnostic threshold | 0.300 |
| Hit@1 | 0.050 |
| Hit@5 | 0.150 |
| MRR | 0.082 |
| No-match rejection | 0.000 |

## Semantic generation quality

### All (n=48)

| Metric | Scored | Mean (0-1) | Median (0-1) | Score 0 | Score 1 | Score 2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Faithfulness | 48 | 0.542 | 0.750 | 20 | 4 | 24 |
| Answer relevance | 48 | 0.740 | 1.000 | 10 | 5 | 33 |

### Expected Match (n=40)

| Metric | Scored | Mean (0-1) | Median (0-1) | Score 0 | Score 1 | Score 2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Faithfulness | 40 | 0.512 | 0.500 | 18 | 3 | 19 |
| Answer relevance | 40 | 0.738 | 1.000 | 9 | 3 | 28 |

### No Match (n=8)

| Metric | Scored | Mean (0-1) | Median (0-1) | Score 0 | Score 1 | Score 2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Faithfulness | 8 | 0.688 | 1.000 | 2 | 1 | 5 |
| Answer relevance | 8 | 0.750 | 1.000 | 1 | 2 | 5 |

## Expert validation

PENDING: the blinded 15-case expert sheet has not been fully scored.

## Representative judge-flagged failures

### Faithfulness

| Case | Reason |
| --- | --- |
| rag_val_001 | The retrieved context describes what should be included in a "Mission, goals and objectives" section (business results), not criteria for evaluating the compliance of a functional requirement. The audit's claim that the requirement is "compliant" with this clause is unsupported by the evidence. |
| rag_val_002 | The audit invents a condition that a requirement about downloading invoices must include payment methods, and assumes the requirement falls under "government services" to link it to the evidence, neither of which is supported by the original requirement or the retrieved evidence. |
| rag_val_005 | The retrieved evidence (ISO 9001:2008 7.2.2) is a general quality management clause about reviewing requirements and customer focus, which does not provide specific criteria to evaluate the functional requirement about searching orders. The audit's conclusion of "compliant" is not supported by the provided evidence. |

### Answer relevance

| Case | Reason |
| --- | --- |
| rag_val_005 | The audit's diagnosis of "compliant" and "no issues" is based on irrelevant evidence, thus the suggested rewrite (no change) does not meaningfully address the requirement in relation to the provided context. The audit fails to identify the irrelevance of the evidence. |
| rag_val_007 | The rewrite completely changes the original intent of specifying a measurable performance metric and replaces it with a vague, less measurable statement. It does not resolve the (incorrectly) diagnosed issue; instead, it removes the existing measurable rate. |
| rag_val_010 | The rewrite fails to address the incorrectly diagnosed issue of 'not_measurable' as the original requirement was already measurable. Instead, it alters the original intent by adding an unsupported exclusion. |

## Interpretation boundary

Descriptive only. The free-form baseline also received retrieved evidence, so these results do not establish improvement over a non-RAG model.
